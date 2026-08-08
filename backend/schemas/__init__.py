"""Pydantic 数据模型（请求/响应校验 + 前后端契约）"""
from .common import ResponseBase, PaginationParams, PaginatedResponse
from .auth import UserCreate, UserLogin, Token, TokenPayload, UserResponse
from .chat import (
    ChatRequest,
    ChatResponse,
    ChatMessageSchema,
    ChatSessionSchema,
    ChatHistoryResponse,
    ClearRequest,
)

__all__ = [
    "ResponseBase",
    "PaginationParams",
    "PaginatedResponse",
    "UserCreate",
    "UserLogin",
    "Token",
    "TokenPayload",
    "UserResponse",
    "ChatRequest",
    "ChatResponse",
    "ChatMessageSchema",
    "ChatSessionSchema",
    "ChatHistoryResponse",
    "ClearRequest",
]