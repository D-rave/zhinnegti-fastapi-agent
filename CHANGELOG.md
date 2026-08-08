# Changelog

所有项目的显著变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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