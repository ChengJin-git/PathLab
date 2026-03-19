"""
DatasetPermissionRepository - Data Access Layer
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import Dataset, DatasetPermission


class DatasetPermissionRepository:
    """Repository for Dataset Permission operations (temporary elevated access)"""

    @staticmethod
    async def create(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        granted_by: str,
        permission_level: str = "pathologist",
        expires_at: datetime = None,
    ) -> DatasetPermission:
        """
        Grant temporary elevated permission to a user for a specific dataset.

        Args:
            db: Database session
            dataset_id: Dataset UUID
            user_id: User UUID to grant permission to
            granted_by: Admin user UUID who granted the permission
            permission_level: Permission level (default: "pathologist")
            expires_at: Optional expiration time
        """
        permission = DatasetPermission(
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=granted_by,
            permission_level=permission_level,
            expires_at=expires_at,
        )
        db.add(permission)
        await db.flush()
        await db.refresh(permission)
        return permission

    @staticmethod
    async def get_by_id(
        db: AsyncSession, permission_id: int
    ) -> Optional[DatasetPermission]:
        """Get permission by ID"""
        result = await db.execute(
            select(DatasetPermission).where(DatasetPermission.id == permission_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_dataset_and_user(
        db: AsyncSession, dataset_id: str, user_id: str
    ) -> Optional[DatasetPermission]:
        """Get permission for a specific user on a specific dataset"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_dataset(
        db: AsyncSession, dataset_id: str
    ) -> List[DatasetPermission]:
        """Get all permissions for a dataset"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_user(db: AsyncSession, user_id: str) -> List[DatasetPermission]:
        """Get all permissions granted to a user"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.user_id == user_id)
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def get_valid_by_user(
        db: AsyncSession, user_id: str
    ) -> List[DatasetPermission]:
        """Get all valid (non-expired) permissions for a user"""
        from datetime import datetime, timezone

        # Use naive UTC datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.user_id == user_id)
            .where(
                (DatasetPermission.expires_at.is_(None))
                | (DatasetPermission.expires_at > now)
            )
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def has_valid_permission(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
            .where(
                (DatasetPermission.expires_at.is_(None))
                | (DatasetPermission.expires_at > now)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def delete(db: AsyncSession, permission_id: int) -> bool:
        """Delete a permission by ID"""
        result = await db.execute(
            delete(DatasetPermission).where(DatasetPermission.id == permission_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete_by_dataset_and_user(
        db: AsyncSession, dataset_id: str, user_id: str
    ) -> bool:
        """Delete permission for a specific user on a specific dataset"""
        result = await db.execute(
            delete(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_all_expired(db: AsyncSession) -> List[DatasetPermission]:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.expires_at.isnot(None))
            .where(DatasetPermission.expires_at <= now)
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_expired(db: AsyncSession) -> int:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await db.execute(
            delete(DatasetPermission)
            .where(DatasetPermission.expires_at.isnot(None))
            .where(DatasetPermission.expires_at <= now)
        )
        await db.flush()
        return result.rowcount
