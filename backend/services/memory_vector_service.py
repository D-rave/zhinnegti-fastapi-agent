"""
记忆向量检索服务 V2
功能：
1. 将用户画像和会话摘要向量化存入 Chroma
2. 对话前根据用户问题检索最相关的记忆片段（top-k）
3. 只注入相关记忆，避免全量注入导致上下文过长

【修复】所有同步 Chroma 操作改为异步包装，避免阻塞 FastAPI 事件循环
"""
import os
import asyncio
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from model.factory import EmbeddingsFactory
from utils.config_handler import load_chroma_config
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


class MemoryVectorStore:
    """
    用户记忆向量存储
    每个用户独立 collection，支持记忆片段的增删改查和语义检索
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.embeddings = EmbeddingsFactory().generator()

        # 加载 Chroma 配置
        chroma_conf = load_chroma_config()
        persist_dir = get_abs_path(chroma_conf.get("persist_directory", "./chroma_db"))
        os.makedirs(persist_dir, exist_ok=True)

        # 每个用户一个 collection
        collection_name = f"memory_user_{user_id}"

        self.vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=self.embeddings,
            persist_directory=persist_dir,
        )
        logger.info(f"[记忆向量] 初始化用户 {user_id} 的记忆库: {collection_name}")

    def _add_memory_sync(self, content: str, memory_type: str = "profile"):
        """同步：添加记忆片段"""
        doc = Document(
            page_content=content,
            metadata={"type": memory_type, "user_id": self.user_id}
        )
        self.vectorstore.add_documents([doc])
        logger.info(f"[记忆向量] 用户 {self.user_id} 添加 {memory_type}: {content[:50]}...")

    async def add_memory_async(self, content: str, memory_type: str = "profile"):
        """异步：添加记忆片段"""
        await asyncio.to_thread(self._add_memory_sync, content, memory_type)

    def _search_relevant_sync(self, query: str, k: int = 3) -> List[str]:
        """同步：检索相关记忆"""
        results = self.vectorstore.similarity_search(query, k=k)
        memories = [doc.page_content for doc in results]
        logger.info(f"[记忆向量] 用户 {self.user_id} 检索 '{query[:30]}...' 命中 {len(memories)} 条记忆")
        for i, m in enumerate(memories):
            logger.info(f"[记忆向量] top-{i+1}: {m[:80]}...")
        return memories

    async def search_relevant_async(self, query: str, k: int = 3) -> List[str]:
        """异步：检索相关记忆"""
        return await asyncio.to_thread(self._search_relevant_sync, query, k)

    def _clear_sync(self):
        """同步：清空记忆"""
        self.vectorstore.delete_collection()
        logger.info(f"[记忆向量] 用户 {self.user_id} 记忆库已清空")

    async def clear_async(self):
        """异步：清空记忆"""
        await asyncio.to_thread(self._clear_sync)


class MemoryVectorService:
    """
    记忆向量服务封装
    提供用户记忆的全生命周期管理：提取 → 存储 → 检索 → 注入
    """

    def __init__(self):
        self._store_cache = {}  # user_id -> MemoryVectorStore

    def _get_store(self, user_id: int) -> MemoryVectorStore:
        """获取或创建用户的记忆向量库"""
        if user_id not in self._store_cache:
            self._store_cache[user_id] = MemoryVectorStore(user_id)
        return self._store_cache[user_id]

    # ---------- 同步方法（保留兼容） ----------
    def save_profile(self, user_id: int, content: str):
        store = self._get_store(user_id)
        store._add_memory_sync(content, memory_type="profile")

    def save_summary(self, user_id: int, content: str):
        store = self._get_store(user_id)
        store._add_memory_sync(content, memory_type="summary")

    def save_fact(self, user_id: int, content: str):
        store = self._get_store(user_id)
        store._add_memory_sync(content, memory_type="fact")

    def retrieve_for_query(self, user_id: int, query: str, k: int = 3) -> str:
        store = self._get_store(user_id)
        memories = store._search_relevant_sync(query, k=k)
        if not memories:
            return ""
        memory_text = "【相关记忆】\n"
        for i, m in enumerate(memories, 1):
            memory_text += f"{i}. {m}\n"
        return memory_text

    # ---------- 异步方法（推荐在 async 路由中使用）----------
    async def save_profile_async(self, user_id: int, content: str):
        store = self._get_store(user_id)
        await store.add_memory_async(content, memory_type="profile")

    async def save_summary_async(self, user_id: int, content: str):
        store = self._get_store(user_id)
        await store.add_memory_async(content, memory_type="summary")

    async def save_fact_async(self, user_id: int, content: str):
        store = self._get_store(user_id)
        await store.add_memory_async(content, memory_type="fact")

    async def retrieve_for_query_async(self, user_id: int, query: str, k: int = 3) -> str:
        store = self._get_store(user_id)
        memories = await store.search_relevant_async(query, k=k)
        if not memories:
            return ""
        memory_text = "【相关记忆】\n"
        for i, m in enumerate(memories, 1):
            memory_text += f"{i}. {m}\n"
        return memory_text

    def clear_user_memory(self, user_id: int):
        """清空某用户的全部记忆"""
        if user_id in self._store_cache:
            self._store_cache[user_id]._clear_sync()
            del self._store_cache[user_id]

    async def clear_user_memory_async(self, user_id: int):
        """异步清空某用户的全部记忆"""
        if user_id in self._store_cache:
            await self._store_cache[user_id].clear_async()
            del self._store_cache[user_id]


# 全局实例
memory_vector_service = MemoryVectorService()