"""
Redis 客户端封装
功能：
1. 连接池管理（单例）
2. 会话列表缓存（减少数据库查询）
3. 用户 Token 黑名单（登出失效）
4. 请求限流计数
5. 热点数据缓存（如健康检查、配置）
"""
import os
import json
import asyncio
from typing import Optional, Any, List

import redis.asyncio as redis
from utils.logger_handler import logger

# Redis 连接配置（优先环境变量，其次默认值）
REDIS_HOST = os.environ.get("REDIS_HOST", "192.168.249.3")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

# 单例连接池
_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """获取 Redis 连接（单例）"""
    global _redis_pool
    if _redis_pool is None:
        try:
            _redis_pool = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
            await _redis_pool.ping()
            logger.info(f"[Redis] ✅ 连接成功 {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
        except Exception as e:
            logger.warning(f"[Redis] ⚠️ 连接失败: {e}，将降级为无缓存模式")
            _redis_pool = None
    return _redis_pool


class RedisCache:
    """
    Redis 缓存操作封装
    所有方法都带降级处理：Redis 不可用时自动跳过，不影响业务
    """

    @staticmethod
    async def _safe_execute(func, fallback=None):
        """安全执行：Redis 失败时返回 fallback，不抛异常"""
        try:
            r = await get_redis()
            if r is None:
                return fallback
            return await func(r)
        except Exception as e:
            logger.warning(f"[Redis] 操作失败: {e}")
            return fallback

    # ========== 会话列表缓存 ==========
    @staticmethod
    async def cache_sessions(user_id: int, sessions: List[dict], expire: int = 300):
        """缓存用户会话列表（5分钟）"""
        key = f"chat:sessions:{user_id}"
        await RedisCache._safe_execute(
            lambda r: r.setex(key, expire, json.dumps(sessions))
        )

    @staticmethod
    async def get_cached_sessions(user_id: int) -> Optional[List[dict]]:
        """获取缓存的会话列表"""
        result = await RedisCache._safe_execute(
            lambda r: r.get(f"chat:sessions:{user_id}")
        )
        if result:
            return json.loads(result)
        return None

    @staticmethod
    async def invalidate_sessions(user_id: int):
        """使某用户的会话列表缓存失效"""
        await RedisCache._safe_execute(
            lambda r: r.delete(f"chat:sessions:{user_id}")
        )

    # ========== Token 黑名单（登出失效）==========
    @staticmethod
    async def blacklist_token(token: str, expire: int = 604800):
        """将 Token 加入黑名单（默认7天，与JWT过期时间一致）"""
        key = f"token:blacklist:{token}"
        await RedisCache._safe_execute(
            lambda r: r.setex(key, expire, "1")
        )

    @staticmethod
    async def is_token_blacklisted(token: str) -> bool:
        """检查 Token 是否在黑名单中"""
        result = await RedisCache._safe_execute(
            lambda r: r.exists(f"token:blacklist:{token}")
        )
        return bool(result)

    # ========== 请求限流 ==========
    @staticmethod
    async def rate_limit_check(key: str, max_requests: int = 60, window: int = 60) -> bool:
        """
        滑动窗口限流
        :param key: 限流标识（如 IP 或 user_id）
        :param max_requests: 窗口内最大请求数
        :param window: 窗口时间（秒）
        :return: True 表示允许通过，False 表示被限流
        """
        async def _check(r):
            pipe = r.pipeline()
            now = asyncio.get_event_loop().time()
            window_key = f"rate_limit:{key}:{int(now // window)}"
            pipe.incr(window_key)
            pipe.expire(window_key, window + 1)
            results = await pipe.execute()
            count = results[0]
            return count <= max_requests

        result = await RedisCache._safe_execute(_check, fallback=True)
        return result

    # ========== 通用缓存 ==========
    @staticmethod
    async def set_cache(key: str, value: Any, expire: int = 300):
        """通用设置缓存"""
        await RedisCache._safe_execute(
            lambda r: r.setex(key, expire, json.dumps(value) if not isinstance(value, str) else value)
        )

    @staticmethod
    async def get_cache(key: str) -> Optional[Any]:
        """通用获取缓存"""
        result = await RedisCache._safe_execute(lambda r: r.get(key))
        if result:
            try:
                return json.loads(result)
            except:
                return result
        return None

    @staticmethod
    async def delete_cache(key: str):
        """删除缓存"""
        await RedisCache._safe_execute(lambda r: r.delete(key))


async def close_redis():
    """关闭 Redis 连接"""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("[Redis] 连接已关闭")