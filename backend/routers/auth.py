"""认证路由（重构版 - 使用 core/security）"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.user import User
from schemas.auth import UserCreate, Token
from schemas.common import ResponseBase
from crud.user import user as user_crud
from core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    validate_password_strength,
)
from core.config import get_settings
from utils.logger_handler import logger

router = APIRouter(prefix="/auth", tags=["认证"])
settings = get_settings()


@router.post("/register", response_model=ResponseBase)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册（带密码强度校验）"""
    # 密码强度校验
    valid, msg = validate_password_strength(user_in.password)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    # 检查用户名
    existing = await user_crud.get_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 检查邮箱
    if user_in.email:
        existing_email = await user_crud.get_by_email(db, user_in.email)
        if existing_email:
            raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 创建用户
    hashed = get_password_hash(user_in.password)
    await user_crud.create_user(
        db,
        username=user_in.username,
        email=user_in.email,
        hashed_password=hashed
    )

    logger.info(f"新用户注册: {user_in.username}")
    return {"success": True, "message": "注册成功"}


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """用户登录"""
    user = await user_crud.get_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
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