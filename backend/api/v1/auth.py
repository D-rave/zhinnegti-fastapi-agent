"""认证路由（重构版 - 使用 core/security）"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.common import ResponseBase, DataResponse
from models.db import get_db
from models.user import User
from schemas.auth import UserCreate, Token, UserLogin, UserResponse
from crud.user import user as user_crud
from core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    validate_password_strength,
)
from core.config import get_settings
from api.deps import get_current_user
from utils.logger_handler import logger

router = APIRouter()
settings = get_settings()


@router.post("/register", response_model=ResponseBase)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    valid, msg = validate_password_strength(user_in.password)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    existing = await user_crud.get_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    hashed = get_password_hash(user_in.password)
    await user_crud.create_user(
        db,
        username=user_in.username,
        hashed_password=hashed
    )

    logger.info(f"新用户注册: {user_in.username}")
    return {"success": True, "message": "注册成功"}


@router.post("/login", response_model=Token)
async def login(
    login_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """用户登录（JSON 格式）"""
    user = await user_crud.get_by_username(db, login_data.username)
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    access_token = create_access_token(data={"sub": str(user.id)})
    logger.info(f"用户登录: {user.username}")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.get("/me", response_model=DataResponse[UserResponse])
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """获取当前用户信息"""
    # 【关键】判断管理员身份
    # 方案A：如果数据库有 is_admin 字段
    is_admin = getattr(current_user, 'is_admin', False)

    # 方案B：临时方案 - id 为 1 的用户视为管理员（数据库无 is_admin 字段时使用）
    # is_admin = current_user.id == 1

    return {
        "success": True,
        "data": {
            "id": current_user.id,
            "username": current_user.username,
            "email": getattr(current_user, 'email', None),
            "is_active": current_user.is_active,
            "is_admin": is_admin,           # 【新增】前端 isAdmin 依赖此字段
            "role": "admin" if is_admin else "user"  # 【新增】兼容前端 role 判断
        }
    }