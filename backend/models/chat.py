"""
聊天会话与消息模型
实现数据库持久化存储
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from models.db import Base


class ChatSession(Base):
    """会话表：每个用户可以有多个会话"""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 未登录用户可为空
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class ChatMessage(Base):
    """消息表：存储每条对话内容"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.session_id"), index=True, nullable=False)
    role = Column(String(20), nullable=False)      # user / assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())