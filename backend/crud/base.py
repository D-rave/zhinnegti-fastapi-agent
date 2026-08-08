"""通用 CRUD 基类"""
from typing import Generic, TypeVar, Type, Optional, List, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from models.db import Base

ModelType = TypeVar("ModelType", bound=Base)


class CRUDBase(Generic[ModelType]):
    """通用 CRUD 操作基类"""

    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: Any) -> Optional[ModelType]:
        """根据 ID 获取单条记录"""
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: Any = None
    ) -> List[ModelType]:
        """获取多条记录"""
        query = select(self.model)
        if order_by is not None:
            query = query.order_by(order_by)
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def create(self, db: AsyncSession, *, obj_in: dict) -> ModelType:
        """创建记录"""
        db_obj = self.model(**obj_in)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: ModelType,
        obj_in: dict
    ) -> ModelType:
        """更新记录"""
        for field, value in obj_in.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, *, id: Any) -> Optional[ModelType]:
        """删除记录"""
        obj = await self.get(db, id)
        if obj:
            await db.delete(obj)
            await db.commit()
        return obj

    async def count(self, db: AsyncSession) -> int:
        """统计总数"""
        result = await db.execute(select(func.count()).select_from(self.model))
        return result.scalar()