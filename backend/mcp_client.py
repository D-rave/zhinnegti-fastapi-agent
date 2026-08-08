"""
MCP (Model Context Protocol) 客户端封装 V2
支持多服务器连接：stdio（本地进程）和 sse（远程 HTTP 流）

使用方式：
    1. 安装 mcp SDK: pip install mcp
    2. 在 lifespan 中依次连接多个 MCP 服务器
    3. 将所有工具合并后传入 ReactAgent

支持的服务器示例：
    - 高德地图（SSE 远程）
    - Tavily 智能搜索（SSE 远程）
    - SQLite（stdio 本地）
    - 文件系统（stdio 本地）
"""
import asyncio
from contextlib import AsyncExitStack
from typing import List, Optional, Any, Dict

from langchain_core.tools import Tool
from utils.logger_handler import logger

# 尝试导入 mcp，未安装则给出友好提示
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("[MCP] mcp 库未安装，MCP 功能不可用。如需使用请执行: pip install mcp")


class MCPClient:
    """
    MCP 客户端管理器 V2
    支持同时管理多个 MCP 服务器连接，并将所有远程工具合并为 LangChain Tool 列表
    """

    def __init__(self):
        self.sessions: Dict[str, Any] = {}     # name -> ClientSession
        self.exit_stack = AsyncExitStack()
        self._all_tools: List[Tool] = []       # 所有服务器工具合并后的列表
        self._tool_source: Dict[str, str] = {}  # tool_name -> server_name（用于调试）

    # ========== stdio 连接（本地进程）==========
    async def connect_stdio(self, name: str, command: str, args: List[str] = None, env: dict = None):
        """
        通过 stdio 方式连接本地 MCP 服务器
        示例：SQLite、文件系统、本地脚本等

        :param name: 服务器标识名（如 "sqlite", "filesystem"）
        :param command: 可执行命令（如 "python", "npx", "uvx"）
        :param args: 命令参数列表
        :param env: 环境变量字典
        """
        if not MCP_AVAILABLE:
            logger.warning(f"[MCP] 跳过连接 {name}，mcp 库未安装")
            return False

        args = args or []
        server_params = StdioServerParameters(command=command, args=args, env=env)

        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write)
            )
            await session.initialize()
            self.sessions[name] = session
            logger.info(f"[MCP] ✅ 通过 stdio 连接到服务器: {name}")

            await self._load_tools_from_session(name, session)
            return True

        except Exception as e:
            logger.error(f"[MCP] ❌ stdio 连接服务器 {name} 失败: {str(e)}")
            return False

    # ========== SSE 连接（远程 HTTP 流）==========
    async def connect_sse(self, name: str, url: str, headers: Optional[dict] = None):
        """
        通过 SSE 方式连接远程 MCP 服务器
        示例：高德地图、Tavily 搜索、魔搭社区 MCP 等

        :param name: 服务器标识名（如 "amap", "tavily"）
        :param url: SSE 端点地址
        :param headers: 请求头（如 Authorization、API Key）
        """
        if not MCP_AVAILABLE:
            logger.warning(f"[MCP] 跳过连接 {name}，mcp 库未安装")
            return False

        try:
            from mcp.client.sse import sse_client

            async with sse_client(url, headers=headers or {}) as (read, write):
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self.sessions[name] = session
                logger.info(f"[MCP] ✅ 通过 SSE 连接到服务器: {name} @ {url}")

                await self._load_tools_from_session(name, session)
                return True

        except Exception as e:
            logger.error(f"[MCP] ❌ SSE 连接服务器 {name} 失败: {str(e)}")
            return False

    # ========== 工具加载 ==========
    async def _load_tools_from_session(self, name: str, session: Any):
        """将 MCP 服务器的工具列表转换为 LangChain Tool 对象"""
        try:
            response = await session.list_tools()
            loaded_count = 0

            for tool_info in response.tools:
                tool_name = tool_info.name

                # 避免同名工具冲突（加前缀）
                unique_name = f"{name}_{tool_name}" if tool_name in self._tool_source else tool_name
                self._tool_source[unique_name] = name

                # 创建 LangChain Tool 包装器
                tool = Tool(
                    name=unique_name,
                    description=f"[{name}] {tool_info.description or tool_name}",
                    func=self._make_tool_caller(session, tool_name),
                    coroutine=self._make_async_tool_caller(session, tool_name),
                )
                self._all_tools.append(tool)
                loaded_count += 1

            logger.info(f"[MCP] 📦 从 {name} 加载了 {loaded_count} 个工具")

        except Exception as e:
            logger.error(f"[MCP] 从 {name} 加载工具失败: {str(e)}")

    def _make_tool_caller(self, session: Any, tool_name: str):
        """创建同步工具调用器（LangChain 兼容）"""
        def caller(**kwargs):
            # 同步调用异步方法（在已有事件循环中）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果在运行中的事件循环，创建新任务
                    future = asyncio.ensure_future(self._call_tool_async(session, tool_name, kwargs))
                    # 这里简化处理，实际应该使用 asyncio.run_coroutine_threadsafe
                    return f"[异步工具 {tool_name} 请使用 await 调用]"
                else:
                    return loop.run_until_complete(self._call_tool_async(session, tool_name, kwargs))
            except RuntimeError:
                return f"[工具 {tool_name} 需要在异步环境中调用]"
        return caller

    def _make_async_tool_caller(self, session: Any, tool_name: str):
        """创建异步工具调用器（主要使用这个）"""
        async def caller(**kwargs):
            return await self._call_tool_async(session, tool_name, kwargs)
        return caller

    async def _call_tool_async(self, session: Any, tool_name: str, kwargs: dict) -> str:
        """实际调用 MCP 工具"""
        try:
            result = await session.call_tool(tool_name, arguments=kwargs)
            # 提取文本内容
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            return "\n".join(texts) if texts else str(result.content)
        except Exception as e:
            logger.error(f"[MCP] 调用工具 {tool_name} 失败: {str(e)}")
            return f"[工具调用失败: {str(e)}]"

    # ========== 获取工具 ==========
    def get_tools(self) -> List[Tool]:
        """获取所有已加载的 MCP 工具（LangChain 格式）"""
        return self._all_tools

    def get_tool_names(self) -> List[str]:
        """获取所有工具名称列表"""
        return [t.name for t in self._all_tools]

    def get_stats(self) -> dict:
        """获取连接统计信息"""
        return {
            "connected_servers": list(self.sessions.keys()),
            "total_tools": len(self._all_tools),
            "tool_names": self.get_tool_names(),
        }

    # ========== 关闭连接 ==========
    async def close(self):
        """关闭所有 MCP 连接"""
        await self.exit_stack.aclose()
        self.sessions.clear()
        self._all_tools.clear()
        self._tool_source.clear()
        logger.info("[MCP] 所有连接已关闭")


# 全局 MCP 客户端单例
_mcp_client: Optional[MCPClient] = None


async def get_mcp_client() -> MCPClient:
    """获取或初始化 MCP 客户端"""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client