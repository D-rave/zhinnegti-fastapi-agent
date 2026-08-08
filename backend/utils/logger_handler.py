"""日志处理器（生产级）"""
import logging
import os
import re
from logging.handlers import RotatingFileHandler

# 敏感信息过滤模式
SENSITIVE_PATTERNS = [
    (r'(["\']?(?:api[_-]?key|apikey|key|token|password|secret)["\']?\s*[:=]\s*["\']?)[\w\-]+', r'\1***'),
    (r'(Authorization:\s*Bearer\s+)[\w\-\.]+', r'\1***'),
]


class SensitiveDataFilter(logging.Filter):
    """敏感数据过滤器"""
    def filter(self, record):
        if isinstance(record.msg, str):
            for pattern, replacement in SENSITIVE_PATTERNS:
                record.msg = re.sub(pattern, replacement, record.msg, flags=re.IGNORECASE)
        return True


def setup_logger(name: str = "zhinengti") -> logging.Logger:
    """配置日志"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(console_handler)

    # 文件输出（带轮转，最大 10MB，保留 5 个备份）
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()