"""入口守卫单元测试（对照 chat-langchain test_ingress_guards_middleware.py 的思路）"""
from agent.middleware.ingress_guards import IngressGuard, MAX_MESSAGE_CHARS


def test_short_text_passes_through():
    """未超限的文本原样返回"""
    guard = IngressGuard(max_chars=100)
    assert guard.apply("扫地机器人怎么选？") == "扫地机器人怎么选？"


def test_oversized_text_is_truncated():
    """超长文本截断到上限"""
    guard = IngressGuard(max_chars=10)
    result = guard.apply("x" * 100)
    assert result == "x" * 10
    assert len(result) == 10


def test_default_cap_matches_chat_langchain():
    """默认上限对齐 chat-langchain 的 50_000 字符"""
    assert MAX_MESSAGE_CHARS == 50_000


def test_multimodal_content_preserves_non_text_blocks():
    """多模态内容：只截断文本块，保留图片等其他内容块"""
    guard = IngressGuard(max_chars=5)
    content = [
        {"type": "text", "text": "一二三四五六七八九十"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
    ]
    result = guard.truncate_content(content)
    assert result[0] == {"type": "text", "text": "一二三四五"}
    assert result[1]["type"] == "image_url"  # 图片块原样保留


def test_multimodal_content_unchanged_when_under_cap():
    """多模态内容未超限时原样返回（identity 语义，不复制）"""
    guard = IngressGuard(max_chars=100)
    content = [{"type": "text", "text": "短文本"}]
    assert guard.truncate_content(content) is content


def test_non_string_content_untouched():
    """非字符串/非列表内容不做处理"""
    guard = IngressGuard(max_chars=10)
    assert guard.truncate_content(None) is None
    assert guard.truncate_content(123) == 123