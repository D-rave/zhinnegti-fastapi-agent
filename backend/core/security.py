"""安全工具函数（使用 bcrypt 直接替代 passlib，避免版本兼容问题）"""
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt

from .config import get_settings

settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    plain_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(plain_bytes, hash_bytes)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    # bcrypt 自动处理 salt，密码超过 72 字节会自动截断
    password_bytes = password.encode('utf-8')
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    密码强度校验
    返回: (是否通过, 错误信息)
    """
    if len(password) < 6:
        return False, "密码长度至少 6 位"
    if len(password) > 128:
        return False, "密码长度不能超过 128 位"
    return True, ""