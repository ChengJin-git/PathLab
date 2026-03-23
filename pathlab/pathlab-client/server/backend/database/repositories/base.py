"""Generic async CRUD base repository for SQLAlchemy 2 + asyncpg."""

from __future__ import annotations

from typing import Any, Generic, Optional, Type, TypeVar
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import utc_now

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Provides generic create/get_by_id/update/delete_by_id for one model.

    Subclasses MUST set both class variables::

        class DatasetRepository(BaseRepository[Dataset]):
            model = Dataset
            pk_field = "dataset_id"   # name of the UUID lookup field

        class WSIRepository(BaseRepository[WSISlide]):
            model = WSISlide
            pk_field = "wsi_id"
    """

    model: Type[T]
    pk_field: str = "id"

    @classmethod
    async def create(cls, db: AsyncSession, **kwargs: Any) -> T:
        obj = cls.model(**kwargs)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    @classmethod
    async def get_by_id(cls, db: AsyncSession, pk_value: Any) -> Optional[T]:
        pk_col = getattr(cls.model, cls.pk_field)
        result = await db.execute(select(cls.model).where(pk_col == pk_value))
        return result.scalar_one_or_none()

    @classmethod
    async def update(
        cls, db: AsyncSession, pk_value: Any, **update_data: Any
    ) -> Optional[T]:
        pk_col = getattr(cls.model, cls.pk_field)
        update_data["updated_at"] = utc_now()
        await db.execute(
            update(cls.model).where(pk_col == pk_value).values(**update_data)
        )
        await db.flush()
        return await cls.get_by_id(db, pk_value)

    @classmethod
    async def delete_by_id(cls, db: AsyncSession, pk_value: Any) -> bool:
        pk_col = getattr(cls.model, cls.pk_field)
        result = await db.execute(delete(cls.model).where(pk_col == pk_value))
        await db.flush()
        return result.rowcount > 0
