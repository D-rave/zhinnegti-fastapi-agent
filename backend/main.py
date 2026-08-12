"""
FastAPI 后端入口 - V5 生产级
集成：DashScope 用量追踪 + 监控告警（Prometheus + Sentry）+ 安全加固
"""
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.logger_handler import logger
from models.db import engine, Base, DB_TYPE
from models.usage import LLMUsageLog  # 确保用量表被注册到 metadata
from middlewares.error_handler import setup_exception_handlers
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.request_log import RequestLogMiddleware
from core.config import get_settings
from api.v1 import api_router
from utils.redis_client import close_redis
from core.dashscope_usage_tracker import usage_tracker
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"[系统启动] 正在初始化数据库（{DB_TYPE}）...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[系统启动] 数据库表创建/检查完成")

    # 连接 MCP 服务器
    from mcp_client import get_mcp_client
    mcp = await get_mcp_client()
    app.state.mcp_tools = []

    amap_key = os.environ.get("AMAP_API_KEY", "")
    if amap_key:
        success = await mcp.connect_stdio(
            name="amap",
            command="npx",
            args=["-y", "@amap/amap-maps-mcp-server"],
            env={"AMAP_MAPS_API_KEY": amap_key}
        )
        if success:
            logger.info("[MCP] 高德地图 MCP 已连接")

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        success = await mcp.connect_stdio(
            name="tavily",
            command="npx",
            args=["-y", "mcp-remote", f"https://mcp.tavily.com/mcp/?tavilyApiKey={tavily_key}"]
        )
        if success:
            logger.info("[MCP] Tavily 搜索已连接")

    app.state.mcp_tools = mcp.get_tools()
    stats = mcp.get_stats()
    logger.info(f"[MCP] 总计加载 {stats['total_tools']} 个外部工具")

    # Redis 连接测试
    from utils.redis_client import get_redis
    try:
        r = await get_redis()
        if r:
            logger.info("[Redis] 缓存服务已就绪")
    except Exception as e:
        logger.warning(f"[Redis] 连接失败: {e}（降级为无缓存模式）")

    # 【监控】初始化 Sentry
    from monitoring.sentry_integration import init_sentry
    init_sentry()

    # 【监控】初始化 Prometheus 应用信息
    from monitoring.prometheus_metrics import init_app_info
    init_app_info()

    # 【用量追踪】保留定时刷盘任务（数据库版仅清空 buffer，兼容旧代码）
    async def _periodic_flush():
        while True:
            await asyncio.sleep(60)
            try:
                from core.dashscope_usage_tracker import usage_tracker
                await usage_tracker.flush_to_redis()
            except Exception as e:
                logger.warning(f"[UsageTracker] 定时刷盘失败: {e}")

    flush_task = asyncio.create_task(_periodic_flush())

    logger.info(f"[系统启动] {settings.APP_NAME} V{settings.APP_VERSION} 已启动")
    yield

    # 关闭清理
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    # 最终刷盘（数据库版仅清空 buffer）
    try:
        from core.dashscope_usage_tracker import usage_tracker
        await usage_tracker.flush_to_redis()
    except Exception as e:
        logger.warning(f"[UsageTracker] 最终刷盘失败: {e}")

    try:
        await mcp.close()
    except Exception as e:
        logger.warning(f"[MCP] 关闭连接时出错: {e}")
    await close_redis()
    logger.info("[系统关闭] 后端服务已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="基于多步 ReAct Agent + RAG + 记忆向量检索 + Redis + MySQL 的智能客服后端",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ========== 中间件注册（顺序很重要）==========

# 1. CORS（最先注册，处理预检请求）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# 2. 【监控】Prometheus 指标收集（在请求日志之前，确保记录所有请求）
from monitoring.prometheus_middleware import PrometheusMiddleware
app.add_middleware(PrometheusMiddleware)

# 3. 请求日志
app.add_middleware(RequestLogMiddleware)

# 4. 速率限制
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)

# ========== 异常处理 ==========
setup_exception_handlers(app)

# ========== 路由注册 ==========
@app.get("/api/health")
async def health_check():
    from mcp_client import get_mcp_client
    from utils.redis_client import get_redis

    mcp = await get_mcp_client()
    stats = mcp.get_stats()

    redis_status = "ok"
    try:
        r = await get_redis()
        if r is None:
            redis_status = "disabled"
    except Exception:
        redis_status = "error"

    return {
        "status": "ok",
        "service": "zhinengti-backend",
        "version": settings.APP_VERSION,
        "database": DB_TYPE,
        "mcp": stats,
        "redis": redis_status,
    }

# 【监控】Prometheus 指标路由
from monitoring.prometheus_metrics import router as metrics_router
app.include_router(metrics_router, prefix="/metrics")

# API v1 路由
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8011, reload=settings.DEBUG)