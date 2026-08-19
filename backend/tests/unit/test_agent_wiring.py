"""
ReactAgent 中间层管道接线测试（对照 chat-langchain 的 wiring 测试思路）

验证各中间层组件确实被接进了 Agent 的执行链路，而不只是"定义了没接上"：
1. 护栏拦截时直接返回拒绝文案，主模型一次都不被调用
2. 文本形式的工具调用被提取、执行，结果回传后模型给出最终答案
3. 超长输入在到达模型前被入口守卫截断
4. 超长历史在构建消息前被摘要压缩

测试通过 sys.modules 打桩隔离重依赖（向量库/数据库/DashScope SDK），
只测 Agent 循环与中间层的接线逻辑，不需要 API Key 和网络。
"""
import asyncio
import sys
import types

import pytest

# ==================== 打桩重依赖（必须在 import react_agent 之前） ====================

# 1) 打桩模型工厂，隔离 langchain_community / DashScope SDK
_stub_model_factory = types.ModuleType("model.factory")


class _StubChatModelFactory:
    def generator(self, query=None):
        return None

    def _get_model(self, name):
        return None


_stub_model_factory.ChatModelFactory = _StubChatModelFactory
_stub_model_factory.chat_model = None
sys.modules["model.factory"] = _stub_model_factory

# 2) 打桩 RAG 工具模块，隔离 chromadb / 向量库初始化
_stub_agent_tools = types.ModuleType("agent.tools.agent_tools")


class _StubRagTool:
    name = "rag_summarize"
    description = "RAG 检索工具（打桩）"

    async def ainvoke(self, params):
        return "打桩知识库结果"


_stub_agent_tools.rag_summarize = _StubRagTool()
sys.modules["agent.tools.agent_tools"] = _stub_agent_tools

# 3) 打桩用量追踪，隔离 sqlalchemy / 数据库
_stub_tracker = types.ModuleType("core.dashscope_usage_tracker")


async def _noop_track_llm_call(**kwargs):
    return None


class _StubUsageTracker:
    pass


_stub_tracker.track_llm_call = _noop_track_llm_call
_stub_tracker.usage_tracker = _StubUsageTracker()
sys.modules["core.dashscope_usage_tracker"] = _stub_tracker

# ==================== 正式导入被测对象 ====================
from langchain_core.messages import AIMessage  # noqa: E402

from agent.middleware.guardrails import GuardrailsService  # noqa: E402
from agent.middleware.ingress_guards import IngressGuard  # noqa: E402
from agent.middleware.summarization import ConversationSummarizer  # noqa: E402
from agent.middleware.tool_retry import ToolRetryPolicy  # noqa: E402
from agent.react_agent import ReactAgent  # noqa: E402


# ==================== 测试替身 ====================

class FakeLLM:
    """按队列返回响应的假主模型。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.model_name = "fake-llm"

    async def ainvoke(self, messages, **kwargs):
        self.calls.append(messages)
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeTool:
    def __init__(self, name="fake_search"):
        self.name = name
        self.calls = []

    async def ainvoke(self, params):
        self.calls.append(params)
        return "工具返回：XX100 续航 120 分钟"


class FakeGuardrailsModel:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, prompt, config=None):
        return type("R", (), {"content": self.content})()


def _build_agent(llm, guardrails=None, tools=None, summarizer=None):
    """绕过 __init__ 的重依赖，手工装配一个接好中间层的 Agent。"""
    agent = ReactAgent.__new__(ReactAgent)
    agent.model_name = "fake-llm"
    agent.user_id = None
    agent.session_id = None
    agent.memory_text = ""
    agent.tools = tools if tools is not None else []
    agent.system_prompt = "你是扫地机器人客服。"
    agent.llm = llm
    agent.enable_middleware = True
    agent.ingress_guard = IngressGuard(max_chars=100)
    agent.guardrails = guardrails
    agent.model_retry = None
    agent.tool_retry = ToolRetryPolicy(max_attempts=2, initial_delay=0)
    agent.summarizer = summarizer
    agent.model_fallback = None
    return agent


# ==================== 接线测试 ====================

def test_blocked_query_short_circuits_before_main_model():
    """护栏拦截 → 直接返回拒绝文案，主模型零调用"""
    llm = FakeLLM([])  # 不准备任何响应：被调用即失败
    guardrails = GuardrailsService(
        classifier_llms=[
            ("fake", FakeGuardrailsModel('{"decision": "BLOCKED", "explanation": "越界"}')),
        ],
        max_retries=0,
    )
    # 第二次调用生成拒绝文案
    guardrails.classifier_llms[0][1].content = '{"decision": "BLOCKED", "explanation": "越界"}'

    agent = _build_agent(llm, guardrails=guardrails)

    # 让 FakeGuardrailsModel 第一次返回 BLOCKED、第二次返回拒绝文案
    class TwoStageModel:
        def __init__(self):
            self.n = 0

        async def ainvoke(self, prompt, config=None):
            self.n += 1
            if self.n == 1:
                return type("R", (), {"content": '{"decision": "BLOCKED", "explanation": "越界"}'})()
            return type("R", (), {"content": "抱歉，我只能解答扫地机器人问题"})()

    guardrails.classifier_llms = [("fake", TwoStageModel())]
    result = asyncio.run(agent.async_execute("帮我写小说"))

    assert "抱歉" in result
    assert len(llm.calls) == 0  # 主模型从未被调用


def test_text_tool_call_extracted_and_executed():
    """模型把工具调用写在文本里时：提取 → 执行工具 → 结果回传 → 最终回答"""
    tool = FakeTool()
    llm = FakeLLM([
        # 第一轮：文本形式的工具调用（通义千问兼容性问题场景）
        AIMessage(content='fake_search: {"query": "XX100续航"}'),
        # 第二轮：基于工具结果的最终回答
        AIMessage(content="XX100 的续航为 120 分钟。"),
    ])
    agent = _build_agent(llm, guardrails=None, tools=[tool])

    result = asyncio.run(agent.async_execute("XX100 续航多久？"))

    assert result == "XX100 的续航为 120 分钟。"
    assert len(tool.calls) == 1                       # 工具确实被执行
    assert tool.calls[0].get("query") == "XX100续航"  # 参数正确解析
    assert len(llm.calls) == 2                        # 工具结果回传后模型再跑一轮


def test_ingress_guard_truncates_before_model():
    """超长输入在到达模型前被截断"""
    llm = FakeLLM([AIMessage(content="回答")])
    agent = _build_agent(llm, guardrails=None)

    asyncio.run(agent.async_execute("长" * 500))

    sent_messages = llm.calls[0]
    last_human = sent_messages[-1].content
    assert len(last_human) == 100  # 被 IngressGuard(max_chars=100) 截断


def test_long_history_summarized_before_building_messages():
    """超长历史先经摘要压缩，再进入模型消息"""
    class FakeSummaryModel:
        async def ainvoke(self, prompt):
            return type("R", (), {"content": "用户此前在对比 XX100 与 XX200"})()

    summarizer = ConversationSummarizer(
        model=FakeSummaryModel(), trigger_tokens=50, keep_tokens=100
    )
    llm = FakeLLM([AIMessage(content="综合看推荐 XX100")])
    agent = _build_agent(llm, guardrails=None, summarizer=summarizer)

    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "历史对话" * 50}
        for i in range(8)
    ]
    asyncio.run(agent.async_execute("那哪个更适合我？", history=long_history))

    sent_messages = llm.calls[0]
    # 摘要被注入为 system 消息，且总消息数远小于原历史
    contents = [m.content for m in sent_messages]
    assert any("此前对话摘要" in c for c in contents)
    assert len(sent_messages) < len(long_history)


@pytest.mark.asyncio
async def test_stream_blocked_yields_rejection():
    """流式路径下护栏拦截：直接 yield 拒绝文案"""
    llm = FakeLLM([])

    class BlockModel:
        def __init__(self):
            self.n = 0

        async def ainvoke(self, prompt, config=None):
            self.n += 1
            if self.n == 1:
                return type("R", (), {"content": "BLOCKED"})()
            return type("R", (), {"content": "抱歉，超出服务范围"})()

    guardrails = GuardrailsService(
        classifier_llms=[("fake", BlockModel())], max_retries=0
    )
    agent = _build_agent(llm, guardrails=guardrails)

    chunks = [c async for c in agent.async_execute_stream("讲个黄段子")]
    assert chunks == ["抱歉，超出服务范围"]
    assert len(llm.calls) == 0