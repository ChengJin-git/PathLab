"""Fast authorized result summaries: no bundle reads on the catalog path."""

import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.common.config import Config
from backend.database.models import TrainingTask, AITask
from backend.ai.result_catalog import ResultCatalog
from backend.services.result_analysis.visuals import class_colors


async def result_entries(db, user, wsi_id):
    training = select(TrainingTask).where(TrainingTask.user_id == str(user.id))
    inference = select(AITask.task_id).where(AITask.user_id == str(user.id))
    if user.is_admin():
        training, inference = select(TrainingTask), select(AITask.task_id)
    # Retrieve only matching task IDs from the indexed catalog, then authorize them.
    catalog = ResultCatalog(Config.get_uploads_dir() / "ai_results_bundles")
    rows = await asyncio.to_thread(catalog.image, wsi_id)
    ids = {row["task_id"] for row in rows}
    if not ids:
        return []
    tasks = {
        row.task_id: row
        for row in (
            await db.scalars(
                training.where(TrainingTask.task_id.in_(ids)).options(
                    selectinload(TrainingTask.data_group)
                )
            )
        ).all()
    }
    allowed = set(tasks) | set(
        (await db.scalars(inference.where(AITask.task_id.in_(ids)))).all()
    )
    grouped = {}
    for row in rows:
        if row["task_id"] not in allowed:
            continue
        key = row["task_id"], row["fold_key"]
        item = grouped.setdefault(
            key, {"summary": {}, "artifacts": set(), "revision": row["revision"]}
        )
        item["summary"].update(row["summary"])
        item["artifacts"].add(row["artifact"])
    entries = []
    for (tid, fold), item in grouped.items():
        meta, artifacts, task = item["summary"], item["artifacts"], tasks.get(tid)
        task_type = meta.get("task_type") or (
            task.data_group.task_type if task and task.data_group else "unknown"
        )
        config = getattr(task, "preprocessing_config", None) or {}
        model_config = getattr(task, "model_config", None) or {}
        artifact = next(
            (a for a in ["attention", "cam", "pred_mask"] if a in artifacts), "result"
        )
        classes = (
            meta.get("class_names")
            or meta.get("classes")
            or getattr(task, "classes", None)
        )
        entries.append(
            {
                **meta,
                "task_id": tid,
                "fold_key": fold,
                "revision": item["revision"],
                "task_type": task_type,
                "task_name": getattr(task, "task_name", None)
                or meta.get("task_name")
                or tid,
                "prediction": meta.get("pred"),
                "classes": classes,
                "class_colors": class_colors(classes),
                "feature_extractor": meta.get("feature_extractor")
                or config.get("feature_extractor"),
                "aggregator": meta.get("aggregator") or model_config.get("aggregator"),
                "created_at": task.created_at.timestamp()
                if task and task.created_at
                else 0,
                "data_type": "patch"
                if task_type.startswith("patch") or artifact in {"cam", "pred_mask"}
                else "wsi",
                "has_heatmap": bool(artifacts & {"attention", "cam"}),
                "artifacts": sorted(artifacts),
                "attention_file": f"{tid}_{artifact}.npy",
                "is_kfold": fold is not None,
            }
        )
    return sorted(
        entries,
        key=lambda item: (-item["created_at"], item["task_id"], item["fold_key"] or ""),
    )
