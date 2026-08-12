"""系统配置 API"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from models.user import User
from api.deps import get_current_user
from utils.logger_handler import logger
from core.config import get_settings
from core.dashscope_usage_tracker import usage_tracker

router = APIRouter()
settings = get_settings()


class SystemSettings(BaseModel):
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 0.9
    daily_budget_cny: Optional[float] = None


@router.get("/settings")
async def get_system_settings(current_user=Depends(get_current_user)):
    """获取系统配置（所有登录用户可见）"""
    stats = await usage_tracker.get_stats()  # 【关键】改为 await

    return {
        "success": True,
        "data": {
            "system_prompt": settings.APP_NAME,
            "temperature": 0.7,
            "max_tokens": 2000,
            "top_p": 0.9,
            "daily_budget": stats["daily_budget"],
            "today_cost": stats["daily_spent"],
            "today_calls": stats["total_calls"],
            "app_version": settings.APP_VERSION,
        }
    }


@router.post("/settings")
async def update_system_settings(
    s: SystemSettings,
    current_user=Depends(get_current_user)
):
    """更新系统配置（所有登录用户可见）"""
    if s.daily_budget_cny is not None:
        usage_tracker.set_daily_budget(s.daily_budget_cny)

    logger.info(f"系统配置已更新: temperature={s.temperature}, max_tokens={s.max_tokens}")
    return {"success": True, "message": "配置已更新"}