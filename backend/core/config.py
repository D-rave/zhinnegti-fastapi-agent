"""Pydantic Settings 统一管理配置"""
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # 应用
    APP_NAME: str = "智扫通智能客服"
    APP_VERSION: str = "3.0.0"
    DEBUG: bool = False

    # 数据库
    DB_TYPE: str = "sqlite"
    DB_HOST: Optional[str] = "localhost"
    DB_PORT: int = 3306
    DB_USER: Optional[str] = "root"
    DB_PASSWORD: Optional[str] = ""
    DB_NAME: Optional[str] = "zhinengti"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None

    # JWT
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # API Key
    AMAP_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # 限流
    RATE_LIMIT_PER_MINUTE: int = 60

    # 文件上传
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS: str = ".pdf,.txt,.docx,.md"

    # Pydantic V2 配置方式
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    @property
    def cors_origins_list(self) -> list:
        """解析 CORS 来源列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_extensions_list(self) -> list:
        """解析允许的文件扩展名"""
        return [ext.strip().lower() for ext in self.ALLOWED_EXTENSIONS.split(",") if ext.strip()]


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()