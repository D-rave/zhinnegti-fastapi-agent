"""系统配置 API"""
import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from models.user import User
from api.deps import get_current_user
from utils.logger_handler import logger

router = APIRouter()

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "system.yml")


class SystemSettings(BaseModel):
    """系统设置"""
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 0.9


@router.get("/settings")
async def get_settings(
    current_user: User = Depends(get_current_user)
):
    """获取系统配置"""
    # TODO: 从配置文件或数据库读取
    return {
        "success": True,
        "data": {
            "system_prompt": "你是一个智能客服助手...",
            "temperature": 0.7,
            "max_tokens": 2000,
            "top_p": 0.9
        }
    }


@router.post("/settings")
async def update_settings(
    settings: SystemSettings,
    current_user: User = Depends(get_current_user)
):
    """更新系统配置"""
    # TODO: 保存到配置文件或数据库
    logger.info(f"系统配置已更新: {settings}")
    return {"success": True, "message": "配置已更新"}