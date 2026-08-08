"""
FastAPI 后端入口 - V4 生产级
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.logger_handler import logger
from models.db import engine, Base, DB_TYPE
from middlewares.error_handler import setup_exception_handlers
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.request_log import RequestLogMiddleware
from core.config import get_settings
from api.v1 import api_router
from utils.redis_client import close_redis

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

    logger.info(f"[系统启动] {settings.APP_NAME} V{settings.APP_VERSION} 已启动")
    yield

    # 关闭清理
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

# ========== 中间件注册（CORS 必须最先注册，确保预检请求被正确拦截）==========

# 1. CORS（最先注册，确保 OPTIONS 预检请求直接返回 200）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境直接放行所有来源
    allow_credentials=False,  # allow_origins=["*"] 时 credentials 必须为 False
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# 2. 请求日志（纯 ASGI 中间件，不干扰请求对象）
app.add_middleware(RequestLogMiddleware)

# 3. 速率限制（纯 ASGI 中间件，跳过 OPTIONS）
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)

# ========== 异常处理 ==========
setup_exception_handlers(app)

# ========== 路由注册 ==========
# 健康检查（无版本前缀）
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

# API v1 路由
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8011, reload=settings.DEBUG)