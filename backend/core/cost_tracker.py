"""
Token 用量统计与成本追踪
支持：按用户/按会话/按接口 统计 Token 消耗与费用
"""
import time
import json
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from functools import wraps

from utils.logger_handler import logger

# 模型单价（元 / 1K tokens）—— 根据阿里云百炼 2026 官方定价调整
MODEL_PRICING = {
    # ===== 对话模型 =====
    "qwen-max": {"input": 0.0024, "output": 0.0096},

    # ===== Embedding 模型（只有输入费用，output 设为 0）=====
    "text-embedding-v4": {"input": 0.0005, "output": 0.0},
}

# 简单问题关键词（用于路由到 cheap model）
SIMPLE_QUERY_PATTERNS = [
    "你好", "在吗", "谢谢", "再见", "拜拜",
    "你是谁", "你能做什么", "介绍一下自己",
    "早上好", "下午好", "晚上好",
]

@dataclass
class TokenUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = 0.0
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    endpoint: Optional[str] = None

    def __post_init__(self):
        # Embedding 模型无输出 Token，强制置 0
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

class CostTracker:
    """全局 Token 用量追踪器"""

    def __init__(self):
        self._usage_buffer: list[TokenUsage] = []
        self._lock = asyncio.Lock()
        self._daily_budget: float = float("inf")  # 日预算，可配置
        self._daily_spent: float = 0.0
        self._last_reset: float = time.time()

    def set_daily_budget(self, budget_cny: float):
        self._daily_budget = budget_cny
        logger.info(f"[Cost] 日预算设置: ¥{budget_cny}")

    def _check_budget(self, cost: float) -> bool:
        """检查是否超预算"""
        now = time.time()
        # 每天重置
        if now - self._last_reset > 86400:
            self._daily_spent = 0.0
            self._last_reset = now

        if self._daily_spent + cost > self._daily_budget:
            logger.warning(f"[Cost] 日预算即将超支: ¥{self._daily_spent:.4f} + ¥{cost:.4f} > ¥{self._daily_budget}")
            return False
        self._daily_spent += cost
        return True

    async def record(self, usage: TokenUsage):
        """记录一次用量"""
        async with self._lock:
            self._usage_buffer.append(usage)

        logger.info(
            f"[Cost] 模型={usage.model}, 输入={usage.input_tokens}, 输出={usage.output_tokens}, "
            f"费用=¥{usage.cost_cny:.6f}, 耗时={usage.latency_ms:.0f}ms, "
            f"用户={usage.user_id}, 接口={usage.endpoint}"
        )

    async def flush_to_redis(self):
        """将缓冲区的用量数据写入 Redis（批量）"""
        from utils.redis_client import get_redis
        try:
            r = await get_redis()
            if not r:
                return

            async with self._lock:
                if not self._usage_buffer:
                    return
                batch = [json.dumps(asdict(u), ensure_ascii=False) for u in self._usage_buffer]
                self._usage_buffer.clear()

            # 写入 Redis List，供后续分析
            key = f"cost:usage:{time.strftime('%Y%m%d')}"
            await r.lpush(key, *batch)
            await r.expire(key, 86400 * 7)  # 保留7天
            logger.info(f"[Cost] 批量写入 {len(batch)} 条用量记录到 Redis")
        except Exception as e:
            logger.warning(f"[Cost] 写入 Redis 失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计"""
        total_cost = sum(u.cost_cny for u in self._usage_buffer)
        total_tokens = sum(u.total_tokens for u in self._usage_buffer)
        return {
            "daily_budget": self._daily_budget,
            "daily_spent": self._daily_spent,
            "buffer_size": len(self._usage_buffer),
            "buffer_cost": round(total_cost, 6),
            "buffer_tokens": total_tokens,
        }

# 全局单例
cost_tracker = CostTracker()


def track_llm_call(model_name: str, endpoint: str = "unknown"):
    """
    装饰器：追踪 LLM 调用的 Token 用量
    用法: @track_llm_call("qwen-max", endpoint="/chat/send")
          @track_llm_call("text-embedding-v4", endpoint="/knowledge/embedding")
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                latency = (time.time() - start) * 1000

                # 尝试从 result 中提取 token 用量
                input_tokens = 0
                output_tokens = 0
                user_id = None
                session_id = None

                # 从 kwargs 中提取用户信息
                if "user_id" in kwargs:
                    user_id = kwargs["user_id"]
                if "session_id" in kwargs:
                    session_id = kwargs["session_id"]

                # Embedding 模型：无输出 Token
                if "embedding" in model_name.lower():
                    input_tokens = kwargs.get("input_tokens", 0)
                    # 尝试从 result 中提取
                    if hasattr(result, "usage_metadata") and result.usage_metadata:
                        um = result.usage_metadata
                        input_tokens = um.get("input_tokens", 0) or um.get("total_tokens", 0)
                    output_tokens = 0
                else:
                    # 从 LangChain 响应中提取 token 用量（对话模型）
                    if hasattr(result, "usage_metadata") and result.usage_metadata:
                        um = result.usage_metadata
                        input_tokens = um.get("input_tokens", 0)
                        output_tokens = um.get("output_tokens", 0)
                    elif hasattr(result, "response_metadata") and result.response_metadata:
                        rm = result.response_metadata
                        if "token_usage" in rm:
                            tu = rm["token_usage"]
                            input_tokens = tu.get("prompt_tokens", 0)
                            output_tokens = tu.get("completion_tokens", 0)

                usage = TokenUsage(
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    user_id=user_id,
                    session_id=session_id,
                    endpoint=endpoint,
                )
                asyncio.create_task(cost_tracker.record(usage))
                return result
            except Exception as e:
                logger.error(f"[Cost] 追踪失败: {e}")
                raise
        return wrapper
    return decorator


def should_use_cheap_model(query: str) -> bool:
    """
    模型路由：判断是否应该使用廉价模型
    规则：简单问候、短查询、无工具调用意图
    """
    query = query.strip().lower()

    # 规则1：匹配简单问候关键词
    for pattern in SIMPLE_QUERY_PATTERNS:
        if pattern in query:
            return True

    # 规则2：查询过短（< 10 字符）且无复杂意图词
    if len(query) < 10:
        complex_keywords = ["查询", "搜索", "路线", "天气", "维修", "故障", "价格", "推荐", "比较"]
        if not any(kw in query for kw in complex_keywords):
            return True

    # 规则3：纯标点或空查询
    if not query or query in ["？", "?", "。", ".", "！"]:
        return True

    return False


class ModelRouter:
    """
    模型路由器：根据查询复杂度自动选择模型
    当前仅配置 qwen-max（对话）与 text-embedding-v4（向量化）
    """

    def __init__(self):
        self.chat_model = "qwen-max"
        self.embedding_model = "text-embedding-v4"

    def select_model(self, query: str, force_model: Optional[str] = None) -> str:
        """选择对话模型"""
        if force_model:
            return force_model
        # 当前只有一个对话模型，所有查询均路由到 qwen-max
        return self.chat_model

    def select_embedding_model(self) -> str:
        """选择 Embedding 模型"""
        return self.embedding_model

    def select_model_for_agent(self, query: str, step: int = 1) -> str:
        """
        Agent 多步推理中的模型选择
        当前只有一个对话模型，所有步骤均使用 qwen-max
        """
        return self.chat_model


# 全局路由器
model_router = ModelRouter()