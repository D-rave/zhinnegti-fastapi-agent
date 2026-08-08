"""聊天相关数据模型"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChatMessageSchema(BaseModel):
    """单条消息"""
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChatSessionSchema(BaseModel):
    """会话信息"""
    session_id: str
    title: str = "新对话"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    """发送消息请求"""
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    session_id: str = Field(default="", description="会话ID，空则创建新会话")


class ChatResponse(BaseModel):
    """流式响应中的完整回复（非流式接口用）"""
    session_id: str
    message: str


class ChatHistoryResponse(BaseModel):
    """历史记录响应"""
    success: bool = True
    session_id: str
    messages: List[ChatMessageSchema] = []


class ClearRequest(BaseModel):
    """清空会话请求"""
    session_id: str = Field(..., description="要清空的会话ID")


class SessionListResponse(BaseModel):
    """会话列表响应"""
    success: bool = True
    sessions: List[ChatSessionSchema] = []