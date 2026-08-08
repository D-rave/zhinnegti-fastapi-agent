"""
聊天路由 V3（多步 ReAct + 记忆向量检索 + Redis 缓存）
新增：
1. 多步 ReAct Agent 支持链式工具调用
2. 记忆向量检索：根据用户问题检索最相关记忆片段
3. Redis 缓存：会话列表缓存、Token 黑名单、限流
4. SSE 生成器使用独立 db session
"""
import asyncio
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from models.db import get_db, async_session_maker
from models.chat import ChatSession, ChatMessage
from models.user import User
from agent.react_agent import ReactAgent
from services.memory_vector_service import MemoryVectorService
from utils.redis_client import RedisCache, close_redis
from utils.logger_handler import logger
from routers.auth import get_current_user

router = APIRouter(prefix="/api/chat", tags=["聊天"])

memory_vector_service = MemoryVectorService()


# ========== 请求模型 ==========
class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ClearRequest(BaseModel):
    session_id: str = ""


# ========== 数据库操作封装 ==========
async def get_or_create_db_session(
    session_id: str,
    user_id: int | None,
    db: AsyncSession
) -> ChatSession:
    """从数据库获取或创建会话记录"""
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        session = ChatSession(
            session_id=session_id or str(uuid.uuid4()),
            user_id=user_id,
            title="新对话"
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def save_message(db: AsyncSession, session_id: str, role: str, content: str):
    """保存单条消息到数据库"""
    msg = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(msg)
    await db.commit()


async def get_session_history(db: AsyncSession, session_id: str) -> list:
    """获取某会话的全部历史消息"""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]


# ========== 长期记忆服务（SQLite 兜底 + 向量检索增强）==========
async def get_user_memory_text(db: AsyncSession, user_id: int, query: str) -> str:
    """
    获取用户长期记忆文本
    策略：向量检索 top-k 相关记忆 + SQLite 兜底补充
    """
    # 1. 向量检索：根据用户问题检索最相关的记忆
    vector_memory = memory_vector_service.retrieve_for_query(user_id, query, k=3)

    # 2. SQLite 兜底：读取全部画像（作为补充）
    sqlite_memory = ""
    try:
        from models.memory import UserProfile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profiles = result.scalars().all()
        if profiles:
            sqlite_memory = "【用户画像】\n"
            for p in profiles:
                sqlite_memory += f"- {p.content}\n"
    except Exception:
        pass

    # 合并：向量记忆优先，SQLite 兜底
    if vector_memory and sqlite_memory:
        return vector_memory + "\n" + sqlite_memory
    return vector_memory or sqlite_memory


# ========== API 接口 ==========
@router.post("/send")
async def chat_send(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发送消息并获取流式 SSE 响应
    支持：多步 ReAct、记忆向量检索、Redis 缓存、客户端中断检测
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    session_id = req.session_id or str(uuid.uuid4())

    # 1. 获取或创建数据库会话记录
    db_session = await get_or_create_db_session(
        session_id,
        current_user.id if current_user else None,
        db
    )
    session_id = db_session.session_id

    # 2. 保存用户消息到数据库
    await save_message(db, session_id, "user", req.message)

    # 3. 获取 MCP 外部工具
    mcp_tools = getattr(request.app.state, "mcp_tools", []) or []

    # 4. 获取用户记忆（向量检索 + SQLite 兜底）
    memory_text = ""
    if current_user:
        memory_text = await get_user_memory_text(db, current_user.id, req.message)

    # 5. 获取历史消息
    history = await get_session_history(db, session_id)
    if history:
        history = history[:-1]  # 排除刚保存的用户消息

    # 6. 创建新 Agent 实例（每次新建，避免缓存污染）
    agent = ReactAgent(extra_tools=mcp_tools, memory_text=memory_text)

    async def event_generator() -> AsyncGenerator[dict, None]:
        """SSE 事件生成器（使用独立 db session）"""
        full_response = []

        async with async_session_maker() as inner_db:
            try:
                yield {"event": "session", "data": session_id}

                # 调用 Agent 异步流式输出
                res_stream = agent.async_execute_stream(req.message, history=history)
                async for chunk in res_stream:
                    if chunk:
                        full_response.append(chunk)
                        yield {"event": "message", "data": chunk}
                        await asyncio.sleep(0.005)

                # 保存 AI 完整回复
                complete_text = "".join(full_response)
                if complete_text:
                    await save_message(inner_db, session_id, "assistant", complete_text)

                # 触发长期记忆总结（后台异步）
                if current_user:
                    try:
                        from services.memory_service import MemoryService
                        memory_service = MemoryService()
                        asyncio.create_task(
                            memory_service.summarize_conversation(
                                inner_db, session_id, current_user.id
                            )
                        )
                    except Exception as e:
                        logger.warning(f"[长期记忆] 总结失败: {e}")

                yield {"event": "done", "data": ""}

            except asyncio.CancelledError:
                partial_text = "".join(full_response)
                if partial_text:
                    await save_message(
                        inner_db, session_id, "assistant",
                        partial_text + "\n\n[用户已停止生成]"
                    )
                    logger.info(f"[聊天接口] 用户停止生成，已保存部分回复（{len(partial_text)} 字符）")
                else:
                    logger.info("[聊天接口] 用户停止生成，无内容可保存")
                raise

            except Exception as e:
                logger.error(f"[聊天接口] 处理消息时出错: {str(e)}", exc_info=True)
                yield {"event": "error", "data": f"处理出错: {str(e)}"}

    return EventSourceResponse(event_generator())


@router.post("/clear")
async def clear_chat(
    req: ClearRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """清空指定会话的聊天记录"""
    session_id = req.session_id or ""

    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    for msg in result.scalars().all():
        await db.delete(msg)
    await db.commit()

    # 使 Redis 缓存失效
    if current_user:
        await RedisCache.invalidate_sessions(current_user.id)

    return {"success": True, "message": "会话已清空", "session_id": session_id}


@router.get("/history")
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取指定会话的历史记录"""
    history = await get_session_history(db, session_id)
    return {
        "success": True,
        "session_id": session_id,
        "messages": history,
    }


@router.get("/sessions")
async def get_user_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前登录用户的所有会话列表（带 Redis 缓存）"""
    if not current_user:
        raise HTTPException(status_code=401, detail="请先登录")

    # 1. 先查 Redis 缓存
    cached = await RedisCache.get_cached_sessions(current_user.id)
    if cached is not None:
        logger.info(f"[Redis] 命中用户 {current_user.id} 会话列表缓存")
        return {"success": True, "sessions": cached}

    # 2. 缓存未命中，查数据库
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(desc(ChatSession.updated_at))
    )
    sessions = result.scalars().all()
    session_list = [
        {
            "session_id": s.session_id,
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sessions
    ]

    # 3. 写入 Redis 缓存
    await RedisCache.cache_sessions(current_user.id, session_list)

    return {
        "success": True,
        "sessions": session_list,
    }