"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
【增强版】新增查询扩展（Query Expansion），提升检索召回率
【修复】同步 LLM 调用改为异步 ainvoke，避免阻塞事件循环
【新增】接入 DashScope Token 用量追踪
"""
import time
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from rag.vector_store import VectorStoreService
from utils.prompt_loader import load_rag_prompts
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from core.dashscope_usage_tracker import track_llm_call

def print_prompt(prompt):
    print("=" * 20)
    print(prompt.to_string())
    print("=" * 20)
    return prompt


class RagSummarizeService(object):
    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.model_name = getattr(self.model, "model_name", "qwen-max")

    async def _expand_query(self, query: str) -> list[str]:
        """
        查询扩展：用 LLM 把用户问题改写成 3 个更精准的专业检索词
        """
        expansion_prompt = """你是扫地机器人领域的查询扩展专家。
请将用户的问题扩展为 3 个不同角度的检索词，帮助从知识库找到更全面的信息。

用户问题：{query}

要求：
1. 使用更专业、更具体的关键词
2. 考虑同义词、近义词、上下位词
3. 每个词换行分隔
4. 只输出检索词，不要解释

扩展检索词："""

        start = time.time()
        response = await self.model.ainvoke(expansion_prompt.format(query=query))
        latency = (time.time() - start) * 1000

        await track_llm_call(
            response=response,
            model_name=self.model_name,
            latency_ms=latency,
            endpoint="rag.expand_query"
        )

        content = response.content if hasattr(response, "content") else str(response)

        expanded = [q.strip() for q in content.strip().split("\n") if q.strip()]

        all_queries = [query] + expanded
        seen = set()
        unique_queries = []
        for q in all_queries:
            if q not in seen and len(q) > 0:
                seen.add(q)
                unique_queries.append(q)

        print(f"[Query Expansion] 原始: '{query}' → 扩展: {unique_queries}")
        return unique_queries[:5]

    def retriever_docs(self, query: str) -> list[Document]:
        """单查询检索（保留原方法，兼容外部调用）"""
        return self.retriever.invoke(query)

    def retriever_docs_multi(self, queries: list[str]) -> list[Document]:
        """
        多查询并行检索，合并去重
        """
        all_docs = []
        for q in queries:
            docs = self.retriever.invoke(q)
            all_docs.extend(docs)

        seen_content = {}
        for doc in all_docs:
            content = doc.page_content.strip()
            if content not in seen_content:
                seen_content[content] = doc

        unique_docs = list(seen_content.values())
        print(f"[Multi-Retrieve] 原始检索 {len(all_docs)} 篇，去重后 {len(unique_docs)} 篇")
        return unique_docs[:10]

    async def rag_summarize(self, query: str) -> str:
        """RAG 总结：检索 + LLM 生成"""
        expanded_queries = await self._expand_query(query)
        context_docs = self.retriever_docs_multi(expanded_queries)

        context = ""
        for i, doc in enumerate(context_docs, 1):
            context += f"【参考资料{i}】: 参考资料：{doc.page_content} | 参考元数据：{doc.metadata}\n"

        # 构建 prompt 并打印
        prompt_value = self.prompt_template.invoke({"input": query, "context": context})
        print_prompt(prompt_value)

        # 直接调用模型以获取 token_usage
        start = time.time()
        response = await self.model.ainvoke(prompt_value)
        latency = (time.time() - start) * 1000

        await track_llm_call(
            response=response,
            model_name=self.model_name,
            latency_ms=latency,
            endpoint="rag.rag_summarize"
        )

        result = StrOutputParser().invoke(response)
        return result