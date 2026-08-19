"""模型重试策略单元测试（对照 chat-langchain ModelRetryMiddleware 的思路）"""
import asyncio

import pytest

from agent.middleware.model_retry import (
    MalformedResponseError,
    ModelRetryPolicy,
    is_retryable_exception,
)


class FakeResponse:
    def __init__(self, content="ok", finish_reason=""):
        self.content = content
        self.response_metadata = {"finish_reason": finish_reason} if finish_reason else {}


def test_retryable_exception_detection():
    """可重试错误判定：限流/超时/5xx"""
    assert is_retryable_exception(Exception("HTTP 429 Too Many Requests"))
    assert is_retryable_exception(Exception("Throttling.RateQuota exceeded"))
    assert is_retryable_exception(Exception("request timed out"))
    assert is_retryable_exception(Exception("503 Service Unavailable"))
    assert not is_retryable_exception(Exception("Invalid API Key"))
    assert not is_retryable_exception(ValueError("bad argument"))


def test_success_without_retry():
    """一次成功不重试"""
    calls = []

    async def call():
        calls.append(1)
        return FakeResponse("回答")

    policy = ModelRetryPolicy(max_retries=2, initial_delay=0)
    result = asyncio.run(policy.execute(call, operation="test"))
    assert result.content == "回答"
    assert len(calls) == 1


def test_retryable_error_then_success():
    """瞬时 429 → 退避后重试成功"""
    outcomes = [Exception("HTTP 429 rate limit"), FakeResponse("恢复")]

    async def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    policy = ModelRetryPolicy(max_retries=2, initial_delay=0)
    result = asyncio.run(policy.execute(call))
    assert result.content == "恢复"
    assert len(outcomes) == 0


def test_non_retryable_error_raises_immediately():
    """鉴权失败等不可重试错误立即抛出，不浪费重试预算"""
    calls = []

    async def call():
        calls.append(1)
        raise Exception("Invalid API Key")

    policy = ModelRetryPolicy(max_retries=3, initial_delay=0)
    with pytest.raises(Exception, match="Invalid API Key"):
        asyncio.run(policy.execute(call))
    assert len(calls) == 1


def test_retryable_finish_reason_retried():
    """模型返回畸形 finish_reason（如 MALFORMED_FUNCTION_CALL）触发重试"""
    outcomes = [
        FakeResponse("", finish_reason="MALFORMED_FUNCTION_CALL"),
        FakeResponse("正常回答", finish_reason="stop"),
    ]

    async def call():
        return outcomes.pop(0)

    policy = ModelRetryPolicy(max_retries=2, initial_delay=0)
    result = asyncio.run(policy.execute(call))
    assert result.content == "正常回答"


def test_malformed_response_raises_after_exhaustion():
    """畸形响应重试耗尽后抛 MalformedResponseError"""

    async def call():
        return FakeResponse("", finish_reason="MALFORMED_FUNCTION_CALL")

    policy = ModelRetryPolicy(max_retries=1, initial_delay=0)
    with pytest.raises(MalformedResponseError):
        asyncio.run(policy.execute(call))


def test_retry_exhaustion_raises_last_error():
    """可重试错误耗尽预算后抛出最后一次异常"""

    async def call():
        raise Exception("HTTP 503 Service Unavailable")

    policy = ModelRetryPolicy(max_retries=2, initial_delay=0)
    with pytest.raises(Exception, match="503"):
        asyncio.run(policy.execute(call))