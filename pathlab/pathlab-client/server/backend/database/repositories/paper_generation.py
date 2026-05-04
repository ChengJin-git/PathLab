"""
PaperGenerationRunRepository - Data Access Layer.

Mirrors the simple repository pattern of `TrainingTaskRepository` but only
exposes the operations the paper-generation pipeline actually needs:

- create / get_by_id / update / delete  (via BaseRepository)
- list_for_user                          (paginated)
- mark_started / mark_completed / mark_failed / mark_cancelled

Heavy data lives on disk under `uploads/paper_generation/{paper_id}/`; this
table only holds a small status row.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PaperGenerationRun, utc_now
from .base import BaseRepository

logger = logging.getLogger(__name__)


class PaperGenerationRunRepository(BaseRepository[PaperGenerationRun]):
    model = PaperGenerationRun
    pk_field = "paper_id"

    @classmethod
    async def list_for_user(
        cls,
        db: AsyncSession,
        user_id: Optional[str],
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PaperGenerationRun], int]:
        """List paper runs visible to `user_id`.

        Passing `user_id=None` lists every run (admin view).
        """
        base_query = select(PaperGenerationRun)
        count_query = select(func.count()).select_from(PaperGenerationRun)

        if user_id is not None:
            base_query = base_query.where(PaperGenerationRun.user_id == user_id)
            count_query = count_query.where(PaperGenerationRun.user_id == user_id)

        base_query = (
            base_query.order_by(PaperGenerationRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        rows_result = await db.execute(base_query)
        items = list(rows_result.scalars().all())

        count_result = await db.execute(count_query)
        total = int(count_result.scalar_one())
        return items, total

    @classmethod
    async def mark_started(
        cls, db: AsyncSession, paper_id: str
    ) -> Optional[PaperGenerationRun]:
        return await cls.update(
            db,
            paper_id,
            status="running",
            started_at=utc_now(),
            error_message=None,
        )

    @classmethod
    async def mark_completed(
        cls, db: AsyncSession, paper_id: str
    ) -> Optional[PaperGenerationRun]:
        return await cls.update(
            db,
            paper_id,
            status="completed",
            current_stage="completed",
            finished_at=utc_now(),
            error_message=None,
        )

    @classmethod
    async def mark_failed(
        cls, db: AsyncSession, paper_id: str, error_message: str
    ) -> Optional[PaperGenerationRun]:
        return await cls.update(
            db,
            paper_id,
            status="failed",
            finished_at=utc_now(),
            error_message=error_message[:4000],  # avoid stuffing 100KB tracebacks
        )

    @classmethod
    async def mark_cancelled(
        cls, db: AsyncSession, paper_id: str
    ) -> Optional[PaperGenerationRun]:
        return await cls.update(
            db,
            paper_id,
            status="cancelled",
            finished_at=utc_now(),
        )

    @classmethod
    async def update_stage(
        cls,
        db: AsyncSession,
        paper_id: str,
        stage: str,
        *,
        status: Optional[str] = None,
    ) -> Optional[PaperGenerationRun]:
        kwargs: dict[str, Any] = {"current_stage": stage}
        if status is not None:
            kwargs["status"] = status
        return await cls.update(db, paper_id, **kwargs)
