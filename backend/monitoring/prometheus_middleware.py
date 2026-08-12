"""Prometheus 指标收集中间件"""
import time
from starlette.types import ASGIApp, Scope, Receive, Send
from monitoring.prometheus_metrics import REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_CONNECTIONS

class PrometheusMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        # 跳过 metrics 端点自身，避免递归
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        ACTIVE_CONNECTIONS.inc()
        start_time = time.time()

        status_code = 200

        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            duration = time.time() - start_time
            ACTIVE_CONNECTIONS.dec()

            REQUEST_COUNT.labels(
                method=method,
                endpoint=path,
                status_code=str(status_code)
            ).inc()
            REQUEST_LATENCY.labels(
                method=method,
                endpoint=path
            ).observe(duration)