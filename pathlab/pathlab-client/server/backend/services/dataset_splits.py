# pyright: reportImplicitRelativeImport=false, reportAny=false

from dataclasses import dataclass

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Dataset, DataGroup, WSISlide, DatasetStats
from backend.database.repositories.dataset_stats import DatasetStatsRepository


@dataclass(frozen=True)
class DatasetSplitSummary:
    has_predefined_splits: bool
    predefined_split_counts: dict[str, int]
    predefined_split_unit: str


class DatasetSplitService:
    @staticmethod
    async def summarize_many(
        db: AsyncSession, dataset_ids: list[str]
    ) -> dict[str, DatasetSplitSummary]:
        if not dataset_ids:
            return {}

        cached_query = (
            select(
                Dataset.dataset_id,
                DataGroup.aggregation_level,
                DatasetStats.split_train_count,
                DatasetStats.split_val_count,
                DatasetStats.split_test_count,
            )
            .select_from(Dataset)
            .join(DataGroup, Dataset.group_id == DataGroup.group_id)
            .outerjoin(DatasetStats, Dataset.dataset_id == DatasetStats.dataset_id)
            .where(Dataset.dataset_id.in_(dataset_ids))
        )
        cached_result = await db.execute(cached_query)
        cached_rows = {row.dataset_id: row for row in cached_result.all()}

        missing_or_empty_ids: list[str] = []
        summaries: dict[str, DatasetSplitSummary] = {}

        for ds_id in dataset_ids:
            row = cached_rows.get(ds_id)
            if row is None:
                missing_or_empty_ids.append(ds_id)
                continue
            total = (row.split_train_count or 0) + (row.split_val_count or 0) + (row.split_test_count or 0)
            if total > 0:
                unit = "cases" if row.aggregation_level == "case" else "files"
                summaries[ds_id] = DatasetSplitSummary(
                    has_predefined_splits=True,
                    predefined_split_counts={
                        "train": row.split_train_count or 0,
                        "val": row.split_val_count or 0,
                        "test": row.split_test_count or 0,
                    },
                    predefined_split_unit=unit,
                )
            else:
                missing_or_empty_ids.append(ds_id)

        if missing_or_empty_ids:
            live_counts = await DatasetSplitService._get_live_split_counts_batch(
                db, missing_or_empty_ids
            )
            for ds_id in missing_or_empty_ids:
                counts = live_counts.get(ds_id, {"train": 0, "val": 0, "test": 0})
                total = counts["train"] + counts["val"] + counts["test"]
                if total > 0:
                    await DatasetStatsRepository.recompute(db, ds_id)
                row = cached_rows.get(ds_id)
                unit = (
                    "cases"
                    if row is not None and row.aggregation_level == "case"
                    else "files"
                )
                summaries[ds_id] = DatasetSplitSummary(
                    has_predefined_splits=total > 0,
                    predefined_split_counts=counts,
                    predefined_split_unit=unit,
                )

        return summaries

    @staticmethod
    async def _get_live_split_counts_batch(
        db: AsyncSession, dataset_ids: list[str]
    ) -> dict[str, dict[str, int]]:
        if not dataset_ids:
            return {}

        split_unit = case(
            (
                DataGroup.aggregation_level == "case",
                func.coalesce(WSISlide.case_id, WSISlide.wsi_id),
            ),
            else_=WSISlide.wsi_id,
        )

        query = (
            select(
                WSISlide.dataset_id,
                func.count(
                    func.distinct(
                        case((func.lower(WSISlide.split) == "train", split_unit))
                    )
                ).label("split_train_count"),
                func.count(
                    func.distinct(
                        case(
                            (
                                func.lower(WSISlide.split).in_(["val", "validation"]),
                                split_unit,
                            )
                        )
                    )
                ).label("split_val_count"),
                func.count(
                    func.distinct(
                        case((func.lower(WSISlide.split) == "test", split_unit))
                    )
                ).label("split_test_count"),
            )
            .join(Dataset, WSISlide.dataset_id == Dataset.dataset_id)
            .join(DataGroup, Dataset.group_id == DataGroup.group_id)
            .where(WSISlide.dataset_id.in_(dataset_ids))
            .group_by(WSISlide.dataset_id)
        )

        result = await db.execute(query)
        return {
            row.dataset_id: {
                "train": row.split_train_count or 0,
                "val": row.split_val_count or 0,
                "test": row.split_test_count or 0,
            }
            for row in result.all()
        }
