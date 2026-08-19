"""
ReAct Agent - V5.2 Function Calling 版（接入中间层管道）
基于通义千问原生 tool_calls，用 HumanMessage 替代 ToolMessage 回传结果

V5.2 参照 chat-langchain 的中间件管道思路，新增模型中间处理能力：
入口守卫 → 话题护栏 → 历史摘要压缩 → 模型重试/降级 → 工具重试
（配置见 config/agent.yml 的 middleware 段，各组件位于 agent/middleware/）
"""
import asyncio
import json
import re
import time
import uuid
import urllib.parse  # 【新增】用于解析 __arg1 字符串参数
from typing import List, Optional, Dict, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from model.factory import ChatModelFactory
from utils.prompt_loader import load_system_prompts
from utils.logger_handler import logger
from utils.config_handler import agent_conf
from agent.tools.agent_tools import rag_summarize
from core.dashscope_usage_tracker import track_llm_call
from agent.middleware.ingress_guards import IngressGuard, MAX_MESSAGE_CHARS
from agent.middleware.guardrails import GuardrailsService
from agent.middleware.model_retry import ModelRetryPolicy
from agent.middleware.tool_retry import ToolRetryPolicy
from agent.middleware.summarization import ConversationSummarizer
from agent.middleware.model_fallback import FallbackChatModel, DEFAULT_FALLBACK_MODELS

MAX_STEPS = 5

TOOL_ALIASES = {
    "amap_route": "maps_direction_transit_integrated",
    "amap_poi_search": "maps_text_search",
    "amap_weather": "maps_weather",
    "amap_geocode": "maps_geo",
}


class ReactAgent:
    def __init__(self, extra_tools=None, memory_text="", user_id=None, session_id=None,
                 enable_middleware: bool = True):
        self.model_name = "qwen-max"
        self.user_id = user_id
        self.session_id = session_id
        self.memory_text = memory_text

        self.tools = [rag_summarize]
        if extra_tools:
            self.tools.extend(extra_tools)
            logger.info(f"[Agent] 已加载 {len(extra_tools)} 个外部 MCP 工具")

        self._enhance_tool_descriptions()

        # ==================== 中间层管道（参照 chat-langchain） ====================
        self._init_middleware(enable_middleware)

        if self.enable_middleware and self.model_fallback is not None:
            # 主模型 + 降级链，每次调用自带重试策略
            self.llm = self.model_fallback.bind_tools(self.tools)
            chain_names = [name for name, _ in self.model_fallback.models]
            logger.info(f"[Agent] 模型降级链: {' -> '.join(chain_names)}")
        else:
            base_llm = ChatModelFactory().generator()
            self.llm = base_llm.bind_tools(self.tools)
        logger.info(f"[Agent] Function Calling 已绑定 {len(self.tools)} 个工具")

        base_prompt = load_system_prompts()
        if memory_text:
            base_prompt = f"【用户记忆】\n{memory_text}\n\n" + base_prompt

        self.system_prompt = f"""{base_prompt}

【你的能力】
你可以调用外部工具来回答用户问题。当用户问题涉及地理位置、天气、店铺搜索、路线规划、产品知识时，请优先使用工具。

【工具使用原则】
1. 分析用户意图，选择最合适的工具
2. 填写参数时务必准确：
   - maps_text_search 的 keywords 只填一个词，如"小米"而非"小米之家"
   - city 必须填写完整城市名
   - 需要地址转坐标时，系统会自动处理
3. 获得工具结果后，如果信息足够直接回答；不够则继续调用（最多 {MAX_STEPS} 次）
4. 如果工具返回空或错误，诚实告知用户，不要编造信息
"""

    def _init_middleware(self, enable_middleware: bool = True):
        """
        初始化中间层管道组件（参照 chat-langchain 的中间件链）。
        配置来自 config/agent.yml 的 middleware 段；初始化失败时降级为
        无中间层模式，保证基础对话能力可用。
        """
        self.enable_middleware = enable_middleware
        self.ingress_guard: Optional[IngressGuard] = None
        self.guardrails: Optional[GuardrailsService] = None
        self.model_retry: Optional[ModelRetryPolicy] = None
        self.tool_retry: Optional[ToolRetryPolicy] = None
        self.summarizer: Optional[ConversationSummarizer] = None
        self.model_fallback: Optional[FallbackChatModel] = None

        if not enable_middleware:
            return

        mw_conf = (agent_conf or {}).get("middleware", {}) or {}
        try:
            # 入口守卫
            self.ingress_guard = IngressGuard(
                max_chars=mw_conf.get("ingress_max_chars", MAX_MESSAGE_CHARS)
            )

            # 模型重试策略（降级链上每个模型共用同一策略参数）
            retry_conf = mw_conf.get("model_retry", {}) or {}
            self.model_retry = ModelRetryPolicy(
                max_retries=retry_conf.get("max_retries", 2),
                initial_delay=retry_conf.get("initial_delay", 0.5),
                backoff_factor=retry_conf.get("backoff_factor", 2.0),
            )

            # 模型降级链
            fallback_models = tuple(
                (mw_conf.get("model_fallback", {}) or {}).get(
                    "models", DEFAULT_FALLBACK_MODELS
                )
            )
            self.model_fallback = FallbackChatModel.from_model_names(
                model_names=fallback_models, retry_policy=self.model_retry
            )
            self.model_name = self.model_fallback.model_name

            # 工具重试策略
            tool_conf = mw_conf.get("tool_retry", {}) or {}
            self.tool_retry = ToolRetryPolicy(
                max_attempts=tool_conf.get("max_attempts", 3),
                initial_delay=tool_conf.get("initial_delay", 0.5),
                backoff_factor=tool_conf.get("backoff_factor", 2.0),
            )

            # 话题护栏
            guard_conf = mw_conf.get("guardrails", {}) or {}
            if guard_conf.get("enabled", True):
                from agent.middleware.guardrails import DEFAULT_CLASSIFIER_MODELS

                classifier_models = tuple(
                    guard_conf.get("classifier_models", DEFAULT_CLASSIFIER_MODELS)
                )
                factory = ChatModelFactory()
                classifier_llms = [
                    (name, factory._get_model(name)) for name in classifier_models
                ]
                self.guardrails = GuardrailsService(
                    classifier_llms=classifier_llms,
                    block_off_topic=guard_conf.get("block_off_topic", True),
                    max_retries=guard_conf.get("max_retries", 2),
                    timeout_seconds=guard_conf.get("timeout_seconds", 10),
                )

            # 历史摘要压缩
            sum_conf = mw_conf.get("summarization", {}) or {}
            self.summarizer = ConversationSummarizer(
                trigger_tokens=sum_conf.get("trigger_tokens", 8_000),
                keep_tokens=sum_conf.get("keep_tokens", 2_000),
            )

            logger.info("[Agent] 中间层管道初始化完成（守卫/护栏/重试/降级/摘要）")
        except Exception as e:
            logger.error(f"[Agent] 中间层管道初始化失败，降级为基础模式: {e}")
            self.enable_middleware = False
            self.guardrails = None
            self.model_fallback = None

    def _enhance_tool_descriptions(self):
        for tool in self.tools:
            name = getattr(tool, "name", "")
            if name == "maps_text_search":
                tool.description = (
                    "【POI地点搜索】根据关键词搜索指定城市的店铺、门店、景点等位置信息。\n"
                    "参数规范：\n"
                    "- keywords: 搜索关键词，只支持一个词，越简洁越好。品牌名直接填品牌，如'小米'、'华为'、'苹果'\n"
                    "- city: 城市名，必填，如'武汉'、'上海'\n"
                    "- types: POI类型，可选，如'购物服务|专卖店|数码电器'\n"
                    "- citylimit: 是否严格限定城市内，建议填 true\n"
                    "示例：搜索武汉的小米店铺 → keywords='小米', city='武汉', types='购物服务|专卖店'"
                )
            elif name == "maps_direction_transit_integrated":
                tool.description = (
                    "【公交/地铁路线规划】规划两地之间的公共交通路线。\n"
                    "参数规范：\n"
                    "- origin: 起点，支持中文地址如'武汉站'，系统会自动转坐标\n"
                    "- destination: 终点，支持中文地址如'江汉路'，系统会自动转坐标\n"
                    "- city: 城市名，如'武汉'"
                )
            elif name == "maps_weather":
                tool.description = (
                    "【天气查询】查询指定城市的天气信息。\n"
                    "参数规范：\n"
                    "- city: 城市名，如'武汉'、'北京'"
                )
            elif name == "tavily_search":
                tool.description = (
                    "【网络搜索】当本地工具找不到信息时，使用网络搜索获取最新信息。\n"
                    "参数规范：\n"
                    "- query: 搜索查询语句，如'武汉小米之家地址 2024'"
                )

    def _resolve_tool_alias(self, name: str) -> str:
        return TOOL_ALIASES.get(name, name)

    async def _invoke_tool(self, tool, params: dict) -> str:
        async def _do_call() -> str:
            if hasattr(tool, "coroutine") and tool.coroutine:
                result = await tool.coroutine(**params)
            elif hasattr(tool, "func") and tool.func:
                result = tool.func(**params)
            elif hasattr(tool, "_run"):
                result = tool._run(**params)
            else:
                result = await tool.ainvoke(params)
            return str(result)

        try:
            if self.tool_retry is not None:
                # 工具重试策略：瞬时故障指数退避，失败返回模型可读错误（不抛异常）
                return await self.tool_retry.execute(tool.name, _do_call)
            return await _do_call()
        except Exception as e:
            logger.error(f"[Agent] 工具 {tool.name} 调用失败: {e}", exc_info=True)
            return f"工具调用失败: {str(e)}"

    async def _call_tool(self, name: str, params: dict) -> str:
        """
        调用工具，支持 __arg1 字符串参数解析（MCP 单参数工具兼容）
        """
        # 【关键修复】MCP 单参数工具被 LangChain 打包成 __arg1 字符串
        if "__arg1" in params and isinstance(params["__arg1"], str):
            arg_str = params["__arg1"].strip()
            try:
                # 尝试解析 "origin=xxx&destination=xxx" 格式
                parsed = urllib.parse.parse_qs(arg_str)
                if parsed:
                    params = {k: v[0] if len(v) == 1 else ",".join(v) for k, v in parsed.items()}
                    logger.info(f"[Agent] __arg1 URL解析: {arg_str} → {params}")
                else:
                    # 尝试 JSON 格式
                    params = json.loads(arg_str)
                    logger.info(f"[Agent] __arg1 JSON解析: {arg_str} → {params}")
            except Exception:
                # fallback：作为 query 参数
                params = {"query": arg_str}
                logger.info(f"[Agent] __arg1 fallback: {arg_str} → {{'query': ...}}")

        name = self._resolve_tool_alias(name)

        if name == "maps_text_search":
            params = self._optimize_poi_params(params)

        GEO_REQUIRED = {
            "maps_direction_transit_integrated",
            "maps_direction_driving",
            "maps_direction_walking",
            "maps_bicycling",
            "maps_distance",
        }
        if name in GEO_REQUIRED:
            params = await self._geo_encode_params(params)

        for tool in self.tools:
            if tool.name == name:
                return await self._invoke_tool(tool, params)

        available = [t.name for t in self.tools]
        logger.error(f"[Agent] 未找到工具: {name}，可用: {available}")
        return f"未找到工具: {name}"

    def _optimize_poi_params(self, params: dict) -> dict:
        p = dict(params)
        kw = p.get("keywords", p.get("query", ""))
        brand_map = {
            "小米之家": "小米", "小米专卖店": "小米", "小米授权店": "小米",
            "华为授权店": "华为", "华为体验店": "华为",
            "苹果直营店": "苹果", "apple store": "苹果",
        }
        for full, simple in brand_map.items():
            if full in kw:
                kw = simple
                break
        p["keywords"] = kw
        p["citylimit"] = "true"
        if not p.get("types"):
            p["types"] = "购物服务|专卖店|数码电器|商场"
        logger.info(f"[Agent] POI 参数优化: {params} → {p}")
        return p

    async def _geo_encode_params(self, params: dict) -> dict:
        p = dict(params)
        for key in ["origin", "destination"]:
            if key in p and p[key]:
                val = str(p[key]).strip()
                if not re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', val):
                    geo = await self._geo_encode(val)
                    if geo:
                        p[key] = geo
                        logger.info(f"[Agent] 坐标转换: {val} → {geo}")
                    else:
                        return {"error": f"地址解析失败: '{val}'"}
        return p

    async def _geo_encode(self, address: str) -> str:
        for tool in self.tools:
            if tool.name == "maps_geo":
                try:
                    result = await self._invoke_tool(tool, {"address": address})
                    m = re.search(r'(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', str(result))
                    if m:
                        return f"{m.group(1)},{m.group(2)}"
                except Exception as e:
                    logger.error(f"[Agent] maps_geo 失败: {e}")
        return ""

    def _build_messages(self, query: str, history: list = None) -> list:
        messages = [SystemMessage(content=self.system_prompt)]
        if history:
            for h in history:
                role = h.get("role", "")
                content = h.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
                elif role == "system":
                    # 摘要压缩产生的"此前对话摘要"等 system 历史，必须透传给模型
                    messages.append(SystemMessage(content=content))
        messages.append(HumanMessage(content=query))
        return messages

    async def _track_usage(self, response, endpoint: str):
        start = getattr(self, "_step_start_time", time.time())
        latency = (time.time() - start) * 1000
        await track_llm_call(
            response=response,
            model_name=self.model_name,
            latency_ms=latency,
            user_id=self.user_id,
            session_id=self.session_id,
            endpoint=endpoint,
        )

    # ==================== 【关键修复】从文本中提取工具调用 ====================
    def _extract_tool_calls_from_text(self, text: str) -> List[Dict[str, Any]]:
        """
        兜底：从 LLM 文本输出中提取工具调用。
        通义千问有时不会填充 response.tool_calls，而是把工具调用写在 content 里。
        支持格式: tool_name: {"arg1": "val1", ...}
        """
        if not text:
            return []

        tool_calls = []
        # 匹配模式: maps_text_search: {"query": "小米", "city": "商丘"}
        # 或 maps_text_search({"query": "小米", "city": "商丘"})
        patterns = [
            r'(\w+)\s*:\s*(\{.*?\})',           # name: {args}
            r'(\w+)\s*\(\s*(\{.*?\})\s*\)',     # name({args})
            r'(\w+)\s*\(([^)]*)\)',              # name(args) — 简单形式
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.DOTALL):
                tool_name = match.group(1)
                args_str = match.group(2).strip()

                # 验证工具名是否存在于已绑定工具中
                valid_names = {t.name for t in self.tools}
                if tool_name not in valid_names:
                    continue

                try:
                    # 尝试解析 JSON
                    if args_str.startswith("{") and args_str.endswith("}"):
                        args = json.loads(args_str)
                    else:
                        # 尝试 key=value 格式
                        args = {}
                        for pair in re.findall(r'(\w+)\s*=\s*["\']?([^,"\'\s]+)["\']?', args_str):
                            args[pair[0]] = pair[1]
                    tool_calls.append({
                        "name": tool_name,
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:8]}"
                    })
                    logger.info(f"[Agent] 从文本提取工具调用: {tool_name}({args})")
                except (json.JSONDecodeError, Exception) as e:
                    logger.debug(f"[Agent] 文本工具解析失败: {e}")
                    continue

        return tool_calls

    # ==================== 【核心修复】处理 tool_calls 结果 ====================
    async def _handle_tool_calls(self, response, messages: list, step: int) -> bool:
        """
        处理模型的 tool_calls，执行工具并用 HumanMessage 回传结果。
        返回 True 表示处理了工具调用，False 表示没有 tool_calls。
        """
        tool_calls = []

        # 1. 先检查结构化的 tool_calls（标准方式）
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_calls = response.tool_calls

        # 2. 【关键兜底】如果结构化为空，从文本 content 中解析
        if not tool_calls and hasattr(response, "content") and response.content:
            text = response.content.strip()
            parsed = self._extract_tool_calls_from_text(text)
            if parsed:
                tool_calls = parsed
                # 截掉文本中的工具调用标记，避免前端显示
                # 保留工具调用之前的文本（如果有说明性文字）
                clean_text = re.sub(r'\s*\w+\s*[:({]\s*\{.*?\}[\s)}]*', '', text, flags=re.DOTALL).strip()
                response.content = clean_text
                logger.info(f"[Agent] 文本工具调用已提取并清理，剩余文本: '{clean_text[:50]}...'")

        if not tool_calls:
            return False

        # 【关键】保留 AIMessage 的 tool_calls，让模型有调用历史
        # 但清空 content 避免幻觉文本干扰
        messages.append(AIMessage(content="", tool_calls=tool_calls))

        for tc in tool_calls:
            tool_name = tc.get("name")
            tool_args = tc.get("args", {})
            tool_id = tc.get("id", f"call_{step}")

            logger.info(f"[Agent] 调用工具: {tool_name}, 参数: {tool_args}")
            observation = await self._call_tool(tool_name, tool_args)

            # 【核心修复】用 HumanMessage 替代 ToolMessage，兼容通义千问
            tool_result_msg = (
                f"【工具 {tool_name} 的返回结果（调用ID: {tool_id}）】\n"
                f"{observation}\n"
                f"请基于以上结果回答用户问题，如果信息不足可以再次调用工具。"
            )
            messages.append(HumanMessage(content=tool_result_msg))

        return True

    # ==================== 中间层管道：请求预处理 ====================
    async def _preprocess(self, query: str, history: list = None) -> Dict[str, Any]:
        """
        请求进入 Agent 循环前的中间层处理（参照 chat-langchain 管道顺序）：
        1. 入口守卫：截断超长输入
        2. 话题护栏：小模型分类，拦截越界请求（fail-open）
        3. 摘要压缩：历史超阈值时压缩，防上下文溢出

        :return: {"query": 处理后的 query, "history": 处理后的 history,
                  "blocked": bool, "rejection": str | None}
        """
        # 1) 入口守卫
        if self.ingress_guard is not None:
            query = self.ingress_guard.apply(query)

        # 2) 话题护栏（fail-open，护栏故障不阻断用户）
        if self.guardrails is not None:
            check = await self.guardrails.check(query, history)
            if not check["allowed"]:
                return {
                    "query": query,
                    "history": history,
                    "blocked": True,
                    "rejection": check["rejection"],
                }

        # 3) 历史摘要压缩
        if self.summarizer is not None and history:
            history = await self.summarizer.summarize(history)

        return {"query": query, "history": history, "blocked": False, "rejection": None}

    # ==================== 非流式执行 ====================
    async def async_execute(self, query: str, history: list = None) -> str:
        pre = await self._preprocess(query, history)
        if pre["blocked"]:
            return pre["rejection"]

        messages = self._build_messages(pre["query"], pre["history"])

        for step in range(1, MAX_STEPS + 1):
            logger.info(f"[Agent] === ReAct 第 {step}/{MAX_STEPS} 轮 ===")

            self._step_start_time = time.time()
            response = await self.llm.ainvoke(messages)
            await self._track_usage(response, f"agent.async_execute.step{step}")

            # 【核心】处理 tool_calls（含文本兜底）
            has_tool_calls = await self._handle_tool_calls(response, messages, step)
            if has_tool_calls:
                continue  # 继续下一轮，让模型基于工具结果推理

            # 无工具调用，直接回答
            content = response.content if hasattr(response, "content") else str(response)
            logger.info(f"[Agent] 无需工具，直接回答")
            return content

        # 达到最大轮数，强制总结
        messages.append(HumanMessage(content="请基于已收集的信息给出最终答案。"))
        self._step_start_time = time.time()
        response = await self.llm.ainvoke(messages)
        await self._track_usage(response, "agent.async_execute.final")
        return response.content if hasattr(response, "content") else str(response)

    # ==================== 流式执行 ====================
    async def async_execute_stream(self, query: str, history: list = None):
        pre = await self._preprocess(query, history)
        if pre["blocked"]:
            yield pre["rejection"]
            return

        messages = self._build_messages(pre["query"], pre["history"])

        for step in range(1, MAX_STEPS + 1):
            logger.info(f"[Agent] === ReAct 流式第 {step}/{MAX_STEPS} 轮 ===")

            self._step_start_time = time.time()
            response = await self.llm.ainvoke(messages)
            await self._track_usage(response, f"agent.async_execute_stream.step{step}")

            # 【核心】处理 tool_calls（含文本兜底）
            has_tool_calls = await self._handle_tool_calls(response, messages, step)
            if has_tool_calls:
                continue  # 继续下一轮

            # 无工具调用，流式输出最终答案
            content = response.content if hasattr(response, "content") else str(response)
            logger.info(f"[Agent] 流式第 {step} 轮无需工具，按段落输出")

            parts = re.split(r'([。！？；\n])', content)
            buffer = ''
            for part in parts:
                buffer += part
                if part in '。！？；\n' and buffer.strip():
                    yield buffer
                    buffer = ''
                await asyncio.sleep(0.03)
            if buffer.strip():
                yield buffer
            return

        # 达到最大轮数
        messages.append(HumanMessage(content="请基于已收集的信息给出最终答案。"))
        self._step_start_time = time.time()
        response = await self.llm.ainvoke(messages)
        await self._track_usage(response, "agent.async_execute_stream.final")

        content = response.content if hasattr(response, "content") else str(response)
        parts = re.split(r'([。！？；\n])', content)
        buffer = ''
        for part in parts:
            buffer += part
            if part in '。！？；\n' and buffer.strip():
                yield buffer
                buffer = ''
            await asyncio.sleep(0.03)
        if buffer.strip():
            yield buffer