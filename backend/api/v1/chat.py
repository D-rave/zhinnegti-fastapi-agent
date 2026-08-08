"""聊天 API（重构版）"""
import asyncio
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db, async_session_maker
from models.chat import ChatSession, ChatMessage
from models.user import User
from schemas.chat import ChatRequest, ChatHistoryResponse, ClearRequest, SessionListResponse
from schemas.common import ResponseBase
from crud.chat import chat_session as session_crud, chat_message as message_crud
from agent.react_agent import ReactAgent
from services.memory_vector_service import MemoryVectorService
from utils.redis_client import RedisCache
from utils.logger_handler import logger
from api.deps import get_current_user, get_current_user_optional

router = APIRouter()

memory_vector_service = MemoryVectorService()


async def get_or_create_session(
        session_id: str,
        user_id: int,
        db: AsyncSession
) -> ChatSession:
    """获取或创建会话"""
    if session_id:
        session = await session_crud.get_by_session_id(db, session_id)
        if session:
            return session

    # 创建新会话
    new_session = await session_crud.create(db, obj_in={
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": "新对话"
    })
    return new_session


@router.post("/send")
async def chat_send(
        req: ChatRequest,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user_optional)
):
    """发送消息（SSE 流式）"""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    user_id = current_user.id if current_user else None
    session = await get_or_create_session(req.session_id, user_id, db)
    session_id = session.session_id

    # 保存用户消息
    await message_crud.create(db, obj_in={
        "session_id": session_id,
        "role": "user",
        "content": req.message
    })

    # 获取 MCP 工具
    mcp_tools = getattr(request.app.state, "mcp_tools", []) or []

    # 获取记忆
    memory_text = ""
    if current_user:
        memory_text = memory_vector_service.retrieve_for_query(
            current_user.id, req.message, k=3
        )

    # 获取历史
    history = await message_crud.get_by_session(db, session_id)
    history = [{"role": m.role, "content": m.content} for m in history[:-1]]

    agent = ReactAgent(extra_tools=mcp_tools, memory_text=memory_text)

    async def event_generator() -> AsyncGenerator[dict, None]:
        full_response = []

        async with async_session_maker() as inner_db:
            try:
                yield {"event": "session", "data": session_id}

                res_stream = agent.async_execute_stream(req.message, history=history)

                # ========== 【修改】透传 Agent 已清理过的流式输出 ==========
                # V4.4 Agent 已经不会把 TOOL_CALL 等中间过程暴露给前端
                # 这里直接透传，不再做模糊过滤（避免误伤正常回答里的"思考"等词）
                async for chunk in res_stream:
                    if not chunk:
                        continue

                    stripped = chunk.strip()
                    if stripped:
                        full_response.append(chunk)
                        yield {"event": "message", "data": chunk}
                        await asyncio.sleep(0.005)
                # ========== 透传结束 ==========

                complete_text = "".join(full_response)
                if complete_text:
                    await message_crud.create(inner_db, obj_in={
                        "session_id": session_id,
                        "role": "assistant",
                        "content": complete_text
                    })

                # 触发记忆总结
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
                        logger.warning(f"记忆总结失败: {e}")

                yield {"event": "done", "data": ""}

            except asyncio.CancelledError:
                partial = "".join(full_response)
                if partial:
                    await message_crud.create(inner_db, obj_in={
                        "session_id": session_id,
                        "role": "assistant",
                        "content": partial + "\n\n[用户已停止生成]"
                    })
                raise

            except Exception as e:
                logger.error(f"聊天处理错误: {e}", exc_info=True)
                yield {"event": "error", "data": f"处理出错: {str(e)}"}

    # ========== 【修改】添加防缓冲头，确保 Nginx/代理不缓存 SSE ==========
    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，关键！
        }
    )


@router.post("/clear", response_model=ResponseBase)
async def clear_chat(
        req: ClearRequest,
        current_user: User = Depends(get_current_user_optional),
        db: AsyncSession = Depends(get_db)
):
    """清空会话"""
    count = await message_crud.delete_by_session(db, req.session_id)

    if current_user:
        await RedisCache.invalidate_sessions(current_user.id)

    return {"success": True, "message": f"已清空 {count} 条消息"}


@router.get("/history", response_model=ChatHistoryResponse)
async def get_history(
        session_id: str,
        current_user: User = Depends(get_current_user_optional),
        db: AsyncSession = Depends(get_db)
):
    """获取历史记录"""
    messages = await message_crud.get_by_session(db, session_id)
    return {
        "success": True,
        "session_id": session_id,
        "messages": [{"role": m.role, "content": m.content} for m in messages]
    }


@router.get("/sessions", response_model=SessionListResponse)
async def get_sessions(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """获取会话列表"""
    if not current_user:
        raise HTTPException(status_code=401, detail="请先登录")

    # 查缓存
    cached = await RedisCache.get_cached_sessions(current_user.id)
    if cached is not None:
        return {"success": True, "sessions": cached}

    # 查数据库
    sessions = await session_crud.get_by_user(db, current_user.id)
    session_list = [
        {
            "session_id": s.session_id,
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        }
        for s in sessions
    ]

    # 写缓存
    await RedisCache.cache_sessions(current_user.id, session_list)

    return {"success": True, "sessions": session_list}