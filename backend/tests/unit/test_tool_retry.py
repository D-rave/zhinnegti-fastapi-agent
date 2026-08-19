"""工具重试策略单元测试（对照 chat-langchain ToolRetryMiddleware 的思路）"""
import asyncio

from agent.middleware.tool_retry import ToolRetryPolicy


def test_success_first_attempt():
    """工具一次成功"""
    async def call():
        return "搜索结果：3 家门店"

    policy = ToolRetryPolicy(max_attempts=3, initial_delay=0)
    result = asyncio.run(policy.execute("maps_text_search", call))
    assert result == "搜索结果：3 家门店"


def test_transient_error_retried_then_success():
    """瞬时超时错误重试后成功"""
    outcomes = [Exception("Connection timed out"), "武汉小米之家：江汉路店"]

    async def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    policy = ToolRetryPolicy(max_attempts=3, initial_delay=0)
    result = asyncio.run(policy.execute("maps_text_search", call))
    assert "江汉路" in result


def test_retry_exhaustion_returns_model_readable_error():
    """重试耗尽后返回模型可读的错误文本，而不是抛异常打断 Agent 循环"""
    async def call():
        raise Exception("HTTP 503 Service Unavailable")

    policy = ToolRetryPolicy(max_attempts=2, initial_delay=0)
    result = asyncio.run(policy.execute("maps_weather", call))
    assert "maps_weather" in result
    assert "重试" in result
    assert "503" in result


def test_non_retryable_error_not_retried():
    """参数错误等不可重试失败不重试，直接回传模型"""
    calls = []

    async def call():
        calls.append(1)
        raise Exception("Invalid parameter: city is required")

    policy = ToolRetryPolicy(max_attempts=3, initial_delay=0)
    result = asyncio.run(policy.execute("maps_text_search", call))
    assert len(calls) == 1
    assert "未重试" in result


def test_no_results_not_retried():
    """'未找到结果'是正常业务结果，不应重试"""
    calls = []

    async def call():
        calls.append(1)
        raise Exception("no results found")

    policy = ToolRetryPolicy(max_attempts=3, initial_delay=0)
    result = asyncio.run(policy.execute("maps_text_search", call))
    assert len(calls) == 1
    assert "未找到" in result or "no results" in result.lower()


def test_status_code_extraction_retryable():
    """带 status_code 属性的异常按状态码判定"""
    class HttpError(Exception):
        status_code = 429

    outcomes = [HttpError("rate limited"), "ok"]

    async def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    policy = ToolRetryPolicy(max_attempts=2, initial_delay=0)
    result = asyncio.run(policy.execute("tavily_search", call))
    assert result == "ok"