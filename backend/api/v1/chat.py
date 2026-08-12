"""聊天 API（重构版 + DashScope 用量追踪 + 输入净化 + 自动标题生成）"""
import asyncio
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

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
from core.security_enhanced import InputSanitizer

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

    new_session = await session_crud.create(db, obj_in={
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": "新对话"
    })
    return new_session


# ========== 自动标题生成 ==========
async def generate_session_title(db: AsyncSession, session_id: str, first_message: str) -> str:
    """
    用 LLM 根据第一条用户消息生成会话标题
    标题要求：10字以内，简洁明了
    """
    try:
        from model.factory import chat_model

        prompt = f"""请根据用户的提问，生成一个简短的会话标题（10字以内）。
要求：不要加标点符号，不要加"咨询""关于"等前缀，直接描述核心主题。

用户提问：{first_message[:100]}

标题："""

        response = await chat_model.ainvoke(prompt)
        title = response.content if hasattr(response, "content") else str(response)

        title = title.strip().replace('"', '').replace("'", "").replace("《", "").replace("》", "")
        if len(title) > 15:
            title = title[:15]
        if not title:
            title = "新对话"

        logger.info(f"[TitleGen] 会话 {session_id} 生成标题: {title}")
        return title
    except Exception as e:
        logger.warning(f"[TitleGen] 生成标题失败: {e}")
        return "新对话"


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

    safe_message = InputSanitizer.sanitize(req.message, max_length=2000, context="chat")
    if not safe_message:
        raise HTTPException(status_code=400, detail="消息内容包含非法字符或为空")

    log_safe = InputSanitizer.mask_sensitive_for_log(safe_message[:50])
    logger.info(f"[Chat] 用户 {current_user.id if current_user else 'anon'} 发送消息: {log_safe}")

    user_id = current_user.id if current_user else None
    session = await get_or_create_session(req.session_id, user_id, db)
    session_id = session.session_id
    is_new_session = session.title == "新对话"

    await message_crud.create(db, obj_in={
        "session_id": session_id,
        "role": "user",
        "content": safe_message
    })

    mcp_tools = getattr(request.app.state, "mcp_tools", []) or []

    memory_text = ""
    if current_user:
        memory_text = await memory_vector_service.retrieve_for_query_async(
            current_user.id, safe_message, k=3
        )

    history = await message_crud.get_by_session(db, session_id)
    history = [{"role": m.role, "content": m.content} for m in history]
    if history and history[-1].get("role") == "user":
        history = history[:-1]

    agent = ReactAgent(
        extra_tools=mcp_tools,
        memory_text=memory_text,
        user_id=user_id,
        session_id=session_id
    )

    async def event_generator() -> AsyncGenerator[dict, None]:
        full_response = []
        chunk_count = 0

        async with async_session_maker() as inner_db:
            try:
                yield {"event": "session", "data": session_id}
                logger.info(f"[event_generator] session 已发送: {session_id}")

                res_stream = agent.async_execute_stream(safe_message, history=history)

                async for chunk in res_stream:
                    if not chunk:
                        continue

                    stripped = chunk.strip()
                    if stripped:
                        full_response.append(chunk)
                        chunk_count += 1
                        logger.info(f"[event_generator] 第 {chunk_count} 个 chunk, 长度: {len(chunk)}")
                        yield {"event": "message", "data": chunk}
                        await asyncio.sleep(0.005)

                complete_text = "".join(full_response)
                logger.info(f"[event_generator] 流式完成, 共 {chunk_count} 个 chunk, 总长度: {len(complete_text)}")

                if complete_text:
                    await message_crud.create(inner_db, obj_in={
                        "session_id": session_id,
                        "role": "assistant",
                        "content": complete_text
                    })

                # ========== 自动标题生成 ==========
                if is_new_session and complete_text and current_user:
                    user_msg_count = await inner_db.scalar(
                        select(func.count(ChatMessage.id)).where(
                            ChatMessage.session_id == session_id,
                            ChatMessage.role == "user"
                        )
                    )
                    if user_msg_count == 1:
                        title = await generate_session_title(inner_db, session_id, safe_message)
                        # 【关键修复】在 inner_db 中重新查询 session 对象，避免跨 Session 绑定错误
                        session_in_inner = await session_crud.get_by_session_id(inner_db, session_id)
                        if session_in_inner:
                            await session_crud.update(
                                inner_db,
                                db_obj=session_in_inner,
                                obj_in={"title": title}
                            )
                            await RedisCache.invalidate_sessions(current_user.id)
                            logger.info(f"[TitleGen] 会话 {session_id} 标题已更新: {title}")
                # =======================================

                if current_user and complete_text:
                    try:
                        from services.memory_service import MemoryService
                        memory_service = MemoryService()

                        async def _do_summarize():
                            async with async_session_maker() as summary_db:
                                try:
                                    await memory_service.summarize_conversation(
                                        summary_db, session_id, current_user.id
                                    )
                                except Exception as e:
                                    logger.warning(f"记忆总结失败: {e}")

                        asyncio.create_task(_do_summarize())
                    except Exception as e:
                        logger.warning(f"记忆总结任务创建失败: {e}")

                yield {"event": "done", "data": ""}
                logger.info("[event_generator] done 事件已发送")

            except asyncio.CancelledError:
                partial = "".join(full_response)
                logger.info(f"[event_generator] 用户取消, 已收到 {chunk_count} 个 chunk, 部分长度: {len(partial)}")
                if partial:
                    await message_crud.create(inner_db, obj_in={
                        "session_id": session_id,
                        "role": "assistant",
                        "content": partial + "\n\n[用户已停止生成]"
                    })
                raise

            except Exception as e:
                logger.error(f"[event_generator] 聊天处理错误: {e}", exc_info=True)
                yield {"event": "error", "data": f"处理出错: {str(e)}"}

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
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

    cached = await RedisCache.get_cached_sessions(current_user.id)
    if cached is not None:
        return {"success": True, "sessions": cached}

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

    await RedisCache.cache_sessions(current_user.id, session_list)

    return {"success": True, "sessions": session_list}