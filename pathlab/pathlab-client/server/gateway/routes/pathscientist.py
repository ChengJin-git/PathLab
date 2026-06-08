"""PathScientist session API routes.

This MVP exposes a small, local-first control surface for PathScientist while
keeping the heavy OpenHands/PathScientist imports lazy. Gateway startup should
not fail just because the optional research-agent runtime is unavailable.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.5"
GATEWAY_SESSION_REGISTRY = "gateway_sessions.json"
GATEWAY_EVENT_DIR = "gateway_events"
GATEWAY_DELETED_SESSIONS = "gateway_deleted_sessions.json"
GATEWAY_DELETE_AUDIT_LOG = "gateway_delete_audit.jsonl"
LEGACY_RUNNING_STALE_SECONDS = int(os.environ.get("PATHSCIENTIST_LEGACY_RUNNING_STALE_SEC", "600"))
DEFAULT_DATASET_CACHE_DIR = "/project/llmponco/wangyihui/original_data/pathlab_test_data"
DOWNLOAD_PROGRESS_POLL_SECONDS = float(os.environ.get("PATHSCIENTIST_DOWNLOAD_PROGRESS_POLL_SEC", "1"))

router = APIRouter(prefix="/pathscientist", tags=["pathscientist"])
_REGISTRY_LOCK = threading.Lock()
_EVENT_LOG_LOCK = threading.Lock()
_DELETE_AUDIT_LOCK = threading.Lock()
_WORKSPACE_SIZE_CACHE_LOCK = threading.Lock()
_WORKSPACE_SIZE_CACHE_TTL_SECONDS = float(os.environ.get("PATHSCIENTIST_WORKSPACE_SIZE_TTL_SEC", "30"))
_WORKSPACE_SIZE_CACHE: dict[str, tuple[float, int]] = {}
_WORKSPACE_SIZE_PENDING: set[str] = set()


class StartPathScientistSessionRequest(BaseModel):
    """Request body for starting a PathScientist session."""

    question: str = Field(..., min_length=1)
    skill: str = ""
    mode: str = "research"
    max_iter: int = Field(5, ge=1, le=20)
    metric: str = "auc"
    model: str = ""
    manual_approval: bool = False
    download_policy: str | None = None
    data_paths: list[str] = Field(default_factory=list)
    external_test_enabled: bool = False
    external_test_contract: dict[str, str] = Field(default_factory=dict)


@dataclass
class SessionRecord:
    """In-memory session state for the MVP Gateway bridge."""

    session_id: str
    conversation_id: str
    question: str
    model: str
    title: str = ""
    title_pending: bool = False
    status: str = "queued"
    stage: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    state: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    cancel_requested: bool = False
    # Monotonic event sequence; ts alone can collide within the same second
    # so SSE consumers dedup by (seq, kind).
    _seq_counter: Any = field(
        default_factory=lambda: itertools.count(1), repr=False, compare=False,
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _condition: threading.Condition | None = field(
        default=None, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        self._condition = threading.Condition(self._lock)

    def add_event(self, event: dict[str, Any]) -> None:
        """Append an event under the lock + wake any SSE waiters."""
        assert self._condition is not None
        with self._condition:
            seq = next(self._seq_counter)
            payload = _normalize_gateway_event({"seq": seq, "ts": time.time(), **event})
            self.events.append(payload)
            self.updated_at = payload["ts"]
            self._condition.notify_all()
        _append_gateway_session_event(self.session_id, payload)

    def hydrate_events(self, events: list[dict[str, Any]]) -> None:
        """Restore persisted events and advance the sequence counter."""
        assert self._condition is not None
        with self._condition:
            self.events = list(events)
            max_seq = 0
            for event in self.events:
                try:
                    max_seq = max(max_seq, int(event.get("seq") or 0))
                except (TypeError, ValueError):
                    continue
            self._seq_counter = itertools.count(max_seq + 1)

    def snapshot_events(self, start_index: int) -> tuple[list[dict[str, Any]], int]:
        """Return events at/after start_index plus the new index pointer."""
        assert self._condition is not None
        with self._condition:
            new = self.events[start_index:]
            return list(new), len(self.events)

    def wait_for_events(self, current_index: int, timeout: float = 1.0) -> bool:
        """Block until a new event lands OR timeout. Returns True iff new events present."""
        assert self._condition is not None
        with self._condition:
            if len(self.events) > current_index:
                return True
            self._condition.wait(timeout=timeout)
            return len(self.events) > current_index

    def set_status(self, status: str, *, stage: str | None = None, error: str | None = None) -> None:
        assert self._condition is not None
        with self._condition:
            self.status = status
            if stage is not None:
                self.stage = stage
            if error is not None:
                self.error = error
            self.updated_at = time.time()
            self._condition.notify_all()

    def summary(self) -> dict[str, Any]:
        payload = {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "title_pending": self.title_pending,
            "question": self.question,
            "model": self.model,
            "status": self.status,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
        if isinstance(self.state, dict):
            for key in (
                "stop_reason",
                "interrupted_reason",
                "user_stop_requested",
                "stop_source",
                "stop_requested_at",
            ):
                if key in self.state:
                    payload[key] = self.state[key]
        payload.update(_workspace_usage_summary(self))
        return payload


@dataclass(frozen=True)
class LegacyRuntimeStatus:
    status: str
    stage: str
    error: str = ""


class SessionStopRequested(RuntimeError):
    """Raised inside the runner bridge when the web UI asks a session to stop."""


class SessionDeleteRejected(RuntimeError):
    """Raised when the UI tries to delete a live session."""


class PathScientistSessionManager:
    """Thread-backed PathScientist session manager for the MVP API.

    Sessions live in memory for live streaming. A small Gateway-owned registry
    is hydrated lazily after restart. The UI also gets a curated view of
    meaningful legacy PathScientist conversations while tiny failed/idle
    OpenHands stubs stay hidden.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()
        self._hydrated_registry = False
        self.create_runner: Callable[
            [Any, str, Callable[[dict[str, Any]], None]], dict[str, Any]
        ] | None = None

    def start(self, req: StartPathScientistSessionRequest) -> SessionRecord:
        config = _build_config(req)
        record = SessionRecord(
            session_id=uuid.uuid4().hex[:12],
            conversation_id="",
            question=req.question,
            model=config.llm_model or DEFAULT_MODEL,
            title="",
            title_pending=True,
        )
        with self._lock:
            self._sessions[record.session_id] = record
        _save_gateway_session_record(record)
        record.add_event({"kind": "session", "status": "queued"})
        _queue_session_title_generation(record, config)
        thread = threading.Thread(target=self._run, args=(record, req, config), daemon=True)
        thread.start()
        return record

    def stop(self, session_id: str) -> SessionRecord | None:
        record = self.get(session_id)
        if record is None:
            return None
        if record.status not in {"queued", "running"}:
            return record

        stop_requested_at = time.time()
        stop_marker = {
            "user_stop_requested": True,
            "stop_source": "pathlab_ui",
            "stop_requested_at": stop_requested_at,
        }

        cleanup_session_ids: list[str] = []
        for candidate in (
            session_id,
            str((record.state or {}).get("session_id") or "").strip()
            if isinstance(record.state, dict)
            else "",
        ):
            if candidate and candidate not in cleanup_session_ids:
                cleanup_session_ids.append(candidate)

        process_cleanup: dict[str, Any] = {
            "active_process_count": 0,
            "terminated_process_groups": [],
            "sigterm_sent": [],
            "sigkill_sent": [],
            "processes": [],
            "session_ids": list(cleanup_session_ids),
        }
        cleanup_errors: list[str] = []
        try:
            from backend.pathscientist.runtime.session_registry import (
                cancel_session_processes,
            )

            for cleanup_session_id in cleanup_session_ids:
                try:
                    cleanup = cancel_session_processes(
                        cleanup_session_id,
                        term_timeout=3.0,
                        kill_timeout=0.5,
                    )
                except Exception as exc:
                    cleanup_errors.append(f"{cleanup_session_id}: {exc}")
                    continue
                process_cleanup["active_process_count"] += int(
                    cleanup.get("active_process_count") or 0
                )
                for key in (
                    "terminated_process_groups",
                    "sigterm_sent",
                    "sigkill_sent",
                ):
                    merged = set(process_cleanup.get(key) or [])
                    merged.update(cleanup.get(key) or [])
                    process_cleanup[key] = sorted(merged)
                process_cleanup["processes"].extend(cleanup.get("processes") or [])
        except Exception as exc:
            cleanup_errors.append(str(exc))
        if cleanup_errors:
            process_cleanup["errors"] = cleanup_errors
            process_cleanup["error"] = "; ".join(cleanup_errors)

        assert record._condition is not None
        with record._condition:
            record.cancel_requested = True
            record.status = "interrupted"
            record.stage = "interrupted"
            record.error = "Stopped by user from PathLab."
            record.state = {
                **_record_state(record),
                "stage": "interrupted",
                "stop_reason": "user_cancelled",
                "interrupted_reason": record.error,
                **stop_marker,
                "process_cleanup": process_cleanup,
            }
            record.updated_at = time.time()
            record._condition.notify_all()
        _save_gateway_session_record(record)
        record.add_event({
            "kind": "state",
            "status": "interrupted",
            "stage": "interrupted",
            "state": record.state,
            "summary": record.error,
            "process_cleanup": process_cleanup,
            **stop_marker,
        })
        return record

    def delete(self, session_id: str) -> dict[str, Any] | None:
        record = self.get(session_id)
        if record is None:
            return None
        if record.status in {"queued", "running"}:
            raise SessionDeleteRejected("Stop this session before deleting it.")

        workspace_delete = _delete_session_workspace(record)
        _append_gateway_delete_audit(record, workspace_delete)
        with self._lock:
            self._sessions.pop(session_id, None)
        _remove_gateway_session_record(session_id)
        _mark_gateway_session_deleted(
            session_id=session_id,
            conversation_id=record.conversation_id,
        )
        _delete_gateway_session_events(session_id)
        return {
            "session_id": session_id,
            "conversation_id": record.conversation_id,
            "deleted": True,
            **workspace_delete,
        }

    def list(self, *, include_persisted: bool = False) -> list[SessionRecord]:
        self._maybe_hydrate_registry()
        deleted = _load_deleted_gateway_sessions()
        with self._lock:
            records = list(self._sessions.values())

        try:
            legacy_records = _scan_persisted_conversations(
                curated_only=not include_persisted,
            )
        except Exception as exc:
            logger.debug("PathScientist disk hydration skipped: %s", exc)
            legacy_records = []
        seen_session_ids = {record.session_id for record in records}
        seen_conversation_ids = {
            _record_conversation_id(record)
            for record in records
            if _record_conversation_id(record)
        }
        records.extend(
            record for record in legacy_records
            if record.session_id not in seen_session_ids
            and (
                not _record_conversation_id(record)
                or _record_conversation_id(record) not in seen_conversation_ids
            )
            and not _is_deleted_gateway_session(record, deleted)
        )

        return sorted(
            records,
            key=lambda record: record.created_at,
            reverse=True,
        )

    def get(self, session_id: str) -> SessionRecord | None:
        deleted = _load_deleted_gateway_sessions()
        with self._lock:
            record = self._sessions.get(session_id)
        if record is not None:
            return record
        self._maybe_hydrate_registry()
        with self._lock:
            record = self._sessions.get(session_id)
        if record is not None:
            return record

        # Details for curated legacy rows shown in the history list.
        for legacy in _scan_persisted_conversations(curated_only=True):
            if legacy.session_id == session_id and not _is_deleted_gateway_session(legacy, deleted):
                return _hydrate_persisted_record_detail(legacy)
        return None

    def _maybe_hydrate_registry(self) -> None:
        """Populate stub SessionRecords from the Gateway-owned registry.

        One-shot per manager instance. Safe to call repeatedly; only mutates
        when the in-memory map is missing entries that exist in the registry.
        """
        if self._hydrated_registry:
            return
        stubs = _load_gateway_session_records()
        deleted = _load_deleted_gateway_sessions()
        deleted_session_ids, _deleted_conversation_ids = deleted
        with self._lock:
            for stub in stubs:
                if stub.session_id in deleted_session_ids:
                    continue
                self._sessions.setdefault(stub.session_id, stub)
            self._hydrated_registry = True

    def _run(
        self,
        record: SessionRecord,
        req: StartPathScientistSessionRequest,
        config: Any,
    ) -> None:
        record.set_status("running", stage="starting")
        _save_gateway_session_record(record)
        record.add_event({"kind": "session", "status": "running"})
        def emit_event(event: dict[str, Any]) -> None:
            if record.cancel_requested:
                raise SessionStopRequested("Stopped by user from PathLab.")
            _apply_live_state_event_to_record(record, event)
            record.add_event(event)

        stop_download_progress_poller = _start_download_progress_poller(record)
        try:
            state = self._invoke_runner(config, req, emit_event)
            if record.cancel_requested or record.status == "interrupted":
                record.state = {
                    **_record_state(record),
                    **state,
                    "stage": "interrupted",
                    "stop_reason": "user_cancelled",
                    "interrupted_reason": record.error or "Stopped by user from PathLab.",
                }
                record.set_status(
                    "interrupted",
                    stage="interrupted",
                    error=record.error or "Stopped by user from PathLab.",
                )
                _save_gateway_session_record(record)
                record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
                return
            record.state = state
            record.conversation_id = str(state.get("conversation_id") or "")
            record.set_status("completed", stage=str(state.get("stage") or "completed"))
            _save_gateway_session_record(record)
            record.add_event({"kind": "state", "state": state})
        except SessionStopRequested as exc:
            record.state = {
                **_record_state(record),
                "stage": "interrupted",
                "stop_reason": "user_cancelled",
                "interrupted_reason": str(exc),
            }
            record.set_status("interrupted", stage="interrupted", error=str(exc))
            _save_gateway_session_record(record)
            record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
        except Exception as exc:
            if record.cancel_requested:
                record.state = {
                    **_record_state(record),
                    "stage": "interrupted",
                    "stop_reason": "user_cancelled",
                    "interrupted_reason": "Stopped by user from PathLab.",
                }
                record.set_status("interrupted", stage="interrupted", error="Stopped by user from PathLab.")
                _save_gateway_session_record(record)
                record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
                return
            record.set_status("failed", stage="failed", error=str(exc))
            _save_gateway_session_record(record)
            record.add_event({"kind": "error", "message": str(exc)})
        finally:
            stop_download_progress_poller()

    def _invoke_runner(
        self,
        config: Any,
        req: StartPathScientistSessionRequest,
        emit: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        if self.create_runner is not None:
            return self.create_runner(config, req.question, emit)

        run_research_session, dump_research_session_state = _load_runner()
        visualizer = _build_streaming_visualizer(emit)
        last_progress_signature = ""

        def emit_research_progress(state: Any) -> None:
            nonlocal last_progress_signature
            payload = state if isinstance(state, dict) else dump_research_session_state(state)
            if not isinstance(payload, dict):
                return
            payload = _enrich_state_with_download_progress(payload)
            signature = json.dumps(payload, sort_keys=True, default=str)
            if signature == last_progress_signature:
                return
            last_progress_signature = signature
            stage = str(payload.get("stage") or "").strip()
            event: dict[str, Any] = {
                "kind": "state",
                "status": "running",
                "state": payload,
            }
            if stage:
                event["stage"] = stage
                event["summary"] = f"Stage {stage}"
            emit(event)

        state, _session, _conversation = run_research_session(
            config,
            req.question,
            auto_approve=not req.manual_approval,
            visualizer=visualizer,
            progress_callback=emit_research_progress,
        )
        return _enrich_state_with_download_progress(dump_research_session_state(state))


def _build_streaming_visualizer(
    emit: Callable[[dict[str, Any]], None],
) -> Any | None:
    """Wrap OpenHands' DefaultConversationVisualizer to also forward events to ``emit``.

    Returns None when the OpenHands SDK is unavailable (tests / lazy import
    environments). The runner accepts ``visualizer=None`` so this is safe.
    """
    try:
        from openhands.sdk.conversation.visualizer import (
            ConversationVisualizerBase,
            DefaultConversationVisualizer,
        )
    except Exception:
        return None

    class _StreamingVisualizer(ConversationVisualizerBase):
        """Forward each OpenHands event to the SSE emitter + the default CLI sink."""

        def __init__(self) -> None:
            self._delegate = DefaultConversationVisualizer()
            self._iteration_counter = 0
            self._conversation_state: Any | None = None
            self._last_progress_signature = ""

        def initialize(self, state: Any) -> None:
            self._conversation_state = state
            self._delegate.initialize(state)
            self._emit_progress(force=True)

        def on_event(self, event: Any) -> None:
            try:
                payload = _project_event(event, self._iteration_counter)
                emit(payload)
                observed_iteration = _coerce_iteration(payload.get("iteration"))
                if observed_iteration is not None and observed_iteration > self._iteration_counter:
                    self._iteration_counter = observed_iteration
                if payload.get("kind") == "tool_observation" and payload.get("tool") in {
                    "ratchet_commit",
                    "ratchet_revert",
                }:
                    self._iteration_counter += 1
                self._emit_progress()
            except Exception as exc:  # never crash the runner on emit failure
                emit({"kind": "emit_error", "message": str(exc)})
            self._delegate.on_event(event)

        def create_sub_visualizer(self, agent_id: str):
            return self._delegate.create_sub_visualizer(agent_id)

        def _emit_progress(self, *, force: bool = False) -> None:
            state = _build_live_progress_state(self._conversation_state)
            if not state:
                return
            signature = json.dumps(state, sort_keys=True, default=str)
            if not force and signature == self._last_progress_signature:
                return
            self._last_progress_signature = signature
            emit({
                "kind": "state",
                "status": "running",
                "stage": state.get("stage"),
                "state": state,
            })

    return _StreamingVisualizer()


def _project_event(event: Any, iteration: int) -> dict[str, Any]:
    """Map an OpenHands SDK event to the SSE wire shape.

    Duck-typed: introspects common attributes (tool_name, action, observation)
    instead of importing the exact event classes — keeps the route resilient to
    SDK shape changes.
    """
    cls_name = event.__class__.__name__
    base: dict[str, Any] = {"kind": "agent_event", "event_class": cls_name}
    tool_name = getattr(event, "tool_name", "") or getattr(
        getattr(event, "action", None), "tool_name", "",
    )

    # ObservationEvent also carries tool_name in current OpenHands versions.
    # Check it before tool calls so live streams do not duplicate every tool as
    # two calls and leave all observations stuck in iteration 0.
    observation = getattr(event, "observation", None)
    if observation is not None:
        observation_payload = _safe_dump(observation)
        observed_iteration = None
        if isinstance(observation_payload, dict):
            observed_iteration = _coerce_iteration(observation_payload.get("iteration"))
        if observed_iteration is None:
            observed_iteration = _coerce_iteration(getattr(observation, "iteration", None))
        return {
            "kind": "tool_observation",
            "tool": str(tool_name or getattr(event, "tool_name", "") or ""),
            "iteration": observed_iteration if observed_iteration is not None else iteration,
            "exit_code": getattr(observation, "exit_code", None),
            "observation": observation_payload,
        }

    # Tool call event (e.g. ActionEvent / FunctionCallEvent in OpenHands).
    if tool_name:
        action = getattr(event, "action", None)
        return {
            "kind": "tool_call",
            "tool": str(tool_name),
            "iteration": iteration,
            "action": _safe_dump(action),
        }

    # Plain message event (UserMessageEvent / AssistantMessageEvent).
    content = getattr(event, "content", None) or getattr(event, "message", None)
    if content is not None:
        role = getattr(event, "source", "") or getattr(event, "role", "")
        return {
            "kind": "message",
            "role": str(role or "agent"),
            "text": _safe_text(content),
        }

    return base


def _safe_dump(value: Any) -> Any:
    """Best-effort JSON-friendly projection of an SDK object."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_dump(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_dump(v) for k, v in value.items()}
    # Pydantic model
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        try:
            return dumper()
        except Exception:
            pass
    # Generic dataclass / object
    for attr in ("to_dict", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    return _safe_text(value)


def _safe_text(value: Any) -> str:
    try:
        if isinstance(value, str):
            return value[:4000]
        return str(value)[:4000]
    except Exception:
        return ""


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_payload_dict(value: Any) -> dict[str, Any]:
    dumped = _safe_dump(value)
    return dumped if isinstance(dumped, dict) else {}


def _as_payload_list(value: Any) -> list[Any]:
    dumped = _safe_dump(value)
    return dumped if isinstance(dumped, list) else []


def _build_live_progress_state(conversation_state: Any) -> dict[str, Any]:
    """Project the mutable OpenHands agent_state into UI progress state."""
    if conversation_state is None:
        return {}
    if isinstance(conversation_state, dict):
        agent_state = conversation_state.get("agent_state") or conversation_state
    else:
        try:
            agent_state = getattr(conversation_state, "agent_state", {}) or {}
        except Exception:
            agent_state = {}
    if not isinstance(agent_state, dict):
        return {}

    research = _as_payload_dict(agent_state.get("research_session"))
    iteration_state = _as_payload_dict(agent_state.get("iteration_state"))
    tracker_state = _as_payload_dict(agent_state.get("tracker_state"))
    if not any((research, iteration_state, tracker_state)):
        return {}

    objective = _as_payload_dict(research.get("objective"))
    run_history = _as_payload_list(research.get("run_history"))
    if not run_history:
        run_history = _as_payload_list(tracker_state.get("history"))

    state = {
        "session_id": research.get("session_id"),
        "conversation_id": research.get("conversation_id"),
        "stage": research.get("stage"),
        "stage_started_at": research.get("stage_started_at"),
        "stage_history": _as_payload_list(research.get("stage_history")),
        "objective": objective,
        "iteration_index": _first_present(
            research.get("iteration_index"),
            iteration_state.get("iteration_index"),
            tracker_state.get("iteration"),
        ),
        "max_iterations": _first_present(
            research.get("max_iterations"),
            iteration_state.get("max_iterations"),
        ),
        "best_metric_value": _first_present(
            research.get("best_metric_value"),
            tracker_state.get("best_value"),
        ),
        "best_run_id": _first_present(
            research.get("best_run_id"),
            tracker_state.get("best_run_id"),
            iteration_state.get("last_run_id"),
        ),
        "run_history": run_history,
        "task_profile": _as_payload_dict(research.get("task_profile")),
        "dataset_candidates": _as_payload_list(research.get("dataset_candidates")),
        "selected_dataset": _as_payload_dict(research.get("selected_dataset")),
        "dataset_manifest_path": research.get("dataset_manifest_path"),
        "acquisition_status": research.get("acquisition_status"),
        "acquisition_notes": research.get("acquisition_notes"),
        "data_readiness": _as_payload_dict(research.get("data_readiness")),
        "execution_plan": _as_payload_dict(research.get("execution_plan")),
        "grounding": _as_payload_dict(research.get("grounding")),
        "ui_run_summary": _as_payload_dict(research.get("ui_run_summary")),
        "latest_review": _as_payload_dict(research.get("latest_review")),
        "review_history": _as_payload_list(research.get("review_history")),
        "review_decision": research.get("review_decision"),
    }
    return {key: value for key, value in state.items() if value not in (None, "", [], {})}


def _apply_live_state_event_to_record(record: SessionRecord, event: dict[str, Any]) -> None:
    """Keep the session list/detail stage in sync with streaming state events."""
    if event.get("kind") != "state" or not isinstance(event.get("state"), dict):
        return
    state = dict(event["state"])
    stage = str(state.get("stage") or event.get("stage") or "").strip()
    conversation_id = str(state.get("conversation_id") or "").strip()
    should_persist = False
    assert record._condition is not None
    with record._condition:
        record.state = {**_record_state(record), **state}
        if stage and record.status in {"queued", "running"}:
            record.stage = stage
        if conversation_id and not record.conversation_id:
            record.conversation_id = conversation_id
            should_persist = True
    if should_persist:
        _save_gateway_session_record(record)


def _resolve_workspace_from_state(state: dict[str, Any]) -> Path | None:
    """Resolve a PathScientist workspace from serialized research state."""
    candidates: list[Any] = [
        state.get("workspace_dir"),
        state.get("workspace_root"),
    ]
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        research_session = summary.get("research_session")
        candidates.extend([
            summary.get("workspace_dir"),
            research_session.get("workspace_dir")
            if isinstance(research_session, dict)
            else "",
        ])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(str(candidate)).expanduser()
        except (TypeError, ValueError):
            continue
        if path.is_dir():
            return path.resolve()

    internal_session_id = str(state.get("session_id") or "").strip()
    if internal_session_id:
        path = _resolve_pathscientist_base_dir() / f"session_{internal_session_id}"
        if path.is_dir():
            return path.resolve()
    return None


def _load_download_progress_for_state(state: dict[str, Any]) -> dict[str, Any]:
    workspace = _resolve_workspace_from_state(state)
    if workspace is None:
        return {}
    path = workspace / ".dataset" / "download_progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _enrich_state_with_download_progress(state: dict[str, Any]) -> dict[str, Any]:
    progress = _load_download_progress_for_state(state)
    if not progress:
        return dict(state)
    return {**state, "download_progress": progress}


def _start_download_progress_poller(record: SessionRecord) -> Callable[[], None]:
    """Emit progress sidecar changes while acquisition is blocked in a provider."""
    stop_event = threading.Event()

    def snapshot_state() -> tuple[dict[str, Any], str, str]:
        assert record._condition is not None
        with record._condition:
            return dict(_record_state(record)), record.status, record.stage

    def loop() -> None:
        last_signature = ""
        interval = max(0.1, DOWNLOAD_PROGRESS_POLL_SECONDS)
        while not stop_event.wait(interval):
            state, status, stage = snapshot_state()
            if status not in {"queued", "running"}:
                break
            progress = _load_download_progress_for_state(state)
            if not progress:
                continue
            signature = json.dumps(progress, sort_keys=True, default=str)
            if signature == last_signature:
                continue
            last_signature = signature
            enriched = {**state, "download_progress": progress}
            event_stage = str(enriched.get("stage") or stage or "acquisition")
            assert record._condition is not None
            with record._condition:
                record.state = enriched
            record.add_event({
                "kind": "state",
                "status": "running",
                "stage": event_stage,
                "state": enriched,
                "summary": "Download progress",
            })

    thread = threading.Thread(
        target=loop,
        name=f"pathscientist-download-progress-{record.session_id}",
        daemon=True,
    )
    thread.start()

    def stop() -> None:
        stop_event.set()
        thread.join(timeout=1.0)

    return stop


def _record_conversation_id(record: SessionRecord) -> str:
    if record.conversation_id:
        return record.conversation_id
    state = _record_state(record)
    return str(state.get("conversation_id") or "").strip()


def _coerce_iteration(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_stage(event: dict[str, Any]) -> str:
    stage = str(event.get("stage") or "").strip()
    if stage:
        return stage
    state = event.get("state")
    if isinstance(state, dict) and state.get("stage"):
        return str(state.get("stage"))
    if str(event.get("kind") or "").startswith("tool_"):
        return "execution"
    return ""


def _event_severity(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "")
    status = str(event.get("status") or "")
    if kind in {"error", "emit_error"} or status == "failed":
        return "error"
    exit_code = event.get("exit_code")
    if exit_code not in (None, "", 0, "0"):
        return "error"
    if kind == "state" and status in {"completed", "finished"}:
        return "success"
    return "info"


def _event_ui_kind(kind: str) -> str:
    if kind in {"heartbeat", "agent_event"}:
        return "internal"
    if kind.startswith("tool_"):
        return "tool"
    if kind.startswith("stage_"):
        return "stage"
    if kind.startswith("iteration_"):
        return "iteration"
    if kind in {"metric_update", "ratchet_commit", "ratchet_revert"}:
        return "metric"
    if kind in {"session", "state"}:
        return "status"
    if kind == "message":
        return "message"
    if kind in {"error", "emit_error"}:
        return "error"
    return "event"


def _terminal_status_from_stage(stage: str) -> str:
    normalized = str(stage or "").strip()
    if normalized == "finished":
        return "completed"
    if normalized in {"completed", "failed", "interrupted"}:
        return normalized
    return ""


def _event_summary(event: dict[str, Any]) -> str:
    if event.get("summary"):
        return _safe_text(event.get("summary"))
    kind = str(event.get("kind") or "")
    tool = str(event.get("tool") or "").strip()
    if kind == "tool_call":
        return tool or "Tool call"
    if kind == "tool_observation":
        suffix = "failed" if _event_severity(event) == "error" else "finished"
        return f"{tool or 'Tool'} {suffix}"
    if kind == "session":
        status = str(event.get("status") or "").strip()
        return f"Session {status}" if status else "Session update"
    if kind == "state":
        status = str(event.get("status") or "").strip()
        if status in {"completed", "finished"}:
            return "Session completed"
        state = event.get("state")
        if isinstance(state, dict) and state.get("stage"):
            return f"Stage {state.get('stage')}"
        return "State update"
    if kind == "message":
        return _safe_text(event.get("text") or event.get("message") or "Message")
    if kind in {"error", "emit_error"}:
        return _safe_text(event.get("message") or "Error")
    if kind == "heartbeat":
        return "Heartbeat"
    return kind or "Event"


def _normalize_gateway_event(event: dict[str, Any]) -> dict[str, Any]:
    """Attach stable UI projection fields used by the execution console."""
    normalized = dict(event)
    kind = str(normalized.get("kind") or "event")
    normalized["kind"] = kind
    iteration = _coerce_iteration(normalized.get("iteration"))
    if iteration is not None:
        normalized["iteration"] = iteration
    elif "iteration" in normalized:
        normalized.pop("iteration", None)
    stage = _event_stage(normalized)
    if stage:
        normalized["stage"] = stage
    if kind == "state" and not normalized.get("status"):
        terminal_status = _terminal_status_from_stage(stage)
        if terminal_status:
            normalized["status"] = terminal_status
    normalized["ui_kind"] = str(normalized.get("ui_kind") or _event_ui_kind(kind))
    normalized["severity"] = str(normalized.get("severity") or _event_severity(normalized))
    normalized["summary"] = _event_summary(normalized)
    return normalized


def _clean_session_title(value: str, *, max_length: int = 72) -> str:
    """Normalize an LLM title into a single compact UI label."""
    title = " ".join(str(value or "").replace("\n", " ").split())
    title = title.strip(" \t\r\n\"'`*_#:-–—.,;:!?，。；：！？")
    if not title:
        return ""
    if len(title) <= max_length:
        return title
    clipped = title[:max_length].rstrip()
    for sep in (" ", "/", "-", "—", "–", ":"):
        idx = clipped.rfind(sep)
        if idx >= 24:
            clipped = clipped[:idx].rstrip()
            break
    return clipped.rstrip(".,;:!?，。；：！？") or title[:max_length].rstrip()


def _fallback_session_title(question: str) -> str:
    """Deterministic fallback when the title LLM is unavailable."""
    text = " ".join(str(question or "").split())
    if not text:
        return "PathScientist session"

    lower = text.lower()
    parts: list[str] = []
    for keyword, label in (
        ("tcga", "TCGA"),
        ("nsclc", "NSCLC"),
        ("luad", "LUAD"),
        ("lusc", "LUSC"),
        ("gdc", "GDC"),
        ("chronic gastritis", "Chronic gastritis"),
        ("gastritis", "Gastritis"),
        ("gleason", "Gleason"),
        ("isup", "ISUP"),
        ("crc-msi", "CRC-MSI"),
        ("msi", "MSI"),
        ("survival", "Survival"),
        ("feature extraction", "Feature extraction"),
        ("wsi", "WSI"),
        ("mil", "MIL"),
        ("patch", "Patch"),
        ("grading", "grading"),
        ("classification", "classification"),
    ):
        if label == "Gastritis" and "Chronic gastritis" in parts:
            continue
        if keyword in lower and label not in parts:
            parts.append(label)
    if any(keyword in lower for keyword in ("data acquisition", "download", "metadata", "检索", "下载", "整理", "获取")):
        if "data acquisition" not in parts:
            parts.append("data acquisition")

    if parts:
        return _clean_session_title(" ".join(parts))
    return _clean_session_title(text)


def _generate_session_title(question: str, config: Any | None = None) -> str:
    """Generate a concise session title with gpt-5.5."""
    try:
        from openhands.sdk.llm import Message, TextContent
        from backend.pathscientist.llm_client import (
            build_chat_llm,
            extract_text,
            invoke_chat_llm,
            make_llm_config,
        )

        llm_config = make_llm_config(config=config, llm_model=DEFAULT_MODEL)
        llm = build_chat_llm(
            llm_config,
            component="PathScientist session title",
            usage_id="pathscientist_session_title",
            temperature=0.0,
        )
        prompt = (
            "Summarize this computational pathology research request as a concise UI title.\n"
            "Return ONLY the title, no quotes, no markdown, no trailing period.\n"
            "Use English if the request mixes English technical terms; keep domain terms.\n"
            "Limit to 3-8 words and at most 72 characters.\n\n"
            f"Request:\n{question}"
        )
        response = invoke_chat_llm(
            llm,
            messages=[Message(role="user", content=[TextContent(text=prompt)])],
            wire_api="completion",
        )
        return _clean_session_title(extract_text(response))
    except Exception as exc:
        logger.debug("PathScientist session title LLM failed: %s", exc)
        return ""


def _refresh_session_title(record: SessionRecord, config: Any | None = None) -> None:
    """Refresh a session title off the create-session request path."""
    try:
        title = _generate_session_title(record.question, config)
    except Exception as exc:
        logger.debug("PathScientist async title generation skipped: %s", exc)
        title = ""
    title = _clean_session_title(title)
    if title == record.title and not record.title_pending:
        return
    assert record._condition is not None
    with record._condition:
        record.title = title
        record.title_pending = False
        record.updated_at = time.time()
        record._condition.notify_all()
    _save_gateway_session_record(record)
    record.add_event({
        "kind": "session_title",
        "title": title,
        "title_pending": False,
        "summary": f"Title generated: {title}" if title else "Title generation unavailable",
    })


def _queue_session_title_generation(record: SessionRecord, config: Any | None = None) -> None:
    """Start best-effort LLM title generation without blocking session creation."""
    thread = threading.Thread(
        target=_refresh_session_title,
        args=(record, config),
        name=f"pathscientist-title-{record.session_id}",
        daemon=True,
    )
    thread.start()


def _resolve_pathscientist_base_dir() -> Path:
    """Resolve the PathScientist base dir without importing heavy runtime pieces."""
    try:
        from backend.pathscientist.runtime.session import _resolve_base_dir

        return Path(_resolve_base_dir()).expanduser().resolve()
    except Exception:
        return Path(
            os.environ.get(
                "PATHSCIENTIST_BASE_DIR",
                "/project/vcompath/storage/ywangrm/tmp/pathscientist",
            )
        ).expanduser().resolve()


def _gateway_session_registry_path() -> Path:
    base_dir = _resolve_pathscientist_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / GATEWAY_SESSION_REGISTRY


def _gateway_deleted_sessions_path() -> Path:
    return _gateway_session_registry_path().parent / GATEWAY_DELETED_SESSIONS


def _gateway_delete_audit_log_path() -> Path:
    return _gateway_session_registry_path().parent / GATEWAY_DELETE_AUDIT_LOG


def _safe_session_filename(session_id: str) -> str:
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"-", "_"})
    return (safe[:128] or "unknown") + ".jsonl"


def _gateway_event_log_path(session_id: str) -> Path:
    event_dir = _gateway_session_registry_path().parent / GATEWAY_EVENT_DIR
    event_dir.mkdir(parents=True, exist_ok=True)
    return event_dir / _safe_session_filename(session_id)


def _append_gateway_session_event(session_id: str, event: dict[str, Any]) -> None:
    """Append one projected Gateway SSE event to the per-session JSONL log."""
    try:
        path = _gateway_event_log_path(session_id)
        line = json.dumps(event, ensure_ascii=False, default=str)
        with _EVENT_LOG_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.debug("PathScientist event persistence skipped: %s", exc)


def _load_gateway_session_events(session_id: str) -> list[dict[str, Any]]:
    """Load persisted Gateway SSE events for one session."""
    path = _gateway_event_log_path(session_id)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                events.append(payload)
    except Exception as exc:
        logger.debug("PathScientist event log unreadable for %s: %s", session_id, exc)
        return []
    return events


def _delete_gateway_session_events(session_id: str) -> None:
    try:
        _gateway_event_log_path(session_id).unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("PathScientist event log delete skipped for %s: %s", session_id, exc)


def _registry_payload(record: SessionRecord) -> dict[str, Any]:
    return {
        **record.summary(),
        "source": "pathlab-gateway",
        "state": record.state,
    }


def _load_gateway_session_records() -> list[SessionRecord]:
    """Load only sessions previously created through the Gateway UI/API."""
    path = _gateway_session_registry_path()
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("PathScientist gateway session registry unreadable: %s", exc)
        return []

    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []

    records: list[SessionRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "")
        if not session_id:
            continue
        status = str(item.get("status") or "completed")
        stage = str(item.get("stage") or status)
        error = str(item.get("error") or "")
        if status in {"queued", "running"}:
            status = "interrupted"
            stage = "interrupted"
            error = error or "Gateway restarted before this session reached a final state."
        try:
            created_at = float(item.get("created_at") or time.time())
        except (TypeError, ValueError):
            created_at = time.time()
        try:
            updated_at = float(item.get("updated_at") or created_at)
        except (TypeError, ValueError):
            updated_at = created_at
        record = SessionRecord(
            session_id=session_id,
            conversation_id=str(item.get("conversation_id") or ""),
            question=str(item.get("question") or "(PathScientist session)")[:280],
            model=str(item.get("model") or ""),
            title=str(item.get("title") or ""),
            title_pending=bool(item.get("title_pending")),
            status=status,
            stage=stage,
            created_at=created_at,
            updated_at=updated_at,
            error=error,
            state=item.get("state") if isinstance(item.get("state"), dict) else {},
        )
        events = _load_gateway_session_events(session_id)
        record.hydrate_events(events)
        for event in events:
            _apply_live_state_event_to_record(record, event)
        records.append(record)
    return records


def _load_deleted_gateway_sessions() -> tuple[set[str], set[str]]:
    path = _gateway_deleted_sessions_path()
    if not path.exists():
        return set(), set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("PathScientist deleted-session registry unreadable: %s", exc)
        return set(), set()
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return set(), set()
    session_ids: set[str] = set()
    conversation_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "").strip()
        conversation_id = str(item.get("conversation_id") or "").strip()
        if session_id:
            session_ids.add(session_id)
        if conversation_id:
            conversation_ids.add(conversation_id)
    return session_ids, conversation_ids


def _is_deleted_gateway_session(
    record: SessionRecord,
    deleted: tuple[set[str], set[str]] | None = None,
) -> bool:
    session_ids, conversation_ids = deleted or _load_deleted_gateway_sessions()
    return record.session_id in session_ids or (
        bool(record.conversation_id) and record.conversation_id in conversation_ids
    )


def _append_gateway_delete_audit(record: SessionRecord, workspace_delete: dict[str, Any]) -> None:
    """Append an audit line for UI-triggered session/workspace deletion."""
    payload = {
        "ts": time.time(),
        "action": "delete_session",
        "source": "pathlab_ui",
        "session_id": record.session_id,
        "conversation_id": record.conversation_id,
        "title": record.title,
        "status_before_delete": record.status,
        "stage_before_delete": record.stage,
        "workspace_path": workspace_delete.get("workspace_path", ""),
        "workspace_deleted": bool(workspace_delete.get("workspace_deleted")),
        "workspace_delete_reason": workspace_delete.get("workspace_delete_reason", ""),
    }
    try:
        path = _gateway_delete_audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _DELETE_AUDIT_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.debug("PathScientist delete audit skipped for %s: %s", record.session_id, exc)


def _delete_session_workspace(record: SessionRecord) -> dict[str, Any]:
    workspace = _resolve_session_workspace(record)
    if workspace is None:
        return {
            "workspace_deleted": False,
            "workspace_path": "",
            "workspace_delete_reason": "No workspace found for this session.",
        }

    workspace = workspace.resolve(strict=False)
    base_dir = _resolve_pathscientist_base_dir().resolve(strict=False)
    payload: dict[str, Any] = {
        "workspace_deleted": False,
        "workspace_path": str(workspace),
    }
    if workspace == base_dir or not workspace.is_relative_to(base_dir):
        payload["workspace_delete_reason"] = "Workspace is outside PathScientist base dir; skipped for safety."
        return payload
    if workspace.name in {GATEWAY_EVENT_DIR, ".conversations", "conversations"}:
        payload["workspace_delete_reason"] = "Workspace path looks like a shared PathScientist directory; skipped for safety."
        return payload

    try:
        shutil.rmtree(workspace)
    except FileNotFoundError:
        payload["workspace_deleted"] = True
        payload["workspace_delete_reason"] = "Workspace was already absent."
    except Exception as exc:
        payload["workspace_delete_reason"] = f"Workspace delete failed: {exc}"
        logger.debug("PathScientist workspace delete failed for %s: %s", workspace, exc)
    else:
        payload["workspace_deleted"] = True
        payload["workspace_delete_reason"] = ""

    with _WORKSPACE_SIZE_CACHE_LOCK:
        _WORKSPACE_SIZE_CACHE.pop(str(workspace), None)
        _WORKSPACE_SIZE_PENDING.discard(str(workspace))
    return payload


def _mark_gateway_session_deleted(*, session_id: str, conversation_id: str = "") -> None:
    path = _gateway_deleted_sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _REGISTRY_LOCK:
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("items", payload) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    existing = [item for item in items if isinstance(item, dict)]
            except Exception as exc:
                logger.debug("PathScientist deleted-session registry reset: %s", exc)

        by_session_id = {
            str(item.get("session_id")): item
            for item in existing
            if item.get("session_id")
        }
        by_session_id[session_id] = {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "deleted_at": time.time(),
        }
        items = sorted(
            by_session_id.values(),
            key=lambda item: float(item.get("deleted_at") or 0),
            reverse=True,
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)


def _remove_gateway_session_record(session_id: str) -> None:
    path = _gateway_session_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _REGISTRY_LOCK:
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("items", payload) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    existing = [item for item in items if isinstance(item, dict)]
            except Exception as exc:
                logger.debug("PathScientist gateway session registry reset: %s", exc)
        items = [
            item for item in existing
            if str(item.get("session_id") or "") != session_id
        ]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)


def _save_gateway_session_record(record: SessionRecord) -> None:
    """Persist the compact session registry used by the web UI history list."""
    path = _gateway_session_registry_path()
    with _REGISTRY_LOCK:
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("items", payload) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    existing = [item for item in items if isinstance(item, dict)]
            except Exception as exc:
                logger.debug("PathScientist gateway session registry reset: %s", exc)

        by_session_id = {
            str(item.get("session_id")): item
            for item in existing
            if item.get("session_id")
        }
        by_session_id[record.session_id] = _registry_payload(record)
        items = sorted(
            by_session_id.values(),
            key=lambda item: float(item.get("created_at") or 0),
            reverse=True,
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)


def _is_curated_persisted_summary(summary: dict[str, Any]) -> bool:
    """Return True for legacy runs that are useful enough for default history."""
    status = str(summary.get("execution_status") or "").lower()
    try:
        event_count = int(summary.get("event_count") or 0)
    except (TypeError, ValueError):
        event_count = 0

    if status == "finished":
        return event_count > 20
    if status == "running":
        # A restarted Gateway can see stale "running" conversations; require
        # enough events to avoid showing empty boot stubs.
        return event_count >= 6
    return False


def _timestamp_to_epoch(value: Any, *, fallback: float | None = None) -> float:
    """Parse persisted OpenHands timestamps into epoch seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value or "").strip()
        if text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    return float(fallback if fallback is not None else time.time())


def _timestamp_to_epoch_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return _timestamp_to_epoch(value)
    except Exception:
        return None


def _legacy_runtime_status(summary: dict[str, Any], *, now: float | None = None) -> LegacyRuntimeStatus:
    """Normalize disk-only conversation status for the web history.

    Persisted OpenHands conversations can remain marked ``running`` after the
    user kills the agent process. Without a live Gateway thread we use the last
    event timestamp as the source of truth and mark stale runs interrupted.
    """
    status = str(summary.get("execution_status") or "completed").strip().lower()
    stage = status or "completed"
    if status != "running":
        return LegacyRuntimeStatus(status=status or "completed", stage=stage)

    timestamp = _timestamp_to_epoch_or_none(summary.get("updated_at") or summary.get("started_at"))
    now = time.time() if now is None else now
    if timestamp is None:
        return LegacyRuntimeStatus(
            status="interrupted",
            stage="interrupted",
            error="No persisted updates were recorded; this run is not attached to a live Gateway process.",
        )

    age_seconds = max(0.0, now - timestamp)
    if age_seconds > LEGACY_RUNNING_STALE_SECONDS:
        return LegacyRuntimeStatus(
            status="interrupted",
            stage="interrupted",
            error="No persisted updates; this run was likely stopped outside the web Gateway.",
        )
    return LegacyRuntimeStatus(status="running", stage="running")


def _first_content_text(content: Any) -> str:
    if isinstance(content, str):
        return _safe_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(_safe_text(item.get("text")))
            elif isinstance(item, str):
                parts.append(_safe_text(item))
        return "\n".join(part for part in parts if part)[:4000]
    return _safe_text(content) if content else ""


def _compact_persisted_observation(observation: Any) -> dict[str, Any]:
    """Keep replay payloads readable; don't send giant file lists to the UI."""
    if not isinstance(observation, dict):
        return {"text": _safe_text(observation)}
    compact: dict[str, Any] = {
        "kind": observation.get("kind"),
        "is_error": observation.get("is_error"),
        "exit_code": observation.get("exit_code"),
        "metrics": observation.get("metrics"),
        "duration": observation.get("duration"),
        "commit_hash": observation.get("commit_hash"),
        "reverted_to": observation.get("reverted_to"),
        "best_metric": observation.get("best_metric"),
        "best_metric_name": observation.get("best_metric_name"),
        "iteration": observation.get("iteration"),
        "history": observation.get("history"),
        "text": _first_content_text(observation.get("content")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [])}


def _project_persisted_openhands_event(
    raw: dict[str, Any],
    *,
    iteration: int | None,
) -> dict[str, Any] | None:
    """Project a persisted OpenHands JSON event into the Gateway event schema."""
    kind = str(raw.get("kind") or "")
    tool_name = str(raw.get("tool_name") or "").strip()
    base = {
        "source": raw.get("source"),
        "event_class": kind,
        "raw_event_id": raw.get("id"),
    }

    if kind == "ActionEvent" and tool_name:
        payload: dict[str, Any] = {
            **base,
            "kind": "tool_call",
            "tool": tool_name,
            "summary": _safe_text(raw.get("summary") or tool_name),
            "action": _safe_dump(raw.get("action")),
        }
        if iteration is not None:
            payload["iteration"] = iteration
        return payload

    if kind == "ObservationEvent" and tool_name:
        observation = raw.get("observation")
        compact = _compact_persisted_observation(observation)
        payload = {
            **base,
            "kind": "tool_observation",
            "tool": tool_name,
            "exit_code": compact.get("exit_code"),
            "observation": compact,
        }
        if raw.get("summary"):
            payload["summary"] = _safe_text(raw.get("summary"))
        observed_iteration = _coerce_iteration(compact.get("iteration"))
        if observed_iteration is not None:
            payload["iteration"] = observed_iteration
        elif iteration is not None:
            payload["iteration"] = iteration
        return payload

    if kind == "MessageEvent":
        llm_message = raw.get("llm_message")
        message = llm_message if isinstance(llm_message, dict) else {}
        return {
            **base,
            "kind": "message",
            "role": str(message.get("role") or raw.get("source") or "agent"),
            "text": _first_content_text(message.get("content")),
        }

    if kind == "SystemPromptEvent":
        return {
            **base,
            "kind": "message",
            "role": "system",
            "text": "PathScientist system prompt initialized",
        }

    if kind:
        return {**base, "kind": "agent_event", "summary": kind}
    return None


def _load_persisted_conversation_events(
    conversation_dir: Path,
    *,
    start_seq: int = 1,
) -> list[dict[str, Any]]:
    """Load legacy OpenHands events as normalized Gateway replay events."""
    events_dir = conversation_dir / "events"
    if not events_dir.is_dir():
        return []

    events: list[dict[str, Any]] = []
    iteration = 0
    for raw_path in sorted(events_dir.glob("event-*.json")):
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("PathScientist legacy event unreadable %s: %s", raw_path, exc)
            continue
        if not isinstance(raw, dict):
            continue

        projected = _project_persisted_openhands_event(raw, iteration=iteration)
        if projected is None:
            continue
        seq = start_seq + len(events)
        event = _normalize_gateway_event(
            {
                "seq": seq,
                "ts": _timestamp_to_epoch(raw.get("timestamp")),
                **projected,
            }
        )
        events.append(event)

        observation = raw.get("observation")
        if isinstance(observation, dict):
            observed_iteration = _coerce_iteration(observation.get("iteration"))
            if observed_iteration is not None:
                iteration = observed_iteration
            if raw.get("tool_name") in {"ratchet_commit", "ratchet_revert"}:
                # The next experiment belongs to the next ratcheted attempt.
                iteration += 1

    return events


def _has_persisted_stage_context(summary: dict[str, Any]) -> bool:
    return any(
        summary.get(key)
        for key in (
            "research_question",
            "research_summary",
            "event_count",
            "tracker_state",
            "iteration_state",
        )
    )


def _format_metric_value(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number >= 10:
        return f"{number:.2f}"
    return f"{number:.4f}"


def _load_research_session_from_conversation_dir(conversation_dir: Path) -> dict[str, Any]:
    """Read the rich research_session payload stored in legacy base_state.json."""
    try:
        payload = json.loads((conversation_dir / "base_state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    agent_state = payload.get("agent_state")
    if not isinstance(agent_state, dict):
        return {}
    research_session = agent_state.get("research_session")
    return research_session if isinstance(research_session, dict) else {}


def _enrich_persisted_summary(
    summary: dict[str, Any],
    conversation_dir: Path,
) -> dict[str, Any]:
    """Merge detail-only persisted state into the compact history summary."""
    research_session = _load_research_session_from_conversation_dir(conversation_dir)
    if not research_session:
        return summary
    enriched = dict(summary)
    enriched.setdefault("research_session", research_session)
    objective = research_session.get("objective")
    if isinstance(objective, dict) and objective.get("question"):
        enriched.setdefault("research_question", objective.get("question"))
    grounding = research_session.get("grounding")
    if isinstance(grounding, dict):
        enriched.setdefault("grounding", grounding)
    return enriched


def _read_nested_dict(container: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = container
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _display_token(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


def _display_sota_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"cache_negative", "miss", "no_dataset_hint", "no_dataset"}:
        return "no SOTA target found"
    if normalized == "disabled":
        return "SOTA lookup disabled"
    if normalized == "error":
        return "SOTA lookup error"
    if normalized in {"cache_hit", "pwc_hit", "fulltext_llm_hit", "local_store_hit", "openalex_llm_hit"}:
        return "SOTA target found"
    return f"SOTA status {status}" if status else ""


def _build_grounding_stage_summary(summary: dict[str, Any], metric_name: str) -> str:
    """Describe what grounding decided, not the final execution result."""
    research_session = _read_nested_dict(summary, "research_session")
    objective = _read_nested_dict(research_session, "objective")
    grounding = (
        _read_nested_dict(research_session, "grounding")
        or _read_nested_dict(summary, "grounding")
    )
    profile = _read_nested_dict(grounding, "task_profile")

    selected_skill = str(grounding.get("selected_skill") or "").strip()
    task_type = str(profile.get("task_type") or "").strip()
    asset_level = str(profile.get("asset_level") or "").strip()
    prediction_target = _display_token(profile.get("prediction_target"))
    dataset = str(
        objective.get("dataset_hint")
        or grounding.get("dataset_hint_inferred")
        or grounding.get("sota_dataset_used")
        or ""
    ).strip()
    sota_status = str(grounding.get("sota_lookup_status") or "").strip()
    sota_text = _display_sota_status(sota_status)
    target_payload = grounding.get("sota_target")
    target = target_payload if isinstance(target_payload, dict) else {}
    target_value = _format_metric_value(target.get("metric_value"))

    routed = selected_skill or task_type
    if routed:
        scope_bits = []
        if asset_level:
            scope_bits.append(f"{asset_level}-level")
        if prediction_target:
            scope_bits.append(prediction_target)
        elif task_type and task_type != routed:
            scope_bits.append(_display_token(task_type))
        scope = " ".join(scope_bits)
        dataset_text = f" on {dataset}" if dataset else ""
        target_text = (
            f"; SOTA target {metric_name}={target_value}"
            if target_value
            else f"; {sota_text}" if sota_text else ""
        )
        return f"Routed to {routed}{f' for {scope}' if scope else ''}{dataset_text}{target_text}."

    return f"Objective grounded for {metric_name} evaluation."


def _build_persisted_stage_events(
    summary: dict[str, Any],
    *,
    start_seq: int = 1,
) -> list[dict[str, Any]]:
    """Synthesize stage breadcrumbs for legacy OpenHands-only event logs.

    Older PathScientist runs persisted detailed OpenHands execution events but
    not the orchestrator's high-level intake/grounding/acquisition milestones.
    The UI stage cards need one normalized event per non-execution milestone.
    """
    if not _has_persisted_stage_context(summary):
        return []

    tracker_state = summary.get("tracker_state")
    if not isinstance(tracker_state, dict):
        tracker_state = {}
    iteration_state = summary.get("iteration_state")
    if not isinstance(iteration_state, dict):
        iteration_state = {}

    question = " ".join(str(summary.get("research_question") or "").split())
    event_count = summary.get("event_count") or 0
    metric_name = str(tracker_state.get("primary_metric") or "metric")
    best_value = _format_metric_value(tracker_state.get("best_value"))
    iteration_index = iteration_state.get("iteration_index") or tracker_state.get("iteration")
    max_iterations = iteration_state.get("max_iterations")
    status = str(summary.get("execution_status") or "completed")
    has_summary = bool(str(summary.get("research_summary") or "").strip())
    grounding_summary = _build_grounding_stage_summary(summary, metric_name)

    metric_summary = (
        f"best {metric_name}={best_value}"
        if best_value
        else f"primary metric: {metric_name}"
    )
    iteration_summary = (
        f"{iteration_index}/{max_iterations} iterations"
        if iteration_index and max_iterations
        else f"{iteration_index} iterations"
        if iteration_index
        else "iteration budget prepared"
    )
    stage_summaries = [
        (
            "intake",
            f"Research request captured: {question[:140]}"
            if question
            else "Research request captured.",
        ),
        ("grounding", grounding_summary),
        (
            "acquisition",
            "Dataset and feature inputs prepared before execution.",
        ),
        ("pre_execution_ready", f"Execution contract ready: {iteration_summary}."),
        ("review", f"Reviewed execution history; {metric_summary}."),
        (
            "synthesis",
            "Session summary generated."
            if has_summary
            else "Synthesis reached from persisted run state.",
        ),
        (
            "completed",
            f"Legacy run marked {status}; {event_count} persisted OpenHands events available.",
        ),
    ]

    started_ts = _timestamp_to_epoch(summary.get("started_at"), fallback=time.time())
    updated_ts = _timestamp_to_epoch(summary.get("updated_at"), fallback=started_ts)
    span = max(1.0, updated_ts - started_ts)

    events: list[dict[str, Any]] = []
    for index, (stage, text) in enumerate(stage_summaries):
        ts = started_ts + (span * index / max(1, len(stage_summaries) - 1))
        event = _normalize_gateway_event(
            {
                "seq": start_seq + len(events),
                "ts": ts,
                "kind": "stage_summary",
                "stage": stage,
                "source": "persisted_summary",
                "summary": text,
            }
        )
        events.append(event)
    return events


def _metric_value_from_history_entry(
    entry: dict[str, Any],
    metric_name: str,
) -> float | None:
    metrics = entry.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(metric_name)
    if value is None and metric_name == "auc":
        value = metrics.get("AUC")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_persisted_session_state(summary: dict[str, Any]) -> dict[str, Any]:
    """Project legacy history summaries into the state shape the UI expects."""
    research_session = summary.get("research_session")
    if not isinstance(research_session, dict):
        research_session = {}
    tracker_state = summary.get("tracker_state")
    if not isinstance(tracker_state, dict):
        tracker_state = {}
    iteration_state = summary.get("iteration_state")
    if not isinstance(iteration_state, dict):
        iteration_state = {}
    metric_name = str(tracker_state.get("primary_metric") or "metric")
    history = tracker_state.get("history")
    if not isinstance(history, list):
        history = iteration_state.get("history") if isinstance(iteration_state.get("history"), list) else []

    run_history: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        metric_value = _metric_value_from_history_entry(item, metric_name)
        run_history.append(
            {
                "iteration": item.get("iteration"),
                "metric_name": metric_name,
                "metric_value": metric_value,
                "committed": bool(item.get("committed")),
                "run_id": item.get("run_id") or "",
                "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
            }
        )

    execution_status = str(summary.get("execution_status") or "").strip()
    research_stage = str(research_session.get("stage") or "").strip()
    state_stage = (
        research_stage
        if execution_status in {"queued", "running"} and research_stage
        else execution_status or research_stage or "completed"
    )

    state = {
        "stage": state_stage,
        "objective": {
            "question": summary.get("research_question") or "",
            "success_metric": metric_name,
        },
        "best_metric_value": tracker_state.get("best_value"),
        "iteration_index": iteration_state.get("iteration_index") or tracker_state.get("iteration"),
        "max_iterations": iteration_state.get("max_iterations"),
        "run_history": run_history,
        "persisted_summary": summary,
    }
    stage_history = research_session.get("stage_history")
    if isinstance(stage_history, list):
        state["stage_history"] = stage_history
    if research_session.get("stage_started_at") is not None:
        state["stage_started_at"] = research_session.get("stage_started_at")
    for key in (
        "task_profile",
        "selected_dataset",
        "data_readiness",
        "execution_plan",
    ):
        value = research_session.get(key)
        if isinstance(value, dict) and value:
            state[key] = value
    dataset_candidates = research_session.get("dataset_candidates")
    if isinstance(dataset_candidates, list):
        state["dataset_candidates"] = dataset_candidates
    for key in ("dataset_manifest_path", "acquisition_status", "acquisition_notes"):
        value = research_session.get(key)
        if value not in (None, "", [], {}):
            state[key] = value
    grounding = research_session.get("grounding")
    if not isinstance(grounding, dict):
        grounding = summary.get("grounding")
    if isinstance(grounding, dict) and grounding:
        state["grounding"] = grounding
    ui_run_summary = research_session.get("ui_run_summary")
    if isinstance(ui_run_summary, dict):
        state["ui_run_summary"] = ui_run_summary
    latest_review = research_session.get("latest_review")
    if isinstance(latest_review, dict):
        state["latest_review"] = latest_review
    review_history = research_session.get("review_history")
    if isinstance(review_history, list):
        state["review_history"] = review_history
    if research_session.get("review_decision"):
        state["review_decision"] = research_session.get("review_decision")
    return {key: value for key, value in state.items() if value not in (None, "", [])}


def _hydrate_persisted_record_detail(record: SessionRecord) -> SessionRecord:
    """Attach replay events/state to a legacy disk-only session detail record."""
    return _refresh_persisted_record_detail(record)


def _refresh_persisted_record_detail(record: SessionRecord) -> SessionRecord:
    """Reload a legacy disk-only session from its persisted conversation dir."""
    try:
        from backend.pathscientist.persistence.history import load_conversation_summary
        from backend.pathscientist.persistence.layout import get_persistence_root
        from backend.pathscientist.runtime.session import _resolve_base_dir
    except Exception as exc:
        logger.debug("PathScientist persistence import failed: %s", exc)
        return record

    summary = record.state.get("persisted_summary") if isinstance(record.state, dict) else None
    conversation_dir = Path(get_persistence_root(_resolve_base_dir())) / record.conversation_id
    if not conversation_dir.is_dir() and "-" in record.conversation_id:
        conversation_dir = conversation_dir.with_name(record.conversation_id.replace("-", ""))
    if conversation_dir.is_dir():
        try:
            loaded_summary = load_conversation_summary(conversation_dir)
            if isinstance(summary, dict):
                loaded_summary = {**summary, **loaded_summary}
            summary = loaded_summary
        except Exception as exc:
            logger.debug("PathScientist summary refresh failed for %s: %s", record.conversation_id, exc)

    stage_events: list[dict[str, Any]] = []
    if isinstance(summary, dict):
        summary = _enrich_persisted_summary(summary, conversation_dir)
        record.state = _build_persisted_session_state(summary)
        stage_events = _build_persisted_stage_events(summary)
        runtime = _legacy_runtime_status(summary)
        if runtime.status == "interrupted":
            record.state["stage"] = "interrupted"
            record.state["interrupted_reason"] = runtime.error
        record.status = runtime.status
        research = summary.get("research_session") if isinstance(summary.get("research_session"), dict) else {}
        record.stage = runtime.stage if runtime.status == "interrupted" else str(research.get("stage") or runtime.stage)
        record.error = runtime.error
        record.updated_at = _timestamp_to_epoch(
            summary.get("updated_at") or summary.get("started_at"),
            fallback=record.updated_at,
        )

    events = stage_events + _load_persisted_conversation_events(
        conversation_dir,
        start_seq=len(stage_events) + 1,
    )
    if events:
        record.hydrate_events(events)
    return record


def _scan_persisted_conversations(*, curated_only: bool = False) -> list[SessionRecord]:
    """Build stub SessionRecords for every persisted conversation on disk.

    Uses ``persistence.history.list_conversations`` to find every
    ``<persistence_root>/<conv_uuid>/base_state.json``. Records hydrated here
    are flagged ``status=completed`` (best-effort — disk-only sessions are
    not actively running) and carry no event timeline; the SSE endpoint will
    serve the final state snapshot on connect.
    """
    try:
        from backend.pathscientist.persistence.history import list_conversations
        from backend.pathscientist.persistence.layout import get_persistence_root
        from backend.pathscientist.runtime.session import _resolve_base_dir
    except Exception as exc:
        logger.debug("PathScientist persistence import failed: %s", exc)
        return []

    base_dir = _resolve_base_dir()
    persistence_root = get_persistence_root(base_dir)
    if not Path(persistence_root).is_dir():
        return []

    stubs: list[SessionRecord] = []
    for summary in list_conversations(Path(persistence_root)):
        if curated_only and not _is_curated_persisted_summary(summary):
            continue
        conv_id = str(summary.get("conversation_id") or "")
        if not conv_id:
            continue
        conversation_dir = Path(persistence_root) / conv_id
        if not conversation_dir.is_dir() and "-" in conv_id:
            conversation_dir = conversation_dir.with_name(conv_id.replace("-", ""))
        if conversation_dir.is_dir():
            summary = _enrich_persisted_summary(summary, conversation_dir)
        # Stable, short session id derived from conversation id so repeated
        # hydration is idempotent.
        session_id = conv_id.replace("-", "")[:12] or uuid.uuid4().hex[:12]
        research = (summary.get("research_session") or {})
        objective = research.get("objective") or {}
        question = (
            objective.get("question")
            or summary.get("research_question", "")
            or summary.get("research_summary", "")
            or "(persisted session)"
        )
        created_ts = _timestamp_to_epoch(
            summary.get("started_at") or summary.get("updated_at"),
            fallback=time.time(),
        )
        updated_ts = _timestamp_to_epoch(
            summary.get("updated_at") or summary.get("started_at"),
            fallback=created_ts,
        )
        runtime = _legacy_runtime_status(summary)
        state = _build_persisted_session_state(summary)
        if runtime.status == "interrupted":
            state["stage"] = "interrupted"
            state["interrupted_reason"] = runtime.error
        stub = SessionRecord(
            session_id=session_id,
            conversation_id=conv_id,
            question=str(question)[:280],
            model="",
            # Avoid blocking the history list on many LLM calls. New web
            # sessions get gpt-5.5 titles at creation; legacy sessions get a
            # deterministic concise fallback unless already migrated later.
            title=_fallback_session_title(str(question)),
            status=runtime.status,
            stage=runtime.stage if runtime.status == "interrupted" else str(research.get("stage") or runtime.stage),
            created_at=created_ts,
            updated_at=updated_ts,
            error=runtime.error,
            state=state,
        )
        stubs.append(stub)
    return stubs


def _build_config(req: StartPathScientistSessionRequest):
    try:
        from backend.pathscientist.config import PathScientistConfig
    except Exception as exc:
        raise RuntimeError(f"PathScientist config unavailable: {exc}") from exc

    config = PathScientistConfig.from_env()
    _apply_pathscientist_gateway_defaults(config)
    # Container path convention: ``/data/<lower(basename)>`` matches
    # ``runner._inject_data_mounts_from_question`` so train.py scripts can
    # rely on ``/data/<name>`` resolving inside the sandbox regardless of
    # the host filesystem layout. Pre-fix the route mapped host→host which
    # would have failed inside the sandbox.
    data_mounts: dict[str, str] = {}
    used: set[str] = set()
    for host in req.data_paths:
        if not host:
            continue
        base = Path(host).name.lower() or "data"
        container = f"/data/{base}"
        suffix = 1
        while container in used:
            suffix += 1
            container = f"/data/{base}_{suffix}"
        used.add(container)
        data_mounts[host] = container
    config.data_mounts = data_mounts
    config.llm_model = req.model or config.llm_model or DEFAULT_MODEL
    config.skill_name = req.skill or ("external_test" if req.mode == "external_test" else config.skill_name)
    config.max_iterations = req.max_iter
    config.primary_metric = req.metric or config.primary_metric
    config.manual_approval = req.manual_approval
    config.download_policy = req.download_policy or config.download_policy or "all"
    config.external_test_enabled = bool(req.external_test_enabled or req.mode == "external_test" or config.skill_name == "external_test")
    config.external_test_contract = dict(req.external_test_contract or {})
    return config


def _env_has_value(name: str) -> bool:
    return os.environ.get(name, "") != ""


def _set_env_default(name: str, value: str) -> bool:
    """Match shell ``${VAR:-default}``: empty env values also get defaults."""
    if _env_has_value(name):
        return False
    os.environ[name] = value
    return True


def _apply_pathscientist_gateway_defaults(config: Any) -> None:
    """Apply frontend/backend Gateway defaults for PathScientist runs.

    ``PathScientistConfig.from_env()`` intentionally uses library defaults
    (safe/off for online search and downloads). Gateway-created sessions are
    the primary startup path, so set the operational defaults here instead of
    relying on the legacy bash launcher.
    """
    if _set_env_default("PATHSCIENTIST_LLM_MODEL", DEFAULT_MODEL):
        config.llm_model = DEFAULT_MODEL
    else:
        config.llm_model = getattr(config, "llm_model", "") or DEFAULT_MODEL

    if _set_env_default("PATHSCIENTIST_LLM_PROFILE", "codex-relay"):
        config.llm_profile = "codex-relay"
    else:
        config.llm_profile = getattr(config, "llm_profile", "") or "codex-relay"

    if _set_env_default("PATHSCIENTIST_LLM_WIRE_API", "responses"):
        config.llm_wire_api = "responses"
    else:
        config.llm_wire_api = getattr(config, "llm_wire_api", "") or "responses"

    if _set_env_default("PATHSCIENTIST_SANDBOX", "auto"):
        config.sandbox_mode = "auto"
    else:
        config.sandbox_mode = getattr(config, "sandbox_mode", "") or "auto"

    if _set_env_default("PATHSCIENTIST_LITERATURE_ONLINE", "1"):
        config.literature_online_enabled = True
    if _set_env_default("PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS", "10"):
        config.literature_online_max_results = 10
    if _set_env_default("PATHSCIENTIST_AUTO_ACQUIRE_DATA", "1"):
        config.auto_acquire_data = True
    if _set_env_default("PATHSCIENTIST_DOWNLOAD_POLICY", "all"):
        config.download_policy = "all"
    if _set_env_default("PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB", "500"):
        config.max_download_size_gb = 500.0
    if _set_env_default("PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS", "1"):
        config.allow_large_downloads = True
    if _set_env_default("PATHSCIENTIST_DATASET_CACHE_DIR", DEFAULT_DATASET_CACHE_DIR):
        config.dataset_cache_dir = DEFAULT_DATASET_CACHE_DIR

    _set_env_default("PATHSCIENTIST_GENERATE_PAPER_DRAFT", "0")
    _set_env_default("PATHSCIENTIST_FEATURE_EXTRACTOR_MODE", "auto")
    extractor_mode = os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR_MODE", "auto").strip().lower()
    if extractor_mode == "fixed":
        _set_env_default("PATHSCIENTIST_FEATURE_EXTRACTOR", "virchow2")
    _set_env_default("OPENHANDS_SUPPRESS_BANNER", "1")


def _load_runner():
    try:
        from backend.pathscientist.orchestrator.runner import run_research_session
        from backend.pathscientist.orchestrator.state_bridge import (
            dump_research_session_state,
        )
    except Exception as exc:
        raise RuntimeError(f"PathScientist runtime unavailable: {exc}") from exc

    return run_research_session, dump_research_session_state


_SESSION_MANAGER = PathScientistSessionManager()


@router.get("/skills")
def list_skills():
    try:
        from backend.pathscientist.domain.skills import registry

        items = [
            {
                "id": skill.name,
                "name": skill.name,
                "description": getattr(skill, "description", ""),
            }
            for skill in registry.list_skills()
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PathScientist skills unavailable: {exc}",
        ) from exc
    return {"items": items}


@router.post("/sessions")
def create_session(req: StartPathScientistSessionRequest):
    try:
        record = _SESSION_MANAGER.start(req)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return record.summary()


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str):
    record = _SESSION_MANAGER.stop(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    return record.summary()


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    try:
        result = _SESSION_MANAGER.delete(session_id)
    except SessionDeleteRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    return result


@router.get("/sessions")
def list_sessions(include_persisted: bool = False):
    return {
        "items": [
            record.summary()
            for record in _SESSION_MANAGER.list(include_persisted=include_persisted)
        ]
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    record = _SESSION_MANAGER.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    return {
        **record.summary(),
        "state": record.state,
        "events": record.events,
    }


@router.get("/sessions/{session_id}/runs/{run_id}/download")
def download_run_artifacts(session_id: str, run_id: str):
    record = _SESSION_MANAGER.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    if not _is_safe_run_id(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")

    workspace = _resolve_session_workspace(record)
    if workspace is None:
        raise HTTPException(status_code=404, detail="PathScientist workspace not found")

    try:
        zip_path = _build_run_artifact_zip(record, workspace, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filename = f"pathscientist-{session_id}-{run_id}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda path=zip_path: Path(path).unlink(missing_ok=True)),
    )


@router.get("/sessions/{session_id}/events")
def stream_session_events(session_id: str):
    record = _SESSION_MANAGER.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")

    async def event_generator():
        next_index = 0
        last_state_signature = ""
        loop = asyncio.get_running_loop()
        terminal_states = {"queued", "running"}
        while True:
            if record.conversation_id and isinstance(_record_state(record).get("persisted_summary"), dict):
                await loop.run_in_executor(None, _refresh_persisted_record_detail, record)
                state_payload = _record_state_sse_payload(record)
                if state_payload:
                    signature = json.dumps(state_payload, sort_keys=True, default=str)
                    if signature != last_state_signature:
                        last_state_signature = signature
                        yield _format_sse(state_payload)

            # 1. Drain anything already queued under a single lock-acquire.
            new_events, next_index = await loop.run_in_executor(
                None, record.snapshot_events, next_index,
            )
            for event in new_events:
                yield _format_sse(event)

            if record.status not in terminal_states:
                break

            # 2. Block (briefly) until a new event lands OR a heartbeat is due.
            got_new = await loop.run_in_executor(
                None, record.wait_for_events, next_index, 5.0,
            )
            if not got_new:
                yield _format_sse({"kind": "heartbeat", "status": record.status})

        # 3. Final drain — between the loop's status check and here, the
        # runner thread may have appended a tail event that we'd otherwise
        # lose. Pull anything left before emitting the closing state.
        tail_events, _ = await loop.run_in_executor(
            None, record.snapshot_events, next_index,
        )
        for event in tail_events:
            yield _format_sse(event)

        yield _format_sse(
            {"kind": "state", "state": record.state, "status": record.status}
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _is_safe_run_id(run_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(run_id or "")))


def _record_state(record: SessionRecord) -> dict[str, Any]:
    return record.state if isinstance(record.state, dict) else {}


def _record_state_sse_payload(record: SessionRecord) -> dict[str, Any]:
    state = _record_state(record)
    if not state:
        return {}
    stage = str(state.get("stage") or record.stage or "").strip()
    payload: dict[str, Any] = {
        "kind": "state",
        "status": record.status,
        "state": state,
    }
    if stage:
        payload["stage"] = stage
    if record.error:
        payload["error"] = record.error
    return payload


def _resolve_workspace_from_state(state: dict[str, Any]) -> Path | None:
    """Find the workspace associated with a serialized PathScientist state."""
    candidates: list[Any] = [
        state.get("workspace_dir"),
        state.get("workspace_root"),
    ]
    grounding = state.get("grounding")
    if isinstance(grounding, dict):
        candidates.extend([
            grounding.get("workspace_dir"),
            grounding.get("workspace_root"),
        ])
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        candidates.extend([
            summary.get("workspace_dir"),
            (summary.get("research_session") or {}).get("workspace_dir")
            if isinstance(summary.get("research_session"), dict)
            else "",
        ])
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.is_dir():
            return path.resolve()

    # Web-created sessions store the internal PathScientist session_id in
    # research state. Default workspaces live at <base>/session_<session_id>.
    internal_session_id = str(state.get("session_id") or "").strip()
    if internal_session_id:
        path = _resolve_pathscientist_base_dir() / f"session_{internal_session_id}"
        if path.is_dir():
            return path.resolve()
    return None


def _resolve_session_workspace(record: SessionRecord) -> Path | None:
    """Find the workspace that owns a Gateway session."""
    return _resolve_workspace_from_state(_record_state(record))


def _download_progress_path_from_state(state: dict[str, Any]) -> Path | None:
    for key in ("download_progress_path",):
        value = state.get(key)
        if value:
            return Path(str(value)).expanduser()
    grounding = state.get("grounding")
    if isinstance(grounding, dict):
        value = grounding.get("download_progress_path")
        if value:
            return Path(str(value)).expanduser()
    workspace = _resolve_workspace_from_state(state)
    if workspace is None:
        return None
    return workspace / ".dataset" / "download_progress.json"


def _load_download_progress_from_state(state: dict[str, Any]) -> dict[str, Any]:
    progress_path = _download_progress_path_from_state(state)
    if progress_path is None or not progress_path.is_file():
        return {}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _enrich_state_with_download_progress(state: dict[str, Any]) -> dict[str, Any]:
    progress = _load_download_progress_from_state(state)
    if not progress:
        return state
    return {**state, "download_progress": progress}


def _start_download_progress_poller(record: SessionRecord) -> Callable[[], None]:
    """Emit SSE state updates while providers update the progress sidecar."""
    stop_event = threading.Event()

    def emit_once(last_signature: str) -> str:
        state = _record_state(record)
        progress = _load_download_progress_from_state(state)
        if not progress:
            return last_signature
        signature = json.dumps(progress, sort_keys=True, default=str)
        if signature == last_signature:
            return last_signature
        enriched = {**state, "download_progress": progress}
        assert record._condition is not None
        with record._condition:
            record.state = enriched
            stage = str(enriched.get("stage") or record.stage or "acquisition")
            if record.status in {"queued", "running"}:
                record.stage = stage
            record._condition.notify_all()
        record.add_event({
            "kind": "state",
            "status": record.status,
            "stage": str(enriched.get("stage") or record.stage or "acquisition"),
            "state": enriched,
        })
        return signature

    def run() -> None:
        last_signature = ""
        while not stop_event.is_set():
            try:
                last_signature = emit_once(last_signature)
            except Exception as exc:
                logger.debug("PathScientist download progress poll failed: %s", exc)
            stop_event.wait(DOWNLOAD_PROGRESS_POLL_SECONDS)

    thread = threading.Thread(
        target=run,
        name=f"pathscientist-download-progress-{record.session_id}",
        daemon=True,
    )
    thread.start()

    def stop() -> None:
        stop_event.set()
        thread.join(timeout=max(0.1, DOWNLOAD_PROGRESS_POLL_SECONDS * 2))

    return stop


def _stat_disk_usage_bytes(stat_result: os.stat_result) -> int:
    blocks = int(getattr(stat_result, "st_blocks", 0) or 0)
    if blocks > 0:
        return blocks * 512
    return int(stat_result.st_size)


def _directory_disk_usage_bytes(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        path = stack.pop()
        try:
            stat_result = path.lstat()
        except OSError:
            continue
        total += _stat_disk_usage_bytes(stat_result)
        if path.is_symlink() or not stat.S_ISDIR(stat_result.st_mode):
            continue
        try:
            stack.extend(path.iterdir())
        except OSError:
            continue
    return total


def _refresh_workspace_size_cache(key: str, workspace: Path) -> None:
    try:
        size = _directory_disk_usage_bytes(workspace)
    except Exception as exc:
        logger.debug("PathScientist workspace size unavailable for %s: %s", workspace, exc)
        size = None
    with _WORKSPACE_SIZE_CACHE_LOCK:
        if size is not None:
            _WORKSPACE_SIZE_CACHE[key] = (time.time(), size)
        _WORKSPACE_SIZE_PENDING.discard(key)


def _cached_workspace_size_bytes(workspace: Path) -> int | None:
    key = str(workspace.resolve())
    now = time.time()
    with _WORKSPACE_SIZE_CACHE_LOCK:
        cached = _WORKSPACE_SIZE_CACHE.get(key)
        if cached and now - cached[0] < _WORKSPACE_SIZE_CACHE_TTL_SECONDS:
            return cached[1]
        stale_size = cached[1] if cached else None
        should_refresh = key not in _WORKSPACE_SIZE_PENDING
        if should_refresh:
            _WORKSPACE_SIZE_PENDING.add(key)

    if should_refresh:
        threading.Thread(
            target=_refresh_workspace_size_cache,
            args=(key, workspace),
            name="pathscientist-workspace-size",
            daemon=True,
        ).start()
    return stale_size


def _workspace_usage_summary(record: SessionRecord) -> dict[str, Any]:
    workspace = _resolve_session_workspace(record)
    if workspace is None:
        return {}
    payload: dict[str, Any] = {"workspace_path": str(workspace)}
    size = _cached_workspace_size_bytes(workspace)
    if size is not None:
        payload["workspace_size_bytes"] = size
    return payload


def _run_history_entry(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    history = state.get("run_history")
    if not isinstance(history, list):
        return {}
    for entry in history:
        if isinstance(entry, dict) and str(entry.get("run_id") or "") == run_id:
            return entry
    return {}


def _load_evidence_record(workspace: Path, run_id: str) -> tuple[dict[str, Any], Path] | None:
    run_dir = workspace / ".evidence" / "runs" / run_id
    record_path = run_dir / "record.json"
    if not record_path.exists():
        return None
    data = json.loads(record_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}, run_dir


def _zip_writestr_json(archive: zipfile.ZipFile, name: str, value: Any) -> None:
    archive.writestr(
        name,
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
    )


def _safe_zip_component(value: Any, fallback: str) -> str:
    text = str(value or fallback)
    text = text.replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_", ".", " "}).strip()
    return cleaned or fallback


def _unique_arcname(existing: set[str], arcname: str) -> str:
    if arcname not in existing:
        existing.add(arcname)
        return arcname
    stem = Path(arcname).stem
    suffix = Path(arcname).suffix
    parent = Path(arcname).parent.as_posix()
    for index in itertools.count(2):
        candidate_name = f"{stem}-{index}{suffix}"
        candidate = candidate_name if parent == "." else f"{parent}/{candidate_name}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    raise RuntimeError("unreachable")


def _add_file_to_zip(
    archive: zipfile.ZipFile,
    existing: set[str],
    source: Path,
    arcname: str,
) -> bool:
    try:
        if not source.is_file():
            return False
        archive.write(source, _unique_arcname(existing, arcname))
        return True
    except OSError:
        return False


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _resolve_artifact_source(
    *,
    workspace: Path,
    evidence_run_dir: Path,
    record_data: dict[str, Any],
    artifact: dict[str, Any],
) -> Path | None:
    copied = evidence_run_dir / "artifacts" / _safe_zip_component(artifact.get("name"), "artifact")
    if copied.is_file():
        return copied

    raw_path = str(artifact.get("path") or "")
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve(strict=False)
    data_output_dir = str(record_data.get("data_output_dir") or "")
    allowed_roots = [workspace.resolve(strict=False)]
    if data_output_dir:
        allowed_roots.append(Path(data_output_dir).expanduser().resolve(strict=False))
    if not any(_path_under(candidate, root) for root in allowed_roots):
        return None
    return candidate if candidate.is_file() else None


def _build_run_artifact_zip(record: SessionRecord, workspace: Path, run_id: str) -> str:
    """Create a zip containing one iteration's results and model artifacts."""
    state = _record_state(record)
    history_entry = _run_history_entry(state, run_id)
    loaded = _load_evidence_record(workspace, run_id)
    if loaded is None and not history_entry:
        raise FileNotFoundError(f"No artifacts found for run_id={run_id}")

    record_data: dict[str, Any] = {}
    evidence_run_dir = workspace / ".evidence" / "runs" / run_id
    if loaded is not None:
        record_data, evidence_run_dir = loaded

    tmp = tempfile.NamedTemporaryFile(
        prefix=f"pathscientist-{run_id}-",
        suffix=".zip",
        delete=False,
    )
    tmp.close()
    existing: set[str] = set()
    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _zip_writestr_json(archive, "run_record.json", history_entry or {"run_id": run_id})
        if record_data:
            _zip_writestr_json(archive, "record.json", record_data)
        metrics = (
            record_data.get("metrics")
            if isinstance(record_data.get("metrics"), dict)
            else history_entry.get("metrics")
            if isinstance(history_entry.get("metrics"), dict)
            else {}
        )
        if not metrics and history_entry:
            metric_name = str(history_entry.get("metric_name") or "metric")
            metric_value = history_entry.get("metric_value")
            metrics = {metric_name: metric_value}
        _zip_writestr_json(archive, "metrics.json", metrics)

        for filename in ("stdout.txt", "stderr.txt", "code_snapshot.py"):
            _add_file_to_zip(archive, existing, evidence_run_dir / filename, filename)

        artifacts = record_data.get("artifacts")
        if isinstance(artifacts, list):
            for item in artifacts:
                if not isinstance(item, dict):
                    continue
                if str(item.get("storage_mode") or "") == "cache_summary":
                    continue
                source = _resolve_artifact_source(
                    workspace=workspace,
                    evidence_run_dir=evidence_run_dir,
                    record_data=record_data,
                    artifact=item,
                )
                if source is None:
                    continue
                name = _safe_zip_component(item.get("name"), source.name)
                _add_file_to_zip(archive, existing, source, f"artifacts/{name}")
    return tmp.name


def _format_sse(event: dict[str, Any]) -> str:
    event_name = "state" if event.get("kind") == "state" else "event"
    return f"event: {event_name}\ndata: {json.dumps(event, default=str)}\n\n"
