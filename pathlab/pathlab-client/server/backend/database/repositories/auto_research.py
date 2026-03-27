"""
AutoResearchRepository — Data Access Layer for auto research sessions, experiments, and events.

Follows the same patterns as research_job.py for event batching and cursor-based replay.
"""
import logging
from typing import Any, Optional

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AutoResearchSession, AutoResearchExperiment, AutoResearchEvent, utc_now

logger = logging.getLogger(__name__)


class AutoResearchRepository:
    """Repository for Auto Research Session, Experiment, and Event operations."""

    # ── Sessions ──────────────────────────────────────────────────

    @staticmethod
    async def create_session(db: AsyncSession, data: dict[str, Any]) -> AutoResearchSession:
        session = AutoResearchSession(**data)
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    @staticmethod
    async def get_session(db: AsyncSession, session_id: str) -> Optional[AutoResearchSession]:
        result = await db.execute(
            select(AutoResearchSession).where(AutoResearchSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_sessions(
        db: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> list[AutoResearchSession]:
        result = await db.execute(
            select(AutoResearchSession)
            .where(AutoResearchSession.user_id == user_id)
            .order_by(desc(AutoResearchSession.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_session(
        db: AsyncSession,
        session_id: str,
        **kwargs,
    ) -> None:
        await db.execute(
            update(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .values(**kwargs, updated_at=utc_now())
        )
        await db.flush()

    # ── Experiments ───────────────────────────────────────────────

    @staticmethod
    async def create_experiment(db: AsyncSession, data: dict[str, Any]) -> AutoResearchExperiment:
        exp = AutoResearchExperiment(**data)
        db.add(exp)
        await db.flush()
        await db.refresh(exp)
        return exp

    @staticmethod
    async def get_session_experiments(
        db: AsyncSession,
        session_id: str,
    ) -> list[AutoResearchExperiment]:
        result = await db.execute(
            select(AutoResearchExperiment)
            .where(AutoResearchExperiment.session_id == session_id)
            .order_by(AutoResearchExperiment.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_experiment_status(
        db: AsyncSession,
        session_id: str,
        training_task_id: str,
        status: str,
        metrics: Optional[dict] = None,
        analysis_id: Optional[str] = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if metrics is not None:
            values["metrics"] = metrics
        if analysis_id is not None:
            values["analysis_id"] = analysis_id

        await db.execute(
            update(AutoResearchExperiment)
            .where(
                AutoResearchExperiment.session_id == session_id,
                AutoResearchExperiment.training_task_id == training_task_id,
            )
            .values(**values)
        )
        await db.flush()

    # ── Events (cursor-based replay) ─────────────────────────────

    @staticmethod
    async def append_events_batch(
        db: AsyncSession,
        session_id: str,
        events: list[dict[str, Any]],
        start_seq: int,
    ) -> int:
        """
        Batch-insert events with sequential numbering.
        Returns the next sequence number.
        """
        for i, event in enumerate(events):
            db.add(AutoResearchEvent(
                session_id=session_id,
                event_type=event["event_type"],
                event_data=event["event_data"],
                sequence=start_seq + i,
            ))
        await db.flush()
        return start_seq + len(events)

    @staticmethod
    async def get_events_after(
        db: AsyncSession,
        session_id: str,
        cursor: int = 0,
        limit: int = 100,
    ) -> list[AutoResearchEvent]:
        """
        Get events after a cursor position for SSE replay.
        """
        result = await db.execute(
            select(AutoResearchEvent)
            .where(
                AutoResearchEvent.session_id == session_id,
                AutoResearchEvent.sequence > cursor,
            )
            .order_by(AutoResearchEvent.sequence)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_latest_sequence(
        db: AsyncSession,
        session_id: str,
    ) -> int:
        """Get the latest event sequence number for a session."""
        result = await db.execute(
            select(AutoResearchEvent.sequence)
            .where(AutoResearchEvent.session_id == session_id)
            .order_by(desc(AutoResearchEvent.sequence))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else 0
