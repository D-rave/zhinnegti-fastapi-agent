"""用户 CRUD"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.user import User
from .base import CRUDBase


class CRUDUser(CRUDBase[User]):
    """用户数据访问"""

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """根据用户名查询"""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def create_user(self, db: AsyncSession, username: str, hashed_password: str) -> User:
        """创建用户"""
        return await self.create(db, obj_in={
            "username": username,
            "hashed_password": hashed_password,
        })


user = CRUDUser(User)