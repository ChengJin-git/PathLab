"""Bounded, read-only prediction snapshots for custom analysis of selected tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import String, and_, select

from backend.database.database import safe_session
from backend.database.models import AIResult, TrainingTaskWSI, WSISlide
from backend.services.manuscripts import clean_json

MAX_BYTES = 256 * 1024 * 1024
PAGE_SIZE = 500
RESULT_FIELDS = {
    "risk_score",
    "event_time",
    "event_status",
    "surv_probs",
    "bin_edges",
    "metrics",
    "class_names",
    "has_ground_truth",
    "num_classes",
    "image_size",
}


def append_batch(path: Path, rows) -> int:
    with path.open("a", encoding="utf-8") as output:
        for row in rows:
            item = dict(row)
            metadata = item.pop("result_metadata") or {}
            item["result_metadata"] = (
                {key: value for key, value in metadata.items() if key in RESULT_FIELDS}
                if isinstance(metadata, dict)
                else {}
            )
            output.write(
                json.dumps(clean_json(item), ensure_ascii=False, allow_nan=False) + "\n"
            )
        size = output.tell()
    if size > MAX_BYTES:
        raise ValueError(
            "Prediction snapshot exceeds 256 MiB; select a smaller task or export the required subset as a file"
        )
    return size


async def export_task(session_id: str, task_id: str, dataset_scope) -> dict:
    """Called only after resolve_references authorizes the task, in the Worker."""
    from .runtime import private_dir

    directory = private_dir(session_id) / "inputs" / "references"
    directory.mkdir(parents=True, exist_ok=True)
    name = "task-" + hashlib.sha256(task_id.encode()).hexdigest()[:24] + ".jsonl"
    target = directory / name
    temporary = directory / ("." + name + "-" + uuid4().hex)
    count, after = 0, 0
    try:
        temporary.touch()
        async with safe_session() as db:
            while True:
                statement = (
                    select(
                        AIResult.id.label("result_id"),
                        AIResult.wsi_id,
                        WSISlide.case_id,
                        WSISlide.dataset_id,
                        WSISlide.label,
                        AIResult.pred,
                        AIResult.probs,
                        AIResult.created_at.cast(String).label("created_at"),
                        TrainingTaskWSI.split,
                        WSISlide.age,
                        WSISlide.gender,
                        WSISlide.source,
                        WSISlide.event_time,
                        WSISlide.event_status,
                        AIResult.extra_metadata.label("result_metadata"),
                    )
                    .join(WSISlide, WSISlide.wsi_id == AIResult.wsi_id)
                    .outerjoin(
                        TrainingTaskWSI,
                        and_(
                            TrainingTaskWSI.task_id == AIResult.task_id,
                            TrainingTaskWSI.wsi_id == AIResult.wsi_id,
                        ),
                    )
                    .where(
                        AIResult.task_id == task_id,
                        AIResult.id > after,
                        WSISlide.dataset_id.in_(dataset_scope),
                    )
                    .order_by(AIResult.id)
                    .limit(PAGE_SIZE)
                )
                rows = (await db.execute(statement)).mappings().all()
                if not rows:
                    break
                writer = asyncio.create_task(
                    asyncio.to_thread(append_batch, temporary, rows)
                )
                try:
                    await asyncio.shield(writer)
                except asyncio.CancelledError:
                    await writer
                    raise
                count += len(rows)
                after = rows[-1]["result_id"]
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "predictions_path": "/research-data/references/" + name,
        "prediction_rows": count,
        "prediction_scope": "All saved predictions in the authorized dataset scope. Preserve split, case_id and result_id. Do not mix train/validation/test or count repeated case predictions as independent patients. Missing predictions or group attributes are missing evidence, not zero.",
    }
