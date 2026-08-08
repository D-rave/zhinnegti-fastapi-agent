"""知识库管理 API（面向用户的知识库查询接口）"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import get_db
from models.user import User
from api.deps import get_current_user
from rag.rag_service import RagSummarizeService  # ← 修正：原来是 RAGService
from utils.logger_handler import logger

router = APIRouter()

rag_service = RagSummarizeService()


@router.post("/query")
async def query_knowledge(
    query: str,
    top_k: int = 5,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    直接查询知识库（不经过 Agent）
    用于测试知识库检索效果
    """
    try:
        result = rag_service.rag_summarize(query)
        return {
            "success": True,
            "data": {
                "query": query,
                "result": result
            }
        }
    except Exception as e:
        logger.error(f"知识库查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))