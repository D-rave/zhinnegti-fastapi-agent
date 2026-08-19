"""pytest 配置和共享 fixtures"""
import sys
import os
import tempfile
import shutil

# 设置环境变量（必须在 import main 之前）
# 使用临时文件数据库（Windows 兼容）
TEST_DB_DIR = tempfile.mkdtemp()
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["DB_TYPE"] = "sqlite"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import pytest
import pytest_asyncio

# 【改进】重依赖（fastapi/httpx/sqlalchemy 等）缺失时优雅降级：
# API 集成测试自动 skip，纯逻辑单元测试（tests/unit/）仍可在最小环境中运行。
# 参照 chat-langchain tests/unit 不依赖外部服务的设计。
try:
    from httpx import AsyncClient, ASGITransport

    # 先 import main，触发 lifespan 创建表
    from main import app
    from models.db import Base, get_db, engine, async_session_maker

    _APP_AVAILABLE = True
except ImportError as _import_err:
    app = None
    _APP_AVAILABLE = False
    _IMPORT_ERROR = _import_err

if _APP_AVAILABLE:
    # ========== 手动创建表 ==========
    async def init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_tables())


@pytest_asyncio.fixture
async def db_session():
    """每个测试用例的独立数据库会话"""
    if not _APP_AVAILABLE:
        pytest.skip(f"应用依赖缺失，跳过 API 集成测试: {_IMPORT_ERROR}")
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """HTTP 测试客户端"""
    if not _APP_AVAILABLE:
        pytest.skip(f"应用依赖缺失，跳过 API 集成测试: {_IMPORT_ERROR}")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    """测试结束后清理临时数据库文件"""
    yield
    # 测试结束后删除临时目录
    if os.path.exists(TEST_DB_DIR):
        shutil.rmtree(TEST_DB_DIR, ignore_errors=True)


@pytest.fixture
def event_loop():
    """每个测试函数独立的事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()