from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DatasetGrant, PermissionAuditLog, utc_now


class DatasetGrantRepository:
    @staticmethod
    async def create(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        granted_by: str,
        can_collaborate: bool = False,
        can_use_gpu: bool = False,
        expires_at: Optional[datetime] = None,
    ) -> DatasetGrant:
        grant = DatasetGrant(
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=granted_by,
            can_collaborate=can_collaborate,
            can_use_gpu=can_use_gpu,
            expires_at=expires_at,
        )
        db.add(grant)
        await db.flush()
        await db.refresh(grant)
        return grant

    @staticmethod
    async def get_by_dataset_and_user(
        db: AsyncSession, dataset_id: str, user_id: str
    ) -> Optional[DatasetGrant]:
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_dataset(db: AsyncSession, dataset_id: str) -> List[DatasetGrant]:
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .order_by(DatasetGrant.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_user(db: AsyncSession, user_id: str) -> List[DatasetGrant]:
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.user_id == user_id)
            .order_by(DatasetGrant.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_valid_by_user(db: AsyncSession, user_id: str) -> List[DatasetGrant]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.user_id == user_id)
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
            .order_by(DatasetGrant.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def has_valid_permission(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def has_valid_read_access(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
            .where(
                (DatasetGrant.can_collaborate.is_(True))
                | (DatasetGrant.can_use_gpu.is_(True))
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def has_valid_collaborate(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
            .where(DatasetGrant.can_collaborate.is_(True))
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def has_valid_gpu(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
            .where(DatasetGrant.can_use_gpu.is_(True))
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_collaborate_dataset_ids_for_user(
        db: AsyncSession, user_id: str
    ) -> List[str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(distinct(DatasetGrant.dataset_id))
            .where(DatasetGrant.user_id == user_id)
            .where(DatasetGrant.can_collaborate.is_(True))
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_read_dataset_ids_for_user(
        db: AsyncSession, user_id: str
    ) -> List[str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(distinct(DatasetGrant.dataset_id))
            .where(DatasetGrant.user_id == user_id)
            .where(
                (DatasetGrant.can_collaborate.is_(True))
                | (DatasetGrant.can_use_gpu.is_(True))
            )
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_gpu_dataset_ids_for_user(
        db: AsyncSession, user_id: str
    ) -> List[str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(distinct(DatasetGrant.dataset_id))
            .where(DatasetGrant.user_id == user_id)
            .where(DatasetGrant.can_use_gpu.is_(True))
            .where(
                (DatasetGrant.expires_at.is_(None)) | (DatasetGrant.expires_at > now)
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        **fields,
    ) -> Optional[DatasetGrant]:
        grant = await DatasetGrantRepository.get_by_dataset_and_user(
            db, dataset_id, user_id
        )
        if not grant:
            return None
        for key, value in fields.items():
            setattr(grant, key, value)
        await db.flush()
        return grant

    @staticmethod
    async def delete(db: AsyncSession, dataset_id: str, user_id: str) -> bool:
        result = await db.execute(
            delete(DatasetGrant)
            .where(DatasetGrant.dataset_id == dataset_id)
            .where(DatasetGrant.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_all_expired(db: AsyncSession) -> List[DatasetGrant]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetGrant)
            .where(DatasetGrant.expires_at.isnot(None))
            .where(DatasetGrant.expires_at <= now)
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_expired(db: AsyncSession) -> int:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            delete(DatasetGrant)
            .where(DatasetGrant.expires_at.isnot(None))
            .where(DatasetGrant.expires_at <= now)
        )
        await db.flush()
        return result.rowcount


class PermissionAuditLogRepository:
    @staticmethod
    async def log(
        db: AsyncSession,
        dataset_id: str,
        actor_id: str,
        target_user_id: str,
        action: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> PermissionAuditLog:
        entry = PermissionAuditLog(
            dataset_id=dataset_id,
            actor_id=actor_id,
            target_user_id=target_user_id,
            action=action,
            extra_metadata=metadata or {},
        )
        db.add(entry)
        await db.flush()
        return entry
