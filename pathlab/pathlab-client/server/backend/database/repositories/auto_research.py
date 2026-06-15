"""
AutoResearchRepository — Data Access Layer for auto research sessions, experiments, and events.

Follows the same patterns as research_job.py for event batching and cursor-based replay.
"""
import logging
from typing import Any, Optional

from sqlalchemy import delete, select, update, desc
from sqlalchemy.exc import IntegrityError
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
        user_id: str | None,
        limit: int = 50,
    ) -> list[AutoResearchSession]:
        statement = select(AutoResearchSession)
        if user_id:
            statement = statement.where(AutoResearchSession.user_id == user_id)
        result = await db.execute(
            statement.order_by(desc(AutoResearchSession.created_at)).limit(limit)
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

    @staticmethod
    async def upsert_session(
        db: AsyncSession,
        data: dict[str, Any],
    ) -> AutoResearchSession:
        session_id = str(data.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")

        existing = await AutoResearchRepository.get_session(db, session_id)
        if existing is None:
            session = AutoResearchSession(**data)
            db.add(session)
            await db.flush()
            await db.refresh(session)
            return session

        for key, value in data.items():
            if key in {"id", "created_at"}:
                continue
            if hasattr(existing, key):
                setattr(existing, key, value)
        existing.updated_at = utc_now()
        await db.flush()
        await db.refresh(existing)
        return existing

    @staticmethod
    async def delete_session(db: AsyncSession, session_id: str) -> bool:
        result = await db.execute(
            delete(AutoResearchSession).where(
                AutoResearchSession.session_id == session_id
            )
        )
        await db.flush()
        return result.rowcount > 0

    # ── Experiments ───────────────────────────────────────────────

    @staticmethod
    async def create_experiment(db: AsyncSession, data: dict[str, Any]) -> AutoResearchExperiment:
        exp = AutoResearchExperiment(**data)
        db.add(exp)
        await db.flush()
        await db.refresh(exp)
        return exp

    @staticmethod
    async def upsert_experiment_by_run_id(
        db: AsyncSession,
        data: dict[str, Any],
    ) -> AutoResearchExperiment:
        session_id = str(data.get("session_id") or "").strip()
        run_id = str(data.get("training_task_id") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        if not run_id:
            raise ValueError("training_task_id/run_id is required")

        result = await db.execute(
            select(AutoResearchExperiment).where(
                AutoResearchExperiment.session_id == session_id,
                AutoResearchExperiment.training_task_id == run_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            exp = AutoResearchExperiment(**data)
            db.add(exp)
            await db.flush()
            await db.refresh(exp)
            return exp

        for key, value in data.items():
            if key in {"id", "created_at"}:
                continue
            if hasattr(existing, key):
                setattr(existing, key, value)
        await db.flush()
        await db.refresh(existing)
        return existing

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
    async def append_event_once(
        db: AsyncSession,
        session_id: str,
        event: dict[str, Any],
        sequence: int,
    ) -> bool:
        result = await db.execute(
            select(AutoResearchEvent.id)
            .where(
                AutoResearchEvent.session_id == session_id,
                AutoResearchEvent.sequence == sequence,
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return False

        event_row = AutoResearchEvent(
            session_id=session_id,
            event_type=str(event.get("event_type") or "event")[:50],
            event_data=event.get("event_data") or {},
            sequence=sequence,
        )
        if not hasattr(db, "begin_nested"):
            db.add(event_row)
            await db.flush()
            return True

        try:
            async with db.begin_nested():
                db.add(event_row)
                await db.flush()
        except IntegrityError:
            return False
        return True

    @staticmethod
    async def get_session_events(
        db: AsyncSession,
        session_id: str,
        limit: int = 5000,
    ) -> list[AutoResearchEvent]:
        result = await db.execute(
            select(AutoResearchEvent)
            .where(AutoResearchEvent.session_id == session_id)
            .order_by(AutoResearchEvent.sequence)
            .limit(limit)
        )
        return list(result.scalars().all())

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
