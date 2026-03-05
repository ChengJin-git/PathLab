"""
AnnotationDraftRepository - Data Access Layer for Annotation Drafts
"""
import logging
from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import AnnotationDraft


class AnnotationDraftRepository:
    """Repository for AnnotationDraft CRUD operations"""

    @staticmethod
    async def upsert_draft(
        db: AsyncSession,
        draft_id: str,
        user_id: str,
        annotations: dict,
        source_dataset_id: Optional[str] = None,
    ) -> AnnotationDraft:
        """
        Create or update an annotation draft.
        If a draft with the given draft_id exists, update it; otherwise create new.
        """
        result = await db.execute(
            select(AnnotationDraft)
            .where(AnnotationDraft.draft_id == draft_id)
            .where(AnnotationDraft.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.annotations = annotations
            if source_dataset_id is not None:
                existing.source_dataset_id = source_dataset_id
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            draft = AnnotationDraft(
                draft_id=draft_id,
                user_id=user_id,
                source_dataset_id=source_dataset_id,
                annotations=annotations,
            )
            db.add(draft)
            await db.flush()
            await db.refresh(draft)
            return draft

    @staticmethod
    async def get_draft(
        db: AsyncSession,
        draft_id: str,
        user_id: str,
    ) -> Optional[AnnotationDraft]:
        """Get a specific draft by draft_id, scoped to user."""
        result = await db.execute(
            select(AnnotationDraft)
            .where(AnnotationDraft.draft_id == draft_id)
            .where(AnnotationDraft.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_drafts_by_user(
        db: AsyncSession,
        user_id: str,
    ) -> List[AnnotationDraft]:
        """Get all drafts for a user, ordered by updated_at desc."""
        result = await db.execute(
            select(AnnotationDraft)
            .where(AnnotationDraft.user_id == user_id)
            .order_by(AnnotationDraft.updated_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def delete_draft(
        db: AsyncSession,
        draft_id: str,
        user_id: str,
    ) -> bool:
        """Delete a draft. Returns True if a row was deleted."""
        result = await db.execute(
            delete(AnnotationDraft)
            .where(AnnotationDraft.draft_id == draft_id)
            .where(AnnotationDraft.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_draft_by_draft_id(
        db: AsyncSession,
        draft_id: str,
    ) -> Optional[AnnotationDraft]:
        """Get a draft by draft_id without user_id filter (for internal pipeline use)."""
        result = await db.execute(
            select(AnnotationDraft)
            .where(AnnotationDraft.draft_id == draft_id)
        )
        return result.scalar_one_or_none()
