"""
长期记忆模型：用户画像、对话摘要、关键事实
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from models.db import Base


class UserProfile(Base):
    """用户画像：长期记忆的关键事实"""
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    category = Column(String(50), nullable=False)  # identity, preference, fact, skill
    content = Column(Text, nullable=False)           # 记忆内容
    source_session = Column(String(64))             # 来源会话
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class ConversationSummary(Base):
    """对话摘要：每个会话的总结"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.session_id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    summary = Column(Text, nullable=False)          # 会话核心内容摘要
    key_facts = Column(Text)                         # 提取的关键事实（JSON）
    created_at = Column(DateTime(timezone=True), server_default=func.now())