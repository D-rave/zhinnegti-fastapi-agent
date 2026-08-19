"""
模型调用重试策略：指数退避 + 可重试失败判定

参照 chat-langchain 的 ModelRetryMiddleware：
- 对"可重试"的模型失败（限流、超时、网关错误、畸形工具调用）做指数退避重试
- 对"不可重试"的失败（参数错误、鉴权失败等）立即抛出，不浪费配额
"""
import asyncio
import re
from typing import Any, Awaitable, Callable

from utils.logger_handler import logger

#: 表示"可重试"的 finish_reason（模型返回了响应但内容不可用）
RETRYABLE_FINISH_REASONS = {
    "MALFORMED_FUNCTION_CALL",  # Gemini：工具调用语法畸形
    "malformed_function_call",
    "tool_call_parse_error",    # 部分厂商：工具调用 JSON 解析失败
}

#: 可重试异常文本标记（覆盖 DashScope / OpenAI 兼容层的常见瞬时错误）
RETRYABLE_ERROR_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "ratelimit",
    "throttling",           # DashScope 限流: Throttling.RateQuota
    "timeout",
    "timed out",
    "connection error",
    "connection reset",
    "bad gateway",
    "gateway time-out",
    "gateway timeout",
    "service unavailable",
    "temporarily unavailable",
    "502",
    "503",
    "504",
)

#: 可重试 HTTP 状态码
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class MalformedResponseError(Exception):
    """模型返回了可重试的畸形响应（重试预算耗尽后抛出）。"""

    pass


def get_finish_reason(response: Any) -> str:
    """从响应中提取 finish_reason（兼容 langchain response_metadata）。"""
    metadata = getattr(response, "response_metadata", None) or {}
    return str(metadata.get("finish_reason", "") or "")


def get_status_code(exc: Exception) -> int | None:
    """从异常中提取 HTTP 状态码（属性 / response 对象 / 错误文本三条路径）。"""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status

    text = str(exc) or exc.__class__.__name__
    status_match = re.search(
        r"\b(?:HTTP|status(?:\s+code)?|error\s+code)[:= ]+"
        r"(429|500|502|503|504)\b",
        text,
        re.IGNORECASE,
    )
    if status_match:
        return int(status_match.group(1))
    return None


def is_retryable_exception(exc: Exception) -> bool:
    """判定异常是否为可重试的瞬时故障。"""
    if get_status_code(exc) in RETRYABLE_STATUS_CODES:
        return True
    text = (str(exc) or exc.__class__.__name__).lower()
    return any(marker in text for marker in RETRYABLE_ERROR_MARKERS)


class ModelRetryPolicy:
    """
    模型调用重试策略（指数退避）。

    用法：
        policy = ModelRetryPolicy(max_retries=2)
        response = await policy.execute(lambda: llm.ainvoke(messages))

    execute 接收一个"返回协程的无参可调用对象"，每次重试都会重新调用它
    （避免重复 await 同一个已失败的协程）。
    """

    def __init__(
        self,
        max_retries: int = 2,
        initial_delay: float = 0.5,
        backoff_factor: float = 2.0,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    def _backoff_delay(self, attempt: int) -> float:
        return self.initial_delay * (self.backoff_factor ** attempt)

    async def execute(
        self,
        call: Callable[[], Awaitable[Any]],
        operation: str = "model_call",
    ) -> Any:
        """
        执行模型调用，对可重试失败做指数退避重试。

        :param call: 无参可调用对象，返回一个协程（lambda: llm.ainvoke(...)）
        :param operation: 操作名（用于日志）
        :raises MalformedResponseError: 畸形响应重试耗尽后抛出
        :raises Exception: 不可重试异常立即抛出；可重试异常耗尽后抛出最后一次异常
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await call()

                finish_reason = get_finish_reason(response)
                if finish_reason in RETRYABLE_FINISH_REASONS:
                    if attempt < self.max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            f"[ModelRetry] {operation} 返回可重试的 "
                            f"finish_reason={finish_reason}，{delay:.1f}s 后重试 "
                            f"({attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise MalformedResponseError(
                        f"模型重试 {self.max_retries} 次后仍返回 {finish_reason}"
                    )

                if attempt > 0:
                    logger.info(f"[ModelRetry] {operation} 第 {attempt + 1} 次尝试成功")
                return response

            except MalformedResponseError:
                raise
            except Exception as exc:
                last_exception = exc
                if not is_retryable_exception(exc):
                    raise
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"[ModelRetry] {operation} 遇到可重试错误: {exc}，"
                        f"{delay:.1f}s 后重试 ({attempt + 1}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # 理论上不会走到（循环内必然 return/raise），防御性兜底
        if last_exception is not None:
            raise last_exception
        raise RuntimeError(f"[ModelRetry] {operation} 未产生任何结果")


__all__ = [
    "ModelRetryPolicy",
    "MalformedResponseError",
    "RETRYABLE_FINISH_REASONS",
    "RETRYABLE_ERROR_MARKERS",
    "RETRYABLE_STATUS_CODES",
    "is_retryable_exception",
    "get_finish_reason",
    "get_status_code",
]