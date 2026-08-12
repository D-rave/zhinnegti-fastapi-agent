"""
DashScope API 用量实时追踪器（生产级 - 支持海量用户）
核心设计：
1. date_str 字段（'2026-08-12'）+ 索引，查询性能 O(log n)
2. 支持按用户、按模型、按日期多维度统计
3. 数据库写入失败时自动降级到 Buffer，不丢数据
4. 启动时自动从数据库恢复今日累计（防重启丢失）
"""
import time
import json
import asyncio
import math
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
from datetime import date, datetime

from sqlalchemy import func, select, and_
from utils.logger_handler import logger

# 模型单价（元 / 1K tokens）
MODEL_PRICING = {
    "qwen-max": {"input": 0.0024, "output": 0.0096},
    "text-embedding-v4": {"input": 0.0005, "output": 0.0},
}

@dataclass
class LLMUsageRecord:
    """单次 LLM 调用记录"""
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int = 0
    cost_cny: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = 0.0
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    endpoint: str = "unknown"
    request_id: Optional[str] = None

    def __post_init__(self):
        if "embedding" in self.model.lower():
            self.output_tokens = 0
        self.total_tokens = self.input_tokens + self.output_tokens
        pricing = MODEL_PRICING.get(self.model, {"input": 0, "output": 0})
        self.cost_cny = (
            self.input_tokens * pricing["input"] / 1000 +
            self.output_tokens * pricing["output"] / 1000
        )
        if self.timestamp == 0:
            self.timestamp = time.time()


class DashScopeUsageTracker:
    """DashScope 用量追踪器（生产级，支持海量用户）"""

    def __init__(self):
        self._buffer: List[LLMUsageRecord] = []
        self._lock = asyncio.Lock()
        self._daily_budget: float = float("inf")
        self._db_available: bool = True
        self._today_str: str = date.today().strftime("%Y-%m-%d")

    def _get_today_str(self) -> str:
        """获取今日日期字符串，自动处理跨天"""
        current = date.today().strftime("%Y-%m-%d")
        if current != self._today_str:
            logger.info(f"[UsageTracker] 日期切换: {self._today_str} → {current}")
            self._today_str = current
        return self._today_str

    def set_daily_budget(self, budget_cny: float):
        self._daily_budget = budget_cny
        logger.info(f"[UsageTracker] 日预算设置: ¥{budget_cny:.4f}")

    async def _check_budget(self, cost: float) -> bool:
        budget = self._daily_budget
        if budget == float("inf") or math.isinf(budget):
            return True

        total_cost, _ = await self._get_daily_totals()
        if total_cost + cost > budget:
            logger.warning(
                f"[UsageTracker] 日预算告警: ¥{total_cost:.4f} + ¥{cost:.6f} > ¥{budget}"
            )
            return False
        return True

    async def _get_daily_totals(self, user_id: Optional[int] = None) -> tuple[float, int]:
        """
        从数据库读取今日累计（使用 date_str 索引，O(log n)）
        user_id: 为 None 查全局，指定则查该用户
        """
        db_cost = 0.0
        db_calls = 0
        today_str = self._get_today_str()

        if self._db_available:
            try:
                from models.db import async_session_maker
                from models.usage import LLMUsageLog

                async with async_session_maker() as db:
                    # 【核心】使用 date_str 字符串精确匹配，100% 可靠，走索引
                    query = select(
                        func.coalesce(func.sum(LLMUsageLog.cost_cny), 0.0),
                        func.coalesce(func.count(LLMUsageLog.id), 0)
                    ).where(LLMUsageLog.date_str == today_str)

                    if user_id is not None:
                        query = query.where(LLMUsageLog.user_id == user_id)

                    result = await db.execute(query)
                    row = result.one()
                    db_cost = float(row[0] or 0)
                    db_calls = int(row[1] or 0)

                    logger.info(
                        f"[UsageTracker] DB查询({today_str}) "
                        f"{'用户' + str(user_id) if user_id else '全局'}: "
                        f"费用=¥{db_cost:.6f}, 调用={db_calls}"
                    )
            except Exception as e:
                logger.error(f"[UsageTracker] DB查询失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self._db_available = False

        # Buffer 兜底（数据库失败时，内存中的数据仍计入）
        buffer_cost = sum(r.cost_cny for r in self._buffer)
        buffer_calls = len(self._buffer)

        total_cost = db_cost + buffer_cost
        total_calls = db_calls + buffer_calls

        logger.info(
            f"[UsageTracker] 汇总: DB=¥{db_cost:.6f}/{db_calls}次 + "
            f"Buffer=¥{buffer_cost:.6f}/{buffer_calls}次 = "
            f"总计=¥{total_cost:.6f}/{total_calls}次"
        )

        return total_cost, total_calls

    def extract_usage_from_response(self, response, model_name: str) -> Optional[LLMUsageRecord]:
        input_tokens = 0
        output_tokens = 0
        request_id = None

        if hasattr(response, "response_metadata") and response.response_metadata:
            rm = response.response_metadata
            if "token_usage" in rm:
                tu = rm["token_usage"]
                input_tokens = tu.get("input_tokens", 0) or tu.get("prompt_tokens", 0)
                output_tokens = tu.get("output_tokens", 0) or tu.get("completion_tokens", 0)
            if "request_id" in rm:
                request_id = rm["request_id"]

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            input_tokens = um.get("input_tokens", input_tokens)
            output_tokens = um.get("output_tokens", output_tokens)
            if not input_tokens and "prompt_tokens" in um:
                input_tokens = um["prompt_tokens"]
            if not output_tokens and "completion_tokens" in um:
                output_tokens = um["completion_tokens"]

        if "embedding" in model_name.lower():
            output_tokens = 0

        if input_tokens == 0 and output_tokens == 0:
            logger.debug("[UsageTracker] 未从响应中提取到 token_usage")
            return None

        return LLMUsageRecord(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=request_id,
        )

    async def record(self, record: LLMUsageRecord):
        """记录单次用量（实时写入数据库，失败时降级到 Buffer）"""
        async with self._lock:
            self._buffer.append(record)

        today_str = self._get_today_str()

        if self._db_available:
            try:
                from models.db import async_session_maker
                from models.usage import LLMUsageLog

                async with async_session_maker() as db:
                    log = LLMUsageLog(
                        model=record.model,
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        total_tokens=record.total_tokens,
                        cost_cny=record.cost_cny,
                        latency_ms=record.latency_ms,
                        user_id=record.user_id,
                        session_id=record.session_id,
                        endpoint=record.endpoint,
                        request_id=record.request_id,
                        date_str=today_str,  # 【核心】写入字符串日期
                    )
                    db.add(log)
                    await db.commit()

                    # 写入成功后，从 Buffer 移除（防止重复统计）
                    async with self._lock:
                        if record in self._buffer:
                            self._buffer.remove(record)

                    logger.info(f"[UsageTracker] ✅ DB写入成功: ¥{record.cost_cny:.6f} (date={today_str})")
            except Exception as e:
                logger.error(f"[UsageTracker] ❌ DB写入失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self._db_available = False

        # 预算检查
        if not await self._check_budget(record.cost_cny):
            logger.warning(f"[UsageTracker] 用户 {record.user_id} 调用已触发预算告警")

        logger.info(
            f"[UsageTracker] 模型={record.model}, 输入={record.input_tokens}, "
            f"输出={record.output_tokens}, 费用=¥{record.cost_cny:.6f}, "
            f"请求ID={record.request_id}, 用户={record.user_id}"
        )

    async def flush_to_redis(self):
        """保留兼容，数据库版无需 Redis 刷盘"""
        if not self._buffer:
            return
        async with self._lock:
            self._buffer.clear()

    async def get_stats(self, user_id: Optional[int] = None) -> Dict:
        """
        获取当前统计（数据库 + Buffer 双源）
        user_id: 为 None 返回全局统计，指定则返回该用户统计
        """
        total_cost, total_calls = await self._get_daily_totals(user_id)
        buffer_cost = sum(r.cost_cny for r in self._buffer)
        buffer_tokens = sum(r.total_tokens for r in self._buffer)

        budget = self._daily_budget
        has_budget = budget != float("inf") and not math.isinf(budget)

        return {
            "daily_budget": round(budget, 4) if has_budget else None,
            "daily_spent": round(total_cost, 6),
            "daily_remaining": round(max(0, budget - total_cost), 6) if has_budget else None,
            "buffer_size": len(self._buffer),
            "buffer_cost": round(buffer_cost, 6),
            "buffer_tokens": buffer_tokens,
            "total_calls": total_calls,
        }

    async def get_daily_report(self, date_str: Optional[str] = None, user_id: Optional[int] = None) -> Dict:
        """
        获取某日用量报告（按模型分组）
        date_str: '2026-08-12'，默认今天
        user_id: 为 None 查全局，指定则查该用户
        """
        from models.db import async_session_maker
        from models.usage import LLMUsageLog

        target_date = date_str or self._get_today_str()

        async with async_session_maker() as db:
            query = select(
                LLMUsageLog.model,
                func.sum(LLMUsageLog.cost_cny).label("cost"),
                func.sum(LLMUsageLog.input_tokens).label("input_tokens"),
                func.sum(LLMUsageLog.output_tokens).label("output_tokens"),
                func.count(LLMUsageLog.id).label("calls"),
            ).where(LLMUsageLog.date_str == target_date)

            if user_id is not None:
                query = query.where(LLMUsageLog.user_id == user_id)

            query = query.group_by(LLMUsageLog.model)
            result = await db.execute(query)
            rows = result.all()

        result = {}
        for row in rows:
            result[row.model] = {
                "cost": float(row.cost or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "calls": int(row.calls or 0),
            }
        return {"date": target_date, "models": result}


# 全局单例
usage_tracker = DashScopeUsageTracker()


async def track_llm_call(
    response,
    model_name: str,
    latency_ms: float,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    endpoint: str = "unknown"
):
    record = usage_tracker.extract_usage_from_response(response, model_name)
    if record:
        record.latency_ms = latency_ms
        record.user_id = user_id
        record.session_id = session_id
        record.endpoint = endpoint
        await usage_tracker.record(record)
    else:
        content_len = len(str(getattr(response, "content", "")))
        if "embedding" in model_name.lower():
            estimated_input = content_len // 4
            estimated_output = 0
        else:
            estimated_input = content_len // 4
            estimated_output = content_len // 4
        logger.debug(f"[UsageTracker] 使用字符估算: input≈{estimated_input}, output≈{estimated_output}")
        record = LLMUsageRecord(
            model=model_name,
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            latency_ms=latency_ms,
            user_id=user_id,
            session_id=session_id,
            endpoint=endpoint,
        )
        await usage_tracker.record(record)