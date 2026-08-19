"""
话题护栏单元测试（对照 chat-langchain test_guardrails_fallback.py 的思路）

核心断言：
1. 主分类模型重试预算耗尽后，备用模型获得自己的完整重试预算
2. 所有模型都失败才抛 GuardrailsClassificationError
3. 分类彻底失败时 check() fail-open 放行，不阻断用户
4. BLOCKED 时生成友好拒绝文案；文案生成失败回退静态文案
"""
import asyncio

import pytest

from agent.middleware.guardrails import (
    FALLBACK_REJECTION_MESSAGE,
    GuardrailsClassificationError,
    GuardrailsService,
    parse_decision,
)


class FakeModel:
    """按队列返回/抛出预设结果的假模型（对照 chat-langchain FakeStructuredModel）。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def ainvoke(self, prompt, config=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeResponse:
    def __init__(self, content):
        self.content = content


def _allowed_json():
    return FakeResponse('{"decision": "ALLOWED", "explanation": "扫地机器人相关问题"}')


def _blocked_json():
    return FakeResponse('{"decision": "BLOCKED", "explanation": "与客服范围无关"}')


# ==================== parse_decision ====================

def test_parse_decision_plain_json():
    decision = parse_decision('{"decision": "BLOCKED", "explanation": "越界"}')
    assert decision["decision"] == "BLOCKED"
    assert decision["explanation"] == "越界"


def test_parse_decision_json_in_markdown():
    """模型输出被 ```json 包裹时也能解析"""
    text = '```json\n{"decision": "ALLOWED", "explanation": "范围内"}\n```'
    assert parse_decision(text)["decision"] == "ALLOWED"


def test_parse_decision_keyword_fallback():
    """无 JSON 时从关键字兜底"""
    assert parse_decision("ALLOWED").__getitem__("decision") == "ALLOWED"
    assert parse_decision("判定结果：BLOCKED")["decision"] == "BLOCKED"


def test_parse_decision_garbage_raises():
    with pytest.raises(ValueError):
        parse_decision("我是一堆无法解析的话")
    with pytest.raises(ValueError):
        parse_decision("")


# ==================== 模型链降级（对照 chat-langchain） ====================

def test_guardrails_falls_back_after_primary_retries():
    """主模型重试耗尽后，备用模型接手并成功"""
    primary = FakeModel([RuntimeError("primary down"), RuntimeError("still down")])
    fallback = FakeModel([_allowed_json()])
    service = GuardrailsService(
        classifier_llms=[("primary", primary), ("fallback", fallback)],
        max_retries=1,
        timeout_seconds=5,
    )

    result = asyncio.run(service.classify("扫地机器人续航多久？"))

    assert result["decision"] == "ALLOWED"
    assert primary.calls == 2   # max_retries=1 → 1 次原始 + 1 次重试
    assert fallback.calls == 1  # 备用模型有自己的完整预算


def test_guardrails_raises_after_all_models_exhausted():
    """所有模型的重试预算都耗尽后才抛 GuardrailsClassificationError"""
    primary = FakeModel([RuntimeError("p1"), RuntimeError("p2")])
    fallback = FakeModel([RuntimeError("f1"), RuntimeError("f2")])
    service = GuardrailsService(
        classifier_llms=[("primary", primary), ("fallback", fallback)],
        max_retries=1,
        timeout_seconds=5,
    )

    with pytest.raises(GuardrailsClassificationError):
        asyncio.run(service.classify("你好"))

    assert primary.calls == 2
    assert fallback.calls == 2


def test_guardrails_unparseable_output_counts_as_failure():
    """模型返回无法解析的内容视为一次分类失败，计入重试预算"""
    primary = FakeModel([FakeResponse("无法解析的乱答"), _allowed_json()])
    service = GuardrailsService(
        classifier_llms=[("primary", primary)], max_retries=1, timeout_seconds=5
    )
    result = asyncio.run(service.classify("扫地机器人怎么清理尘盒？"))
    assert result["decision"] == "ALLOWED"
    assert primary.calls == 2


# ==================== check() 对外行为 ====================

def test_check_fail_open_when_classification_fails():
    """分类彻底失败时放行（fail-open），护栏故障不阻断正常用户"""
    service = GuardrailsService(classifier_llms=[], max_retries=0)
    result = asyncio.run(service.check("扫地机器人推荐"))
    assert result["allowed"] is True
    assert result["rejection"] is None


def test_check_allowed_query_passes():
    service = GuardrailsService(
        classifier_llms=[("fake", FakeModel([_allowed_json()]))], max_retries=0
    )
    result = asyncio.run(service.check("扫地机器人怎么选？"))
    assert result["allowed"] is True
    assert result["decision"]["decision"] == "ALLOWED"


def test_check_blocked_query_returns_rejection():
    """拦截时生成友好拒绝文案（用分类模型生成）"""
    fake = FakeModel([_blocked_json(), FakeResponse("抱歉，我只能解答扫地机器人相关问题～")])
    service = GuardrailsService(
        classifier_llms=[("fake", fake)], max_retries=0, block_off_topic=True
    )
    result = asyncio.run(service.check("帮我写一篇武侠小说"))
    assert result["allowed"] is False
    assert "扫地机器人" in result["rejection"]


def test_check_blocked_rejection_falls_back_to_static():
    """拒绝文案生成失败时回退到静态兜底文案"""
    fake = FakeModel([_blocked_json(), RuntimeError("llm down")])
    service = GuardrailsService(
        classifier_llms=[("fake", fake)], max_retries=0, block_off_topic=True
    )
    result = asyncio.run(service.check("帮我写作业"))
    assert result["allowed"] is False
    assert result["rejection"] == FALLBACK_REJECTION_MESSAGE


def test_block_off_topic_false_observes_only():
    """观测模式：记录拦截判定但仍放行（灰度场景）"""
    fake = FakeModel([_blocked_json()])
    service = GuardrailsService(
        classifier_llms=[("fake", fake)], max_retries=0, block_off_topic=False
    )
    result = asyncio.run(service.check("帮我写代码"))
    assert result["allowed"] is True
    assert result["decision"]["decision"] == "BLOCKED"