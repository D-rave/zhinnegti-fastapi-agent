"""聊天相关 CRUD"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from models.chat import ChatSession, ChatMessage
from .base import CRUDBase


class CRUDChatSession(CRUDBase[ChatSession]):
    """会话 CRUD"""

    async def get_by_session_id(self, db: AsyncSession, session_id: str) -> Optional[ChatSession]:
        """根据 session_id 查询"""
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[ChatSession]:
        """获取用户的所有会话"""
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(desc(ChatSession.updated_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    # 【新增】更新会话（用于自动标题生成）
    async def update(self, db: AsyncSession, *, db_obj: ChatSession, obj_in: dict) -> ChatSession:
        """更新会话字段"""
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


class CRUDChatMessage(CRUDBase[ChatMessage]):
    """消息 CRUD"""

    async def get_by_session(
        self,
        db: AsyncSession,
        session_id: str
    ) -> List[ChatMessage]:
        """获取会话的所有消息"""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return result.scalars().all()

    async def delete_by_session(self, db: AsyncSession, session_id: str) -> int:
        """删除会话的所有消息"""
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
        )
        messages = result.scalars().all()
        count = len(messages)
        for msg in messages:
            await db.delete(msg)
        await db.commit()
        return count


chat_session = CRUDChatSession(ChatSession)
chat_message = CRUDChatMessage(ChatMessage)