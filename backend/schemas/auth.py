"""认证相关数据模型"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class UserBase(BaseModel):
    """用户基础信息"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")


class UserCreate(UserBase):
    """用户注册请求"""
    password: str = Field(..., min_length=6, max_length=128, description="密码")


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserResponse(UserBase):
    """用户信息响应"""
    id: int
    is_active: bool = True
    is_admin: bool = False          # 【新增】管理员标识
    role: str = "user"              # 【新增】用户角色

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class TokenPayload(BaseModel):
    """Token 载荷"""
    sub: Optional[int] = None
    exp: Optional[int] = None