"""Best-effort PostgreSQL persistence for PathScientist web sessions."""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import logging
import math
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.database.database import safe_session
from backend.database.models import TrainingTask, TrainedModel, utc_now
from backend.database.repositories import DataGroupRepository, WSIRepository
from backend.database.repositories.auto_research import AutoResearchRepository

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 20000
MAX_JSON_TEXT_LENGTH = 12000
MAX_RESEARCH_QUESTION_LENGTH = 4000
MAX_JSON_SAFE_DEPTH = 20
MAX_JSON_SAFE_BYTES = 200_000
PERSISTENCE_QUEUE_MAXSIZE = max(
    1,
    int(os.getenv("PATHSCIENTIST_PERSISTENCE_QUEUE_MAXSIZE", "1024")),
)
PERSISTENCE_ENQUEUE_TIMEOUT_SECONDS = max(
    0.01,
    float(os.getenv("PATHSCIENTIST_PERSISTENCE_ENQUEUE_TIMEOUT_SECONDS", "0.25")),
)

_gateway_loop: asyncio.AbstractEventLoop | None = None
_persist_queues: dict[int, asyncio.Queue[tuple[Any, str]]] = {}
_persist_workers: dict[int, asyncio.Task[None]] = {}


def configure_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Register the Gateway event loop used by SQLAlchemy's async engine."""
    global _gateway_loop
    _gateway_loop = loop or asyncio.get_running_loop()
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if running_loop is _gateway_loop and not _gateway_loop.is_closed():
        _ensure_persistence_worker(_gateway_loop)


def persist_session_created(
    *,
    session_id: str,
    user_id: str,
    question: str,
    max_iterations: int,
    metric: str,
    model: str,
    workspace_path: str = "",
) -> None:
    _run_best_effort(
        _persist_session_created(
            session_id=session_id,
            user_id=user_id,
            question=question,
            max_iterations=max_iterations,
            metric=metric,
            model=model,
            workspace_path=workspace_path,
        ),
        "create PathScientist auto-research session",
    )


def persist_event(
    *,
    session_id: str,
    event: dict[str, Any],
) -> None:
    sequence = _event_sequence(event)
    if sequence <= 0:
        return
    _run_best_effort(
        _persist_event(
            session_id=session_id,
            event=event,
            sequence=sequence,
        ),
        "append PathScientist auto-research event",
    )


def persist_session_state(
    *,
    session_id: str,
    user_id: str,
    question: str,
    status: str,
    stage: str,
    state: dict[str, Any],
    max_iterations: int | None = None,
    metric: str = "",
    model: str = "",
    workspace_path: str = "",
) -> None:
    _run_best_effort(
        _persist_session_state(
            session_id=session_id,
            user_id=user_id,
            question=question,
            status=status,
            stage=stage,
            state=state,
            max_iterations=max_iterations,
            metric=metric,
            model=model,
            workspace_path=workspace_path,
        ),
        "persist PathScientist auto-research final state",
    )


def delete_session(session_id: str) -> None:
    _run_best_effort(
        _delete_session(session_id=session_id),
        "delete PathScientist auto-research session",
    )


async def import_session_bundle(
    *,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    default_user_id: str,
) -> None:
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        return
    state = session.get("state") if isinstance(session.get("state"), dict) else {}
    state = dict(state)
    for key in (
        "conversation_id",
        "persistence_dir",
        "conversation_dir",
        "workspace_path",
        "workspace_dir",
        "resume_available",
    ):
        if session.get(key) not in (None, "", [], {}):
            state.setdefault(key, session.get(key))
    user_id = str(session.get("user_id") or default_user_id or "").strip()
    if not user_id:
        raise ValueError(f"user_id is required to import session {session_id}")
    question = str(session.get("question") or _objective_question(state) or "")
    status = str(session.get("status") or state.get("stage") or "completed")
    stage = str(session.get("stage") or state.get("stage") or status)
    max_iterations = _int_or_none(
        session.get("max_iterations")
        or state.get("max_iterations")
        or session.get("max_iter")
    )
    metric = str(session.get("metric") or _metric_name(state) or "")
    model = str(session.get("model") or "")
    workspace_path = str(session.get("workspace_path") or "")

    async with safe_session() as db:
        await AutoResearchRepository.upsert_session(
            db,
            _session_payload(
                session_id=session_id,
                user_id=user_id,
                question=question,
                status=status,
                stage=stage,
                state=state,
                max_iterations=max_iterations,
                metric=metric,
                model=model,
                workspace_path=workspace_path,
            ),
        )
        for event in events:
            if not isinstance(event, dict):
                continue
            sequence = _event_sequence(event)
            if sequence <= 0:
                continue
            await AutoResearchRepository.append_event_once(
                db,
                session_id,
                _event_payload(event),
                sequence,
            )
        for experiment in _experiment_payloads(
            session_id=session_id,
            state=state,
            metric=metric,
        ):
            await AutoResearchRepository.upsert_experiment_by_run_id(db, experiment)
        await db.commit()


async def _persist_session_created(
    *,
    session_id: str,
    user_id: str,
    question: str,
    max_iterations: int,
    metric: str,
    model: str,
    workspace_path: str,
) -> None:
    async with safe_session() as db:
        await AutoResearchRepository.upsert_session(
            db,
            {
                "session_id": session_id,
                "user_id": user_id or "unknown",
                "research_question": question,
                "phase": "queued",
                "status": "queued",
                "thread_id": session_id,
                "conversation_id": None,
                "persistence_dir": None,
                "workspace_path": workspace_path or None,
                "resume_available": False,
                "event_source_version": "gateway-v1",
                "recovery_metadata": _json_safe({
                    "workspace_path": workspace_path,
                    "artifact_policy": "database stores metadata and paths; large artifacts stay on disk",
                }),
                "experiment_plan": _json_safe({
                    "model": model,
                    "workspace_path": workspace_path,
                    "artifact_policy": "database stores metadata and paths; large artifacts stay on disk",
                }),
                "best_metric_name": metric or "auc",
                "current_iteration": 0,
                "max_iterations": max_iterations,
            },
        )
        await db.commit()


async def _persist_event(
    *,
    session_id: str,
    event: dict[str, Any],
    sequence: int,
) -> None:
    async with safe_session() as db:
        await AutoResearchRepository.append_event_once(
            db,
            session_id,
            _event_payload(event),
            sequence,
        )
        if _is_state_event(event):
            existing = await AutoResearchRepository.get_session(db, session_id)
            state = dict(event.get("state") or {})
            stage = str(
                event.get("stage")
                or state.get("stage")
                or getattr(existing, "phase", "")
                or event.get("status")
                or "running"
            )
            status = _event_status(event, state=state, existing_status=getattr(existing, "status", ""))
            experiment_plan = getattr(existing, "experiment_plan", None)
            if not isinstance(experiment_plan, dict):
                experiment_plan = {}
            await AutoResearchRepository.upsert_session(
                db,
                _session_payload(
                    session_id=session_id,
                    user_id=str(getattr(existing, "user_id", "") or "unknown"),
                    question=str(
                        getattr(existing, "research_question", "")
                        or _objective_question(state)
                    ),
                    status=status,
                    stage=stage,
                    state=state,
                    max_iterations=(
                        getattr(existing, "max_iterations", None)
                        if existing is not None
                        else _int_or_none(state.get("max_iterations"))
                    ),
                    metric=str(
                        getattr(existing, "best_metric_name", "")
                        or _metric_name(state)
                        or ""
                    ),
                    model=str(experiment_plan.get("model") or ""),
                    workspace_path=str(getattr(existing, "workspace_path", "") or ""),
                ),
            )
        await db.commit()


async def _persist_session_state(
    *,
    session_id: str,
    user_id: str,
    question: str,
    status: str,
    stage: str,
    state: dict[str, Any],
    max_iterations: int | None,
    metric: str,
    model: str,
    workspace_path: str,
) -> None:
    async with safe_session() as db:
        state = dict(state)
        registration_result = await _safe_register_pathlab_trained_model(
            db,
            session_id=session_id,
            user_id=user_id or "unknown",
            question=question,
            state=state,
            status=status,
            stage=stage,
            metric=metric,
        )
        if registration_result:
            state["pathlab_model_registration"] = registration_result
        await AutoResearchRepository.upsert_session(
            db,
            _session_payload(
                session_id=session_id,
                user_id=user_id or "unknown",
                question=question,
                status=status,
                stage=stage,
                state=state,
                max_iterations=max_iterations,
                metric=metric,
                model=model,
                workspace_path=workspace_path,
            ),
        )
        for experiment in _experiment_payloads(
            session_id=session_id,
            state=state,
            metric=metric,
        ):
            await AutoResearchRepository.upsert_experiment_by_run_id(db, experiment)
        await db.commit()


async def _delete_session(*, session_id: str) -> None:
    async with safe_session() as db:
        await AutoResearchRepository.delete_session(db, session_id)
        await db.commit()


def _session_payload(
    *,
    session_id: str,
    user_id: str,
    question: str,
    status: str,
    stage: str,
    state: dict[str, Any],
    max_iterations: int | None,
    metric: str,
    model: str,
    workspace_path: str,
) -> dict[str, Any]:
    run_history = _run_history(state)
    metric_name = metric or _metric_name(state) or "auc"
    conversation_id = _conversation_id(state)
    persistence_dir = _persistence_dir(state, conversation_id)
    workspace_path = workspace_path or _workspace_path(state)
    recovery_metadata = _recovery_metadata(
        state,
        conversation_id=conversation_id,
        persistence_dir=persistence_dir,
        workspace_path=workspace_path,
    )
    best_run_id = str(state.get("best_run_id") or "")
    best_experiment = _best_experiment(run_history, best_run_id)
    best_metric = _float_or_none(state.get("best_metric_value"))
    if best_metric is None and best_experiment:
        best_metric = _float_or_none(best_experiment.get("metric_value"))
    current_iteration = _int_or_none(state.get("iteration_index"))
    if current_iteration is None:
        current_iteration = len(run_history)

    return {
        "session_id": session_id,
        "user_id": user_id,
        "research_question": _truncate_text(
            question or _objective_question(state),
            MAX_RESEARCH_QUESTION_LENGTH,
        ),
        "phase": (stage or str(state.get("stage") or status or "running"))[:50],
        "status": (status or "running")[:20],
        "thread_id": session_id,
        "conversation_id": conversation_id or None,
        "persistence_dir": persistence_dir or None,
        "workspace_path": workspace_path or None,
        "resume_available": _resume_available(
            conversation_id=conversation_id,
            persistence_dir=persistence_dir,
        ),
        "event_source_version": "gateway-v1",
        "recovery_metadata": _json_safe(recovery_metadata),
        "experiment_plan": _experiment_plan(state, model, workspace_path),
        "best_metric": best_metric,
        "best_metric_name": metric_name[:50],
        "best_experiment": _json_safe(best_experiment),
        "comparison_results": _json_safe({
            "run_history": [_compact_run(entry) for entry in run_history],
            "external_test_history": _compact_history_list(
                state.get("external_test_history")
            ),
            "review_history": _compact_history_list(state.get("review_history")),
            "integrity_report": state.get("integrity_report"),
            "artifact_policy": "large artifacts remain in PATHSCIENTIST_BASE_DIR or dataset cache",
        }),
        "final_report": _truncate_text(_final_report(state)),
        "current_iteration": current_iteration,
        "max_iterations": max_iterations or _int_or_none(state.get("max_iterations")) or 0,
    }


def _experiment_payloads(
    *,
    session_id: str,
    state: dict[str, Any],
    metric: str,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    metric_name = metric or _metric_name(state) or "metric"
    for index, entry in enumerate(_run_history(state), start=1):
        if not isinstance(entry, dict):
            continue
        run_id = str(entry.get("run_id") or "").strip()
        if not run_id:
            continue
        metrics = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {}
        pathlab_linkage = _pathlab_linkage(entry)
        status = "completed" if bool(entry.get("committed")) else "failed"
        if entry.get("exit_code") == 0:
            status = "completed"
        if entry.get("error_type"):
            status = "failed"
        payloads.append({
            "session_id": session_id,
            "experiment_name": str(entry.get("name") or entry.get("label") or run_id)[:500],
            "training_task_id": pathlab_linkage.get("training_task_id") or run_id,
            "dataset_id": _string_or_none(
                entry.get("dataset_id")
                or entry.get("dataset")
                or _nested_get(entry, "data_output_dir")
            ),
            "feature_extractor": _string_or_none(
                entry.get("feature_extractor") or _nested_get(entry, "extractor")
            ),
            "aggregator": _string_or_none(
                entry.get("aggregator") or _nested_get(entry, "model")
            ),
            "hyperparams": _json_safe({
                "metric_name": entry.get("metric_name") or metric_name,
                "metric_value": entry.get("metric_value"),
                "committed": bool(entry.get("committed")),
                "run_id": run_id if pathlab_linkage else None,
                "run_dir": entry.get("run_dir"),
                "model_path": entry.get("model_path"),
                "data_output_dir": entry.get("data_output_dir"),
                "artifacts": entry.get("data_output_artifacts"),
                "quick_check": entry.get("quick_check"),
                "run_kind": entry.get("run_kind"),
                "error_type": entry.get("error_type"),
                "pathlab_linkage": pathlab_linkage or None,
            }),
            "status": status[:20],
            "metrics": _json_safe(metrics),
            "iteration": _int_or_none(entry.get("iteration")) or index,
        })
    return payloads


async def _safe_register_pathlab_trained_model(
    db: Any,
    *,
    session_id: str,
    user_id: str,
    question: str,
    state: dict[str, Any],
    status: str,
    stage: str,
    metric: str,
) -> dict[str, Any] | None:
    if not _is_terminal_success(status=status, stage=stage):
        return None
    try:
        begin_nested = getattr(db, "begin_nested", None)
        if callable(begin_nested):
            async with begin_nested():
                return await _register_pathlab_trained_model(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
                    state=state,
                    status=status,
                    stage=stage,
                    metric=metric,
                )
        return await _register_pathlab_trained_model(
            db,
            session_id=session_id,
            user_id=user_id,
            question=question,
            state=state,
            status=status,
            stage=stage,
            metric=metric,
        )
    except Exception as exc:
        logger.warning(
            "Failed to register PathScientist trained model for session %s: %s",
            session_id,
            exc,
        )
        return {
            "registered": False,
            "reason": str(exc),
            "session_id": session_id,
        }


async def _register_pathlab_trained_model(
    db: Any,
    *,
    session_id: str,
    user_id: str,
    question: str,
    state: dict[str, Any],
    status: str,
    stage: str,
    metric: str,
) -> dict[str, Any]:
    candidate = _pathlab_model_candidate(state=state, status=status, stage=stage)
    if not candidate:
        return {
            "registered": False,
            "reason": "no_completed_training_model",
            "session_id": session_id,
        }

    run_id = str(candidate.get("run_id") or "").strip()
    task_id = _bounded_identifier(
        f"pathscientist_{_safe_identifier_fragment(session_id)}_{_safe_identifier_fragment(run_id)}"
    )
    model_id = _bounded_identifier(f"{task_id}_model")
    model_path = str(candidate.get("model_path") or "").strip()
    model_path_obj = Path(model_path).expanduser()
    config_path = _model_config_path(model_path_obj)
    metric_name = str(candidate.get("metric_name") or metric or _metric_name(state) or "auc")
    metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    task_type = _infer_model_task_type(state=state, entry=candidate, question=question)
    group = await DataGroupRepository.get_or_create(
        db,
        data_type="wsi",
        aggregation_level="file",
        task_type=task_type,
        name=f"WSI File-level {task_type.capitalize()}",
        description="PathScientist generated model registration tasks",
    )

    feature_extractor = _bounded_text(
        _entry_string(candidate, "feature_extractor", "extractor", "backbone"),
        100,
    )
    aggregator = _bounded_text(
        _entry_string(candidate, "aggregator", "mil_model", "model", "architecture"),
        100,
    )
    classes = _model_classes(state, candidate)
    now = utc_now()
    started_at = _datetime_or_none(candidate.get("started_at")) or now
    pathlab_linkage = _pathlab_linkage(candidate)
    features_dir = (
        pathlab_linkage.get("features_dir")
        or _string_or_none(candidate.get("features_dir"))
        or _string_or_none(candidate.get("data_output_dir"))
    )
    feature_registration = await _register_pathlab_feature_outputs(
        db,
        task_id=task_id,
        features_dir=features_dir,
        pathlab_linkage=pathlab_linkage,
    )

    preprocessing_config = _json_safe({
        "source": "pathscientist",
        "session_id": session_id,
        "run_id": run_id,
        "features_dir": features_dir,
        "task_features_dir": feature_registration.get("task_features_dir"),
        "feature_count": feature_registration.get("feature_count", 0),
        "feature_extracted_rows": feature_registration.get("feature_extracted_rows", 0),
        "data_output_dir": candidate.get("data_output_dir"),
        "run_dir": candidate.get("run_dir"),
        "workspace_path": _workspace_path(state),
        "pathlab_linkage": pathlab_linkage or None,
    })
    model_config = _json_safe({
        "source": "pathscientist",
        "session_id": session_id,
        "run_id": run_id,
        "model_path": model_path,
        "config_path": str(config_path) if config_path else None,
        "feature_extractor": feature_extractor,
        "aggregator": aggregator,
        "metric_name": metric_name,
        "metric_value": _float_or_none(candidate.get("metric_value")),
        "quick_check": bool(candidate.get("quick_check")),
    })

    task = await _get_by_pk(db, TrainingTask, "task_id", task_id)
    if task is None:
        task = TrainingTask(task_id=task_id)
        db.add(task)
    task.task_name = _pathscientist_task_name(question, run_id)
    task.task_description = _bounded_text(
        f"PathScientist completed training run {run_id} from session {session_id}.",
        2000,
    )
    task.group_id = group.group_id
    task.user_id = user_id or "unknown"
    task.status = "completed"
    task.progress = 100
    task.error_message = None
    task.preprocessing_config = preprocessing_config
    task.model_config = model_config
    task.classes = classes
    task.started_at = started_at
    task.finished_at = now
    if hasattr(task, "updated_at"):
        task.updated_at = now

    model = await _get_by_pk(db, TrainedModel, "model_id", model_id)
    if model is None:
        model = TrainedModel(model_id=model_id)
        db.add(model)
    model.task_id = task_id
    model.model_name = _pathscientist_model_name(question, run_id, aggregator)
    model.user_id = user_id or "unknown"
    model.model_path = model_path
    model.config_path = str(config_path) if config_path else None
    model.classes = classes
    model.feature_extractor = feature_extractor
    model.aggregator = aggregator
    model.train_metrics = _json_safe({
        "source": "pathscientist",
        "run_id": run_id,
        "metric_name": metric_name,
    })
    model.val_metrics = _json_safe(metrics)
    model.is_default = False
    model.is_active = True
    if hasattr(model, "updated_at"):
        model.updated_at = now

    await db.flush()
    return {
        "registered": True,
        "session_id": session_id,
        "run_id": run_id,
        "training_task_id": task_id,
        "model_id": model_id,
        "model_path": model_path,
        "config_path": str(config_path) if config_path else None,
        "feature_extractor": feature_extractor,
        "aggregator": aggregator,
        "task_type": task_type,
        "features_registered": feature_registration.get("feature_count", 0),
        "feature_extracted_rows": feature_registration.get("feature_extracted_rows", 0),
        "task_features_dir": feature_registration.get("task_features_dir"),
    }


async def _register_pathlab_feature_outputs(
    db: Any,
    *,
    task_id: str,
    features_dir: str | None,
    pathlab_linkage: dict[str, Any],
) -> dict[str, Any]:
    """Mirror PathScientist features into PathLab's task feature view."""
    feature_root = Path(str(features_dir or "")).expanduser()
    feature_files = _feature_tensor_files(feature_root)
    if not feature_files:
        return {
            "feature_count": 0,
            "feature_extracted_rows": 0,
            "task_features_dir": None,
        }

    uploads_dir = _infer_uploads_dir_from_feature_root(
        feature_root,
        pathlab_linkage=pathlab_linkage,
    )
    task_features_dir = (
        uploads_dir / "training" / task_id / "features"
        if uploads_dir is not None
        else None
    )
    wsi_ids = [path.stem for path in feature_files]
    if task_features_dir is not None:
        for feature_path in feature_files:
            _create_relative_symlink(
                task_features_dir / f"{feature_path.stem}.pt",
                feature_path,
            )

    try:
        updated_rows = await WSIRepository.bulk_update_feature_extracted(
            db,
            wsi_ids,
            True,
        )
    except Exception as exc:
        logger.warning(
            "Failed to mark PathScientist feature_extracted rows for task %s: %s",
            task_id,
            exc,
        )
        updated_rows = 0

    return {
        "feature_count": len(feature_files),
        "feature_extracted_rows": int(updated_rows or 0),
        "task_features_dir": str(task_features_dir) if task_features_dir is not None else None,
    }


def _feature_tensor_files(features_dir: Path) -> list[Path]:
    try:
        if not features_dir.is_dir():
            return []
        return sorted(
            path
            for path in features_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".pt", ".pth"}
        )
    except OSError:
        return []


def _infer_uploads_dir_from_feature_root(
    features_dir: Path,
    *,
    pathlab_linkage: dict[str, Any],
) -> Path | None:
    explicit = _string_or_none(pathlab_linkage.get("uploads_dir"))
    if explicit:
        return Path(explicit).expanduser()
    parts = features_dir.parts
    for index, part in enumerate(parts):
        if part == "features" and index > 0:
            return Path(*parts[:index]).expanduser()
    return None


def _create_relative_symlink(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    try:
        rel_path = Path(os.path.relpath(target_path, link_path.parent))
        link_path.symlink_to(rel_path)
    except OSError:
        link_path.symlink_to(target_path)


def _pathlab_model_candidate(
    *,
    state: dict[str, Any],
    status: str,
    stage: str,
) -> dict[str, Any] | None:
    if not _is_terminal_success(status=status, stage=stage):
        return None

    run_history = _run_history(state)
    best_run_id = str(state.get("best_run_id") or "").strip()
    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add(entry: dict[str, Any]) -> None:
        marker = id(entry)
        if marker not in seen:
            seen.add(marker)
            ordered.append(entry)

    if best_run_id:
        for entry in run_history:
            if str(entry.get("run_id") or "") == best_run_id:
                add(entry)
                break
    for entry in reversed(run_history):
        if entry.get("committed"):
            add(entry)
    for entry in reversed(run_history):
        add(entry)

    for entry in ordered:
        candidate = _validated_model_candidate(entry)
        if candidate:
            return candidate
    return None


def _validated_model_candidate(entry: dict[str, Any]) -> dict[str, Any] | None:
    run_kind = str(entry.get("run_kind") or "").strip().lower()
    if run_kind in {"external_test", "external-validation", "external_validation"}:
        return None
    if bool(entry.get("quick_check")):
        return None
    if entry.get("error_type"):
        return None
    exit_code = _int_or_none(entry.get("exit_code"))
    if exit_code is not None and exit_code != 0:
        return None
    if not entry.get("committed") and exit_code != 0:
        return None

    linkage = _pathlab_linkage(entry)
    model_path = _string_or_none(entry.get("model_path")) or linkage.get("model_path")
    if not model_path:
        return None
    model_path_obj = Path(model_path).expanduser()
    if not model_path_obj.is_file():
        return None

    candidate = dict(entry)
    candidate["model_path"] = str(model_path_obj)
    if linkage:
        candidate.setdefault("pathlab_linkage", linkage)
    return candidate


def _is_terminal_success(*, status: str, stage: str) -> bool:
    status_value = str(status or "").strip().lower()
    stage_value = str(stage or "").strip().lower()
    return status_value in {
        "completed",
        "complete",
        "finished",
        "success",
        "succeeded",
    } or stage_value in {
        "completed",
        "complete",
        "finished",
        "success",
        "succeeded",
        "synthesis",
    }


async def _get_by_pk(db: Any, model_cls: Any, pk_field: str, pk_value: Any) -> Any:
    result = await db.execute(
        select(model_cls).where(getattr(model_cls, pk_field) == pk_value)
    )
    return result.scalar_one_or_none()


def _safe_identifier_fragment(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return text or "unknown"


def _bounded_identifier(value: str, limit: int = 255) -> str:
    text = _safe_identifier_fragment(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("._-") or text[:limit]


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _pathscientist_task_name(question: str, run_id: str) -> str:
    base = str(question or "").strip() or f"run {run_id}"
    return _bounded_text(f"PathScientist: {base}", 500)


def _pathscientist_model_name(question: str, run_id: str, aggregator: str | None) -> str:
    if question:
        base = f"PathScientist: {question}"
    elif aggregator:
        base = f"PathScientist {aggregator} run {run_id}"
    else:
        base = f"PathScientist run {run_id}"
    return _bounded_text(base, 500)


def _model_config_path(model_path: Path) -> Path | None:
    for name in (
        "config.json",
        "model_config.json",
        "training_config.json",
        "config.yaml",
        "config.yml",
    ):
        candidate = model_path.parent / name
        if candidate.is_file():
            return candidate
    return None


def _entry_string(entry: dict[str, Any], *keys: str) -> str | None:
    containers: list[Any] = [
        entry,
        entry.get("metrics"),
        entry.get("config"),
        entry.get("hyperparams"),
        entry.get("metadata"),
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = _string_or_none(container.get(key))
            if value:
                return value
    return None


def _model_classes(state: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    for value in (
        entry.get("classes"),
        _nested_get(entry, "classes"),
        state.get("classes"),
        _nested_get(state, "classes"),
    ):
        parsed = _string_list(value)
        if parsed:
            return parsed
    metrics = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {}
    for key in ("class_names", "labels", "label_names"):
        parsed = _string_list(metrics.get(key))
        if parsed:
            return parsed
    for key in ("class_to_idx", "label_to_idx", "label_mapping"):
        parsed = _mapping_keys(metrics.get(key))
        if parsed:
            return parsed
    for key in ("idx_to_class", "id_to_label", "idx_to_label"):
        parsed = _mapping_values(metrics.get(key), sort_numeric_keys=True)
        if parsed:
            return parsed
    return []


def _mapping_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return _string_list(list(value.keys()))


def _mapping_values(value: Any, *, sort_numeric_keys: bool = False) -> list[str]:
    if not isinstance(value, dict):
        return []
    items = list(value.items())
    if sort_numeric_keys:
        items.sort(key=lambda item: _mapping_sort_key(item[0]))
    return _string_list([item[1] for item in items])


def _mapping_sort_key(value: Any) -> tuple[int, Any]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = list(value.keys())
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    seen = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _infer_model_task_type(
    *,
    state: dict[str, Any],
    entry: dict[str, Any],
    question: str,
) -> str:
    for value in (
        entry.get("task_type"),
        _nested_get(entry, "task_type"),
        state.get("task_type"),
        _nested_get(state, "task_type"),
    ):
        normalized = _normalize_task_type(value)
        if normalized:
            return normalized

    text_parts = [
        question,
        str(state.get("research_question") or ""),
        str(state.get("objective") or ""),
        str(state.get("grounding") or ""),
        str(entry.get("run_kind") or ""),
    ]
    text = " ".join(text_parts).lower()
    if "survival" in text or "cox" in text:
        return "survival"
    if "segment" in text or "segmentation" in text or "mask" in text:
        return "segmentation"
    return "classification"


def _normalize_task_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"classification", "survival", "segmentation"}:
        return text
    if text in {"classify", "cls"}:
        return "classification"
    if text in {"segment", "seg"}:
        return "segmentation"
    return ""


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("kind") or event.get("event_type") or "event")[:50]
    return {
        "event_type": event_type,
        "event_data": _json_safe(event),
    }


def _is_state_event(event: dict[str, Any]) -> bool:
    return (
        str(event.get("kind") or event.get("event_type") or "").strip() == "state"
        and isinstance(event.get("state"), dict)
    )


def _event_status(
    event: dict[str, Any],
    *,
    state: dict[str, Any],
    existing_status: Any,
) -> str:
    explicit = str(event.get("status") or "").strip()
    if explicit:
        return explicit
    stage = str(state.get("stage") or event.get("stage") or "").strip().lower()
    if stage in {"completed", "complete", "finished", "synthesis"}:
        return "completed"
    if stage in {"failed", "error"}:
        return "failed"
    if stage in {"interrupted", "cancelled", "canceled", "stopped"}:
        return "interrupted"
    return str(existing_status or "running")


def _experiment_plan(
    state: dict[str, Any],
    model: str,
    workspace_path: str,
) -> dict[str, Any]:
    plan = {
        "model": model,
        "workspace_path": workspace_path,
        "artifact_policy": "database stores metadata and paths; large artifacts stay on disk",
    }
    for key in (
        "objective",
        "task_profile",
        "selected_dataset",
        "dataset_manifest_path",
        "acquisition_status",
        "acquisition_notes",
        "data_readiness",
        "execution_plan",
        "grounding",
    ):
        if key in state:
            plan[key] = state.get(key)
    return _json_safe(plan)


def _conversation_id(state: dict[str, Any]) -> str:
    for key in ("conversation_id",):
        value = state.get(key)
        if value:
            return str(value).strip()
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        value = summary.get("conversation_id")
        if value:
            return str(value).strip()
    return ""


def _workspace_path(state: dict[str, Any]) -> str:
    for key in ("workspace_path", "workspace_dir", "workspace_root"):
        value = state.get(key)
        if value:
            return str(value)
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        for key in ("workspace_path", "workspace_dir", "workspace_root"):
            value = summary.get(key)
            if value:
                return str(value)
        research = summary.get("research_session")
        if isinstance(research, dict):
            value = research.get("workspace_dir") or research.get("workspace_root")
            if value:
                return str(value)
    return ""


def _persistence_dir(state: dict[str, Any], conversation_id: str) -> str:
    for key in ("persistence_dir", "conversation_dir"):
        value = state.get(key)
        if value:
            return str(value)
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        for key in ("persistence_dir", "conversation_dir"):
            value = summary.get(key)
            if value:
                return str(value)
    if not conversation_id:
        return ""
    try:
        from backend.pathscientist.persistence.layout import get_persistence_root
        from backend.pathscientist.runtime.session import _resolve_base_dir

        root = Path(get_persistence_root(_resolve_base_dir()))
        for candidate in (
            root / conversation_id,
            root / conversation_id.replace("-", ""),
        ):
            if candidate.exists():
                return str(candidate)
        return str(root / conversation_id.replace("-", ""))
    except Exception:
        return ""


def _resume_available(*, conversation_id: str, persistence_dir: str) -> bool:
    if not conversation_id or not persistence_dir:
        return False
    return (Path(persistence_dir).expanduser() / "base_state.json").is_file()


def _compact_history_list(value: Any, *, limit: int = 20) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [_json_safe(item) for item in value[:limit]]


def _recovery_metadata(
    state: dict[str, Any],
    *,
    conversation_id: str,
    persistence_dir: str,
    workspace_path: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "conversation_id": conversation_id,
        "persistence_dir": persistence_dir,
        "workspace_path": workspace_path,
        "artifact_policy": "database stores metadata and paths; OpenHands state and artifacts stay on disk",
    }
    for key in (
        "session_id",
        "external_test",
        "external_test_history",
        "latest_review",
        "review_history",
        "review_decision",
        "integrity_report",
        "pathlab_model_registration",
    ):
        if key in state:
            metadata[key] = state.get(key)
    return metadata


def _run_history(state: dict[str, Any]) -> list[dict[str, Any]]:
    history = state.get("run_history")
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _best_experiment(
    run_history: list[dict[str, Any]],
    best_run_id: str,
) -> dict[str, Any] | None:
    if best_run_id:
        for entry in run_history:
            if str(entry.get("run_id") or "") == best_run_id:
                return _compact_run(entry)
    committed = [entry for entry in run_history if entry.get("committed")]
    if committed:
        return _compact_run(committed[-1])
    if run_history:
        return _compact_run(run_history[-1])
    return None


def _pathlab_linkage(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize links from a PathScientist run to PathLab-owned artifacts."""
    raw = entry.get("pathlab") if isinstance(entry.get("pathlab"), dict) else {}
    linkage: dict[str, Any] = {}
    for key in (
        "uploads_dir",
        "training_task_id",
        "training_dir",
        "features_dir",
        "models_dir",
        "logs_dir",
        "progress_dir",
        "model_path",
        "analysis_id",
        "dataset_id",
    ):
        value = _string_or_none(raw.get(key))
        if value:
            linkage[key] = value

    aliases = {
        "pathlab_training_task_id": "training_task_id",
        "training_task_id": "training_task_id",
        "pathlab_training_dir": "training_dir",
        "pathlab_features_dir": "features_dir",
        "pathlab_models_dir": "models_dir",
        "pathlab_logs_dir": "logs_dir",
        "pathlab_progress_dir": "progress_dir",
        "analysis_id": "analysis_id",
        "dataset_id": "dataset_id",
    }
    for source, target in aliases.items():
        value = _string_or_none(entry.get(source))
        if value and target not in linkage:
            linkage[target] = value

    for source, target in (
        ("data_output_dir", "features_dir"),
        ("model_path", "model_path"),
    ):
        value = _string_or_none(entry.get(source))
        if value and target not in linkage:
            linkage[target] = value
    return linkage


def _compact_run(entry: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "run_id": entry.get("run_id"),
        "iteration": entry.get("iteration"),
        "metric_name": entry.get("metric_name"),
        "metric_value": entry.get("metric_value"),
        "committed": entry.get("committed"),
        "metrics": entry.get("metrics"),
        "run_dir": entry.get("run_dir"),
        "model_path": entry.get("model_path"),
        "data_output_dir": entry.get("data_output_dir"),
        "quick_check": entry.get("quick_check"),
        "run_kind": entry.get("run_kind"),
        "error_type": entry.get("error_type"),
    }
    pathlab_linkage = _pathlab_linkage(entry)
    if pathlab_linkage:
        compact["pathlab_linkage"] = pathlab_linkage
    return _json_safe(compact)


def _metric_name(state: dict[str, Any]) -> str:
    objective = state.get("objective") if isinstance(state.get("objective"), dict) else {}
    return str(
        objective.get("success_metric")
        or state.get("metric_name")
        or state.get("best_metric_name")
        or "auc"
    )


def _objective_question(state: dict[str, Any]) -> str:
    objective = state.get("objective") if isinstance(state.get("objective"), dict) else {}
    return str(objective.get("question") or state.get("research_question") or "")


def _final_report(state: dict[str, Any]) -> str:
    for key in ("final_report", "report", "summary", "final_summary"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value
    ui_summary = state.get("ui_run_summary")
    if isinstance(ui_summary, dict):
        for key in ("summary", "text", "final_report"):
            value = ui_summary.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _json_safe(
    value: Any,
    *,
    max_depth: int = MAX_JSON_SAFE_DEPTH,
    byte_budget: int = MAX_JSON_SAFE_BYTES,
) -> Any:
    remaining = [max(0, int(byte_budget))]

    def _consume(text: str) -> str:
        if remaining[0] <= 0:
            return "[truncated:json_budget]"
        encoded_len = len(text.encode("utf-8", errors="ignore"))
        if encoded_len <= remaining[0]:
            remaining[0] -= encoded_len
            return text
        allowed = max(0, remaining[0])
        remaining[0] = 0
        return _truncate_text(text, allowed)

    def _walk(item: Any, depth: int) -> Any:
        if depth < 0:
            return "[truncated:max_depth]"
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if isinstance(item, str):
            return _consume(item)
        if isinstance(item, Path):
            return _consume(str(item))
        if isinstance(item, datetime):
            return _consume(item.isoformat())
        if isinstance(item, dict):
            out: dict[str, Any] = {}
            for key, child in item.items():
                if child is None:
                    continue
                safe_key = _consume(str(key))
                if safe_key == "[truncated:json_budget]":
                    out[safe_key] = safe_key
                    break
                out[safe_key] = _walk(child, depth - 1)
                if remaining[0] <= 0:
                    out["[truncated]"] = "[truncated:json_budget]"
                    break
            return out
        if isinstance(item, (list, tuple, set)):
            out_list = []
            for child in item:
                out_list.append(_walk(child, depth - 1))
                if remaining[0] <= 0:
                    out_list.append("[truncated:json_budget]")
                    break
            return out_list
        return _consume(_truncate_text(str(item), MAX_JSON_TEXT_LENGTH))

    return _walk(value, max_depth)


def _truncate_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _event_sequence(event: dict[str, Any]) -> int:
    try:
        return int(event.get("seq") or event.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nested_get(entry: dict[str, Any], key: str) -> Any:
    for container_key in ("hyperparams", "config", "metadata"):
        container = entry.get(container_key)
        if isinstance(container, dict) and key in container:
            return container.get(key)
    return None


def _loop_key(loop: asyncio.AbstractEventLoop) -> int:
    return id(loop)


def _ensure_persistence_worker(
    loop: asyncio.AbstractEventLoop,
) -> asyncio.Queue[tuple[Any, str]]:
    key = _loop_key(loop)
    queue = _persist_queues.get(key)
    if queue is None:
        queue = asyncio.Queue(maxsize=PERSISTENCE_QUEUE_MAXSIZE)
        _persist_queues[key] = queue

    worker = _persist_workers.get(key)
    if worker is None or worker.done():
        _persist_workers[key] = loop.create_task(
            _persistence_worker(queue),
            name="pathscientist-persistence-worker",
        )
    return queue


async def _persistence_worker(queue: asyncio.Queue[tuple[Any, str]]) -> None:
    while True:
        coro, action = await queue.get()
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Failed to %s: %s", action, exc)
        finally:
            queue.task_done()


def _enqueue_best_effort(coro: Any, action: str) -> None:
    assert _gateway_loop is not None
    queue = _ensure_persistence_worker(_gateway_loop)
    try:
        queue.put_nowait((coro, action))
    except asyncio.QueueFull:
        with contextlib.suppress(Exception):
            coro.close()
        logger.warning(
            "Skipped %s because PathScientist persistence queue is full",
            action,
        )


async def drain_persistence_queue(timeout: float | None = None) -> None:
    loop = asyncio.get_running_loop()
    queue = _persist_queues.get(_loop_key(loop))
    if queue is None:
        return
    if timeout is None:
        await queue.join()
        return
    await asyncio.wait_for(queue.join(), timeout=timeout)


def _run_best_effort(coro: Any, action: str) -> None:
    try:
        loop = _gateway_loop
        if loop is None or loop.is_closed():
            coro.close()
            logger.warning(
                "Skipped %s because Gateway event loop is not configured",
                action,
            )
            return

        current_loop = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if current_loop is loop:
            _enqueue_best_effort(coro, action)
            return

        future = asyncio.run_coroutine_threadsafe(
            _enqueue_best_effort_from_loop(coro, action),
            loop,
        )
        try:
            future.result(timeout=PERSISTENCE_ENQUEUE_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            future.cancel()
            with contextlib.suppress(Exception):
                coro.close()
            logger.warning("Timed out while trying to %s", action)
        except Exception as exc:
            with contextlib.suppress(Exception):
                coro.close()
            logger.warning("Failed to %s: %s", action, exc)
    except Exception as exc:
        with contextlib.suppress(Exception):
            coro.close()
        logger.warning("Failed to %s: %s", action, exc)


async def _enqueue_best_effort_from_loop(coro: Any, action: str) -> None:
    _enqueue_best_effort(coro, action)
