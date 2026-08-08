"""用户管理 API"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.user import User
from schemas.auth import UserResponse
from schemas.common import ResponseBase, DataResponse, PaginatedResponse
from api.deps import get_current_active_user, get_current_user
from crud.user import user as user_crud
from utils.logger_handler import logger

router = APIRouter()


@router.get("/me", response_model=DataResponse[UserResponse])
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取当前登录用户信息"""
    return {"success": True, "data": current_user}


@router.get("/list", response_model=PaginatedResponse[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """获取用户列表（管理员）"""
    users = await user_crud.get_multi(db, skip=skip, limit=limit)
    total = await user_crud.count(db)
    return {
        "success": True,
        "data": users,
        "total": total,
        "page": skip // limit + 1,
        "page_size": limit,
        "total_pages": (total + limit - 1) // limit
    }