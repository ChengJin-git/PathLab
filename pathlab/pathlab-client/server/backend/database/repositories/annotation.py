import logging
from typing import List, Optional, Any
from sqlalchemy import select, delete, update, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import SegmentationAnnotation, utc_now


class VersionConflictError(Exception):
    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__(f"Version conflict: current version is {current_version}")


class AnnotationOwnershipConflictError(Exception):
    def __init__(self, annotation_id: str):
        self.annotation_id = annotation_id
        super().__init__(f"Annotation ownership conflict: {annotation_id}")


class SegmentationAnnotationRepository:
    """Repository for SegmentationAnnotation CRUD operations."""

    @staticmethod
    async def upsert(
        db: AsyncSession,
        annotation_id: str,
        user_id: str,
        annotations: dict[str, Any],
        source_dataset_id: Optional[str] = None,
        status: str = "draft",
        annotation_mode: str = "personal",
        source: str = "viewer",
    ) -> SegmentationAnnotation:
        """
        Create or update a segmentation annotation atomically.

        ``annotation_mode`` is the only supported API name. The underlying DB
        column is still named ``visibility_mode`` until a later schema cleanup.
        The legacy ``inherit`` mode is no longer supported.

        ``annotation_id`` is globally unique in the database, so viewer auto-save
        must use a PostgreSQL upsert here to avoid duplicate-key races when two
        save requests for the same draft arrive concurrently.
        """
        if annotation_mode not in {"personal", "shared"}:
            raise ValueError(
                "Unsupported annotation mode. "
                "The legacy 'inherit' mode has been removed; use 'personal' or 'shared'."
            )

        if status == "draft":
            existing_result = await db.execute(
                select(SegmentationAnnotation.user_id).where(
                    SegmentationAnnotation.annotation_id == annotation_id
                )
            )
            existing_owner = existing_result.scalar_one_or_none()
            if existing_owner is not None and existing_owner != user_id:
                raise AnnotationOwnershipConflictError(annotation_id)

        timestamp = utc_now()
        stmt = (
            insert(SegmentationAnnotation)
            .values(
                annotation_id=annotation_id,
                user_id=user_id,
                source_dataset_id=source_dataset_id,
                annotations=annotations,
                status=status,
                visibility_mode=annotation_mode,
                source=source,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_update(
                index_elements=[SegmentationAnnotation.annotation_id],
                set_={
                    "user_id": user_id,
                    "source_dataset_id": source_dataset_id,
                    "annotations": annotations,
                    "status": status,
                    "visibility_mode": annotation_mode,
                    "source": source,
                    "updated_at": timestamp,
                },
            )
            .returning(SegmentationAnnotation.id)
        )
        result = await db.execute(stmt)
        annotation_pk = result.scalar_one()

        annotation_result = await db.execute(
            select(SegmentationAnnotation).where(
                SegmentationAnnotation.id == annotation_pk
            )
        )
        return annotation_result.scalar_one()

    @staticmethod
    async def get(
        db: AsyncSession,
        annotation_id: str,
        user_id: str,
    ) -> Optional[SegmentationAnnotation]:
        """Get a specific annotation by annotation_id, scoped to user."""
        result = await db.execute(
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.annotation_id == annotation_id)
            .where(SegmentationAnnotation.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user(
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
    ) -> List[SegmentationAnnotation]:
        """Get annotations for a user, optionally filtered by status."""
        query = (
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.user_id == user_id)
            .order_by(SegmentationAnnotation.updated_at.desc())
        )
        if status is not None:
            query = query.where(SegmentationAnnotation.status == status)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def delete(
        db: AsyncSession,
        annotation_id: str,
        user_id: str,
    ) -> bool:
        """Delete an annotation. Returns True if a row was deleted."""
        result = await db.execute(
            delete(SegmentationAnnotation)
            .where(SegmentationAnnotation.annotation_id == annotation_id)
            .where(SegmentationAnnotation.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete_by_dataset_and_user(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> int:
        """
        Delete personal draft annotations for a user within a dataset.

        Historical/finalized annotations must remain stable even after permission
        revocation, so this method is reserved for explicit draft cleanup flows.
        """
        result = await db.execute(
            delete(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.user_id == user_id)
            .where(SegmentationAnnotation.status == "draft")
        )
        await db.flush()
        return int(result.rowcount or 0)

    @staticmethod
    async def get_with_permission(
        db: AsyncSession,
        annotation_id: str,
        user_id: str,
        is_admin: bool = False,
        elevated_dataset_ids: Optional[set[str]] = None,
    ) -> Optional["SegmentationAnnotation"]:
        """
        Get an annotation if the user has permission.

        ``elevated_dataset_ids`` is ignored. Finalized records are resolved
        through route-level dataset access, and personal drafts remain
        owner/admin only.
        """
        _ = elevated_dataset_ids
        result = await db.execute(
            select(SegmentationAnnotation).where(
                SegmentationAnnotation.annotation_id == annotation_id
            )
        )
        annotation = result.scalar_one_or_none()
        if annotation is None:
            return None
        if is_admin:
            return annotation
        if annotation.user_id == user_id:
            return annotation
        return None

    @staticmethod
    async def get_by_dataset(
        db: AsyncSession,
        dataset_id: str,
    ) -> Optional[SegmentationAnnotation]:
        """Get annotation for a specific dataset (first match)."""
        result = await db.execute(
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .order_by(SegmentationAnnotation.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_dataset_level_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        include_drafts: bool = True,
    ) -> Optional[SegmentationAnnotation]:
        """Get the dataset-level COCO annotation record for a dataset."""
        query = (
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.annotation_id == f"annot_{dataset_id}")
            .order_by(SegmentationAnnotation.updated_at.desc())
            .limit(1)
        )
        if not include_drafts:
            query = query.where(SegmentationAnnotation.status != "draft")

        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_draft_by_dataset_for_user(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> Optional[SegmentationAnnotation]:
        """Get the newest draft annotation for a dataset scoped to one user."""
        result = await db.execute(
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.user_id == user_id)
            .where(SegmentationAnnotation.status == "draft")
            .order_by(SegmentationAnnotation.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_draft_meta_by_dataset_for_user(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get lightweight metadata for the newest draft annotation of a dataset."""
        result = await db.execute(
            select(
                SegmentationAnnotation.annotation_id,
                SegmentationAnnotation.updated_at,
            )
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.user_id == user_id)
            .where(SegmentationAnnotation.status == "draft")
            .order_by(SegmentationAnnotation.updated_at.desc())
            .limit(1)
        )
        row = result.first()
        if not row:
            return None
        return {
            "annotation_id": row.annotation_id,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    async def get_all_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        include_drafts: bool = True,
    ) -> List[SegmentationAnnotation]:
        """Get all annotations linked to a dataset, newest first."""
        query = (
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .order_by(SegmentationAnnotation.updated_at.desc())
        )
        if not include_drafts:
            query = query.where(SegmentationAnnotation.status == "finalized")

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_finalized_for_wsis_or_dataset(
        db: AsyncSession,
        dataset_id: str,
        wsi_ids: List[str],
    ) -> List[SegmentationAnnotation]:
        """Get finalized annotations relevant to a page of WSIs.

        Returns per-WSI records like ``annot_{wsi_id}`` plus the optional
        dataset-level record ``annot_{dataset_id}``.
        """
        target_ids = [f"label_{wsi_id}" for wsi_id in wsi_ids if wsi_id]
        target_ids.append(f"label_{dataset_id}")

        query = (
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.status == "finalized")
            .where(SegmentationAnnotation.annotation_id.in_(target_ids))
            .order_by(SegmentationAnnotation.updated_at.desc())
        )

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_finalized_dataset_cache_key(
        db: AsyncSession,
        dataset_id: str,
    ) -> dict[str, Any]:
        """Return a lightweight cache key for finalized annotations of a dataset."""
        result = await db.execute(
            select(
                func.count(SegmentationAnnotation.id),
                func.max(SegmentationAnnotation.updated_at),
            )
            .where(SegmentationAnnotation.source_dataset_id == dataset_id)
            .where(SegmentationAnnotation.status == "finalized")
        )
        count, latest_updated_at = result.one()
        return {
            "count": int(count or 0),
            "latest_updated_at": latest_updated_at.isoformat()
            if latest_updated_at
            else None,
        }

    @staticmethod
    async def get_shared_draft(
        db: AsyncSession,
        dataset_id: str,
    ) -> Optional[SegmentationAnnotation]:
        result = await db.execute(
            select(SegmentationAnnotation).where(
                SegmentationAnnotation.annotation_id == f"shared_{dataset_id}"
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_shared(
        db: AsyncSession,
        dataset_id: str,
        owner_user_id: str,
        last_edited_by: str,
        annotations: dict[str, Any],
        expected_version: int,
        force: bool = False,
    ) -> SegmentationAnnotation:
        """
        Atomically create-or-update the shared_draft for a dataset.

        force=True  (owner / admin): skip version check, always overwrite.
        force=False (collaborator):  UPDATE only when version == expected_version.
                                     Raises VersionConflictError if stale.
        """
        annotation_id = f"shared_{dataset_id}"
        timestamp = utc_now()

        if force:
            stmt = (
                insert(SegmentationAnnotation)
                .values(
                    annotation_id=annotation_id,
                    user_id=owner_user_id,
                    source_dataset_id=dataset_id,
                    annotations=annotations,
                    status="shared_draft",
                    visibility_mode="shared",
                    source="viewer",
                    version=expected_version + 1,
                    last_edited_by=last_edited_by,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                .on_conflict_do_update(
                    index_elements=[SegmentationAnnotation.annotation_id],
                    set_={
                        "annotations": annotations,
                        "visibility_mode": "shared",
                        "version": SegmentationAnnotation.version + 1,
                        "last_edited_by": last_edited_by,
                        "updated_at": timestamp,
                    },
                )
                .returning(SegmentationAnnotation)
            )
            return (await db.execute(stmt)).scalar_one()

        existing = await SegmentationAnnotationRepository.get_shared_draft(
            db, dataset_id
        )
        if existing is None:
            stmt = (
                insert(SegmentationAnnotation)
                .values(
                    annotation_id=annotation_id,
                    user_id=owner_user_id,
                    source_dataset_id=dataset_id,
                    annotations=annotations,
                    status="shared_draft",
                    visibility_mode="shared",
                    source="viewer",
                    version=1,
                    last_edited_by=last_edited_by,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                .on_conflict_do_nothing()
                .returning(SegmentationAnnotation)
            )
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return row
            current = await SegmentationAnnotationRepository.get_shared_draft(
                db, dataset_id
            )
            raise VersionConflictError(
                current_version=current.version if current else 0
            )

        upd = (
            update(SegmentationAnnotation)
            .where(SegmentationAnnotation.annotation_id == annotation_id)
            .where(SegmentationAnnotation.version == expected_version)
            .values(
                annotations=annotations,
                visibility_mode="shared",
                version=expected_version + 1,
                last_edited_by=last_edited_by,
                updated_at=timestamp,
            )
            .returning(SegmentationAnnotation)
        )
        upd_result = await db.execute(upd)
        updated = upd_result.scalar_one_or_none()
        if updated is None:
            current = await SegmentationAnnotationRepository.get_shared_draft(
                db, dataset_id
            )
            raise VersionConflictError(
                current_version=current.version if current else 0
            )
        return updated

    @staticmethod
    async def delete_shared(
        db: AsyncSession,
        dataset_id: str,
    ) -> bool:
        result = await db.execute(
            delete(SegmentationAnnotation).where(
                SegmentationAnnotation.annotation_id == f"shared_{dataset_id}"
            )
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def bulk_delete_regions_by_creator(
        db: AsyncSession,
        dataset_id: str,
        creator_user_id: str,
    ) -> int:
        shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
        if shared is None:
            return 0

        original: dict[str, Any] = (
            shared.annotations if isinstance(shared.annotations, dict) else {}
        )
        filtered: dict[str, Any] = {}
        deleted_count = 0

        for wsi_id, regions in original.items():
            if not isinstance(regions, list):
                filtered[wsi_id] = regions
                continue
            kept = [r for r in regions if r.get("created_by") != creator_user_id]
            deleted_count += len(regions) - len(kept)
            filtered[wsi_id] = kept

        if deleted_count == 0:
            return 0

        timestamp = utc_now()
        await db.execute(
            update(SegmentationAnnotation)
            .where(SegmentationAnnotation.annotation_id == f"shared_{dataset_id}")
            .values(
                annotations=filtered,
                version=shared.version + 1,
                updated_at=timestamp,
            )
        )
        await db.flush()
        return deleted_count
