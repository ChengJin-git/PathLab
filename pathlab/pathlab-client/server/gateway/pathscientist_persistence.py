"""Best-effort PostgreSQL persistence for PathScientist web sessions."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import threading
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.database.database import safe_session
from backend.database.repositories.auto_research import AutoResearchRepository

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 20000
MAX_JSON_TEXT_LENGTH = 12000

_persist_lock = threading.Lock()
_gateway_loop: asyncio.AbstractEventLoop | None = None


def configure_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Register the Gateway event loop used by SQLAlchemy's async engine."""
    global _gateway_loop
    _gateway_loop = loop or asyncio.get_running_loop()


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
        "research_question": question or _objective_question(state),
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
        status = "completed" if bool(entry.get("committed")) else "failed"
        if entry.get("exit_code") == 0:
            status = "completed"
        if entry.get("error_type"):
            status = "failed"
        payloads.append({
            "session_id": session_id,
            "experiment_name": str(entry.get("name") or entry.get("label") or run_id)[:500],
            "training_task_id": run_id,
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
                "run_dir": entry.get("run_dir"),
                "model_path": entry.get("model_path"),
                "data_output_dir": entry.get("data_output_dir"),
                "artifacts": entry.get("data_output_artifacts"),
                "quick_check": entry.get("quick_check"),
                "run_kind": entry.get("run_kind"),
                "error_type": entry.get("error_type"),
            }),
            "status": status[:20],
            "metrics": _json_safe(metrics),
            "iteration": _int_or_none(entry.get("iteration")) or index,
        })
    return payloads


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("kind") or event.get("event_type") or "event")[:50]
    return {
        "event_type": event_type,
        "event_data": _json_safe(event),
    }


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


def _compact_run(entry: dict[str, Any]) -> dict[str, Any]:
    return _json_safe({
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
    })


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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    text = str(value)
    return _truncate_text(text, MAX_JSON_TEXT_LENGTH)


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
            task = loop.create_task(coro)

            def _log_failure(done: asyncio.Task[Any]) -> None:
                try:
                    done.result()
                except Exception as exc:
                    logger.warning("Failed to %s: %s", action, exc)

            task.add_done_callback(_log_failure)
            return

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            with _persist_lock:
                future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            logger.warning("Timed out while trying to %s", action)
        except Exception as exc:
            logger.warning("Failed to %s: %s", action, exc)
    except Exception as exc:
        with contextlib.suppress(Exception):
            coro.close()
        logger.warning("Failed to %s: %s", action, exc)
