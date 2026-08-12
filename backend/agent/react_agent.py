"""
ReAct Agent - V5.1 Function Calling 版（修复通义千问 ToolMessage 兼容性问题）
基于通义千问原生 tool_calls，用 HumanMessage 替代 ToolMessage 回传结果
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
from agent.tools.agent_tools import rag_summarize
from core.dashscope_usage_tracker import track_llm_call

MAX_STEPS = 5

TOOL_ALIASES = {
    "amap_route": "maps_direction_transit_integrated",
    "amap_poi_search": "maps_text_search",
    "amap_weather": "maps_weather",
    "amap_geocode": "maps_geo",
}


class ReactAgent:
    def __init__(self, extra_tools=None, memory_text="", user_id=None, session_id=None):
        self.model_name = "qwen-max"
        self.user_id = user_id
        self.session_id = session_id
        self.memory_text = memory_text

        self.tools = [rag_summarize]
        if extra_tools:
            self.tools.extend(extra_tools)
            logger.info(f"[Agent] 已加载 {len(extra_tools)} 个外部 MCP 工具")

        self._enhance_tool_descriptions()

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
        try:
            if hasattr(tool, "coroutine") and tool.coroutine:
                result = await tool.coroutine(**params)
            elif hasattr(tool, "func") and tool.func:
                result = tool.func(**params)
            elif hasattr(tool, "_run"):
                result = tool._run(**params)
            else:
                result = await tool.ainvoke(params)
            return str(result)
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

    # ==================== 非流式执行 ====================
    async def async_execute(self, query: str, history: list = None) -> str:
        messages = self._build_messages(query, history)

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
        messages = self._build_messages(query, history)

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