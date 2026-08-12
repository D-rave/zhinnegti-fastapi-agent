"""
用量监控大盘 API
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from models.user import User
from api.deps import get_current_user
from core.dashscope_usage_tracker import usage_tracker

router = APIRouter()


class BudgetUpdateRequest(BaseModel):
    daily_budget_cny: float


@router.get("/stats")
async def get_usage_stats(current_user=Depends(get_current_user)):
    """
    获取用量监控大盘数据
    前端字段映射：daily_spent, total_calls, daily_budget, daily_remaining, buffer_cost, buffer_tokens
    """
    stats = await usage_tracker.get_stats()

    return {
        "success": True,
        "data": {
            # 【修复】字段名与前端 AdminView.vue 绑定一致
            "daily_spent": stats["daily_spent"],        # 前端：usageStats.daily_spent
            "total_calls": stats["total_calls"],        # 前端：usageStats.total_calls
            "daily_budget": stats["daily_budget"],      # 前端：usageStats.daily_budget
            "daily_remaining": stats["daily_remaining"], # 前端：usageStats.daily_remaining
            "buffer_cost": stats["buffer_cost"],        # 前端：usageStats.buffer_cost
            "buffer_tokens": stats["buffer_tokens"],    # 前端：usageStats.buffer_tokens
        }
    }


@router.post("/budget")
async def update_daily_budget(
    req: BudgetUpdateRequest,
    current_user=Depends(get_current_user)
):
    """设置日预算"""
    usage_tracker.set_daily_budget(req.daily_budget_cny)
    return {
        "success": True,
        "message": f"日预算已设置为 ¥{req.daily_budget_cny:.2f}",
        "data": {"daily_budget": req.daily_budget_cny}
    }