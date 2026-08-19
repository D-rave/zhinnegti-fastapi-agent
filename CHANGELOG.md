# Changelog

所有项目的显著变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **Agent 中间层管道**（`backend/agent/middleware/`，参照 [chat-langchain](https://github.com/langchain-ai/chat-langchain) 的中间件思路）：
  - 入口守卫：超长用户输入截断（默认 50,000 字符）
  - 话题护栏：轻量模型（qwen-turbo）在主模型前做 ALLOWED/BLOCKED 分类，支持分类模型降级链、独立重试预算、单次超时、fail-open 放行、友好拒绝文案
  - 模型重试：指数退避，支持可重试 finish_reason（MALFORMED_FUNCTION_CALL）与限流/超时/5xx 异常判定
  - 模型降级链：主模型故障时依次切换备用模型（qwen-max → qwen-plus → qwen-turbo），每个模型享有独立重试预算
  - 工具重试：工具瞬时故障（429/5xx/超时）指数退避重试，耗尽后返回模型可读错误而非中断循环
  - 历史摘要压缩：对话超 token 阈值时自动摘要老消息、保留最近消息，摘要失败退化为截断
- 中间层配置项（`backend/config/agent.yml` 的 `middleware` 段）
- **单元测试套件**（`backend/tests/unit/`，52 个用例，Fake 模型零网络依赖）：
  - 入口守卫截断 / 多模态内容保留
  - 护栏模型链降级、fail-open、拒绝文案兜底、观测模式
  - 模型重试退避、可重试判定、畸形响应处理
  - 工具重试、模型可读错误回传
  - 历史摘要触发/预算/失败退化
  - Agent 接线测试（护栏短路、文本工具调用提取、输入截断、历史摘要透传）
  - 提示词约束断言（防止护栏规则被改丢）

### Changed
- ReactAgent 接入中间层管道（`_preprocess`：守卫 → 护栏 → 摘要 → 重试/降级循环）
- `_build_messages` 透传 system 角色的历史消息（修复摘要注入后被丢弃的问题）
- `tests/conftest.py` 重依赖缺失时优雅降级：API 集成测试自动 skip，单元测试可在最小环境运行

### Added
- 项目初始化，完成基础架构搭建
- FastAPI + Vue 3 前后端分离架构
- ReAct Agent 多步推理
- RAG 知识库检索（Chroma）
- 长期记忆系统（SQLite + 向量检索）
- MCP 工具集成（高德地图、Tavily 搜索）
- JWT 用户认证
- SSE 流式对话
- Redis 缓存
- Docker + Docker Compose 部署
- 单元测试（pytest）
- CI/CD 工作流（GitHub Actions）
- 管理后台（用户管理、知识库管理、系统配置）
- 速率限制中间件
- 请求日志中间件
- 全局异常处理
- 日志轮转和敏感信息过滤
- 代码格式化（black、isort、prettier）

### Changed
- 后端路由重构为 API v1 版本
- 引入 Pydantic Settings 统一管理配置
- CORS 配置精细化（生产环境白名单）

### Fixed
- 前端实时输出问题
- 历史会话丢失问题

## [3.0.0] - 2026-08-06

### Added
- 首次发布完整版智能客服系统