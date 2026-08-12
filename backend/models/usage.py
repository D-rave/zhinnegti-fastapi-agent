from sqlalchemy import Column, Integer, String, Float, DateTime, func, Index
from models.db import Base

class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(50), nullable=False, index=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_cny = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    user_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(100), nullable=True)
    endpoint = Column(String(100), default="unknown")
    request_id = Column(String(100), nullable=True)

    # 【核心】字符串日期字段，用于 SQLite/MySQL 通用精确查询
    date_str = Column(String(10), nullable=False, index=True, default="")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 【性能】联合索引：按用户 + 日期查询
    __table_args__ = (
        Index("idx_usage_user_date", "user_id", "date_str"),
        Index("idx_usage_model_date", "model", "date_str"),
    )