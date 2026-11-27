"""Result catalog and authorization. Index at publication, read metadata on entry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import selectinload

from backend.database.models import (
    AIResult,
    AutoResearchSession,
    ResultSource,
    ResultSourceDataset,
    TrainingTask,
    TrainingTaskWSI,
    TrainedModel,
    WSISlide,
    utc_now,
)
from backend.services.workspaces import resolve_scope
from backend.common.config import Config
from .contracts import family


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]


def readable_title(name: str | None, research_title: str | None = None) -> str:
    """Use the original human-authored research title for technical run names."""
    candidate = (name or "").strip()
    technical = re.fullmatch(
        r"(?:run|job|experiment|research|task)_[a-zA-Z0-9_-]+", candidate
    )
    return (
        (research_title or "").strip() if not candidate or technical else candidate
    )[:500] or "Untitled experiment"


async def index_experiment(db, session, experiment):
    configuration = experiment.hyperparams or {}
    declared = configuration.get("config") or configuration
    types = declared.get("task_types") or (
        [declared["task_type"]] if declared.get("task_type") else []
    )
    if not isinstance(types, list):
        types = []
    if not types and experiment.dataset_id:
        from backend.database.models import DatasetTask
        types = list((await db.scalars(select(DatasetTask.task_type).where(DatasetTask.dataset_id == experiment.dataset_id))).all())
    task_families = sorted(
        {family(value) for value in types if isinstance(value, str)}
    ) or ["custom"]
    from backend.autoresearch.engine.analysis_results import AnalysisTask

    facets = [
        AnalysisTask.model_validate(task).model_dump()
        for task in declared.get("analysis_tasks", [])
    ]
    if facets:
        task_families = sorted(
            (set(task_families) - {"custom"})
            | {family(task["task_type"]) for task in facets}
        )
    await put_source(
        db,
        source_id=f"experiment:{session.session_id}:{experiment.training_task_id}",
        user_id=session.user_id,
        session_id=session.session_id,
        kind="experiment",
        title=readable_title(experiment.experiment_name, session.research_question),
        task_type=types[0]
        if len(types) == 1
        else "multitask"
        if len(task_families) > 1
        else "custom",
        details={
            "metrics": flatten_metrics(experiment.metrics),
            "prediction_count": 0,
            "splits": [],
            "run_id": experiment.training_task_id,
            "iteration": max(1, experiment.iteration),
            "research_title": session.research_question,
            "task_families": task_families,
            "facets": facets,
            "dataset_ids": [experiment.dataset_id] if experiment.dataset_id else [],
            "workspace_id": (session.recovery_metadata or {}).get("workspace_id"),
        },
        dataset_ids=[experiment.dataset_id] if experiment.dataset_id else [],
        created_at=experiment.created_at,
    )


def flatten_metrics(value, prefix="") -> dict:
    import math

    result = {}
    for key, item in (value or {}).items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict) and "value" not in item:
            result.update(flatten_metrics(item, name))
        elif (
            isinstance(item, dict)
            and isinstance(item.get("value"), (int, float))
            and math.isfinite(item["value"])
        ):
            result[name] = {
                k: item[k]
                for k in ("value", "label", "unit", "ci_lower", "ci_upper")
                if k in item
            }
        elif (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
        ):
            result[name] = {"value": item, "unit": ""}
    return result


async def put_source(
    db,
    *,
    source_id,
    user_id,
    task_id=None,
    session_id=None,
    kind,
    title,
    task_type,
    details,
    dataset_ids=(),
    created_at=None,
):
    row = await db.get(ResultSource, source_id)
    revision = digest(details)
    if row is None:
        row = ResultSource(
            source_id=source_id,
            user_id=str(user_id or ""),
            created_at=created_at or utc_now(),
        )
        db.add(row)
    row.task_id, row.session_id, row.kind = task_id, session_id, kind
    row.user_id = str(user_id or '')
    row.title, row.task_type, row.revision, row.details = (
        title[:500],
        task_type,
        revision,
        details,
    )
    row.updated_at = utc_now()
    await db.flush()
    await db.execute(
        delete(ResultSourceDataset).where(ResultSourceDataset.source_id == source_id)
    )
    db.add_all(
        [
            ResultSourceDataset(source_id=source_id, dataset_id=did)
            for did in set(dataset_ids)
            if did
        ]
    )
    await db.flush()
    return row


async def index_task(db, task_id: str):
    task = (
        await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.task_id == task_id)
        )
    ).scalar_one_or_none()
    if task is None or task.status != "completed":
        return
    group = task.data_group
    mc = task.model_config or {}
    task_type = group.task_type if group else "wsi_classification"
    join = and_(
        AIResult.task_id == TrainingTaskWSI.task_id,
        AIResult.wsi_id == TrainingTaskWSI.wsi_id,
    )
    split = func.coalesce(TrainingTaskWSI.split, "unassigned")
    labelled = (
        WSISlide.label.isnot(None)
        if family(task_type) == "classification"
        else AIResult.extra_metadata["has_ground_truth"].as_boolean().is_(True)
        if family(task_type) in {"detection", "segmentation"}
        else and_(WSISlide.event_time.isnot(None), WSISlide.event_status.isnot(None))
    )
    stats = (
        await db.execute(
            select(
                split.label("split"),
                func.count(AIResult.id),
                func.count(AIResult.id).filter(labelled),
                func.count(AIResult.id).filter(AIResult.probs.isnot(None)),
            )
            .join(WSISlide, WSISlide.wsi_id == AIResult.wsi_id)
            .outerjoin(TrainingTaskWSI, join)
            .where(AIResult.task_id == task_id)
            .group_by(split)
        )
    ).all()
    models = (
        (
            await db.execute(
                select(TrainedModel)
                .where(TrainedModel.task_id == task_id)
                .order_by(TrainedModel.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    model = models[0] if models else None
    dataset_ids = set(
        (
            await db.execute(
                select(WSISlide.dataset_id)
                .join(AIResult, AIResult.wsi_id == WSISlide.wsi_id)
                .where(AIResult.task_id == task_id)
                .distinct()
            )
        ).scalars()
    )
    dataset_ids.update(
        (
            await db.execute(
                select(WSISlide.dataset_id)
                .join(TrainingTaskWSI, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(TrainingTaskWSI.task_id == task_id)
                .distinct()
            )
        ).scalars()
    )
    if mc.get("dataset_id"):
        dataset_ids.add(mc["dataset_id"])
    sample = (
        await db.execute(
            select(AIResult.extra_metadata)
            .where(AIResult.task_id == task_id)
            .order_by(AIResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or {}
    segmentation_thresholds = False
    if task_type == "patch_segmentation":
        # The last prediction may be unlabelled. Capability comes from all GT
        # rows, so unlabelled tail images cannot hide available threshold controls.
        threshold_rows = await db.execute(select(
            func.count(AIResult.id),
            func.count(AIResult.id).filter(AIResult.extra_metadata["threshold_counts"]["positive"].as_string().isnot(None)),
        ).where(AIResult.task_id == task_id, labelled))
        labelled_count, threshold_count = threshold_rows.one()
        segmentation_thresholds = labelled_count > 0 and threshold_count == labelled_count
    provenance = (
        "external"
        if task_id.startswith("extval_")
        else "inference"
        if task_id.startswith(("binfer_", "indinfer_"))
        else "research"
        if mc.get("source") == "autoresearch"
        else "training"
    )
    details = {
        "task_families": [family(task_type)],
        "facets": [],
        "prediction_count": sum(row[1] for row in stats),
        "gt_count": sum(row[2] for row in stats),
        "probability_count": sum(row[3] for row in stats),
        "splits": [row[0] for row in stats],
        "split_counts": {row[0]: row[1] for row in stats},
        "classes": task.classes
        or (model.classes if model else [])
        or sample.get("class_names", []),
        "unit": group.aggregation_level if group else "file",
        "metrics": flatten_metrics(model.val_metrics if model else {}),
        "model_id": model.model_id if model else mc.get("model_id"),
        "dataset_ids": sorted(did for did in dataset_ids if did),
        "segmentation_metrics": task_type == "patch_segmentation" and sum(row[2] for row in stats) > 0,
        "segmentation_thresholds": segmentation_thresholds,
        "detection_boxes": bool(sample.get("detection")),
        "survival": bool(sample.get("surv_probs")),
        "updated_predictions": str(
            (
                await db.execute(
                    select(func.max(AIResult.created_at)).where(
                        AIResult.task_id == task_id
                    )
                )
            ).scalar()
        ),
    }

    def history_path():
        candidates = (
            [Path(model.model_path).parent / "metrics.json"] if model else []
        ) + [
            Config.get_uploads_dir()
            / "training"
            / task_id
            / "checkpoints"
            / "metrics.json",
            Config.get_uploads_dir() / "training" / task_id / "metrics.json",
        ]
        return next((str(path) for path in candidates if path.is_file()), None)

    details["history_path"] = await asyncio.to_thread(history_path)
    details["training_history"] = bool(details["history_path"])
    fold_splits = [value for value in details["splits"] if value.startswith("fold_")]
    if fold_splits:
        details["splits"].insert(0, "oof")
        details["split_counts"]["oof"] = sum(
            details["split_counts"][value] for value in fold_splits
        )
    research_title = None
    if mc.get("session_id"):
        research_title = await db.scalar(
            select(AutoResearchSession.research_question).where(
                AutoResearchSession.session_id == mc["session_id"]
            )
        )
        details["research_title"] = research_title
    await put_source(
        db,
        source_id=f"task:{task_id}",
        task_id=task_id,
        user_id=task.user_id,
        kind=provenance,
        title=readable_title(task.task_name, research_title),
        task_type=task_type,
        details=details,
        dataset_ids=dataset_ids,
        created_at=task.created_at,
    )


async def index_research(session, entry: dict, result: dict):
    from backend.database.database import safe_session

    async with safe_session() as db:
        metadata = session.recovery_metadata or {}
        dataset_ids = metadata.get("dataset_ids", [])
        prediction_details = {}
        if result.get("predictions"):
            from .artifacts import read_predictions

            prediction_details = await asyncio.to_thread(
                read_predictions,
                Path(session.workspace_path),
                result["predictions"],
                inspect_only=True,
            )
            prediction_details.pop("rows", None)
            dataset_ids = list(
                set(dataset_ids) | set(prediction_details["dataset_ids"])
            )
        # References may include tasks from other datasets; retain their complete scope.
        for ref in metadata.get("resource_references", []):
            if ref.get("kind") == "task":
                source = await db.get(ResultSource, f"task:{ref.get('id')}")
                if source:
                    dataset_ids = list(
                        set(dataset_ids) | set(source.details.get("dataset_ids", []))
                    )
        await put_source(
            db,
            source_id=f"research:{session.session_id}:{entry['id']}",
            session_id=session.session_id,
            user_id=session.user_id,
            kind="analysis",
            title=result["title"],
            task_type=result["predictions"]["task_type"]
            if result.get("predictions")
            else "multitask"
            if len({family(task["task_type"]) for task in result.get("tasks", [])}) > 1
            else (result["tasks"][0]["task_type"] if result.get("tasks") else "custom"),
            details={
                "metrics": flatten_metrics(result.get("metrics")),
                "analysis_id": entry["id"],
                "path": entry["path"],
                "artifact_revision": entry["revision"],
                "prediction_count": 0,
                "splits": [],
                "summary": result.get("summary", "")[:1200],
                "workspace_id": metadata.get("workspace_id"),
                "task_families": sorted(
                    {family(task["task_type"]) for task in result.get("tasks", [])}
                    | (
                        {family(result["predictions"]["task_type"])}
                        if result.get("predictions")
                        else set()
                    )
                )
                or ["custom"],
                "facets": result.get("tasks", []),
                **prediction_details,
                "dataset_ids": dataset_ids,
                "prediction_artifact": result.get("predictions"),
            },
            dataset_ids=dataset_ids,
        )
        await db.commit()


def visibility(user, scope):
    members = select(ResultSourceDataset.source_id).where(
        ResultSourceDataset.source_id == ResultSource.source_id
    )
    allowed = scope.datasets(user)
    clauses = [] if user.is_admin() else [ResultSource.user_id == str(user.id)]
    if not user.is_admin():
        clauses.append(or_(ResultSource.task_id.is_(None), ResultSource.task_id.in_(
            select(TrainingTask.task_id).where(TrainingTask.user_id == str(user.id)))))
    if not user.is_admin() or scope.workspace_id:
        clauses.append(
            ~exists(members.where(ResultSourceDataset.dataset_id.not_in(allowed)))
        )
    if scope.workspace_id:
        clauses.append(
            or_(
                exists(members),
                ResultSource.details["workspace_id"].as_string() == scope.workspace_id,
            )
        )
    return clauses


async def authorized_sources(db, user, ids, workspace_id=None):
    scope = await resolve_scope(db, user, workspace_id)
    rows = (
        (
            await db.execute(
                select(ResultSource).where(
                    ResultSource.source_id.in_(ids), *visibility(user, scope)
                )
            )
        )
        .scalars()
        .all()
    )
    mapped = {row.source_id: row for row in rows}
    if set(ids) - mapped.keys():
        raise HTTPException(404, "Result source unavailable in the current scope")
    return [mapped[identity] for identity in ids]


def public_source(row):
    details = {
        k: v
        for k, v in row.details.items()
        if k
        not in {"path", "history_path", "prediction_artifact", "updated_predictions"}
    }
    return {
        **details,
        "source_id": row.source_id,
        "title": row.title,
        "kind": row.kind,
        "task_type": row.task_type,
        "task_id": row.task_id,
        "session_id": row.session_id,
        "revision": row.revision,
        "created_at": row.created_at.isoformat() + "Z",
    }
