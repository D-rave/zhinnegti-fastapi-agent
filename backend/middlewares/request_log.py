"""请求日志中间件（纯 ASGI 实现，不干扰 CORS）"""
import time
import uuid

from utils.logger_handler import logger


class RequestLogMiddleware:
    """记录每个请求的耗时和基本信息（纯 ASGI，避免 BaseHTTPMiddleware 干扰请求）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 只处理 HTTP 请求，WebSocket 直接透传
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "") or scope.get("raw_path", b"").decode()

        # 记录请求开始
        logger.info(f"[{request_id}] {method} {path} - 开始处理")

        # 包装 send 函数，在响应开始时记录状态码和耗时
        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                process_time = (time.time() - start_time) * 1000

                # 添加自定义响应头
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-process-time", str(process_time).encode()))
                message["headers"] = headers

                logger.info(
                    f"[{request_id}] {method} {path} - {status_code} - {process_time:.2f}ms"
                )
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as exc:
            process_time = (time.time() - start_time) * 1000
            logger.error(
                f"[{request_id}] {method} {path} - ERROR - {process_time:.2f}ms - {str(exc)}"
            )
            raise