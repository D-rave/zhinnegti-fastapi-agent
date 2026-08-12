"""Prometheus 指标暴露"""
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi import APIRouter, Response

router = APIRouter()

# HTTP 请求指标
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'active_connections',
    'Number of active connections'
)

# LLM 调用指标
LLM_CALL_COUNT = Counter(
    'llm_calls_total',
    'Total LLM calls',
    ['model', 'status']
)

LLM_LATENCY = Histogram(
    'llm_call_duration_seconds',
    'LLM call latency',
    ['model']
)

# 应用信息
APP_INFO = Info('app_info', 'Application information')

def init_app_info():
    from core.config import get_settings
    settings = get_settings()
    APP_INFO.info({
        'name': settings.APP_NAME,
        'version': settings.APP_VERSION,
    })

@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)