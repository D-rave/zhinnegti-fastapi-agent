"""Sentry 错误追踪集成"""
import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from utils.logger_handler import logger

def init_sentry():
    """初始化 Sentry（仅在环境变量设置时启用）"""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.info("[Sentry] 未配置 SENTRY_DSN，跳过初始化")
        return

    environment = os.environ.get("ENVIRONMENT", "development")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,      # 10% 请求采样
        profiles_sample_rate=0.05,
        send_default_pii=False,       # 不发送个人身份信息
    )
    logger.info(f"[Sentry] 已初始化，环境: {environment}")