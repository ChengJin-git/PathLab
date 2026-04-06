"""
KnowhowRepository — Data Access Layer for the Know-How Experience Store.

Provides CRUD and query operations for structured domain knowledge entries
used by the experiment planner to design better experiments.
"""
import logging
from typing import Any, Optional

from sqlalchemy import select, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import KnowhowEntry

logger = logging.getLogger(__name__)


class KnowhowRepository:
    """Repository for Know-How entry operations."""

    # ── Insert ──────────────────────────────────────────────────────

    @staticmethod
    async def insert_entry(db: AsyncSession, data: dict[str, Any]) -> KnowhowEntry:
        """Insert a new knowhow entry."""
        entry = KnowhowEntry(**data)
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        return entry

    @staticmethod
    async def upsert_curated(db: AsyncSession, data: dict[str, Any]) -> Optional[KnowhowEntry]:
        """
        Insert or skip a curated entry.
        Dedup key: source_type='curated' + feature_extractor + aggregator + task_type.
        """
        result = await db.execute(
            select(KnowhowEntry).where(
                KnowhowEntry.source_type == "curated",
                KnowhowEntry.feature_extractor == data.get("feature_extractor"),
                KnowhowEntry.aggregator == data.get("aggregator"),
                KnowhowEntry.task_type == data.get("task_type"),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        entry = KnowhowEntry(**data)
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        return entry

    # ── Query ───────────────────────────────────────────────────────

    @staticmethod
    async def query_by_task_organ(
        db: AsyncSession,
        task_type: str,
        organ: Optional[str] = None,
        limit: int = 5,
    ) -> list[KnowhowEntry]:
        """Query entries matching task_type and optionally organ, sorted by metric."""
        conditions = [KnowhowEntry.task_type == task_type]
        if organ:
            conditions.append(KnowhowEntry.organ == organ)

        result = await db.execute(
            select(KnowhowEntry)
            .where(and_(*conditions))
            .order_by(desc(KnowhowEntry.metric_value))
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def query_by_keywords(
        db: AsyncSession,
        keywords: list[str],
        limit: int = 10,
    ) -> list[KnowhowEntry]:
        """
        Query entries whose keywords array overlaps with the given keywords.
        Uses PostgreSQL ARRAY overlap operator (&&).
        """
        if not keywords:
            return []

        result = await db.execute(
            select(KnowhowEntry)
            .where(KnowhowEntry.keywords.overlap(keywords))
            .order_by(
                desc(KnowhowEntry.confidence * func.coalesce(KnowhowEntry.metric_value, 0))
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_top_entries(
        db: AsyncSession,
        task_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[KnowhowEntry]:
        """Get top entries ranked by confidence * metric_value."""
        query = select(KnowhowEntry)
        if task_type:
            query = query.where(KnowhowEntry.task_type == task_type)

        result = await db.execute(
            query.order_by(
                desc(KnowhowEntry.confidence * func.coalesce(KnowhowEntry.metric_value, 0))
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_source(db: AsyncSession) -> dict[str, int]:
        """Count entries grouped by source_type."""
        result = await db.execute(
            select(KnowhowEntry.source_type, func.count(KnowhowEntry.id))
            .group_by(KnowhowEntry.source_type)
        )
        return {row[0]: row[1] for row in result.all()}
