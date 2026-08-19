"""
入口守卫：截断超长用户输入

参照 chat-langchain 的 IngressGuardsMiddleware：
在请求进入 Agent 循环之前限制用户输入大小，防止超长文本
打爆上下文窗口或产生异常高额 Token 费用。
"""
from typing import Any

from utils.logger_handler import logger

#: 用户单条输入的字符上限（对齐 chat-langchain 的 MAX_MESSAGE_CHARS）
MAX_MESSAGE_CHARS = 50_000


class IngressGuard:
    """入口输入守卫：超长输入截断。"""

    def __init__(self, max_chars: int = MAX_MESSAGE_CHARS):
        self.max_chars = max_chars

    def truncate_text(self, text: str) -> str:
        """纯文本截断，未超限则原样返回。"""
        if not isinstance(text, str):
            return text
        return text[: self.max_chars] if len(text) > self.max_chars else text

    def truncate_content(self, content: Any) -> Any:
        """
        截断消息内容，保留非文本内容块（如图片）。
        支持 str 或 LangChain 多模态 content block 列表。
        """
        if isinstance(content, str):
            return self.truncate_text(content)

        if not isinstance(content, list):
            return content

        remaining = self.max_chars
        changed = False
        truncated: list[Any] = []
        for block in content:
            if isinstance(block, str):
                text = block[:remaining]
                changed = changed or len(text) != len(block)
                truncated.append(text)
                remaining -= len(text)
            elif (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                text = block["text"][:remaining]
                changed = changed or len(text) != len(block["text"])
                truncated.append({**block, "text": text})
                remaining -= len(text)
            else:
                truncated.append(block)
        return truncated if changed else content

    def apply(self, query: str) -> str:
        """对单条用户查询应用入口守卫，发生截断时记录日志。"""
        capped = self.truncate_text(query)
        if capped != query:
            logger.warning(
                f"[IngressGuard] 用户输入超长（{len(query)} 字符），"
                f"已截断至 {self.max_chars} 字符"
            )
        return capped


__all__ = ["IngressGuard", "MAX_MESSAGE_CHARS"]