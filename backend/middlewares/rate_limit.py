"""速率限制中间件（纯 ASGI 实现）"""
from starlette.responses import JSONResponse

from utils.redis_client import get_redis
from utils.logger_handler import logger


class RateLimitMiddleware:
    """基于 Redis 的速率限制中间件（纯 ASGI）"""

    def __init__(self, app, requests_per_minute: int = 60):
        self.app = app
        self.requests_per_minute = requests_per_minute

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 跳过健康检查和文档
        if path in ["/api/health", "/docs", "/openapi.json"]:
            await self.app(scope, receive, send)
            return

        # 跳过 OPTIONS 预检请求（让 CORS 处理）
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # 获取客户端 IP
        headers = dict(scope.get("headers", []))
        client_ip = "unknown"
        for key, value in headers.items():
            if key == b"x-forwarded-for":
                client_ip = value.decode().split(",")[0].strip()
                break
        if client_ip == "unknown":
            client = scope.get("client")
            if client:
                client_ip = client[0]

        key = f"rate_limit:{client_ip}"

        try:
            redis = await get_redis()
            if redis:
                current = await redis.get(key)
                if current and int(current) >= self.requests_per_minute:
                    # 返回 429
                    response = JSONResponse(
                        status_code=429,
                        content={"detail": "请求过于频繁，请稍后再试"}
                    )
                    await response(scope, receive, send)
                    return

                pipe = redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, 60)
                await pipe.execute()
        except Exception as e:
            logger.warning(f"速率限制检查失败（降级放行）: {e}")

        await self.app(scope, receive, send)