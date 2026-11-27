"""Published dataset reference labels. Mutable viewer objects have their own store."""

from typing import Any
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SegmentationAnnotation, utc_now


class SegmentationAnnotationRepository:
    @staticmethod
    async def upsert(
        db: AsyncSession,
        annotation_id: str,
        user_id: str,
        annotations: dict[str, Any],
        source_dataset_id: str | None = None,
        status: str = "finalized",
        source: str = "viewer",
        task_type: str = "patch_segmentation",
        refresh_summary: bool = True,
    ):
        if status != "finalized":
            raise ValueError("Editable annotations must use viewer regions")
        values = dict(
            user_id=user_id,
            source_dataset_id=source_dataset_id,
            annotations=annotations,
            status="finalized",
            source=source,
            task_type=task_type,
            updated_at=utc_now(),
        )
        result = await db.execute(
            insert(SegmentationAnnotation)
            .values(annotation_id=annotation_id, created_at=utc_now(), **values)
            .on_conflict_do_update(
                index_elements=[SegmentationAnnotation.annotation_id], set_=values
            )
            .returning(SegmentationAnnotation.id)
        )
        identity = result.scalar_one()
        if source_dataset_id and refresh_summary:
            from backend.services.dataset_catalog import refresh_spatial_summary

            await refresh_spatial_summary(db, source_dataset_id, task_type)
        return await db.scalar(
            select(SegmentationAnnotation)
            .where(SegmentationAnnotation.id == identity)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    async def get_all_by_dataset(db, dataset_id, task_type=None):
        query = (
            select(SegmentationAnnotation)
            .where(
                SegmentationAnnotation.source_dataset_id == dataset_id,
                SegmentationAnnotation.status == "finalized",
            )
            .order_by(SegmentationAnnotation.updated_at.desc())
        )
        if task_type:
            query = query.where(SegmentationAnnotation.task_type == task_type)
        return (await db.scalars(query)).all()

    @staticmethod
    async def get_finalized_for_wsis_or_dataset(db, dataset_id, wsi_ids):
        identities = [
            f"{task}_{identity}"
            for identity in [*wsi_ids, dataset_id]
            if identity
            for task in ("patch_segmentation", "patch_detection", "label")
        ]
        return (
            await db.scalars(
                select(SegmentationAnnotation)
                .where(
                    SegmentationAnnotation.source_dataset_id == dataset_id,
                    SegmentationAnnotation.status == "finalized",
                    SegmentationAnnotation.annotation_id.in_(identities),
                )
                .order_by(SegmentationAnnotation.updated_at.desc())
            )
        ).all()

    @staticmethod
    async def get_finalized_dataset_cache_key(db, dataset_id):
        count, updated = (
            await db.execute(
                select(
                    func.count(SegmentationAnnotation.id),
                    func.max(SegmentationAnnotation.updated_at),
                ).where(
                    SegmentationAnnotation.source_dataset_id == dataset_id,
                    SegmentationAnnotation.status == "finalized",
                )
            )
        ).one()
        return {
            "count": int(count or 0),
            "latest_updated_at": updated.isoformat() if updated else None,
        }
