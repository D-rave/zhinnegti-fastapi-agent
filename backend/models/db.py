"""
数据库连接配置 V5
支持：SQLite（本地开发）和 MySQL（生产部署）切换
通过环境变量 DB_TYPE 控制：sqlite | mysql
新增：支持 DATABASE_URL 环境变量覆盖（用于测试内存数据库）

修复：用 importlib 延迟导入所有模型，确保 Base.metadata 包含所有表，避免循环导入
"""
import os
import importlib
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from utils.logger_handler import logger

# ========== 新增：支持 DATABASE_URL 环境变量覆盖（pytest 测试用）==========
DATABASE_URL = os.environ.get("DATABASE_URL")

# 在 models/db.py 的 DATABASE_URL 处理部分，确保路径正确
if DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    DB_TYPE = "sqlite"
    logger.info(f"[数据库] 使用环境变量 DATABASE_URL: {DATABASE_URL}")

else:
    DB_TYPE = os.environ.get("DB_TYPE", "sqlite").lower()

    if DB_TYPE == "mysql":
        DB_HOST = os.environ.get("DB_HOST", "localhost")
        DB_PORT = os.environ.get("DB_PORT", "3306")
        DB_USER = os.environ.get("DB_USER", "root")
        DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
        DB_NAME = os.environ.get("DB_NAME", "zhinengti")

        if not DB_PASSWORD:
            logger.warning("[数据库] ⚠️ MySQL 密码未设置（环境变量 DB_PASSWORD），连接可能失败")

        SQLALCHEMY_DATABASE_URL = (
            f"mysql+asyncmy://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            f"?charset=utf8mb4"
        )
        logger.info(f"[数据库] 使用 MySQL 模式: {DB_HOST}:{DB_PORT}/{DB_NAME}")

    else:
        DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "zhinengti.db")
        SQLALCHEMY_DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
        logger.info(f"[数据库] 使用 SQLite 模式: {DB_PATH}")


# ========== 引擎创建（根据数据库类型选择参数）==========
if DB_TYPE == "mysql":
    engine = create_async_engine(
        SQLALCHEMY_DATABASE_URL,
        echo=False,
        future=True,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
else:
    # SQLite（文件或内存）不支持 pool_size/max_overflow
    engine = create_async_engine(
        SQLALCHEMY_DATABASE_URL,
        echo=False,
        future=True,
    )

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


# ========== 延迟导入所有模型，确保 Base.metadata 包含所有表 ==========
# 【关键修复】新增 models.usage，确保 llm_usage_logs 表被创建
for _model_module in ["models.user", "models.chat", "models.memory", "models.usage"]:
    try:
        importlib.import_module(_model_module)
        logger.info(f"[数据库] 模型模块已加载: {_model_module}")
    except Exception as e:
        logger.warning(f"[数据库] 模型模块加载失败: {_model_module} - {e}")


async def get_db() -> AsyncSession:
    """FastAPI Depends 用的数据库会话生成器"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()