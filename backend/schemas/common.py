"""通用响应模型"""
from typing import Generic, TypeVar, Optional, List
from pydantic import BaseModel

T = TypeVar("T")


class ResponseBase(BaseModel):
    """统一响应包装"""
    success: bool = True
    message: Optional[str] = None


class DataResponse(ResponseBase, Generic[T]):
    """带数据的响应"""
    data: Optional[T] = None


class PaginationParams(BaseModel):
    """分页参数"""
    page: int = 1
    page_size: int = 20


class PaginatedResponse(ResponseBase, Generic[T]):
    """分页响应"""
    data: List[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0