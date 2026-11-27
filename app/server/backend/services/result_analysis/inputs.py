"""Bounded prediction queries; no full ORM hydration or image/mask loading."""

from __future__ import annotations

from sqlalchemy import and_, func, select
from backend.database.models import AIResult, TrainingTaskWSI, WSISlide
from .contracts import AnalysisConfig

MAX_ROWS = 500_000


def prediction_query(task_id: str, config: AnalysisConfig):
    statement = (
        select(
            AIResult.id.label("result_id"),
            AIResult.wsi_id,
            AIResult.pred,
            AIResult.probs,
            AIResult.extra_metadata.label("metadata"),
            WSISlide.case_id,
            WSISlide.dataset_id,
            WSISlide.label,
            WSISlide.original_filename.label("filename"),
            WSISlide.age,
            WSISlide.gender,
            WSISlide.source,
            WSISlide.event_time,
            WSISlide.event_status,
            func.coalesce(TrainingTaskWSI.split, "unassigned").label("split"),
        )
        .join(WSISlide, WSISlide.wsi_id == AIResult.wsi_id)
        .outerjoin(
            TrainingTaskWSI,
            and_(
                TrainingTaskWSI.task_id == AIResult.task_id,
                TrainingTaskWSI.wsi_id == AIResult.wsi_id,
            ),
        )
        .where(AIResult.task_id == task_id)
    )
    if config.split == "oof":
        statement = statement.where(TrainingTaskWSI.split.like("fold_%"))
    else:
        statement = statement.where(
            func.coalesce(TrainingTaskWSI.split, "unassigned") == config.split
        )
    filters = config.filters
    if filters.source:
        statement = statement.where(WSISlide.source == filters.source)
    if filters.gender:
        statement = statement.where(WSISlide.gender == filters.gender)
    if filters.age_min is not None:
        statement = statement.where(WSISlide.age >= filters.age_min)
    if filters.age_max is not None:
        statement = statement.where(WSISlide.age <= filters.age_max)
    return statement.order_by(AIResult.id)


async def load_predictions(db, source, config: AnalysisConfig):
    rows, after = [], 0
    base = prediction_query(source.task_id, config)
    byte_count = 0
    import json

    while True:
        page = (
            (await db.execute(base.where(AIResult.id > after).limit(2000)))
            .mappings()
            .all()
        )
        if not page:
            return rows
        for row in page:
            item = dict(row)
            # Metadata stores task-specific scalars, never transfer attention arrays.
            metadata = item["metadata"] or {}
            item["metadata"] = {
                key: metadata[key]
                for key in (
                    "risk_score",
                    "surv_probs",
                    "bin_edges",
                    "metrics",
                    "has_ground_truth",
                    "class_names",
                    "detection",
                    "threshold_counts",
                    "image_size",
                    "segmentation_preview",
                )
                if key in metadata
            }
            byte_count += len(json.dumps(item, default=str))
            rows.append(item)
        if len(rows) > MAX_ROWS or byte_count > 256 * 1024 * 1024:
            raise ValueError(
                "Analysis input exceeds 500,000 rows / 256 MiB. Select a smaller split or subgroup."
            )
        after = page[-1]["result_id"]
