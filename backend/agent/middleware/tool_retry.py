"""
工具调用重试策略：瞬时故障重试 + 模型可读的错误回传

参照 chat-langchain 的 ToolRetryMiddleware：
- 工具抛出瞬时错误（429/5xx/超时/连接重置）时指数退避重试
- 重试耗尽后不抛异常打断 Agent 循环，而是返回"模型可读"的错误文本，
  让模型自行决定换工具、换参数或诚实告知用户
- "未找到结果"属于正常业务结果，不重试
"""
import asyncio
from typing import Awaitable, Callable

from agent.middleware.model_retry import get_status_code
from utils.logger_handler import logger

#: 可重试的工具错误：HTTP 状态码
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

#: 可重试的工具错误文本标记
RETRYABLE_ERROR_MARKERS = (
    "bad gateway",
    "connection error",
    "connection reset",
    "gateway time-out",
    "gateway timeout",
    "service unavailable",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "too many requests",
    "rate limit",
    "throttling",
    "429",
    "502",
    "503",
    "504",
)

#: "无结果"标记：属于正常业务返回，不应重试
NO_RESULTS_MARKERS = (
    "no results found",
    "no result found",
    "未找到相关",
    "暂无结果",
)


class ToolRetryPolicy:
    """
    工具调用重试策略（指数退避）。

    用法：
        policy = ToolRetryPolicy(max_attempts=3)
        result_text = await policy.execute("maps_text_search", lambda: tool.ainvoke(params))
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.5,
        backoff_factor: float = 2.0,
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    def _is_no_results(self, error: Exception) -> bool:
        text = (str(error) or error.__class__.__name__).lower()
        return any(marker in text for marker in NO_RESULTS_MARKERS)

    def _is_retryable(self, error: Exception) -> bool:
        if get_status_code(error) in RETRYABLE_STATUS_CODES:
            return True
        text = (str(error) or error.__class__.__name__).lower()
        return any(marker in text for marker in RETRYABLE_ERROR_MARKERS)

    async def execute(
        self,
        tool_name: str,
        call: Callable[[], Awaitable[str]],
    ) -> str:
        """
        执行工具调用并对瞬时故障重试。

        :return: 工具结果文本；重试耗尽或不可重试时返回模型可读的错误说明
                 （不抛异常，保证 Agent 循环可以继续推理）
        """
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await call()
            except Exception as exc:
                last_error = exc

                if self._is_no_results(exc):
                    # 正常的"无结果"，直接回传模型
                    return f"工具 {tool_name} 未找到相关结果，可尝试更换关键词或告知用户。"

                if not self._is_retryable(exc):
                    logger.error(f"[ToolRetry] 工具 {tool_name} 不可重试错误: {exc}")
                    return (
                        f"工具 {tool_name} 调用失败（非瞬时错误，未重试）: "
                        f"{exc}。请更换方案或如实告知用户。"
                    )

                if attempt < self.max_attempts:
                    delay = self.initial_delay * (2.0 ** (attempt - 1)) \
                        if self.backoff_factor == 2.0 else \
                        self.initial_delay * (self.backoff_factor ** (attempt - 1))
                    logger.warning(
                        f"[ToolRetry] 工具 {tool_name} 瞬时错误: {exc}，"
                        f"{delay:.1f}s 后重试 ({attempt}/{self.max_attempts})"
                    )
                    await asyncio.sleep(delay)

        logger.error(
            f"[ToolRetry] 工具 {tool_name} 重试 {self.max_attempts} 次后仍失败: {last_error}"
        )
        return (
            f"工具 {tool_name} 暂时不可用（已自动重试 {self.max_attempts} 次）: "
            f"{last_error}。请尝试其他工具，或告知用户稍后再试。"
        )


__all__ = [
    "ToolRetryPolicy",
    "RETRYABLE_STATUS_CODES",
    "RETRYABLE_ERROR_MARKERS",
    "NO_RESULTS_MARKERS",
]