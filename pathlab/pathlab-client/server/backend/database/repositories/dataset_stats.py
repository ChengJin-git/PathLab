from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
            CASE WHEN dg.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        COUNT(DISTINCT CASE WHEN LOWER(w.split) IN ('val', 'validation') THEN
            CASE WHEN dg.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        COUNT(DISTINCT CASE WHEN LOWER(w.split) = 'test' THEN
            CASE WHEN dg.aggregation_level = 'case'
                THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END
        END),
        NOW()
    FROM wsi_slides w
    JOIN datasets d ON w.dataset_id = d.dataset_id
    JOIN data_groups dg ON d.group_id = dg.group_id
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

_DELETE_IF_EMPTY_SQL = text("""
    DELETE FROM dataset_stats
    WHERE dataset_id = :dataset_id
    AND NOT EXISTS (
        SELECT 1 FROM wsi_slides WHERE dataset_id = :dataset_id
    )
""")


class DatasetStatsRepository:
    @staticmethod
    async def recompute(db: AsyncSession, dataset_id: str) -> None:
        await db.execute(_RECOMPUTE_SQL, {"dataset_id": dataset_id})
        await db.execute(_DELETE_IF_EMPTY_SQL, {"dataset_id": dataset_id})
