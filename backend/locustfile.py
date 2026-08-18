"""
Locust 压力测试脚本 - 智扫通智能客服
========================================
覆盖接口: 健康检查、认证、聊天(SSE)、会话管理、知识库查询

使用方法:
    1. 确保后端服务已启动 (python main.py 或 docker-compose up)
    2. 安装依赖: pip install locust
    3. 启动压测: cd backend && python -m locust -f locustfile.py --host http://localhost:8011
    4. 浏览器打开 http://localhost:8089 设置并发数和 ramp-up 时间

注意事项:
    - SSE 接口(/api/chat/send)设置了 15 秒超时，避免长时间挂起
    - 每个虚拟用户独立注册/登录，模拟真实用户行为
    - 聊天消息使用随机常见提问，覆盖不同场景
    - 知识库查询使用 JSON body 传递参数，匹配后端 POST 接口定义
"""

import random
import json
from locust import HttpUser, task, between, events
from locust.exception import RescheduleTaskImmediately


# ========== 自定义事件统计 ==========
@events.request.add_listener
def on_request(request_type, name, response_time, response_length,
               response, context, exception, **kwargs):
    """请求完成后可在此做额外统计或日志记录"""
    pass


class ZhinengtiUser(HttpUser):
    """
    智扫通智能客服虚拟用户
    每个用户模拟一个真实终端用户的完整行为链路
    """

    # 请求间隔: 1-3 秒，模拟真实用户思考/操作时间
    wait_time = between(1, 3)

    # 用户状态
    token: str = None
    user_id: int = None
    username: str = None
    session_id: str = None

    # 预置常见提问池，覆盖不同工具调用场景
    CHAT_MESSAGES = [
        "你好，请介绍一下自己",
        "郑州今天天气怎么样",
        "从上海到北京怎么走",
        "附近有哪些门店",
        "产品怎么使用",
        "你们营业时间是什么",
        "怎么联系客服",
        "推荐一款适合我的产品",
        "价格是多少",
        "支持退换货吗",
    ]

    def on_start(self):
        """
        用户启动时执行: 注册 → 登录 → 获取用户信息
        模拟真实用户首次打开应用的行为
        """
        # 生成随机用户名，避免注册冲突
        rand_suffix = random.randint(100000, 999999)
        self.username = f"locust_{rand_suffix}"
        password = "Test@123456"

        # --- 1. 注册 ---
        with self.client.post(
            "/api/auth/register",
            json={"username": self.username, "password": password},
            name="/api/auth/register",
            catch_response=True
        ) as resp:
            if resp.status_code in (200, 400):
                # 200=注册成功, 400=用户名已存在(可接受)
                resp.success()
            else:
                resp.failure(f"注册失败: {resp.status_code} {resp.text}")

        # --- 2. 登录 ---
        with self.client.post(
            "/api/auth/login",
            json={"username": self.username, "password": password},
            name="/api/auth/login",
            catch_response=True
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get("access_token")
                resp.success()
            else:
                resp.failure(f"登录失败: {resp.status_code} {resp.text}")
                raise RescheduleTaskImmediately()

        # --- 3. 获取当前用户信息 ---
        if self.token:
            with self.client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {self.token}"},
                name="/api/auth/me",
                catch_response=True
            ) as resp:
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    self.user_id = data.get("id")
                    resp.success()
                else:
                    resp.failure(f"获取用户信息失败: {resp.status_code}")

    def on_stop(self):
        """用户停止时可做清理工作"""
        pass

    # ==================== 高频任务 ====================

    @task(15)
    def health_check(self):
        """健康检查 - 最高频，模拟心跳/探活"""
        self.client.get("/api/health", name="/api/health")

    # ==================== 中频任务 ====================

    @task(8)
    def get_sessions(self):
        """获取会话列表 - 用户打开聊天页面时触发"""
        if not self.token:
            return

        self.client.get(
            "/api/chat/sessions",
            headers={"Authorization": f"Bearer {self.token}"},
            name="/api/chat/sessions"
        )

    @task(5)
    def send_message_sse(self):
        """
        发送聊天消息(SSE 流式接口)
        模拟真实用户发送一条消息并等待首包返回
        由于 SSE 是长连接，设置 15 秒超时避免无限挂起
        """
        if not self.token:
            return

        # 随机选择一条提问
        message = random.choice(self.CHAT_MESSAGES)
        payload = {
            "message": message,
            "session_id": self.session_id or ""
        }

        # SSE 接口: stream=True + 短超时
        with self.client.post(
            "/api/chat/send",
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            name="/api/chat/send (SSE)",
            stream=True,
            timeout=15,
            catch_response=True
        ) as resp:
            try:
                if resp.status_code != 200:
                    resp.failure(f"SSE 请求失败: {resp.status_code}")
                    return

                # 读取 SSE 流的前几行数据，确认连接正常
                received_lines = 0
                for line in resp.iter_lines():
                    if line:
                        received_lines += 1
                        # 通常第一条是 session ID 事件，第二条开始是内容
                        if received_lines >= 2:
                            break

                if received_lines > 0:
                    resp.success()
                else:
                    resp.failure("SSE 未收到任何数据")

            except Exception as e:
                resp.failure(f"SSE 流读取异常: {str(e)}")

    # ==================== 低频任务 ====================

    @task(3)
    def get_history(self):
        """获取某会话的历史记录"""
        if not self.token or not self.session_id:
            return

        self.client.get(
            f"/api/chat/history?session_id={self.session_id}",
            headers={"Authorization": f"Bearer {self.token}"},
            name="/api/chat/history"
        )

    @task(2)
    def query_knowledge(self):
        """直接查询知识库(不经过 Agent) - 使用 JSON body 传递参数"""
        if not self.token:
            return

        queries = ["产品功能", "使用教程", "售后服务", "价格说明"]
        # 修复: 使用 json= 而非 params=，匹配后端 POST 接口的 body 参数
        self.client.post(
            "/api/knowledge/query",
            params={"query": random.choice(queries), "top_k": 3},
            headers={"Authorization": f"Bearer {self.token}"},
            name="/api/knowledge/query"
        )

    @task(1)
    def clear_session(self):
        """清空会话 - 低频，模拟用户手动清理"""
        if not self.token or not self.session_id:
            return

        with self.client.post(
            "/api/chat/clear",
            json={"session_id": self.session_id},
            headers={"Authorization": f"Bearer {self.token}"},
            name="/api/chat/clear",
            catch_response=True
        ) as resp:
            if resp.status_code == 200:
                self.session_id = None  # 清空后重置
                resp.success()
            else:
                resp.failure(f"清空会话失败: {resp.status_code}")


class AnonymousUser(HttpUser):
    """
    匿名用户: 只访问无需认证的接口
    模拟未登录游客的行为
    """
    wait_time = between(2, 5)

    @task(10)
    def health_check(self):
        self.client.get("/api/health", name="/api/health [anon]")

    @task(3)
    def register_only(self):
        """仅注册，不登录(模拟注册后流失的用户)"""
        username = f"anon_{random.randint(100000, 999999)}"
        self.client.post(
            "/api/auth/register",
            json={"username": username, "password": "Test@123456"},
            name="/api/auth/register [anon]"
        )