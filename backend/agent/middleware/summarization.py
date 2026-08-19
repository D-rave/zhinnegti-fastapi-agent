"""
对话历史摘要压缩：防止长对话撑爆上下文窗口

参照 chat-langchain 的 SummarizationMiddleware：
- 历史估算 token 超过 trigger 阈值时触发摘要
- 用摘要替换老消息，保留最近 keep 阈值内的消息原文
- 摘要模型独立于主模型（带重试/降级），摘要失败时退化为"只保留最近消息"，
  绝不因为摘要失败而中断对话
"""
from typing import Any, Optional

from utils.logger_handler import logger

#: 默认触发摘要的历史 token 阈值（中文按 字符数/2 估算）
DEFAULT_TRIGGER_TOKENS = 8_000

#: 摘要后保留的最近消息 token 预算
DEFAULT_KEEP_TOKENS = 2_000

SUMMARY_PROMPT = """请将以下对话历史压缩为一段简洁的摘要，保留：
1. 用户的核心需求和偏好（预算、户型、品牌倾向等）
2. 已确认的关键事实和结论
3. 尚未解决的问题

只输出摘要本身，不要加"摘要："等前缀。

对话历史：
{messages}"""


def estimate_tokens(text: str) -> int:
    """估算文本 token 数（中文为主，按 字符数/2 保守估计，与 embedding 估算口径一致）。"""
    return max(1, len(text) // 2)


def history_tokens(history: list[dict]) -> int:
    """估算整段历史的 token 数。"""
    return sum(estimate_tokens(str(h.get("content", ""))) for h in history)


class ConversationSummarizer:
    """
    对话历史摘要器。

    :param model: 用于生成摘要的模型（需有 ainvoke）；None 时懒加载默认模型
    :param trigger_tokens: 历史 token 超过该值才触发摘要
    :param keep_tokens: 摘要后保留最近消息的 token 预算
    """

    def __init__(
        self,
        model: Optional[Any] = None,
        trigger_tokens: int = DEFAULT_TRIGGER_TOKENS,
        keep_tokens: int = DEFAULT_KEEP_TOKENS,
        summary_prompt: str = SUMMARY_PROMPT,
    ):
        self._model = model
        self.trigger_tokens = trigger_tokens
        self.keep_tokens = keep_tokens
        self.summary_prompt = summary_prompt

    @property
    def model(self):
        """懒加载摘要模型，避免模块 import 时初始化外部依赖。"""
        if self._model is None:
            from model.factory import chat_model

            self._model = chat_model
        return self._model

    def needs_summary(self, history: Optional[list[dict]]) -> bool:
        if not history:
            return False
        return history_tokens(history) > self.trigger_tokens

    def split_for_summary(self, history: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        把历史切成 (待摘要的老消息, 保留原文的最近消息)。
        从后往前累积最近消息，直到达到 keep_tokens 预算。
        """
        kept: list[dict] = []
        budget = self.keep_tokens
        for msg in reversed(history):
            cost = estimate_tokens(str(msg.get("content", "")))
            if kept and budget - cost < 0:
                break
            kept.append(msg)
            budget -= cost
        kept.reverse()
        to_summarize = history[: len(history) - len(kept)]
        return to_summarize, kept

    def _format_history(self, messages: list[dict]) -> str:
        lines = []
        for m in messages:
            role = {"user": "用户", "assistant": "客服"}.get(
                m.get("role", ""), m.get("role", "未知")
            )
            lines.append(f"{role}: {m.get('content', '')}")
        return "\n".join(lines)

    async def _create_summary(self, messages_to_summarize: list[dict]) -> str:
        """调用摘要模型生成摘要，失败时抛出（由上层兜底）。"""
        formatted = self._format_history(messages_to_summarize)
        prompt = self.summary_prompt.format(messages=formatted).rstrip()
        response = await self.model.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip()

    async def summarize(self, history: Optional[list[dict]]) -> list[dict]:
        """
        压缩对话历史。

        - 未超阈值：原样返回
        - 超阈值：返回 [摘要 system 消息] + [最近保留消息]
        - 摘要失败：退化为只保留最近消息（截断），不中断对话
        """
        if not history or not self.needs_summary(history):
            return list(history) if history else []

        to_summarize, kept = self.split_for_summary(history)
        if not to_summarize:
            return list(history)

        try:
            summary_text = await self._create_summary(to_summarize)
            logger.info(
                f"[Summarizer] 历史 {history_tokens(history)} tokens 超阈值 "
                f"{self.trigger_tokens}，已摘要 {len(to_summarize)} 条老消息，"
                f"保留最近 {len(kept)} 条"
            )
            return [
                {
                    "role": "system",
                    "content": f"【此前对话摘要】{summary_text}",
                },
                *kept,
            ]
        except Exception as exc:
            logger.error(f"[Summarizer] 摘要生成失败，退化为截断保留: {exc}")
            return kept


__all__ = [
    "ConversationSummarizer",
    "estimate_tokens",
    "history_tokens",
    "SUMMARY_PROMPT",
    "DEFAULT_TRIGGER_TOKENS",
    "DEFAULT_KEEP_TOKENS",
]