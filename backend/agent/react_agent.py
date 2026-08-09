"""
ReAct Agent 封装 - V4.7 MCP 工具强制调用版
修复：
1. 强化 system prompt，强制 LLM 严格按 TOOL_CALL 格式输出
2. 增加"伪工具调用"检测与纠正机制
3. 【关键修复】async_execute_stream 去掉工具调用状态消息 yield，避免 SSE 中断
4. 多步 ReAct 循环，兼容通义千问 API 格式
5. 路径规划工具自动中文地址转经纬度坐标
6. maps_text_search 自动用高德 maps_geo 解析城市名
7. 补充缺失的 _invoke_tool 方法
8. async_execute_stream 不再把 TOOL_CALL/思考过程暴露给前端
"""
import asyncio
import json
import re
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from model.factory import ChatModelFactory
from utils.prompt_loader import load_system_prompts
from utils.logger_handler import logger
from agent.tools.agent_tools import rag_summarize

MAX_STEPS = 5

# 工具别名映射
TOOL_ALIASES = {
    "amap_route": "maps_direction_transit_integrated",
    "amap_poi_search": "maps_text_search",
    "amap_weather": "maps_weather",
    "amap_geocode": "maps_geo",
    "maps_direction_transit_integrated": "maps_direction_transit_integrated",
    "maps_text_search": "maps_text_search",
    "maps_weather": "maps_weather",
    "maps_geo": "maps_geo",
    "maps_direction_driving": "maps_direction_driving",
    "maps_direction_walking": "maps_direction_walking",
    "maps_bicycling": "maps_bicycling",
    "maps_distance": "maps_distance",
    "maps_around_search": "maps_around_search",
    "maps_search_detail": "maps_search_detail",
    "maps_regeocode": "maps_regeocode",
    "maps_ip_location": "maps_ip_location",
}


class ReactAgent:
    def __init__(self, extra_tools=None, memory_text=""):
        self.llm = ChatModelFactory().generator()

        self.tools = [rag_summarize]

        if extra_tools:
            self.tools.extend(extra_tools)
            logger.info(f"[Agent] 已加载 {len(extra_tools)} 个外部 MCP 工具")
            for t in extra_tools:
                logger.info(f"[Agent] - {t.name}: {t.description[:50]}...")

        tools_desc = "\n".join([
            f"- {t.name}: {t.description}"
            for t in self.tools
        ])

        base_prompt = load_system_prompts()
        if memory_text:
            base_prompt = f"【用户记忆】\n{memory_text}\n\n" + base_prompt

        self.system_prompt = f"""{base_prompt}

你可以使用以下工具来回答用户问题：
{tools_desc}

【强制工具调用规则 - 必须遵守】
1. 如果用户问题涉及以下任何场景，你必须调用工具，禁止直接回答：
   - 地理位置、地址、坐标、城市、区域
   - 天气、气温、降雨、风力
   - 店铺、门店、专卖店、体验店、维修点、服务网点
   - 路线、导航、距离、交通方式、怎么走
   - 品牌在某个城市的销售点、哪里有卖

2. 【极其重要】调用工具时，必须且只能输出以下格式，不要加任何其他文字：
TOOL_CALL: {{"tool": "工具名称", "params": {{"参数名": "参数值"}}}}

3. 【错误示例 - 禁止这样输出】：
   ❌ "为了查询天气，我将使用 maps_weather 工具..."
   ❌ "让我调用高德地图来查询..."
   ❌ 把工具调用说明和答案混在一起

4. 【正确示例 - 必须这样输出】：
   ✅ TOOL_CALL: {{"tool": "maps_weather", "params": {{"city": "上海"}}}}
   ✅ TOOL_CALL: {{"tool": "maps_direction_transit_integrated", "params": {{"origin": "焦作", "destination": "上海市中心"}}}}

5. 获得工具结果后，如果信息足够，直接回答用户；如果还需要更多信息，可以再次调用工具（最多 {MAX_STEPS} 次）。

6. 如果用户问题与上述场景无关，可以直接回答，不需要工具。

【工具使用指南】
- maps_text_search: 搜索店铺、门店、维修点等 POI 地点
- maps_weather: 查询城市天气
- maps_geo: 地址转坐标
- maps_direction_transit_integrated: 公交/地铁路线规划
- maps_direction_driving: 驾车路线规划
- maps_direction_walking: 步行路线规划
- maps_bicycling: 骑行路线规划
- maps_distance: 测量两地距离
- maps_around_search: 周边搜索
- maps_search_detail: 查询 POI 详细信息
- rag_summarize: 从知识库检索产品信息
"""
        logger.info(f"[Agent] 初始化完成，总工具数: {len(self.tools)}")

    def _detect_tool_call(self, text: str):
        """检测 LLM 输出中是否包含工具调用意图"""
        match = re.search(r'TOOL_CALL:\s*(.+)', text, re.DOTALL)

        if not match:
            loose_match = re.search(r'("tool"\s*:\s*"[^"]+")', text)
            if loose_match:
                json_match = re.search(r'\{[^{}]*"tool"[^{}]*\}', text)
                if json_match:
                    match = json_match

        if not match:
            return None, None

        raw = match.group(1).strip() if hasattr(match, 'group') else match.group(0).strip()

        if raw.startswith('"tool"'):
            start_idx = text.find('{')
            if start_idx != -1:
                raw = text[start_idx:]
        else:
            start = raw.find('{')
            if start == -1:
                return None, None
            raw = raw[start:]

        depth = 0
        json_str = ""
        for i, c in enumerate(raw):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            json_str += c
            if depth == 0 and json_str.strip():
                break

        try:
            data = json.loads(json_str)
            tool_name = data.get("tool")
            params = data.get("params", {})

            original_name = tool_name
            if tool_name in TOOL_ALIASES:
                tool_name = TOOL_ALIASES[tool_name]
                if original_name != tool_name:
                    logger.info(f"[Agent] 工具别名映射: {original_name} → {tool_name}")

            logger.info(f"[Agent] 检测到工具调用: {tool_name}, 参数: {params}")
            return tool_name, params
        except json.JSONDecodeError as e:
            logger.warning(f"[Agent] JSON 解析失败: {e}, 内容: {json_str[:100]}")
            return None, None

    async def _invoke_tool(self, tool, params: dict) -> str:
        """内部辅助方法：统一调用 tool 对象"""
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
        """异步调用指定工具（自动处理中文地址转坐标）"""

        GEO_REQUIRED_TOOLS = {
            "maps_direction_transit_integrated",
            "maps_direction_driving",
            "maps_direction_walking",
            "maps_bicycling",
            "maps_distance",
        }

        if name in GEO_REQUIRED_TOOLS:
            new_params = dict(params)
            for key in ["origin", "destination"]:
                if key in new_params and new_params[key]:
                    val = str(new_params[key]).strip()
                    if not re.match(r'^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$', val):
                        geo_result = await self._geo_encode(val)
                        if geo_result:
                            new_params[key] = geo_result
                            logger.info(f"[Agent] 自动坐标转换: {val} → {geo_result}")
                        else:
                            return f"地址解析失败: 无法将 '{val}' 转换为经纬度坐标，请检查地址是否正确。"
            params = new_params

        for tool in self.tools:
            if tool.name == name:
                return await self._invoke_tool(tool, params)

        available = [t.name for t in self.tools]
        logger.error(f"[Agent] 未找到工具: {name}，可用工具: {available}")
        return f"未找到工具: {name}。可用工具: {', '.join(available)}"

    async def _geo_encode(self, address: str) -> str:
        """调用 maps_geo 将中文地址转为 经度,纬度 格式"""
        for tool in self.tools:
            if tool.name == "maps_geo":
                try:
                    result = await self._invoke_tool(tool, {"address": address})
                    result_str = str(result)

                    try:
                        data = json.loads(result_str)
                        if isinstance(data, dict):
                            loc = data.get("location")
                            if not loc and "geocodes" in data:
                                loc = data["geocodes"][0].get("location")
                            if loc and "," in loc:
                                return loc
                    except Exception:
                        pass

                    match = re.search(r'(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', result_str)
                    if match:
                        return f"{match.group(1)},{match.group(2)}"

                    return ""
                except Exception as e:
                    logger.error(f"[Agent] maps_geo 调用失败: {e}")
                    return ""
        return ""

    async def _extract_city_by_geo(self, address: str) -> str:
        """调用 maps_geo 解析地址，提取城市名"""
        for tool in self.tools:
            if tool.name == "maps_geo":
                try:
                    result = await self._invoke_tool(tool, {"address": address})
                    result_str = str(result)

                    try:
                        data = json.loads(result_str)
                        if isinstance(data, dict):
                            geocodes = data.get("geocodes", [])
                            if geocodes and isinstance(geocodes, list):
                                city = geocodes[0].get("city", "")
                                if city:
                                    return city.replace("市", "").replace("县", "").replace("区", "")
                    except Exception:
                        pass

                    match = re.search(r'"city":\s*"([^"]+)"', result_str)
                    if match:
                        city = match.group(1)
                        return city.replace("市", "").replace("县", "").replace("区", "")

                    return ""
                except Exception as e:
                    logger.warning(f"[Agent] maps_geo 解析城市失败: {e}")
                    return ""
        return ""

    async def async_execute(self, query: str, history: list = None) -> str:
        """非流式执行 - 支持历史消息"""
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

        for step in range(1, MAX_STEPS + 1):
            logger.info(f"[Agent] === ReAct 第 {step}/{MAX_STEPS} 轮 ===")

            response = await self.llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            logger.info(f"[Agent] 第 {step} 轮回复: {content[:200]}...")

            tool_name, params = self._detect_tool_call(content)

            if not tool_name:
                if self._is_pseudo_tool_call(content):
                    logger.warning(f"[Agent] 第 {step} 轮检测到伪工具调用，要求重新输出")
                    messages.append(AIMessage(content=content))
                    messages.append(HumanMessage(
                        content='你没有按正确格式输出工具调用。请严格使用以下格式，不要加任何其他文字：\n'
                                'TOOL_CALL: {"tool": "工具名称", "params": {"参数名": "参数值"}}'
                    ))
                    continue

                logger.info(f"[Agent] 第 {step} 轮无需工具，直接回答，结束循环")
                return content

            logger.info(f"[Agent] 第 {step} 轮调用工具: {tool_name}, 参数: {params}")
            observation = await self._call_tool(tool_name, params)
            logger.info(f"[Agent] 第 {step} 轮工具返回: {observation[:200]}...")

            messages.append(AIMessage(content=content))
            messages.append(HumanMessage(
                content=f"【工具 {tool_name} 的返回结果（第 {step} 轮）】\n{observation}"
            ))

        logger.info(f"[Agent] 达到最大轮数 {MAX_STEPS}，强制总结")
        messages.append(HumanMessage(
            content="你已经使用了多次工具，现在请基于所有收集到的信息，直接给出最终答案。"
        ))
        response = await self.llm.ainvoke(messages)
        final_content = response.content if hasattr(response, "content") else str(response)
        return final_content

    # ==================== 【关键修复】async_execute_stream ====================
    async def async_execute_stream(self, query: str, history: list = None):
        """
        【修复】简化流式执行：
        1. 工具调用期间不 yield 任何内容（避免 SSE 中断）
        2. 只按段落 yield 最终答案
        3. 如果无需工具，直接按段落 yield
        """
        try:
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

            for step in range(1, MAX_STEPS + 1):
                logger.info(f"[Agent] === ReAct 流式第 {step}/{MAX_STEPS} 轮 ===")

                response = await self.llm.ainvoke(messages)
                full_content = response.content if hasattr(response, "content") else str(response)
                logger.info(f"[Agent] 第 {step} 轮完整回复: {full_content[:200]}...")

                tool_name, params = self._detect_tool_call(full_content)

                # 【关键修复】检测伪工具调用
                if not tool_name and self._is_pseudo_tool_call(full_content):
                    logger.warning(f"[Agent] 第 {step} 轮检测到伪工具调用，追加纠正提示")
                    messages.append(AIMessage(content=full_content))
                    messages.append(HumanMessage(
                        content="注意：你没有按正确格式输出工具调用。\n"
                                "如果确实需要调用工具，请严格使用以下格式（不要加任何其他文字）：\n"
                                'TOOL_CALL: {"tool": "工具名称", "params": {"参数名": "参数值"}}\n'
                                "如果不需要工具，请直接回答用户问题。"
                    ))
                    # 重新生成
                    response = await self.llm.ainvoke(messages)
                    full_content = response.content if hasattr(response, "content") else str(response)
                    logger.info(f"[Agent] 第 {step} 轮纠正后回复: {full_content[:200]}...")
                    tool_name, params = self._detect_tool_call(full_content)

                if not tool_name:
                    # 无需工具调用，按段落切分 yield 最终答案
                    logger.info(f"[Agent] 第 {step} 轮无需工具，按段落流式输出")
                    parts = re.split(r'([。！？；\n])', full_content)
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

                # 【关键修复】检测到工具调用，不再 yield 状态消息，直接静默调用
                logger.info(f"[Agent] 第 {step} 轮调用工具: {tool_name}, 参数: {params}")
                observation = await self._call_tool(tool_name, params)
                logger.info(f"[Agent] 第 {step} 轮工具返回: {observation[:200]}...")

                # 将工具结果加入上下文，进入下一轮
                messages.append(AIMessage(content=full_content))
                messages.append(HumanMessage(
                    content=f"【工具 {tool_name} 的返回结果（第 {step} 轮）】\n{observation}"
                ))

            # 达到最大轮数，强制总结并流式输出
            logger.info(f"[Agent] 达到最大轮数 {MAX_STEPS}，强制总结")
            messages.append(HumanMessage(
                content="你已经使用了多次工具，现在请基于所有收集到的信息，直接给出最终答案。"
            ))
            response = await self.llm.ainvoke(messages)
            final_content = response.content if hasattr(response, "content") else str(response)

            parts = re.split(r'([。！？；\n])', final_content)
            buffer = ''
            for part in parts:
                buffer += part
                if part in '。！？；\n' and buffer.strip():
                    yield buffer
                    buffer = ''
                await asyncio.sleep(0.03)
            if buffer.strip():
                yield buffer

        except Exception as e:
            logger.error(f"[Agent] 流式执行出错: {e}", exc_info=True)
            yield "处理出错，请稍后重试。"

    def _is_pseudo_tool_call(self, text: str) -> bool:
        """检测 LLM 是否在用自然语言描述调用工具，而不是真正输出 TOOL_CALL 格式"""
        if "TOOL_CALL:" in text:
            return False

        pseudo_patterns = [
            r"我将使用.*工具",
            r"让我调用",
            r"我将调用",
            r"使用高德地图",
            r"使用.*查询",
            r"让我用.*来",
            r"我将用.*来",
            r"正在使用.*工具",
            r"调用.*功能",
            r"使用.*功能",
        ]

        for pattern in pseudo_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return False