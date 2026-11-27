from sqlalchemy import select, text, func, case, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DatasetStats, Dataset, WSISlide, utc_now

_RECOMPUTE_SQL = text("""
    INSERT INTO dataset_stats (
        dataset_id, file_count, total_size,
        split_train_count, split_val_count, split_test_count, updated_at
    )
    SELECT
        w.dataset_id,
        COUNT(*),
        COALESCE(SUM(w.file_size), 0),
        COUNT(DISTINCT CASE WHEN LOWER(w.split) = 'train' THEN
            CASE WHEN d.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        COUNT(DISTINCT CASE WHEN LOWER(w.split) IN ('val', 'validation') THEN
            CASE WHEN d.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        COUNT(DISTINCT CASE WHEN LOWER(w.split) = 'test' THEN
            CASE WHEN d.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        NOW()
    FROM wsi_slides w
    JOIN datasets d ON w.dataset_id = d.dataset_id
    WHERE w.dataset_id = :dataset_id
    GROUP BY w.dataset_id
    ON CONFLICT (dataset_id) DO UPDATE SET
        file_count       = EXCLUDED.file_count,
        total_size       = EXCLUDED.total_size,
        split_train_count = EXCLUDED.split_train_count,
        split_val_count  = EXCLUDED.split_val_count,
        split_test_count = EXCLUDED.split_test_count,
        updated_at       = EXCLUDED.updated_at
""")

_RESET_IF_EMPTY_SQL = text("""
    UPDATE dataset_stats SET file_count=0,total_size=0,split_train_count=0,split_val_count=0,split_test_count=0
    WHERE dataset_id = :dataset_id
    AND NOT EXISTS (
        SELECT 1 FROM wsi_slides WHERE dataset_id = :dataset_id
    )
""")


class DatasetStatsRepository:
    @staticmethod
    async def record_upload(db: AsyncSession, dataset_id: str, fields: dict) -> None:
        """One indexed case lookup and counter update per upload, not a full rescan."""
        # NO KEY UPDATE serializes counters without deadlocking upload inserts'
        # foreign-key KEY SHARE locks on the same dataset.
        await db.scalar(
            select(Dataset.id)
            .where(Dataset.dataset_id == dataset_id)
            .with_for_update(key_share=True)
        )
        aggregation = await db.scalar(
            select(Dataset.aggregation_level)
            .where(Dataset.dataset_id == dataset_id)
        )
        split = fields.get("split")
        same_case = select(WSISlide.wsi_id).where(
            WSISlide.dataset_id == dataset_id,
            WSISlide.case_id == fields.get("case_id"),
            WSISlide.wsi_id != fields["wsi_id"],
        )
        if aggregation == "case" and fields.get("case_id") and split:
            if await db.scalar(
                same_case.where(
                    WSISlide.split.is_not(None), WSISlide.split != split
                ).limit(1)
            ):
                raise ValueError(
                    "A case cannot belong to different train/val/test splits"
                )
        stats = await db.get(DatasetStats, dataset_id)
        if stats is None:
            unit = (
                func.coalesce(WSISlide.case_id, WSISlide.wsi_id)
                if aggregation == "case"
                else WSISlide.wsi_id
            )
            row = (
                await db.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(WSISlide.file_size), 0),
                        *(
                            func.count(distinct(case((WSISlide.split == name, unit))))
                            for name in ["train", "val", "test"]
                        ),
                    ).where(WSISlide.dataset_id == dataset_id)
                )
            ).one()
            db.add(
                DatasetStats(
                    dataset_id=dataset_id,
                    file_count=row[0],
                    total_size=row[1],
                    split_train_count=row[2],
                    split_val_count=row[3],
                    split_test_count=row[4],
                    updated_at=utc_now(),
                )
            )
            return
        stats.file_count += 1
        stats.total_size += fields.get("file_size") or 0
        if split in {"train", "val", "test"}:
            already_counted = (
                aggregation == "case"
                and fields.get("case_id")
                and await db.scalar(same_case.where(WSISlide.split == split).limit(1))
            )
            if not already_counted:
                key = f"split_{split}_count"
                setattr(stats, key, getattr(stats, key) + 1)
        stats.updated_at = utc_now()

    @staticmethod
    async def get_by_dataset_id(
        db: AsyncSession, dataset_id: str
    ) -> DatasetStats | None:
        result = await db.execute(
            select(DatasetStats).where(DatasetStats.dataset_id == dataset_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def recompute(db: AsyncSession, dataset_id: str) -> None:
        await db.execute(_RECOMPUTE_SQL, {"dataset_id": dataset_id})
        await db.execute(_RESET_IF_EMPTY_SQL, {"dataset_id": dataset_id})
