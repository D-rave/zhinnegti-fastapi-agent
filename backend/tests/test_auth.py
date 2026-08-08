"""认证模块测试"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """测试注册成功"""
    response = await client.post("/api/auth/register", json={  # ← 去掉 /v1
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient):
    """测试重复用户名注册失败"""
    await client.post("/api/auth/register", json={  # ← 去掉 /v1
        "username": "duplicate",
        "email": "dup@example.com",
        "password": "testpass123"
    })
    response = await client.post("/api/auth/register", json={  # ← 去掉 /v1
        "username": "duplicate",
        "email": "dup2@example.com",
        "password": "testpass123"
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """测试登录成功"""
    await client.post("/api/auth/register", json={  # ← 去掉 /v1
        "username": "logintest",
        "email": "login@example.com",
        "password": "testpass123"
    })
    response = await client.post("/api/auth/login", data={  # ← 去掉 /v1
        "username": "logintest",
        "password": "testpass123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """测试密码错误"""
    await client.post("/api/auth/register", json={  # ← 去掉 /v1
        "username": "wrongpass",
        "email": "wrong@example.com",
        "password": "testpass123"
    })
    response = await client.post("/api/auth/login", data={  # ← 去掉 /v1
        "username": "wrongpass",
        "password": "wrongpassword"
    })
    assert response.status_code == 401