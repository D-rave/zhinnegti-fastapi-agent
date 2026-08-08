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
from httpx import AsyncClient, ASGITransport

# 先 import main，触发 lifespan 创建表
from main import app
from models.db import Base, get_db, engine, async_session_maker

# ========== 手动创建表 ==========
async def init_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(init_tables())


@pytest_asyncio.fixture
async def db_session():
    """每个测试用例的独立数据库会话"""
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """HTTP 测试客户端"""
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