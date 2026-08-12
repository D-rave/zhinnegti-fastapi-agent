"""模型工厂 - 支持懒加载、异常降级、模型名记录"""
from abc import ABC, abstractmethod
from typing import Optional, Union
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import rag_conf
from utils.logger_handler import logger


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        pass


class ChatModelFactory(BaseModelFactory):
    @lru_cache(maxsize=4)
    def _get_model(self, model_name: str) -> Optional[BaseChatModel]:
        """按模型名获取实例（带缓存）"""
        try:
            model = ChatTongyi(model=model_name)
            # 【关键】用 object.__setattr__ 绕过 Pydantic 字段校验，附加模型名供用量追踪使用
            object.__setattr__(model, "model_name", model_name)
            logger.info(f"[Model] 聊天模型初始化成功: {model_name}")
            return model
        except Exception as e:
            logger.error(f"[Model] 聊天模型 {model_name} 初始化失败: {e}")
            raise

    def generator(self, query: Optional[str] = None) -> BaseChatModel:
        """
        获取聊天模型
        如果传入 query，自动根据复杂度路由到合适模型（当前默认 qwen-max）
        """
        model_name = rag_conf.get("chat_model_name", "qwen-max")
        return self._get_model(model_name)

    def generator_for_step(self, query: str, step: int = 1) -> BaseChatModel:
        """Agent 步骤化模型选择（当前统一使用 qwen-max）"""
        model_name = rag_conf.get("chat_model_name", "qwen-max")
        return self._get_model(model_name)


class EmbeddingsFactory(BaseModelFactory):
    @lru_cache(maxsize=1)
    def generator(self) -> Optional[Embeddings]:
        """懒加载 Embedding 模型"""
        model_name = rag_conf.get("embedding_model_name", "text-embedding-v4")
        try:
            model = DashScopeEmbeddings(model=model_name)
            # 【关键】用 object.__setattr__ 绕过 Pydantic 字段校验
            object.__setattr__(model, "model_name", model_name)
            logger.info(f"[Model] Embedding 模型初始化成功: {model_name}")
            return model
        except Exception as e:
            logger.error(f"[Model] Embedding 模型 {model_name} 初始化失败: {e}")
            raise RuntimeError(
                f"无法初始化 Embedding 模型。请检查：\n"
                f"1. DashScope API Key 是否设置\n"
                f"2. 网络是否通畅\n"
                f"原始错误: {e}"
            )


# ========== 兼容旧代码的模块级变量（懒加载） ==========
_chat_model_instance = None
_embed_model_instance = None


def _get_chat_model():
    global _chat_model_instance
    if _chat_model_instance is None:
        _chat_model_instance = ChatModelFactory().generator()
    return _chat_model_instance


def _get_embed_model():
    global _embed_model_instance
    if _embed_model_instance is None:
        _embed_model_instance = EmbeddingsFactory().generator()
    return _embed_model_instance


# 使用 __getattr__ 实现 from model.factory import chat_model 的兼容性
def __getattr__(name):
    if name == "chat_model":
        return _get_chat_model()
    if name == "embed_model":
        return _get_embed_model()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")