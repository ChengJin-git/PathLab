# pyright: reportImplicitRelativeImport=false, reportAny=false, reportExplicitAny=false

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.task_taxonomy import is_segmentation_task
from backend.database.models import Dataset, DataGroup, WSISlide, DatasetStats, WSISlideUserSplit


@dataclass(frozen=True)
class DatasetSplitSummary:
    has_predefined_splits: bool
    predefined_split_counts: dict[str, int]
    predefined_split_unit: str


@dataclass(frozen=True)
class DatasetSplitApplyResult:
    updated_count: int
    auto_val_count: int
    not_found_files: list[str]


def _normalize_file_key(file_name: str | None) -> str | None:
    if not file_name:
        return None
    normalized = Path(str(file_name)).name.strip().lower()
    return normalized or None


def _build_split_wsi_lookups(slides: list[Any]) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    exact_lookup: dict[str, Any] = {}
    stem_candidates: dict[str, dict[str, Any]] = {}

    for slide in slides:
        for candidate in (
            getattr(slide, "original_filename", None),
            getattr(slide, "wsi_path", None),
        ):
            key = _normalize_file_key(candidate)
            if not key:
                continue
            exact_lookup[key] = slide
            stem_candidates.setdefault(Path(key).stem, {})[slide.wsi_id] = slide

    stem_lookup = {
        stem: next(iter(candidates.values()))
        for stem, candidates in stem_candidates.items()
        if len(candidates) == 1
    }
    ambiguous_stems = {
        stem for stem, candidates in stem_candidates.items() if len(candidates) > 1
    }
    return exact_lookup, stem_lookup, ambiguous_stems


def _resolve_split_wsi_by_filename(
    filename: str,
    exact_lookup: dict[str, Any],
    stem_lookup: dict[str, Any],
    ambiguous_stems: set[str],
):
    key = _normalize_file_key(filename)
    if not key:
        return None

    if key in exact_lookup:
        return exact_lookup[key]

    stem = Path(key).stem
    if stem in ambiguous_stems:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ambiguous filename '{filename}' in CSV. Include the full filename "
                "with extension to match the target slide."
            ),
        )

    return stem_lookup.get(stem)


class DatasetSplitService:
    @staticmethod
    def parse_csv_assignments(csv_text: str) -> tuple[list[dict[str, str]], str, str | None]:
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            if not reader.fieldnames:
                raise HTTPException(
                    status_code=400, detail="CSV is empty or has no header row"
                )

            filename_key = next(
                (
                    h
                    for h in reader.fieldnames
                    if h.strip().lower()
                    in ["filename", "file_name", "original_filename"]
                ),
                None,
            )
            if not filename_key:
                raise HTTPException(
                    status_code=400, detail="CSV must contain 'filename' column"
                )

            split_key = next(
                (h for h in reader.fieldnames if h.strip().lower() == "split"), None
            )
            rows = list(reader)
            if not rows:
                raise HTTPException(status_code=400, detail="CSV has no data rows")

            valid_splits = {"train", "val", "validation", "test"}
            if split_key:
                for i, row in enumerate(rows, start=2):
                    split_val = row.get(split_key, "").strip().lower()
                    if split_val and split_val not in valid_splits:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Invalid split value '{row.get(split_key)}' at row {i}. "
                                "Allowed values: train, val, test"
                            ),
                        )

            return rows, filename_key, split_key
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(exc)}")

    @staticmethod
    async def apply_csv_splits(
        db: AsyncSession,
        dataset_id: str,
        slides: list[Any],
        csv_text: str,
        task_type: str,
        target_user_id: str | None = None,
    ) -> DatasetSplitApplyResult:
        rows, filename_key, split_key = DatasetSplitService.parse_csv_assignments(csv_text)
        exact_lookup, stem_lookup, ambiguous_stems = _build_split_wsi_lookups(slides)

        updated_count = 0
        override_rows: list[dict[str, str]] = []
        not_found_files: list[str] = []
        for row in rows:
            fname = row.get(filename_key, "").strip()
            if not fname:
                continue

            target_wsi = _resolve_split_wsi_by_filename(
                fname, exact_lookup, stem_lookup, ambiguous_stems
            )
            if not target_wsi:
                not_found_files.append(fname)
                continue

            if split_key:
                split_val = row.get(split_key, "").strip().lower()
                if split_val:
                    normalized_split = "val" if split_val == "validation" else split_val
                    if target_user_id:
                        override_rows.append(
                            {
                                "wsi_id": target_wsi.wsi_id,
                                "user_id": target_user_id,
                                "split": normalized_split,
                            }
                        )
                    else:
                        target_wsi.split = normalized_split

            if not target_user_id:
                DatasetSplitService._apply_metadata_row(target_wsi, row, task_type)
            updated_count += 1

        if override_rows:
            await DatasetSplitService._upsert_user_split_overrides(db, override_rows)
        auto_val_count = 0 if target_user_id else DatasetSplitService._auto_create_val_split(slides)
        if not target_user_id:
            from backend.database.repositories.dataset_stats import DatasetStatsRepository

            await DatasetStatsRepository.recompute(db, dataset_id)
        return DatasetSplitApplyResult(
            updated_count=updated_count,
            auto_val_count=auto_val_count,
            not_found_files=not_found_files,
        )

    @staticmethod
    async def _upsert_user_split_overrides(
        db: AsyncSession,
        rows: list[dict[str, str]],
    ) -> None:
        if not rows:
            return
        statement = pg_insert(WSISlideUserSplit).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["wsi_id", "user_id"],
            set_={
                "split": statement.excluded.split,
                "updated_at": func.now(),
            },
        )
        await db.execute(statement)

    @staticmethod
    async def resolve_effective_splits(
        db: AsyncSession,
        slides: list[Any],
        user_id: str | None,
    ) -> dict[str, str]:
        baseline = {slide.wsi_id: slide.split for slide in slides if getattr(slide, "split", None)}
        if not user_id or not slides:
            return baseline

        wsi_ids = [slide.wsi_id for slide in slides]
        result = await db.execute(
            select(WSISlideUserSplit.wsi_id, WSISlideUserSplit.split).where(
                WSISlideUserSplit.user_id == user_id,
                WSISlideUserSplit.wsi_id.in_(wsi_ids),
            )
        )
        for row in result.all():
            baseline[row.wsi_id] = row.split
        return baseline

    @staticmethod
    def _apply_metadata_row(target_wsi: Any, row: dict[str, str], task_type: str) -> None:
        for key, val in row.items():
            norm_key = key.strip().lower()
            if not val:
                continue

            val = val.strip()
            if norm_key == "label":
                if is_segmentation_task(task_type):
                    continue
                target_wsi.label = val
            elif norm_key == "case_id":
                target_wsi.case_id = val
            elif norm_key == "age":
                if val.isdigit():
                    target_wsi.age = int(val)
            elif norm_key == "gender":
                target_wsi.gender = val
            elif norm_key == "event_time":
                try:
                    target_wsi.event_time = float(val)
                except (ValueError, TypeError):
                    pass
            elif norm_key == "event_status":
                if val in ["0", "1"]:
                    target_wsi.event_status = int(val)

    @staticmethod
    def _auto_create_val_split(slides: list[Any]) -> int:
        train_slides = [slide for slide in slides if slide.split == "train"]
        val_slides = [slide for slide in slides if slide.split == "val"]
        if val_slides or not train_slides:
            return 0

        import random

        auto_val_count = 0
        n_val = max(1, int(len(train_slides) * 0.1))
        random.shuffle(train_slides)
        for i in range(min(n_val, len(train_slides))):
            train_slides[i].split = "val"
            auto_val_count += 1
        return auto_val_count

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
                    from backend.database.repositories.dataset_stats import DatasetStatsRepository

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
