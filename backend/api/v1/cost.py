"""成本统计 API"""
from fastapi import APIRouter, Depends
from core.cost_tracker import cost_tracker
from api.deps import get_current_user

router = APIRouter()

@router.get("/stats")
async def get_cost_stats(current_user=Depends(get_current_user)):
    """获取当前 Token 用量统计"""
    stats = cost_tracker.get_stats()
    return {
        "success": True,
        "data": stats
    }