"""聊天模块测试"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_send_without_auth(client: AsyncClient):
    """测试未登录发送消息（应该允许匿名）"""
    response = await client.post("/api/chat/send", json={  # ← 去掉 /v1
        "message": "你好",
        "session_id": ""
    })
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_history(client: AsyncClient):
    """测试获取历史记录"""
    await client.post("/api/chat/send", json={  # ← 去掉 /v1
        "message": "测试消息",
        "session_id": "test-session-123"
    })
    response = await client.get("/api/chat/history?session_id=test-session-123")  # ← 去掉 /v1
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "messages" in data


@pytest.mark.asyncio
async def test_clear_chat(client: AsyncClient):
    """测试清空会话"""
    response = await client.post("/api/chat/clear", json={  # ← 去掉 /v1
        "session_id": "test-clear-session"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True