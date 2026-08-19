"""
Agent 中间层（Model Middleware Pipeline）

参照 langchain-ai/chat-langchain 的中间件管道思路，
为手写的 ReactAgent 循环提供生产级模型中间处理能力：

- ingress_guards:  入口守卫，截断超长用户输入
- guardrails:      小模型话题护栏（主模型 + 降级链 + 独立重试预算 + 超时 + fail-open）
- model_retry:     模型调用指数退避重试（含可重试 finish_reason / 异常判定）
- tool_retry:      工具瞬时故障重试（429/5xx/超时），失败返回模型可读错误
- summarization:   对话历史超阈值时摘要压缩，防止上下文溢出
- model_fallback:  主模型故障时沿降级链切换备用模型

所有组件均支持依赖注入（传入 Fake 模型即可单测），
单测不需要真实 API Key / 网络。
"""