"""
对话历史摘要压缩单元测试（对照 chat-langchain test_summarization_middleware_wiring.py）

核心断言：
1. 未超阈值不改写历史
2. 超阈值时老消息被摘要替换，最近消息按 token 预算保留原文
3. 摘要模型失败时退化为截断保留，不中断对话
"""
import asyncio

from agent.middleware.summarization import (
    ConversationSummarizer,
    estimate_tokens,
    history_tokens,
)


class FakeSummaryModel:
    def __init__(self, summary_text="【摘要】用户想要 2000 元价位带集尘功能的扫地机器人。"):
        self.summary_text = summary_text
        self.calls = 0

    async def ainvoke(self, prompt):
        self.calls += 1
        return type("R", (), {"content": self.summary_text})()


def _long_history(msg_count=10, msg_chars=200):
    """构造一段超阈值的长历史"""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "对话" * msg_chars}
        for i in range(msg_count)
    ]


def test_estimate_tokens_chinese():
    """中文按 字符数/2 估算"""
    assert estimate_tokens("扫地机器人") == 2  # 5 字 → 2
    assert estimate_tokens("") >= 1


def test_history_below_threshold_unchanged():
    """历史未超阈值时原样返回"""
    model = FakeSummaryModel()
    summarizer = ConversationSummarizer(
        model=model, trigger_tokens=10_000, keep_tokens=1_000
    )
    history = [{"role": "user", "content": "扫地机器人怎么选？"}]
    result = asyncio.run(summarizer.summarize(history))
    assert result == history
    assert model.calls == 0  # 未触发摘要模型


def test_history_above_threshold_summarized():
    """超阈值：摘要替换老消息 + 保留最近消息"""
    model = FakeSummaryModel()
    summarizer = ConversationSummarizer(
        model=model, trigger_tokens=100, keep_tokens=150
    )
    history = _long_history(msg_count=10, msg_chars=100)
    assert history_tokens(history) > 100

    result = asyncio.run(summarizer.summarize(history))

    assert model.calls == 1
    assert result[0]["role"] == "system"
    assert "此前对话摘要" in result[0]["content"]
    assert model.summary_text in result[0]["content"]
    # 最近消息按 keep 预算保留原文
    assert len(result) > 1
    assert result[-1] == history[-1]
    # 总长度必须小于原历史
    assert len(result) < len(history)


def test_split_respects_keep_budget():
    """保留的最近消息不超出 keep_tokens 预算"""
    summarizer = ConversationSummarizer(
        model=FakeSummaryModel(), trigger_tokens=100, keep_tokens=100
    )
    history = _long_history(msg_count=8, msg_chars=100)  # 每条约 100 tokens
    to_summarize, kept = summarizer.split_for_summary(history)
    assert history_tokens(kept) <= 100 + 100  # 至少保留 1 条，允许单条超预算
    assert len(to_summarize) + len(kept) == len(history)
    assert len(kept) >= 1


def test_summary_failure_degrades_to_truncation():
    """摘要模型故障时退化为只保留最近消息，不抛异常"""
    class BrokenModel:
        async def ainvoke(self, prompt):
            raise RuntimeError("summary model down")

    summarizer = ConversationSummarizer(
        model=BrokenModel(), trigger_tokens=100, keep_tokens=150
    )
    history = _long_history(msg_count=10, msg_chars=100)
    result = asyncio.run(summarizer.summarize(history))
    assert len(result) < len(history)
    assert result[-1] == history[-1]
    assert all(m["role"] != "system" for m in result)


def test_empty_history():
    summarizer = ConversationSummarizer(model=FakeSummaryModel())
    assert asyncio.run(summarizer.summarize(None)) == []
    assert asyncio.run(summarizer.summarize([])) == []