from typing import Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AnnotationAuditLog, utc_now


class AnnotationAuditLogRepository:
    @staticmethod
    async def log(
        db: AsyncSession,
        dataset_id: str,
        user_id: Optional[str],
        event_type: str,
        event_metadata: dict[str, Any],
    ) -> None:
        entry = AnnotationAuditLog(
            dataset_id=dataset_id,
            user_id=user_id,
            event_type=event_type,
            event_metadata=event_metadata,
            created_at=utc_now(),
        )
        db.add(entry)

    @staticmethod
    async def list_entries(
        db: AsyncSession,
        dataset_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AnnotationAuditLog]:
        q = select(AnnotationAuditLog).order_by(AnnotationAuditLog.created_at.desc())
        if dataset_id:
            q = q.where(AnnotationAuditLog.dataset_id == dataset_id)
        if event_type:
            q = q.where(AnnotationAuditLog.event_type == event_type)
        q = q.limit(limit).offset(offset)
        result = await db.execute(q)
        return list(result.scalars().all())
