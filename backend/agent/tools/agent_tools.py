"""
Agent 工具集合
只保留真实功能工具，删除所有假数据/模拟数据工具

真实工具：
 - rag_summarize: 本地向量库 RAG 检索（查扫地机器人知识库）
 - tavily_search / tavily_extract 等: Tavily 智能搜索（通过 MCP 接入）
"""

from langchain_core.tools import tool
from rag.rag_service import RagSummarizeService

rag = RagSummarizeService()


@tool(description="从本地向量存储中检索扫地机器人相关的参考资料，入参 query 为用户问题关键词")
async def rag_summarize(query: str) -> str:
    """
    RAG 检索工具：查询本地知识库中的扫地机器人产品资料、维修手册、常见问题等
    【修复】改为 async，内部调用异步 chain.ainvoke，避免阻塞事件循环
    """
    return await rag.rag_summarize(query)