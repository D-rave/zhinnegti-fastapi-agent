"""模型工厂 - 支持懒加载和异常降级"""
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
    @lru_cache(maxsize=1)
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """懒加载聊天模型，失败时自动降级"""
        model_name = rag_conf.get("chat_model_name", "qwen-turbo")

        try:
            model = ChatTongyi(model=model_name)
            logger.info(f"[Model] 聊天模型初始化成功: {model_name}")
            return model
        except Exception as e:
            logger.error(f"[Model] 聊天模型 {model_name} 初始化失败: {e}")

            # 降级：尝试基础模型
            fallback_name = "qwen-turbo"
            if model_name != fallback_name:
                try:
                    model = ChatTongyi(model=fallback_name)
                    logger.warning(f"[Model] 已降级到 {fallback_name}")
                    return model
                except Exception as e2:
                    logger.error(f"[Model] 降级到 {fallback_name} 也失败: {e2}")

            raise RuntimeError(
                f"无法初始化聊天模型。请检查：\n"
                f"1. DashScope API Key 是否设置（环境变量 DASHSCOPE_API_KEY）\n"
                f"2. 网络是否通畅\n"
                f"3. 模型名称 '{model_name}' 是否正确\n"
                f"原始错误: {e}"
            )


class EmbeddingsFactory(BaseModelFactory):
    @lru_cache(maxsize=1)
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """懒加载 Embedding 模型"""
        model_name = rag_conf.get("embedding_model_name", "text-embedding-v1")

        try:
            model = DashScopeEmbeddings(model=model_name)
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