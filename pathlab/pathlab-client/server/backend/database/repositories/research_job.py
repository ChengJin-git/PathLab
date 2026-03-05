"""
ResearchJobRepository - Data Access Layer for deep research jobs and events.
"""
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import ResearchJob, ResearchJobEvent, utc_now


class ResearchJobRepository:
    """Repository for Research Job and Event operations"""

    @staticmethod
    async def create_job(db: AsyncSession, data: Dict[str, Any]) -> ResearchJob:
        """Insert a new research_jobs row."""
        job = ResearchJob(**data)
        db.add(job)
        await db.flush()
        await db.refresh(job)
        return job

    @staticmethod
    async def get_job(db: AsyncSession, job_id: str) -> Optional[ResearchJob]:
        """Get a job by job_id."""
        result = await db.execute(
            select(ResearchJob).where(ResearchJob.job_id == job_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_job_by_conversation(
        db: AsyncSession, conversation_id: str
    ) -> Optional[ResearchJob]:
        """Get the most recent job for a conversation."""
        result = await db.execute(
            select(ResearchJob)
            .where(ResearchJob.conversation_id == conversation_id)
            .order_by(desc(ResearchJob.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        job_id: str,
        status: str,
        error: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> None:
        """Update job status, optionally error and current_stage."""
        values: Dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if error is not None:
            values["error"] = error
        if stage is not None:
            values["current_stage"] = stage
        await db.execute(
            update(ResearchJob).where(ResearchJob.job_id == job_id).values(**values)
        )
        await db.flush()

    @staticmethod
    async def update_stage(db: AsyncSession, job_id: str, stage: str) -> None:
        """Update only the current_stage field."""
        await db.execute(
            update(ResearchJob)
            .where(ResearchJob.job_id == job_id)
            .values(current_stage=stage, updated_at=utc_now())
        )
        await db.flush()

    @staticmethod
    async def set_cancel_requested(db: AsyncSession, job_id: str) -> None:
        """Mark cancel_requested = True."""
        await db.execute(
            update(ResearchJob)
            .where(ResearchJob.job_id == job_id)
            .values(cancel_requested=True, updated_at=utc_now())
        )
        await db.flush()

    @staticmethod
    async def increment_next_seq(db: AsyncSession, job_id: str, count: int) -> int:
        """Atomically increment next_seq by count, return the old value (start seq)."""
        result = await db.execute(
            select(ResearchJob.next_seq).where(ResearchJob.job_id == job_id)
        )
        old_seq = result.scalar_one()
        await db.execute(
            update(ResearchJob)
            .where(ResearchJob.job_id == job_id)
            .values(next_seq=old_seq + count, updated_at=utc_now())
        )
        await db.flush()
        return old_seq

    @staticmethod
    async def append_events_batch(
        db: AsyncSession, job_id: str, events_list: List[Dict[str, Any]]
    ) -> None:
        """Batch insert events. Each dict must have: seq, event_type, data."""
        if not events_list:
            return
        objs = [
            ResearchJobEvent(
                job_id=job_id,
                seq=e["seq"],
                event_type=e["event_type"],
                data=e["data"],
            )
            for e in events_list
        ]
        db.add_all(objs)
        await db.flush()

    @staticmethod
    async def get_events_after(
        db: AsyncSession, job_id: str, cursor: int, limit: int = 500
    ) -> List[ResearchJobEvent]:
        """Get events with seq > cursor, ordered by seq, up to limit."""
        result = await db.execute(
            select(ResearchJobEvent)
            .where(
                ResearchJobEvent.job_id == job_id,
                ResearchJobEvent.seq > cursor,
            )
            .order_by(ResearchJobEvent.seq)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_active_jobs_for_user(
        db: AsyncSession, user_email: str
    ) -> List[ResearchJob]:
        """Get jobs with status IN (pending, running) for a user."""
        result = await db.execute(
            select(ResearchJob)
            .where(
                ResearchJob.user_email == user_email,
                ResearchJob.status.in_(["pending", "running"]),
            )
            .order_by(desc(ResearchJob.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def mark_interrupted_jobs(db: AsyncSession) -> int:
        """Mark all pending/running jobs as interrupted. Returns count."""
        result = await db.execute(
            update(ResearchJob)
            .where(ResearchJob.status.in_(["pending", "running"]))
            .values(status="interrupted", updated_at=utc_now())
        )
        await db.flush()
        return result.rowcount
