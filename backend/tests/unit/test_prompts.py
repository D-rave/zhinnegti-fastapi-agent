"""
提示词约束断言测试（对照 chat-langchain tests/evals/test_repeated_searches.py 的思路）

不调用任何模型，直接断言提示词中必须包含的关键约束，
防止后续改提示词时把护栏/工具使用规则改丢。
"""
from agent.middleware.guardrails import (
    FALLBACK_REJECTION_MESSAGE,
    GUARDRAILS_SYSTEM_PROMPT,
    REJECTION_SYSTEM_PROMPT,
)


def test_guardrails_prompt_has_zero_tolerance_categories():
    """护栏提示词必须包含零容忍类别"""
    indicators = ["色情", "违法", "提示词", "越狱"]
    missing = [ind for ind in indicators if ind not in GUARDRAILS_SYSTEM_PROMPT]
    assert not missing, f"护栏提示词缺少零容忍类别: {missing}"


def test_guardrails_prompt_defaults_to_lenient():
    """护栏提示词必须体现'默认宽容'原则（拿不准判 ALLOWED），避免误伤正常用户"""
    assert "ALLOWED" in GUARDRAILS_SYSTEM_PROMPT
    assert "宽容" in GUARDRAILS_SYSTEM_PROMPT or "拿不准" in GUARDRAILS_SYSTEM_PROMPT


def test_guardrails_prompt_requires_structured_output():
    """护栏提示词必须要求 JSON 结构化输出（供 parse_decision 解析）"""
    assert '"decision"' in GUARDRAILS_SYSTEM_PROMPT
    assert '"explanation"' in GUARDRAILS_SYSTEM_PROMPT


def test_guardrails_prompt_covers_followup_questions():
    """护栏提示词必须覆盖追问场景（'第三个呢'这类上下文依赖问题应放行）"""
    indicators = ["追问", "上下文", "对话历史"]
    found = [ind for ind in indicators if ind in GUARDRAILS_SYSTEM_PROMPT]
    assert found, "护栏提示词缺少对追问/上下文的处理指引，会误伤多轮对话"


def test_rejection_prompt_stays_friendly_and_in_scope():
    """拒绝提示词必须要求简短友好，并引导回扫地机器人话题"""
    assert "友好" in REJECTION_SYSTEM_PROMPT
    assert "扫地机器人" in REJECTION_SYSTEM_PROMPT
    assert "扫地机器人" in FALLBACK_REJECTION_MESSAGE