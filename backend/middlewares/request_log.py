"""请求日志中间件（安全增强版）"""
import time
from starlette.types import ASGIApp, Scope, Receive, Send

from utils.logger_handler import logger
from core.security_enhanced import sanitize_for_log

class RequestLogMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        # 净化路径（防止日志注入）
        safe_path = sanitize_for_log(path, max_length=200)

        start_time = time.time()

        # 拦截响应状态
        status_code = 200

        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        await self.app(scope, receive, wrapped_send)

        duration = (time.time() - start_time) * 1000

        # 安全日志：不记录敏感路径的详细内容
        sensitive_paths = ["/api/auth/login", "/api/auth/register"]
        if safe_path in sensitive_paths:
            logger.info(f"[Request] {method} {safe_path} {status_code} {duration:.2f}ms from {client_ip} [SENSITIVE]")
        else:
            logger.info(f"[Request] {method} {safe_path} {status_code} {duration:.2f}ms from {client_ip}")