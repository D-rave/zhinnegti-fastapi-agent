"""模型降级链单元测试（对照 chat-langchain ModelFallbackMiddleware 的思路）"""
import asyncio

import pytest

from agent.middleware.model_fallback import FallbackChatModel
from agent.middleware.model_retry import ModelRetryPolicy


class FakeChatModel:
    """假聊天模型：按队列抛出/返回结果，记录调用次数。"""

    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0
        self.bound_tools = None

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def bind_tools(self, tools, **kwargs):
        clone = FakeChatModel(self.name, self.outcomes)
        clone.bound_tools = list(tools)
        return clone


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _fast_retry():
    return ModelRetryPolicy(max_retries=1, initial_delay=0)


def test_primary_model_succeeds():
    """主模型正常时不触碰备用模型"""
    primary = FakeChatModel("primary", [FakeResponse("主模型回答")])
    fallback = FakeChatModel("fallback", [FakeResponse("备用回答")])
    chain = FallbackChatModel(
        [("primary", primary), ("fallback", fallback)], retry_policy=_fast_retry()
    )

    result = asyncio.run(chain.ainvoke([]))
    assert result.content == "主模型回答"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert chain.model_name == "primary"


def test_fallback_after_primary_exhausts_retries():
    """主模型重试耗尽后切换备用模型，备用模型享有完整重试预算"""
    primary = FakeChatModel("primary", [Exception("HTTP 429"), Exception("HTTP 429")])
    fallback = FakeChatModel("fallback", [Exception("HTTP 503"), FakeResponse("备用恢复")])
    chain = FallbackChatModel(
        [("primary", primary), ("fallback", fallback)], retry_policy=_fast_retry()
    )

    result = asyncio.run(chain.ainvoke([]))
    assert result.content == "备用恢复"
    assert primary.calls == 2   # 自己的完整重试预算
    assert fallback.calls == 2  # 备用模型也有自己的完整预算


def test_all_models_fail_raises_last():
    """链上所有模型失败时抛出最后一次异常"""
    primary = FakeChatModel("primary", [Exception("HTTP 500")] * 2)
    fallback = FakeChatModel("fallback", [Exception("HTTP 503")] * 2)
    chain = FallbackChatModel(
        [("primary", primary), ("fallback", fallback)], retry_policy=_fast_retry()
    )

    with pytest.raises(Exception, match="503"):
        asyncio.run(chain.ainvoke([]))


def test_bind_tools_returns_new_chain_with_bound_models():
    """bind_tools 后链上每个模型都绑定了同样的工具"""
    primary = FakeChatModel("primary", [FakeResponse("ok")])
    fallback = FakeChatModel("fallback", [FakeResponse("ok")])
    chain = FallbackChatModel([("primary", primary), ("fallback", fallback)])

    bound = chain.bind_tools(["tool_a", "tool_b"])

    assert bound is not chain
    assert all(m.bound_tools == ["tool_a", "tool_b"] for _, m in bound.models)


def test_empty_chain_rejected():
    with pytest.raises(ValueError):
        FallbackChatModel([])