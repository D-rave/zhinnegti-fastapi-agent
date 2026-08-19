"""
模型降级链：主模型故障时依次切换备用模型

参照 chat-langchain 的 ModelFallbackMiddleware + init_retry_fallback_model：
- 调用链上的每个模型都先经过重试策略（ModelRetryPolicy）
- 重试仍失败则切换到下一个备用模型，备用模型同样享有完整重试预算
- 全部失败时抛出最后一次异常（由上层转友好提示）
- bind_tools 返回新的降级链包装，链上每个模型都绑定同样的工具
"""
from typing import Any, List, Optional, Tuple

from agent.middleware.model_retry import ModelRetryPolicy
from utils.logger_handler import logger

#: 默认降级链（主模型在前）；生产环境可通过 config/agent.yml 覆盖
DEFAULT_FALLBACK_MODELS = ("qwen-max", "qwen-plus", "qwen-turbo")


class FallbackChatModel:
    """
    带降级链的聊天模型包装器，对外暴露与 ChatModel 一致的 ainvoke 接口。

    :param models: [(模型名, 模型实例), ...]，按优先级排列
    :param retry_policy: 每个模型各自的重试策略；None 时创建默认策略
    """

    def __init__(
        self,
        models: List[Tuple[str, Any]],
        retry_policy: Optional[ModelRetryPolicy] = None,
    ):
        if not models:
            raise ValueError("FallbackChatModel 至少需要一个模型")
        self.models = models
        self.retry_policy = retry_policy or ModelRetryPolicy()
        # 记录主模型名，供用量追踪使用（兼容原有 self.model_name 用法）
        self.model_name = models[0][0]

    @classmethod
    def from_model_names(
        cls,
        model_names: tuple[str, ...] = DEFAULT_FALLBACK_MODELS,
        retry_policy: Optional[ModelRetryPolicy] = None,
    ) -> "FallbackChatModel":
        """按模型名构建真实降级链（懒加载，供生产环境使用）。"""
        from model.factory import ChatModelFactory

        factory = ChatModelFactory()
        models = [(name, factory._get_model(name)) for name in model_names]
        return cls(models=models, retry_policy=retry_policy)

    def bind_tools(self, tools: list, **kwargs) -> "FallbackChatModel":
        """链上每个模型绑定同样的工具，返回新的降级链包装。"""
        bound = [(name, m.bind_tools(tools, **kwargs)) for name, m in self.models]
        return FallbackChatModel(models=bound, retry_policy=self.retry_policy)

    async def ainvoke(self, messages: list, **kwargs) -> Any:
        """
        依次尝试链上模型，每个模型先走重试策略。
        全部失败抛出最后一次异常。
        """
        last_exception: Exception | None = None

        for idx, (name, model) in enumerate(self.models):
            try:
                if idx > 0:
                    logger.warning(
                        f"[ModelFallback] 主模型不可用，切换到备用模型: {name}"
                    )
                return await self.retry_policy.execute(
                    lambda: model.ainvoke(messages, **kwargs),
                    operation=f"ainvoke({name})",
                )
            except Exception as exc:
                last_exception = exc
                logger.error(f"[ModelFallback] 模型 {name} 最终失败: {exc}")
                continue

        raise last_exception  # type: ignore[misc]


__all__ = ["FallbackChatModel", "DEFAULT_FALLBACK_MODELS"]