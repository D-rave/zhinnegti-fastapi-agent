"""
记忆向量检索服务
功能：
1. 将用户画像和会话摘要向量化存入 Chroma
2. 对话前根据用户问题检索最相关的记忆片段（top-k）
3. 只注入相关记忆，避免全量注入导致上下文过长
"""
import os
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

    def add_memory(self, content: str, memory_type: str = "profile"):
        """
        添加记忆片段
        :param content: 记忆内容
        :param memory_type: 类型 - profile(画像) / summary(摘要) / fact(事实)
        """
        doc = Document(
            page_content=content,
            metadata={"type": memory_type, "user_id": self.user_id}
        )
        self.vectorstore.add_documents([doc])
        logger.info(f"[记忆向量] 用户 {self.user_id} 添加 {memory_type}: {content[:50]}...")

    def search_relevant(self, query: str, k: int = 3) -> List[str]:
        """
        根据查询问题检索最相关的记忆片段
        :param query: 用户当前问题
        :param k: 返回 top-k 条
        :return: 记忆文本列表
        """
        results = self.vectorstore.similarity_search(query, k=k)
        memories = [doc.page_content for doc in results]
        logger.info(f"[记忆向量] 用户 {self.user_id} 检索 '{query[:30]}...' 命中 {len(memories)} 条记忆")
        for i, m in enumerate(memories):
            logger.info(f"[记忆向量]  top-{i+1}: {m[:80]}...")
        return memories

    def clear(self):
        """清空该用户的所有记忆"""
        self.vectorstore.delete_collection()
        logger.info(f"[记忆向量] 用户 {self.user_id} 记忆库已清空")


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

    def save_profile(self, user_id: int, content: str):
        """保存用户画像"""
        store = self._get_store(user_id)
        store.add_memory(content, memory_type="profile")

    def save_summary(self, user_id: int, content: str):
        """保存会话摘要"""
        store = self._get_store(user_id)
        store.add_memory(content, memory_type="summary")

    def save_fact(self, user_id: int, content: str):
        """保存关键事实"""
        store = self._get_store(user_id)
        store.add_memory(content, memory_type="fact")

    def retrieve_for_query(self, user_id: int, query: str, k: int = 3) -> str:
        """
        根据用户问题检索相关记忆，格式化为文本
        :return: 格式化的记忆文本，可直接注入系统提示词
        """
        store = self._get_store(user_id)
        memories = store.search_relevant(query, k=k)

        if not memories:
            return ""

        memory_text = "【相关记忆】\n"
        for i, m in enumerate(memories, 1):
            memory_text += f"{i}. {m}\n"
        return memory_text

    def clear_user_memory(self, user_id: int):
        """清空某用户的全部记忆"""
        if user_id in self._store_cache:
            self._store_cache[user_id].clear()
            del self._store_cache[user_id]


# 全局实例
memory_vector_service = MemoryVectorService()