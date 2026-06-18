"""PathScientist session API routes.

This MVP exposes a small, local-first control surface for PathScientist while
keeping the heavy OpenHands/PathScientist imports lazy. Gateway startup should
not fail just because the optional research-agent runtime is unavailable.
"""
from __future__ import annotations

import asyncio
import csv
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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend.auth import (
    User,
    PATHSCIENTIST_ACCESS_TOKEN_SECRET,
    create_pathscientist_access_token,
    current_active_user,
    get_pathscientist_access_token_claims,
    get_pathscientist_header_or_access_token_claims,
    get_user_from_header_or_param,
    get_user_from_token_param,
)
from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.repositories.auto_research import AutoResearchRepository
from gateway import pathscientist_persistence
logger = logging.getLogger(__name__)

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_LLM_PROFILE = "codex-relay"
DEFAULT_LLM_WIRE_API = "completion"
GATEWAY_SESSION_REGISTRY = "gateway_sessions.json"
GATEWAY_EVENT_DIR = "gateway_events"
GATEWAY_DELETED_SESSIONS = "gateway_deleted_sessions.json"
GATEWAY_DELETE_AUDIT_LOG = "gateway_delete_audit.jsonl"
LEGACY_RUNNING_STALE_SECONDS = int(os.environ.get("PATHSCIENTIST_LEGACY_RUNNING_STALE_SEC", "600"))
TRAINING_LOG_ACTIVE_SECONDS = int(os.environ.get("PATHSCIENTIST_TRAINING_LOG_ACTIVE_SEC", "7200"))
DEFAULT_DATASET_CACHE_DIR = ""
DOWNLOAD_PROGRESS_POLL_SECONDS = float(os.environ.get("PATHSCIENTIST_DOWNLOAD_PROGRESS_POLL_SEC", "1"))
_DB_HISTORY_ENABLED = os.environ.get("PATHSCIENTIST_DB_HISTORY", "1").strip().lower() not in {"0", "false", "no"}

router = APIRouter(prefix="/pathscientist", tags=["pathscientist"])
_REGISTRY_LOCK = threading.Lock()
_EVENT_LOG_LOCK = threading.Lock()
_DELETE_AUDIT_LOCK = threading.Lock()
_WORKSPACE_SIZE_CACHE_LOCK = threading.Lock()
_WORKSPACE_SIZE_CACHE_TTL_SECONDS = float(os.environ.get("PATHSCIENTIST_WORKSPACE_SIZE_TTL_SEC", "30"))
_WORKSPACE_SIZE_CACHE: dict[str, tuple[float, int]] = {}
_WORKSPACE_SIZE_PENDING: set[str] = set()
_TRAINING_EPOCH_RE = re.compile(r"\bEpoch\s+(\d+)\s*/\s*(\d+)\b", re.IGNORECASE)
_TRAINING_METRIC_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]*)=([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)


class StartPathScientistSessionRequest(BaseModel):
    """Request body for starting a PathScientist session."""

    question: str = Field(..., min_length=1, max_length=4000)
    skill: str = ""
    mode: str = "research"
    max_iter: int = Field(5, ge=1, le=20)
    metric: str = "auc"
    model: str = ""
    manual_approval: bool = False
    download_policy: str | None = None
    data_paths: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    external_test_enabled: bool = False
    external_test_contract: dict[str, str] = Field(default_factory=dict)


class PathScientistAccessTokenRequest(BaseModel):
    purpose: str = Field(..., pattern=r"^(events|session_download|run_download)$")
    run_id: str = ""


@dataclass
class SessionRecord:
    """In-memory session state for the MVP Gateway bridge."""

    session_id: str
    conversation_id: str
    question: str
    model: str
    user_id: str = ""
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
        pathscientist_persistence.persist_event(
            session_id=self.session_id,
            event=payload,
        )

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
            "user_id": self.user_id,
            "status": self.status,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
        if isinstance(self.state, dict):
            current_iteration = _coerce_iteration(self.state.get("iteration_index"))
            if current_iteration is None:
                current_iteration = _coerce_iteration(self.state.get("current_iteration"))
            max_iterations = _coerce_iteration(self.state.get("max_iterations"))
            if current_iteration is not None:
                payload["current_iteration"] = current_iteration
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
            for key in (
                "persistence_dir",
                "workspace_path",
                "resume_available",
                "event_source_version",
                "stop_reason",
                "interrupted_reason",
                "user_stop_requested",
                "stop_source",
                "stop_requested_at",
            ):
                if key in self.state:
                    payload[key] = self.state[key]
        payload.update(_workspace_usage_summary(self))
        training_progress = _training_progress_summary(self)
        if training_progress:
            payload["training_progress"] = training_progress
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


class SessionResumeRejected(RuntimeError):
    """Raised when a historical session cannot be resumed safely."""


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

    def start(
        self,
        req: StartPathScientistSessionRequest,
        *,
        user_id: str = "",
        dataset_mounts: dict[str, str] | None = None,
    ) -> SessionRecord:
        config = _build_config(req)
        config.pathlab_user_id = str(user_id or "")
        if dataset_mounts:
            _merge_data_mounts(config.data_mounts, dataset_mounts)
            _apply_external_contract_from_pathlab_mounts(req, config)
        record = SessionRecord(
            session_id=uuid.uuid4().hex[:12],
            conversation_id="",
            question=req.question,
            model=config.llm_model or DEFAULT_MODEL,
            user_id=user_id,
            title="",
            title_pending=True,
        )
        with self._lock:
            self._sessions[record.session_id] = record
        _save_gateway_session_record(record)
        pathscientist_persistence.persist_session_created(
            session_id=record.session_id,
            user_id=record.user_id,
            question=record.question,
            max_iterations=req.max_iter,
            metric=req.metric,
            model=record.model,
            workspace_path=str(_resolve_session_workspace(record) or ""),
        )
        record.add_event({"kind": "session", "status": "queued"})
        _queue_session_title_generation(record, config)
        thread = threading.Thread(target=self._run, args=(record, req, config), daemon=True)
        thread.start()
        return record

    def resume(self, record: SessionRecord, req: StartPathScientistSessionRequest) -> SessionRecord:
        if record.status in {"queued", "running"}:
            raise SessionResumeRejected("This PathScientist session is already running.")
        if not record.conversation_id:
            raise SessionResumeRejected("This session does not have a persisted conversation id.")
        if _conversation_uuid(record.conversation_id) is None:
            raise SessionResumeRejected("This session has an invalid persisted conversation id.")
        if not _conversation_base_state_exists(record.conversation_id, _record_state(record)):
            raise SessionResumeRejected("This session can be viewed, but its resume checkpoint is missing.")
        config = _build_config(req)
        config.pathlab_user_id = str(record.user_id or "")

        assert record._condition is not None
        with record._condition:
            record.cancel_requested = False
            record.status = "running"
            record.stage = "resuming"
            record.error = ""
            record.state = {
                **_record_state(record),
                "stage": "resuming",
                "resume_available": True,
            }
            record.updated_at = time.time()
            record._condition.notify_all()
        with self._lock:
            self._sessions[record.session_id] = record
        _save_gateway_session_record(record)
        _persist_record_state(record, req)
        record.add_event({
            "kind": "session",
            "status": "running",
            "stage": "resuming",
            "summary": "Resuming persisted PathScientist conversation.",
        })
        thread = threading.Thread(
            target=self._resume_run,
            args=(record, req, config),
            daemon=True,
        )
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
        pathscientist_persistence.delete_session(session_id)
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

    def register_hydrated(self, record: SessionRecord) -> SessionRecord:
        with self._lock:
            existing = self._sessions.get(record.session_id)
            if existing is not None:
                return existing
            self._sessions[record.session_id] = record
            return record

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
                _persist_record_state(record, req)
                record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
                return
            sync_result = _sync_pathscientist_manifest_to_pathlab_best_effort(record, state)
            state["pathlab_download_sync"] = sync_result
            final_status, final_stage, final_error = _final_status_from_state(state)
            if final_status == "failed":
                state = {
                    **state,
                    "workflow_stage": state.get("stage"),
                    "stage": final_stage,
                    "error": final_error,
                }
            record.state = state
            record.conversation_id = str(state.get("conversation_id") or "")
            record.set_status(
                final_status,
                stage=final_stage,
                error=final_error or None,
            )
            _save_gateway_session_record(record)
            _persist_record_state(record, req)
            record.add_event({"kind": "state", "state": state, "status": final_status})
        except SessionStopRequested as exc:
            record.state = {
                **_record_state(record),
                "stage": "interrupted",
                "stop_reason": "user_cancelled",
                "interrupted_reason": str(exc),
            }
            record.set_status("interrupted", stage="interrupted", error=str(exc))
            _save_gateway_session_record(record)
            _persist_record_state(record, req)
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
                _persist_record_state(record, req)
                record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
                return
            record.set_status("failed", stage="failed", error=str(exc))
            _save_gateway_session_record(record)
            record.state = {
                **_record_state(record),
                "stage": "failed",
                "error": str(exc),
            }
            _persist_record_state(record, req)
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

    def _resume_run(
        self,
        record: SessionRecord,
        req: StartPathScientistSessionRequest,
        config: Any,
    ) -> None:
        stop_download_progress_poller = _start_download_progress_poller(record)
        try:
            state = self._invoke_resume_runner(config, req, record)
            final_status, final_stage, final_error = _final_status_from_state(state)
            if final_status == "failed":
                state = {
                    **state,
                    "workflow_stage": state.get("stage"),
                    "stage": final_stage,
                    "error": final_error,
                }
            record.state = state
            record.conversation_id = str(state.get("conversation_id") or record.conversation_id or "")
            record.set_status(
                final_status,
                stage=final_stage,
                error=final_error or None,
            )
            _save_gateway_session_record(record)
            _persist_record_state(record, req)
            record.add_event({"kind": "state", "state": record.state, "status": record.status})
        except SessionStopRequested as exc:
            record.state = {
                **_record_state(record),
                "stage": "interrupted",
                "stop_reason": "user_cancelled",
                "interrupted_reason": str(exc),
            }
            record.set_status("interrupted", stage="interrupted", error=str(exc))
            _save_gateway_session_record(record)
            _persist_record_state(record, req)
            record.add_event({"kind": "state", "state": record.state, "status": "interrupted"})
        except Exception as exc:
            record.set_status("failed", stage="failed", error=str(exc))
            record.state = {
                **_record_state(record),
                "stage": "failed",
                "error": str(exc),
            }
            _save_gateway_session_record(record)
            _persist_record_state(record, req)
            record.add_event({"kind": "error", "message": str(exc)})
        finally:
            stop_download_progress_poller()

    def _invoke_resume_runner(
        self,
        config: Any,
        req: StartPathScientistSessionRequest,
        record: SessionRecord,
    ) -> dict[str, Any]:
        try:
            from backend.pathscientist.orchestrator.runner import continue_research_session
            from backend.pathscientist.orchestrator.state_bridge import (
                dump_research_session_state,
                load_research_session_state,
            )
            from backend.pathscientist.persistence.resume import resume_conversation
        except Exception as exc:
            raise RuntimeError(f"PathScientist resume runtime unavailable: {exc}") from exc

        conversation_id = _conversation_uuid(record.conversation_id)
        if conversation_id is None:
            raise RuntimeError("PathScientist conversation id is invalid")
        conversation, session = resume_conversation(config, conversation_id)
        state = load_research_session_state(conversation)
        state, _session, _conversation = continue_research_session(
            config,
            state,
            session,
            conversation,
            auto_approve=not req.manual_approval,
        )
        payload = dump_research_session_state(state)
        if isinstance(payload, dict):
            payload = {
                **payload,
                "conversation_id": str(conversation_id),
                "resume_available": _conversation_base_state_exists(
                    str(conversation_id),
                    payload,
                ),
            }
        return _enrich_state_with_download_progress(payload)


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
        _persist_record_state(record)


_FAILED_FINAL_REVIEW_STATUSES = {"failed", "no_finalized_run", "error"}


def _is_committed_run(entry: Any) -> bool:
    return isinstance(entry, dict) and bool(entry.get("committed"))


def _run_failed(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("committed"):
        return False
    exit_code = entry.get("exit_code")
    if exit_code not in (None, "", 0, "0"):
        return True
    metrics = entry.get("metrics")
    if isinstance(metrics, dict) and str(metrics.get("status") or "").lower() == "failed":
        return True
    return bool(entry.get("error") or entry.get("error_type"))


def _final_failure_message(state: dict[str, Any]) -> str:
    latest_review = state.get("latest_review") if isinstance(state.get("latest_review"), dict) else {}
    for key in ("summary", "reason", "message"):
        text = str(latest_review.get(key) or "").strip()
        if text:
            return text
    for entry in reversed(state.get("run_history") if isinstance(state.get("run_history"), list) else []):
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            text = str(metrics.get("error") or "").strip()
            if text:
                return text
        text = str(entry.get("error") or entry.get("error_type") or "").strip()
        if text:
            return text
    return "PathScientist finished without a committed successful run."


def _final_status_from_state(state: dict[str, Any]) -> tuple[str, str, str]:
    """Map workflow completion to UI/API status.

    PathScientist can reach synthesis/completed after exhausting retries even
    when every experiment failed. In that case the Gateway must expose a failed
    session, not a successful one.
    """
    stage = str(state.get("stage") or "completed").strip() or "completed"
    if stage in {"failed", "interrupted"}:
        return stage, stage, str(state.get("error") or state.get("interrupted_reason") or "")

    run_history = state.get("run_history")
    runs = [entry for entry in run_history if isinstance(entry, dict)] if isinstance(run_history, list) else []
    if any(_is_committed_run(entry) for entry in runs):
        return "completed", stage, ""

    latest_review = state.get("latest_review") if isinstance(state.get("latest_review"), dict) else {}
    latest_review_status = str(latest_review.get("status") or "").strip().lower()
    review_decision = str(
        state.get("review_decision") or latest_review.get("decision") or ""
    ).strip().lower()
    has_failed_run_evidence = bool(runs) and all(_run_failed(entry) for entry in runs)
    if (
        stage in {"completed", "finished", "synthesis"}
        and review_decision == "enter_synthesis"
        and (
            latest_review_status in _FAILED_FINAL_REVIEW_STATUSES
            or has_failed_run_evidence
        )
    ):
        return "failed", "failed", _final_failure_message(state)

    return "completed", stage, ""


def _resolve_workspace_from_state(state: dict[str, Any]) -> Path | None:
    """Resolve a PathScientist workspace from serialized research state."""
    candidates: list[Any] = [
        state.get("workspace_path"),
        state.get("workspace_dir"),
        state.get("workspace_root"),
    ]
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        research_session = summary.get("research_session")
        candidates.extend([
            summary.get("workspace_path"),
            summary.get("workspace_dir"),
            research_session.get("workspace_path")
            if isinstance(research_session, dict)
            else "",
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
    """Generate a concise session title with the active PathScientist LLM."""
    try:
        from openhands.sdk.llm import Message, TextContent
        from backend.pathscientist.llm_client import (
            build_chat_llm,
            extract_text,
            invoke_chat_llm,
            make_llm_config,
        )

        title_model = str(getattr(config, "llm_model", "") or "").strip() or DEFAULT_MODEL
        llm_config = make_llm_config(config=config, llm_model=title_model)
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
        default_base_dir = Path(__file__).resolve().parents[3] / "uploads" / "pathscientist"
        return Path(
            os.environ.get(
                "PATHSCIENTIST_BASE_DIR",
                str(default_base_dir),
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
            item_state = item.get("state") if isinstance(item.get("state"), dict) else {}
            workspace = _resolve_workspace_from_state({
                **item_state,
                "workspace_path": item.get("workspace_path") or item_state.get("workspace_path"),
                "workspace_dir": item.get("workspace_path") or item_state.get("workspace_dir"),
            })
            if _workspace_has_recent_training_log(workspace):
                stage = str(item_state.get("stage") or stage or "execution")
                error = ""
            else:
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
            user_id=str(item.get("user_id") or ""),
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
    *,
    match_conversation: bool = True,
) -> bool:
    session_ids, conversation_ids = deleted or _load_deleted_gateway_sessions()
    if record.session_id in session_ids:
        return True
    return bool(
        match_conversation
        and record.conversation_id
        and record.conversation_id in conversation_ids
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


def _db_runtime_status(session: Any, *, now: float | None = None) -> LegacyRuntimeStatus:
    status = str(getattr(session, "status", None) or "completed").strip().lower()
    stage = str(getattr(session, "phase", None) or status or "completed").strip().lower()
    if status not in {"queued", "running"}:
        return LegacyRuntimeStatus(status=status or "completed", stage=stage or status or "completed")

    now = time.time() if now is None else now
    recovery = getattr(session, "recovery_metadata", None)
    recovery = recovery if isinstance(recovery, dict) else {}
    workspace = _resolve_workspace_from_state({
        "workspace_path": getattr(session, "workspace_path", None),
        "workspace_dir": getattr(session, "workspace_path", None),
        "recovery_metadata": recovery,
    })
    if _workspace_has_recent_training_log(workspace, now=now):
        return LegacyRuntimeStatus(status=status, stage=stage or status)

    timestamp = _timestamp_to_epoch_or_none(
        getattr(session, "updated_at", None) or getattr(session, "created_at", None)
    )
    if timestamp is None:
        return LegacyRuntimeStatus(
            status="interrupted",
            stage="interrupted",
            error="No database updates were recorded; this run is not attached to a live Gateway process.",
        )
    age_seconds = max(0.0, now - timestamp)
    if age_seconds > LEGACY_RUNNING_STALE_SECONDS:
        return LegacyRuntimeStatus(
            status="interrupted",
            stage="interrupted",
            error="No recent database updates; this run was likely stopped outside the web Gateway.",
        )
    return LegacyRuntimeStatus(status=status, stage=stage or status)


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


def _db_datetime_to_epoch(value: Any, *, fallback: float | None = None) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return _timestamp_to_epoch(value, fallback=fallback or time.time())


def _event_row_to_gateway_event(row: Any) -> dict[str, Any]:
    data = row.event_data if isinstance(getattr(row, "event_data", None), dict) else {}
    event = dict(data)
    event.setdefault("kind", getattr(row, "event_type", None) or "event")
    event.setdefault("seq", getattr(row, "sequence", None))
    event.setdefault(
        "ts",
        _db_datetime_to_epoch(getattr(row, "created_at", None), fallback=time.time()),
    )
    return _normalize_gateway_event(event)


def _db_session_to_record(session: Any, events: list[dict[str, Any]] | None = None) -> SessionRecord:
    runtime = _db_runtime_status(session)
    plan = session.experiment_plan if isinstance(getattr(session, "experiment_plan", None), dict) else {}
    comparison = (
        session.comparison_results
        if isinstance(getattr(session, "comparison_results", None), dict)
        else {}
    )
    recovery = (
        session.recovery_metadata
        if isinstance(getattr(session, "recovery_metadata", None), dict)
        else {}
    )
    state: dict[str, Any] = {
        "stage": runtime.stage,
        "objective": {
            "question": getattr(session, "research_question", "") or "",
            "success_metric": getattr(session, "best_metric_name", None) or "auc",
        },
        "best_metric_value": getattr(session, "best_metric", None),
        "best_experiment": getattr(session, "best_experiment", None),
        "comparison_results": comparison,
        "run_history": comparison.get("run_history") if isinstance(comparison.get("run_history"), list) else [],
        "final_report": getattr(session, "final_report", None),
        "current_iteration": getattr(session, "current_iteration", None),
        "iteration_index": getattr(session, "current_iteration", None),
        "max_iterations": getattr(session, "max_iterations", None),
        "conversation_id": getattr(session, "conversation_id", None),
        "persistence_dir": getattr(session, "persistence_dir", None) or recovery.get("persistence_dir"),
        "workspace_path": getattr(session, "workspace_path", None) or recovery.get("workspace_path"),
        "resume_available": bool(getattr(session, "resume_available", False)),
        "event_source_version": getattr(session, "event_source_version", None) or "gateway-v1",
        "recovery_metadata": recovery,
        "experiment_plan": plan,
        "persisted_summary": {
            "conversation_id": getattr(session, "conversation_id", None),
            "research_question": getattr(session, "research_question", "") or "",
            "execution_status": runtime.status,
            "started_at": getattr(session, "created_at", None),
            "updated_at": getattr(session, "updated_at", None),
            "tracker_state": {
                "primary_metric": getattr(session, "best_metric_name", None) or "auc",
                "best_value": getattr(session, "best_metric", None),
                "history": comparison.get("run_history") if isinstance(comparison.get("run_history"), list) else [],
            },
            "iteration_state": {
                "iteration_index": getattr(session, "current_iteration", None),
                "max_iterations": getattr(session, "max_iterations", None),
            },
            "research_session": {
                "objective": {
                    "question": getattr(session, "research_question", "") or "",
                    "success_metric": getattr(session, "best_metric_name", None) or "auc",
                },
                "stage": runtime.stage,
            },
        },
    }
    if runtime.error:
        state["interrupted_reason"] = runtime.error
    for key in (
        "external_test",
        "external_test_history",
        "latest_review",
        "review_history",
        "review_decision",
        "integrity_report",
    ):
        if key in recovery:
            state[key] = recovery[key]
        elif key in comparison:
            state[key] = comparison[key]
    state = {key: value for key, value in state.items() if value not in (None, "", [])}
    record = SessionRecord(
        session_id=str(getattr(session, "session_id", "") or ""),
        conversation_id=str(getattr(session, "conversation_id", "") or ""),
        question=str(getattr(session, "research_question", "") or "(PathScientist session)")[:280],
        model=str(plan.get("model") or ""),
        user_id=str(getattr(session, "user_id", "") or ""),
        title=_fallback_session_title(str(getattr(session, "research_question", "") or "")),
        status=runtime.status,
        stage=runtime.stage,
        created_at=_db_datetime_to_epoch(getattr(session, "created_at", None), fallback=time.time()),
        updated_at=_db_datetime_to_epoch(getattr(session, "updated_at", None), fallback=time.time()),
        state=state,
        error=runtime.error,
    )
    if events:
        record.hydrate_events(events)
        for event in events:
            _apply_live_state_event_to_record(record, event)
    return record


async def _load_db_record(
    session_id: str,
    *,
    user: User | None = None,
    include_events: bool = True,
    hydrate_disk: bool = True,
    register: bool = True,
) -> SessionRecord | None:
    if not _DB_HISTORY_ENABLED:
        return None
    try:
        async with safe_session() as db:
            owner_scope = _db_owner_scope_for_user(user)
            session = await AutoResearchRepository.get_session(
                db,
                session_id,
                user_id=owner_scope,
            )
            if session is None:
                return None
            if not _can_access_db_session(session, user):
                raise HTTPException(status_code=403, detail="PathScientist session access denied")
            event_rows = (
                await AutoResearchRepository.get_session_events(
                    db,
                    session_id,
                    user_id=owner_scope,
                )
                if include_events
                else []
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("PathScientist DB session load skipped for %s: %s", session_id, exc)
        return None

    db_events = [_event_row_to_gateway_event(row) for row in event_rows]
    record = _db_session_to_record(session, db_events)
    if hydrate_disk and record.conversation_id:
        record = _hydrate_persisted_record_detail(record)
        if db_events:
            record.hydrate_events(db_events)
    if register:
        record = _SESSION_MANAGER.register_hydrated(record)
    return record


async def _load_db_events(session_id: str, *, user: User | None = None) -> list[dict[str, Any]]:
    if not _DB_HISTORY_ENABLED:
        return []
    try:
        async with safe_session() as db:
            owner_scope = _db_owner_scope_for_user(user)
            session = await AutoResearchRepository.get_session(
                db,
                session_id,
                user_id=owner_scope,
            )
            if session is None:
                return []
            if not _can_access_db_session(session, user):
                raise HTTPException(status_code=403, detail="PathScientist session access denied")
            rows = await AutoResearchRepository.get_session_events(
                db,
                session_id,
                user_id=owner_scope,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("PathScientist DB event load skipped for %s: %s", session_id, exc)
        return []
    return [_event_row_to_gateway_event(row) for row in rows]


async def _load_db_session_list(
    *,
    user: User | None,
    include_persisted: bool,
    limit: int = 100,
) -> list[SessionRecord]:
    if not _DB_HISTORY_ENABLED:
        return []
    user_id = None if _user_is_admin(user) else str(getattr(user, "id", "") or "")
    if user is not None and not user_id and not _user_is_admin(user):
        return []
    try:
        async with safe_session() as db:
            sessions = await AutoResearchRepository.get_user_sessions(
                db,
                user_id,
                limit=limit,
            )
    except Exception as exc:
        logger.debug("PathScientist DB session list skipped: %s", exc)
        return []
    return [
        _db_session_to_record(session, events=[])
        for session in sessions
        if include_persisted or _is_curated_db_session(session)
    ]


def _user_is_admin(user: User | None) -> bool:
    if user is None:
        return False
    is_admin = getattr(user, "is_admin", None)
    if callable(is_admin):
        try:
            return bool(is_admin())
        except Exception:
            return False
    return getattr(user, "role", "") == "admin"


def _can_access_db_session(session: Any, user: User | None) -> bool:
    if user is None or _user_is_admin(user):
        return True
    owner = str(getattr(session, "user_id", "") or "")
    return bool(owner) and owner == str(getattr(user, "id", "") or "")


def _db_owner_scope_for_user(user: User | None) -> str | None:
    if user is None or _user_is_admin(user):
        return None
    user_id = str(getattr(user, "id", "") or "").strip()
    return user_id if user_id else "__pathscientist_no_authenticated_user__"


def _can_access_record(record: SessionRecord, user: User | None) -> bool:
    if user is None or _user_is_admin(user):
        return True
    owner = str(getattr(record, "user_id", "") or "").strip()
    return bool(owner) and owner == str(getattr(user, "id", "") or "")


def _claims_user(claims: dict[str, Any]) -> User:
    user = claims.get("user")
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _validate_pathscientist_access_claims(
    claims: dict[str, Any],
    *,
    session_id: str,
    purpose: str,
    run_id: str = "",
) -> User:
    user = _claims_user(claims)
    token_purpose = str(claims.get("purpose") or "")
    if token_purpose == "header":
        return user
    if token_purpose != purpose or str(claims.get("sid") or "") != session_id:
        raise HTTPException(status_code=403, detail="PathScientist access token scope denied")
    if purpose == "run_download" and str(claims.get("rid") or "") != run_id:
        raise HTTPException(status_code=403, detail="PathScientist access token scope denied")
    return user


def _pathscientist_no_referrer_headers(
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {"Referrer-Policy": "no-referrer"}
    if extra:
        headers.update(extra)
    return headers


def _is_curated_db_session(session: Any) -> bool:
    status = str(getattr(session, "status", "") or "")
    question = str(getattr(session, "research_question", "") or "").strip()
    return bool(question) and status not in {"error"}


def _merge_session_records(*groups: list[SessionRecord]) -> list[SessionRecord]:
    selected: dict[str, SessionRecord] = {}
    conversation_seen: dict[str, str] = {}
    for group in groups:
        for record in group:
            if _is_deleted_gateway_session(record, match_conversation=False):
                continue
            existing_key = selected.get(record.session_id)
            if existing_key is None:
                conv = _record_conversation_id(record)
                if conv and conv in conversation_seen:
                    existing = selected.get(conversation_seen[conv])
                    if existing is not None and _record_rank(existing) >= _record_rank(record):
                        continue
                    selected.pop(conversation_seen[conv], None)
                selected[record.session_id] = record
                if conv:
                    conversation_seen[conv] = record.session_id
                continue
            if _record_rank(record) > _record_rank(existing_key):
                selected[record.session_id] = record
    return sorted(selected.values(), key=lambda record: record.created_at, reverse=True)


def _record_rank(record: SessionRecord) -> int:
    rank = 0
    if record.status in {"queued", "running"}:
        rank += 100
    if record.events:
        rank += 10
    if record.state:
        rank += 5
    if record.user_id:
        rank += 2
    return rank


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


def _owner_from_persisted_summary(summary: dict[str, Any]) -> str:
    candidates: list[Any] = [
        summary.get("user_id"),
        summary.get("pathlab_user_id"),
        summary.get("owner_user_id"),
    ]
    research_session = summary.get("research_session")
    if isinstance(research_session, dict):
        candidates.extend([
            research_session.get("user_id"),
            research_session.get("pathlab_user_id"),
            research_session.get("owner_user_id"),
        ])
        recovery = research_session.get("recovery_metadata")
        if isinstance(recovery, dict):
            candidates.extend([
                recovery.get("user_id"),
                recovery.get("pathlab_user_id"),
                recovery.get("owner_user_id"),
            ])
    recovery = summary.get("recovery_metadata")
    if isinstance(recovery, dict):
        candidates.extend([
            recovery.get("user_id"),
            recovery.get("pathlab_user_id"),
            recovery.get("owner_user_id"),
        ])
    for value in candidates:
        owner = str(value or "").strip()
        if owner:
            return owner
    return ""


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


def _canonical_conversation_uuid(conversation_id: str) -> str:
    text = str(conversation_id or "").strip()
    if not text:
        return text
    if "-" in text:
        return text
    if len(text) == 32:
        return f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"
    return text


def _conversation_uuid(conversation_id: str):
    try:
        from uuid import UUID

        return UUID(_canonical_conversation_uuid(conversation_id))
    except Exception:
        return None


def _candidate_conversation_dirs(conversation_id: str, state: dict[str, Any] | None = None) -> list[Path]:
    state = state if isinstance(state, dict) else {}
    candidates: list[Path] = []
    for key in ("persistence_dir", "conversation_dir"):
        value = state.get(key)
        if value:
            candidates.append(Path(str(value)).expanduser())
    recovery = state.get("recovery_metadata")
    if isinstance(recovery, dict):
        for key in ("persistence_dir", "conversation_dir"):
            value = recovery.get(key)
            if value:
                candidates.append(Path(str(value)).expanduser())
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        for key in ("persistence_dir", "conversation_dir"):
            value = summary.get(key)
            if value:
                candidates.append(Path(str(value)).expanduser())

    if conversation_id:
        try:
            from backend.pathscientist.persistence.layout import get_persistence_root
            from backend.pathscientist.runtime.session import _resolve_base_dir

            root = Path(get_persistence_root(_resolve_base_dir()))
            candidates.extend([
                root / conversation_id,
                root / conversation_id.replace("-", ""),
            ])
        except Exception as exc:
            logger.debug("PathScientist conversation dir probe skipped: %s", exc)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _conversation_base_state_exists(
    conversation_id: str,
    state: dict[str, Any] | None = None,
) -> bool:
    return any((path / "base_state.json").is_file() for path in _candidate_conversation_dirs(conversation_id, state))


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
            user_id=_owner_from_persisted_summary(summary),
            # Avoid blocking the history list on many LLM calls. New web
            # sessions queue title generation at creation; legacy sessions get
            # a deterministic concise fallback unless already migrated later.
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


def _unique_nonempty_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _pathlab_dataset_slug(name: str, dataset_id: str) -> str:
    raw = str(name or dataset_id or "dataset").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if not slug:
        slug = "dataset"
    suffix = re.sub(r"[^a-z0-9]+", "", str(dataset_id or "").lower())[:8]
    if suffix and suffix not in slug:
        slug = f"{slug}_{suffix}"
    return slug[:96]


def _safe_slide_id(value: str) -> str:
    raw = str(value or "").strip() or uuid.uuid4().hex
    slide_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return (slide_id or uuid.uuid4().hex)[:180]


def _normalized_split(value: Any) -> str:
    split = str(value or "").strip().lower()
    if split in {"valid", "validation"}:
        return "val"
    return split if split in {"train", "val", "test"} else ""


def _unique_container_mount(container: str, used: set[str]) -> str:
    normalized = str(container or "").strip()
    if not normalized:
        normalized = "/data/dataset"
    if not normalized.startswith("/"):
        normalized = "/" + normalized.strip("/")
    normalized = normalized.rstrip("/") or "/data/dataset"
    candidate = normalized
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{normalized}_{suffix}"
    used.add(candidate)
    return candidate


def _add_data_mount(
    data_mounts: dict[str, str],
    used: set[str],
    host: str,
    container: str | None = None,
) -> None:
    host_path = str(host or "").strip()
    if not host_path:
        return
    if container is None:
        base = Path(host_path).name.lower() or "data"
        container = f"/data/{base}"
    data_mounts[host_path] = _unique_container_mount(container, used)


def _pathlab_dataset_view_parent() -> Path:
    base = _resolve_pathscientist_base_dir()
    return base / "pathlab_datasets" / "session_inputs"



def _normalize_dataset_match_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _dataset_match_aliases(value: str) -> set[str]:
    normalized = _normalize_dataset_match_text(value)
    if not normalized:
        return set()
    aliases = {normalized, normalized.replace(" ", "")}
    tokens = [token for token in normalized.split() if token]
    stop = {"dataset", "local"}
    meaningful = [token for token in tokens if token not in stop]
    if meaningful:
        aliases.add(" ".join(meaningful))
        aliases.add("".join(meaningful))
    return {alias for alias in aliases if alias}


def _dataset_alias_score(alias: str) -> int:
    tokens = alias.split()
    return max(len(alias), len(tokens) * 20)


def _match_pathlab_datasets_from_question(
    question: str,
    datasets: list[dict[str, Any]],
) -> list[str]:
    normalized_question = f" {_normalize_dataset_match_text(question)} "
    raw_question = str(question or "").lower()
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    for dataset in datasets:
        dataset_id = str(dataset.get("dataset_id") or "").strip()
        if not dataset_id or dataset_id in seen:
            continue
        dataset_name = str(dataset.get("dataset_name") or dataset.get("name") or "").strip()
        normalized_name = _normalize_dataset_match_text(dataset_name)
        normalized_id = _normalize_dataset_match_text(dataset_id)
        matched = False
        score = 0
        if dataset_id.lower() in raw_question:
            matched = True
            score = max(score, len(dataset_id) + 1000)
        if normalized_id and f" {normalized_id} " in normalized_question:
            matched = True
            score = max(score, len(normalized_id) + 900)
        name_aliases = _dataset_match_aliases(dataset_name)
        for alias in name_aliases:
            if alias and f" {alias} " in normalized_question:
                matched = True
                score = max(score, _dataset_alias_score(alias))
        if matched:
            seen.add(dataset_id)
            matches.append((score, dataset_id))
    matches.sort(key=lambda item: item[0], reverse=True)
    return [dataset_id for _score, dataset_id in matches]


async def _resolve_pathlab_dataset_mounts(
    dataset_ids: list[str],
    user: User,
    *,
    question: str = "",
) -> dict[str, str]:
    selected_ids = _unique_nonempty_strings(dataset_ids)
    explicit_selection = bool(selected_ids)
    if not selected_ids and not str(question or "").strip():
        return {}

    try:
        from backend.auth.dependencies import get_dataset_with_access, get_permitted_dataset_ids
        from backend.database.repositories import WSIRepository
    except Exception as exc:
        raise RuntimeError(f"PathLab dataset repository unavailable: {exc}") from exc

    mounts: dict[str, str] = {}
    used_containers: set[str] = set()
    view_session_dir = _pathlab_dataset_view_parent() / uuid.uuid4().hex[:12]
    try:
        async with safe_session() as db:
            user_id_filter = None if _user_is_admin(user) else str(getattr(user, "id", "") or "")
            elevated_dataset_ids = (
                await get_permitted_dataset_ids(user, db)
                if callable(getattr(user, "is_admin", None))
                else []
            )
            if not selected_ids:
                visible_datasets = await WSIRepository.get_datasets(
                    db,
                    data_type="wsi",
                    user_id=user_id_filter,
                    elevated_dataset_ids=elevated_dataset_ids,
                    limit=0,
                )
                selected_ids = _match_pathlab_datasets_from_question(question, visible_datasets)
            if not selected_ids:
                return {}
            for dataset_id in selected_ids:
                dataset = await get_dataset_with_access(
                    dataset_id,
                    user,
                    db,
                    not_found_detail=f"Dataset not found: {dataset_id}",
                    forbidden_detail="You don't have permission to use this dataset in PathScientist",
                )
                slides = await WSIRepository.get_by_dataset(
                    db,
                    dataset_id,
                    user_id=user_id_filter,
                    data_type="wsi",
                    elevated_dataset_ids=elevated_dataset_ids,
                    sort_by="original_filename",
                    sort_order="asc",
                )
                if not slides:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Dataset has no accessible WSI files: {dataset_id}",
                    )
                slug = _pathlab_dataset_slug(getattr(dataset, "name", ""), dataset_id)
                view_dir = _prepare_pathlab_dataset_view(
                    dataset=dataset,
                    slides=slides,
                    view_dir=view_session_dir / slug,
                )
                mounts[str(view_dir)] = _unique_container_mount(f"/data/{slug}", used_containers)
    except HTTPException:
        raise
    except Exception as exc:
        if explicit_selection:
            raise
        logger.debug("PathLab dataset auto-match skipped: %s", exc)
        return {}
    return mounts


_FEATURE_TENSOR_EXTS = (".pt", ".pth")


def _create_relative_view_symlink(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    try:
        rel_target = os.path.relpath(target_path, link_path.parent)
        os.symlink(rel_target, link_path)
    except OSError:
        os.symlink(target_path, link_path)


def _tcga_pathology_root_and_cohort(source: Path) -> tuple[Path, str] | None:
    try:
        resolved = source.resolve(strict=False)
    except OSError:
        resolved = source
    parts = resolved.parts
    lowered = [part.lower() for part in parts]
    for idx, part in enumerate(lowered):
        if part != "original_data":
            continue
        if idx + 2 >= len(parts) or lowered[idx + 1] != "tcga":
            continue
        root = Path(*parts[:idx]) if idx else Path(parts[0])
        cohort = str(parts[idx + 2]).strip()
        if cohort:
            return root, cohort
    return None


def _tcga_feature_stem_candidates(source: Path, original_filename: str) -> list[str]:
    candidates = [source.stem]
    if original_filename:
        original_stem = Path(original_filename).stem
        candidates.append(original_stem)
        if "__" in original_stem:
            candidates.append(original_stem.split("__", 1)[1])
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _discover_tcga_patches_feature_files(
    *,
    source: Path,
    original_filename: str,
) -> dict[str, Path]:
    root_and_cohort = _tcga_pathology_root_and_cohort(source)
    if root_and_cohort is None:
        return {}
    pathology_root, cohort = root_and_cohort
    cohort_dirs = []
    for name in (cohort, cohort.upper(), cohort.lower()):
        candidate = pathology_root / "Patches" / "TCGA" / f"TCGA-{name}" / "pt_files"
        if candidate not in cohort_dirs:
            cohort_dirs.append(candidate)
    stems = _tcga_feature_stem_candidates(source, original_filename)
    found: dict[str, Path] = {}
    for pt_root in cohort_dirs:
        if not pt_root.is_dir():
            continue
        try:
            extractor_dirs = sorted(path for path in pt_root.iterdir() if path.is_dir())
        except OSError:
            continue
        for extractor_dir in extractor_dirs:
            extractor = extractor_dir.name
            if extractor in found:
                continue
            for stem in stems:
                for suffix in _FEATURE_TENSOR_EXTS:
                    feature = extractor_dir / f"{stem}{suffix}"
                    if feature.is_file():
                        found[extractor] = feature
                        break
                if extractor in found:
                    break
    return found


def _link_existing_pathlab_features_for_view_slide(
    *,
    view_dir: Path,
    slide_id: str,
    source: Path,
    original_filename: str,
) -> dict[str, Path]:
    feature_files = _discover_tcga_patches_feature_files(
        source=source,
        original_filename=original_filename,
    )
    linked: dict[str, Path] = {}
    for extractor, feature_path in feature_files.items():
        link_path = view_dir / "features" / extractor / f"{slide_id}{feature_path.suffix.lower()}"
        try:
            _create_relative_view_symlink(link_path, feature_path)
        except OSError as exc:
            logger.debug(
                "Failed to link PathLab feature %s for PathScientist slide %s: %s",
                feature_path,
                slide_id,
                exc,
            )
            continue
        linked[extractor] = link_path
    return linked


def _prepare_pathlab_dataset_view(*, dataset: Any, slides: list[Any], view_dir: Path) -> Path:
    view_dir.mkdir(parents=True, exist_ok=True)
    wsi_dir = view_dir / "wsi_files"
    wsi_dir.mkdir(parents=True, exist_ok=True)
    for dirname in (
        "features",
        "training",
        "models",
        "logs",
        "progress",
        "metadata",
        "coordinates",
        "ai_results",
        "masks",
        "annotations",
    ):
        (view_dir / dirname).mkdir(exist_ok=True)

    rows: list[dict[str, str]] = []
    used_slide_ids: set[str] = set()
    missing_sources: list[str] = []
    linked_feature_count = 0
    linked_feature_extractors: set[str] = set()
    for slide in slides:
        source_raw = str(getattr(slide, "wsi_path", "") or "").strip()
        if not source_raw:
            continue
        source = Path(source_raw).expanduser()
        if not source.exists():
            missing_sources.append(str(getattr(slide, "wsi_id", "") or source.name))
            continue
        label = str(getattr(slide, "label", "") or "").strip()
        if not label:
            continue
        stem_source = str(getattr(slide, "wsi_id", "") or "").strip() or source.stem
        base_slide_id = _safe_slide_id(stem_source)
        slide_id = base_slide_id
        suffix = 1
        while slide_id in used_slide_ids:
            suffix += 1
            slide_id = _safe_slide_id(f"{base_slide_id}_{suffix}")
        used_slide_ids.add(slide_id)
        original_filename = str(getattr(slide, "original_filename", "") or "").strip()
        ext = source.suffix or Path(original_filename).suffix or ".svs"
        if not ext.startswith("."):
            ext = f".{ext}"
        link_path = wsi_dir / f"{slide_id}{ext}"
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        os.symlink(source, link_path)
        linked_features = _link_existing_pathlab_features_for_view_slide(
            view_dir=view_dir,
            slide_id=slide_id,
            source=source,
            original_filename=original_filename,
        )
        linked_feature_count += len(linked_features)
        linked_feature_extractors.update(linked_features)
        rows.append({
            "slide_id": slide_id,
            "label": label,
            "split": _normalized_split(getattr(slide, "split", "")),
        })

    if len(rows) < 3:
        raise HTTPException(
            status_code=400,
            detail="Selected dataset needs at least 3 accessible labeled WSI files for PathScientist.",
        )

    split_values = [row["split"] for row in rows]
    use_db_splits = all(split_values) and {"train", "val", "test"}.issubset(set(split_values))
    labels_path = view_dir / "labels.csv"
    with labels_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["slide_id", "label"] + (["split"] if use_db_splits else [])
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    try:
        from backend.pathscientist.dataset.wsi_splits import build_classification_splits_from_labels

        build_classification_splits_from_labels(labels_path, view_dir / "splits.json")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Selected dataset cannot be split for PathScientist: {exc}",
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"PathScientist split builder unavailable: {exc}") from exc

    label_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row["label"]] = label_counts.get(row["label"], 0) + 1
    manifest = {
        "dataset_id": str(getattr(dataset, "dataset_id", "") or ""),
        "dataset_name": str(getattr(dataset, "name", "") or ""),
        "layout": "pathlab_dataset_view",
        "wsi_dir": "wsi_files",
        "labels_file": "labels.csv",
        "splits_file": "splits.json",
        "num_wsi": len(rows),
        "classes": sorted(label_counts),
        "label_counts": label_counts,
        "source_organ": getattr(dataset, "source_organ", None),
        "missing_source_count": len(missing_sources),
        "feature_link_count": linked_feature_count,
        "feature_extractors": sorted(linked_feature_extractors),
    }
    (view_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return view_dir


def _merge_data_mounts(data_mounts: dict[str, str], extra_data_mounts: dict[str, str]) -> None:
    used = set(data_mounts.values())
    for host, container in (extra_data_mounts or {}).items():
        _add_data_mount(data_mounts, used, host, container)


def _container_path_join(root: str, *parts: str) -> str:
    clean = [str(part).strip("/") for part in parts if str(part or "").strip("/")]
    return "/".join([str(root or "").rstrip("/")] + clean)


def _pathlab_view_feature_leaf(view_dir: Path) -> Path | None:
    features_root = view_dir / "features"
    if not features_root.is_dir():
        return None
    for candidate in [features_root, *sorted(features_root.rglob("*"))]:
        if not candidate.is_dir():
            continue
        try:
            if any(path.is_file() and path.suffix.lower() in _FEATURE_TENSOR_EXTS for path in candidate.iterdir()):
                return candidate
        except OSError:
            continue
    return None


def _pathlab_view_manifest(view_dir: Path) -> dict[str, Any]:
    manifest_path = view_dir / "dataset_manifest.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _role_marker_positions(question: str) -> list[tuple[int, str]]:
    raw = str(question or "").lower()
    markers = (
        ("internal", "internal"),
        ("training", "internal"),
        ("train", "internal"),
        ("内部", "internal"),
        ("训练", "internal"),
        ("external validation", "external"),
        ("external", "external"),
        ("validation", "external"),
        ("validate", "external"),
        ("independent", "external"),
        ("验证", "external"),
        ("外部", "external"),
    )
    positions: list[tuple[int, str]] = []
    for marker, role in markers:
        start = 0
        while True:
            pos = raw.find(marker, start)
            if pos < 0:
                break
            positions.append((pos, role))
            start = pos + max(1, len(marker))
    positions.sort(key=lambda item: item[0])
    return positions


def _dataset_alias_raw_variants(alias: str) -> set[str]:
    alias_text = str(alias or "").strip().lower()
    if not alias_text:
        return set()
    variants = {alias_text}
    dashed = re.sub(r"\s+", "-", alias_text)
    underscored = re.sub(r"\s+", "_", alias_text)
    spaced_hyphen = re.sub(r"\s+", " - ", alias_text)
    variants.update({dashed, underscored, spaced_hyphen})
    return {item for item in variants if item}


def _alias_occurrences_in_question(question: str, aliases: set[str]) -> list[tuple[int, int]]:
    raw = str(question or "").lower()
    occurrences: list[tuple[int, int]] = []
    for alias in aliases:
        for variant in _dataset_alias_raw_variants(alias):
            start = 0
            while True:
                pos = raw.find(variant, start)
                if pos < 0:
                    break
                occurrences.append((pos, pos + len(variant)))
                start = pos + max(1, len(variant))
    return occurrences


def _role_for_alias_occurrences(
    question: str,
    occurrences: list[tuple[int, int]],
) -> str:
    markers = _role_marker_positions(question)
    best: tuple[int, int, str] | None = None
    for start, end in occurrences:
        for marker_pos, role in markers:
            if marker_pos <= start:
                distance = start - marker_pos
                if distance > 120:
                    continue
                side_penalty = 0
            else:
                distance = marker_pos - end
                if distance > 48:
                    continue
                side_penalty = 20
            candidate = (distance + side_penalty, 0 if role == "internal" else 1, role)
            if best is None or candidate < best:
                best = candidate
    return best[2] if best is not None else ""


def _classify_pathlab_mount_roles(question: str, mounts: dict[str, str]) -> dict[str, dict[str, str]]:
    roles: dict[str, dict[str, str]] = {}
    for host, container in mounts.items():
        view_dir = Path(str(host))
        manifest = _pathlab_view_manifest(view_dir)
        dataset_name = str(manifest.get("dataset_name") or view_dir.name).strip()
        aliases = _dataset_match_aliases(dataset_name) | _dataset_match_aliases(view_dir.name)
        role = _role_for_alias_occurrences(
            question,
            _alias_occurrences_in_question(question, aliases),
        )
        lower_name = _normalize_dataset_match_text(dataset_name)
        lower_view = _normalize_dataset_match_text(view_dir.name)
        if not role and (" external " in f" {lower_name} " or " external " in f" {lower_view} "):
            role = "external"
        if role:
            roles[role] = {
                "host": str(host),
                "container": str(container).rstrip("/"),
                "dataset_name": dataset_name,
            }
    return roles


def _pathlab_dataset_contract_updates(host: str, container: str) -> dict[str, str]:
    view_dir = Path(str(host))
    container_root = str(container).rstrip("/")
    updates: dict[str, str] = {
        "pathlab_uploads_dir": container_root,
        "data_layout": "pathlab_uploads",
    }
    wsi_dir = view_dir / "wsi_files"
    if wsi_dir.is_dir():
        updates["wsi_dir"] = _container_path_join(container_root, "wsi_files")
        updates["pathlab_wsi_files_dir"] = updates["wsi_dir"]
    images_dir = view_dir / "images"
    if images_dir.is_dir():
        updates["images_dir"] = _container_path_join(container_root, "images")
    splits_file = view_dir / "splits.json"
    if splits_file.is_file():
        updates["splits_file"] = _container_path_join(container_root, "splits.json")
    labels_json = view_dir / "labels.json"
    if labels_json.is_file():
        updates["labels_file"] = _container_path_join(container_root, "labels.json")
    feature_leaf = _pathlab_view_feature_leaf(view_dir)
    if feature_leaf is not None:
        rel = feature_leaf.relative_to(view_dir).as_posix()
        updates["features_dir"] = _container_path_join(container_root, rel)
        updates["external_features_ready"] = "true"
    return updates


def _set_contract_dataset_paths(contract: dict[str, Any], role: str, path: str) -> None:
    path_text = str(path or "").strip()
    if not path_text:
        return
    datasets = contract.setdefault("datasets", [])
    dataset = next(
        (item for item in datasets if isinstance(item, dict) and item.get("role") == role),
        None,
    )
    if dataset is None:
        dataset = {"role": role}
        datasets.append(dataset)
    paths = [str(item) for item in dataset.get("paths") or [] if str(item or "").strip()]
    if path_text not in paths:
        paths.append(path_text)
    dataset["paths"] = paths


def _external_task_type_from_request(req: StartPathScientistSessionRequest) -> str:
    explicit = str((req.external_test_contract or {}).get("external_task_type") or "").strip()
    if explicit:
        return explicit
    skill = str(req.skill or "").strip()
    if skill in {"patch_classification", "mil_classification", "survival", "segmentation"}:
        return skill
    question = f" {_normalize_dataset_match_text(req.question)} "
    if any(token in question for token in (" patch ", " patch level ", " patch classification ")):
        return "patch_classification"
    return "mil_classification"


def _apply_external_contract_from_pathlab_mounts(req: StartPathScientistSessionRequest, config: Any) -> None:
    mounts = dict(getattr(config, "data_mounts", {}) or {})
    if not mounts:
        return
    roles = _classify_pathlab_mount_roles(req.question, mounts)
    external = roles.get("external")
    if not external:
        return
    try:
        from backend.pathscientist.orchestrator.external_contract import (
            normalize_external_test_contract,
            update_external_dataset,
        )
    except Exception as exc:
        logger.debug("PathScientist external contract helper unavailable: %s", exc)
        return

    contract = normalize_external_test_contract(getattr(config, "external_test_contract", {}) or {})
    contract.setdefault("model_source", "best_run")
    contract.setdefault("external_task_type", _external_task_type_from_request(req))
    contract = update_external_dataset(
        contract,
        {
            "dataset_name": external.get("dataset_name", ""),
            **_pathlab_dataset_contract_updates(external["host"], external["container"]),
        },
    )
    _set_contract_dataset_paths(contract, "external", external.get("container", ""))
    internal = roles.get("internal")
    if internal:
        contract = normalize_external_test_contract(
            contract,
            training_data={
                "role": "internal",
                "dataset_name": internal.get("dataset_name", ""),
                "paths": [internal.get("container", "")],
            },
        )
        _set_contract_dataset_paths(contract, "internal", internal.get("container", ""))
    config.external_test_enabled = True
    config.external_test_contract = contract


def _path_is_within(parent: Path, child: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _pathscientist_wsi_files_under(root: Path) -> list[Path]:
    try:
        from backend.common.file_types import TIF_EXTENSIONS, WSI_EXTENSIONS
    except Exception:
        WSI_EXTENSIONS = frozenset({".svs", ".svslide", ".ndpi", ".scn", ".mrxs", ".bif", ".vsi", ".vms", ".vmu", ".kfb", ".sdpc", ".tmap", ".qptiff"})
        TIF_EXTENSIONS = frozenset({".tif", ".tiff"})
    allowed = {str(ext).lower() for ext in (set(WSI_EXTENSIONS) | set(TIF_EXTENSIONS))}
    root = Path(root)
    if not root.is_dir():
        return []
    try:
        return sorted(
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in allowed
        )
    except OSError:
        return []


def _read_pathscientist_label_map(path_value: Any) -> dict[str, str]:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_file():
        return {}
    labels: dict[str, str] = {}
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            for row in reader:
                slide_id = str(row.get("slide_id") or row.get("wsi_id") or row.get("filename") or "").strip()
                label = str(row.get("label") or row.get("class") or "").strip()
                if slide_id and label:
                    labels[Path(slide_id).stem] = label
    except OSError:
        return {}
    return labels


def _read_pathscientist_split_map(path_value: Any) -> dict[str, str]:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out
    for split in ("train", "val", "test"):
        values = payload.get(split) or []
        if not isinstance(values, list):
            continue
        for value in values:
            slide_id = Path(str(value or "")).stem
            if slide_id:
                out[slide_id] = split
    return out


def _pathscientist_dataset_display_name(state: dict[str, Any], manifest: dict[str, Any], raw_root: Path) -> str:
    selected = state.get("selected_dataset") if isinstance(state, dict) else {}
    if isinstance(selected, dict):
        name = str(selected.get("name") or "").strip()
        if name:
            return name
    prepared_contract = manifest.get("prepared_contract") if isinstance(manifest, dict) else {}
    if isinstance(prepared_contract, dict):
        datasets = prepared_contract.get("datasets")
        if isinstance(datasets, list) and datasets:
            names = [str(item.get("name") or item.get("dataset_id") or "").strip() for item in datasets if isinstance(item, dict)]
            names = [name for name in names if name]
            if names:
                return " + ".join(names[:3])
    return raw_root.parent.name or str(manifest.get("dataset_id") or "PathScientist dataset")


def _pathscientist_sync_wsi_id(dataset_id: str, slide_path: Path) -> str:
    raw = f"pathscientist:{dataset_id}:{slide_path.stem}"
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw).strip("._:-")
    return slug[:240] or uuid.uuid4().hex


async def _sync_pathscientist_manifest_to_pathlab(
    record: SessionRecord,
    state: dict[str, Any],
) -> dict[str, Any]:
    manifest_path_raw = str((state or {}).get("dataset_manifest_path") or "").strip()
    if not manifest_path_raw:
        return {"status": "skipped", "reason": "no_dataset_manifest"}
    manifest_path = Path(manifest_path_raw).expanduser()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "skipped", "reason": f"manifest_unreadable:{exc}"}
    if str(manifest.get("status") or "") != "prepared":
        return {"status": "skipped", "reason": "manifest_not_prepared"}
    try:
        from backend.pathscientist.dataset.pathlab_registration import (
            register_manifest_with_pathlab,
        )
        from backend.pathscientist.dataset.types import DatasetManifest
    except Exception as exc:
        return {"status": "skipped", "reason": f"repository_unavailable:{exc}"}

    owner_id = str(getattr(record, "user_id", "") or "") or None
    async with safe_session() as db:
        try:
            payload = await register_manifest_with_pathlab(
                db=db,
                manifest=DatasetManifest.from_dict(manifest),
                session_id=str(getattr(record, "session_id", "") or ""),
                user_id=owner_id,
            )
            await db.commit()
            return payload
        except Exception:
            await db.rollback()
            raise

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
        _add_data_mount(data_mounts, used, host)
    config.data_mounts = data_mounts
    config.pathlab_selected_datasets = list(req.dataset_ids or [])
    config.llm_model = config.llm_model or DEFAULT_MODEL
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


def _pathlab_feature_checkpoint_dir() -> Path:
    return SERVER_ROOT / "backend" / "ai" / "extractors" / "checkpoints"


def _normalize_pathscientist_model(model: str) -> str:
    """Return a LiteLLM/OpenHands-compatible model id."""
    model = str(model or "").strip()
    if not model:
        return ""
    if "/" in model:
        return model if model.startswith("openai/") else f"openai/{model}"
    return f"openai/{model}"


def _pathlab_llm_credentials() -> dict[str, str]:
    """Resolve reusable LLM credentials from PathLab global settings.

    PathScientist keeps its own execution model/profile because the OpenHands
    Codex runtime requires a Codex-compatible model. PathLab's OpenRouter
    fields are still reused as the shared OpenAI-compatible relay credentials.
    """
    try:
        settings = Config.get_global_settings()
    except Exception as exc:
        logger.debug("PathLab LLM credentials unavailable for PathScientist: %s", exc)
        return {}

    openrouter_key = str(settings.get("openrouter_api_key") or "").strip()
    openrouter_base_url = str(settings.get("openrouter_base_url") or "").strip()
    if openrouter_base_url or openrouter_key:
        return {
            "base_url": openrouter_base_url,
            "api_key": openrouter_key,
        }

    return {}


def _pathlab_huggingface_token() -> str:
    """Return the PathLab global Hugging Face token for PathScientist."""
    try:
        settings = Config.get_global_settings()
    except Exception as exc:
        logger.debug("PathLab Hugging Face token unavailable for PathScientist: %s", exc)
        return ""
    return str(settings.get("huggingface_token") or "").strip()


def _apply_pathscientist_llm_defaults(config: Any) -> None:
    """Apply the Gateway LLM defaults used by OpenHands PathScientist runs."""
    credentials = _pathlab_llm_credentials()
    config.llm_model = DEFAULT_MODEL
    config.llm_base_url = credentials.get("base_url") or str(getattr(config, "llm_base_url", "") or "")
    config.llm_api_key = credentials.get("api_key") or str(getattr(config, "llm_api_key", "") or "")
    config.llm_profile = DEFAULT_LLM_PROFILE
    config.llm_wire_api = DEFAULT_LLM_WIRE_API
    os.environ["PATHSCIENTIST_LLM_MODEL"] = config.llm_model
    os.environ["PATHSCIENTIST_LLM_BASE_URL"] = config.llm_base_url
    os.environ["PATHSCIENTIST_LLM_API_KEY"] = config.llm_api_key
    os.environ["PATHSCIENTIST_LLM_PROFILE"] = config.llm_profile
    os.environ["PATHSCIENTIST_LLM_WIRE_API"] = config.llm_wire_api


def _apply_pathlab_huggingface_token(config: Any) -> bool:
    """Apply PathLab global HF token over PathScientist-specific token env."""
    token = _pathlab_huggingface_token()
    if not token:
        return False

    config.huggingface_token = token
    os.environ["PATHSCIENTIST_HUGGINGFACE_TOKEN"] = token
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    return True


def _default_pathscientist_dataset_cache_dir() -> str:
    try:
        return str(Config.get_uploads_dir())
    except Exception as exc:
        logger.debug("PathLab uploads dir unavailable for PathScientist cache: %s", exc)
        return DEFAULT_DATASET_CACHE_DIR


def _apply_pathscientist_gateway_defaults(config: Any) -> None:
    """Apply frontend/backend Gateway defaults for PathScientist runs.

    ``PathScientistConfig.from_env()`` intentionally uses library defaults
    (safe/off for online search and downloads). Gateway-created sessions are
    the primary startup path, so set the operational defaults here instead of
    relying on the legacy bash launcher.
    """
    _apply_pathscientist_llm_defaults(config)

    _apply_pathlab_huggingface_token(config)
    _set_env_default("PATHLAB_CKPT_DIR", str(_pathlab_feature_checkpoint_dir()))

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
    default_cache_dir = _default_pathscientist_dataset_cache_dir()
    if _set_env_default("PATHSCIENTIST_DATASET_CACHE_DIR", default_cache_dir):
        config.dataset_cache_dir = default_cache_dir

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
async def create_session(
    req: StartPathScientistSessionRequest,
    user: User = Depends(current_active_user),
):
    try:
        dataset_mounts = await _resolve_pathlab_dataset_mounts(
            req.dataset_ids,
            user,
            question=req.question,
        )
        record = _SESSION_MANAGER.start(
            req,
            user_id=str(user.id),
            dataset_mounts=dataset_mounts,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return record.summary()


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    user: User = Depends(current_active_user),
):
    existing = _SESSION_MANAGER.get(session_id)
    if existing is not None and not _can_access_record(existing, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if existing is None:
        await _load_db_record(
            session_id,
            user=user,
            include_events=False,
            hydrate_disk=False,
            register=False,
        )
    record = _SESSION_MANAGER.stop(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    return record.summary()


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    req: StartPathScientistSessionRequest | None = None,
    user: User = Depends(current_active_user),
):
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        record = await _load_db_record(session_id, user=user)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    resume_req = req or StartPathScientistSessionRequest(
        question=record.question or "Continue PathScientist session",
    )
    if not resume_req.question:
        resume_req.question = record.question or "Continue PathScientist session"
    try:
        resumed = _SESSION_MANAGER.resume(record, resume_req)
    except SessionResumeRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return resumed.summary()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(current_active_user),
):
    existing = _SESSION_MANAGER.get(session_id)
    if existing is not None and not _can_access_record(existing, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if existing is None:
        await _load_db_record(
            session_id,
            user=user,
            include_events=False,
            hydrate_disk=False,
            register=False,
        )
    try:
        result = _SESSION_MANAGER.delete(session_id)
    except SessionDeleteRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    return result


@router.get("/sessions")
async def list_sessions(
    include_persisted: bool = False,
    user: User = Depends(current_active_user),
):
    records = _merge_session_records(
        await _load_db_session_list(user=user, include_persisted=include_persisted),
        [
            record for record in _SESSION_MANAGER.list(include_persisted=include_persisted)
            if _can_access_record(record, user)
        ],
    )
    return {"items": [record.summary() for record in records]}


@router.post("/sessions/{session_id}/access-token")
async def mint_pathscientist_access_token(
    session_id: str,
    request: PathScientistAccessTokenRequest,
    user: User = Depends(current_active_user),
):
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        record = await _load_db_record(session_id, user=user)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    if request.purpose == "run_download" and not _is_safe_run_id(request.run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")

    token, expires_in = create_pathscientist_access_token(
        user=user,
        session_id=session_id,
        purpose=request.purpose,
        run_id=request.run_id,
    )
    return {
        "token": token,
        "token_type": "pathscientist_access",
        "purpose": request.purpose,
        "session_id": session_id,
        "run_id": request.run_id if request.purpose == "run_download" else "",
        "expires_in": expires_in,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(current_active_user),
):
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        record = await _load_db_record(session_id, user=user)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    state = _session_detail_state(record)
    return {
        **record.summary(),
        "state": state,
        "events": record.events,
    }


@router.get("/sessions/{session_id}/download")
async def download_session_artifacts(
    session_id: str,
    access_claims: dict[str, Any] = Depends(get_pathscientist_header_or_access_token_claims),
):
    user = _validate_pathscientist_access_claims(
        access_claims,
        session_id=session_id,
        purpose="session_download",
    )
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        record = await _load_db_record(session_id, user=user)
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")

    workspace = _resolve_session_workspace(record)
    if workspace is None:
        raise HTTPException(status_code=404, detail="PathScientist workspace not found")

    try:
        zip_path = _build_session_artifact_zip(record, workspace)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filename = f"pathscientist-{session_id}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        headers=_pathscientist_no_referrer_headers(),
        background=BackgroundTask(lambda path=zip_path: Path(path).unlink(missing_ok=True)),
    )


@router.get("/sessions/{session_id}/runs/{run_id}/download")
async def download_run_artifacts(
    session_id: str,
    run_id: str,
    access_claims: dict[str, Any] = Depends(get_pathscientist_header_or_access_token_claims),
):
    user = _validate_pathscientist_access_claims(
        access_claims,
        session_id=session_id,
        purpose="run_download",
        run_id=run_id,
    )
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        record = await _load_db_record(session_id, user=user)
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
        headers=_pathscientist_no_referrer_headers(),
        background=BackgroundTask(lambda path=zip_path: Path(path).unlink(missing_ok=True)),
    )


@router.get("/sessions/{session_id}/events")
async def stream_session_events(
    session_id: str,
    access_claims: dict[str, Any] = Depends(get_pathscientist_access_token_claims),
):
    user = _validate_pathscientist_access_claims(
        access_claims,
        session_id=session_id,
        purpose="events",
    )
    record = _SESSION_MANAGER.get(session_id)
    if record is not None and not _can_access_record(record, user):
        raise HTTPException(status_code=403, detail="PathScientist session access denied")
    if record is None:
        db_record = await _load_db_record(session_id, user=user)
        if db_record is not None:
            record = db_record
    if record is None:
        raise HTTPException(status_code=404, detail="PathScientist session not found")
    if record.status not in {"queued", "running"}:
        db_events = await _load_db_events(session_id, user=user)
        if db_events:
            record.hydrate_events(db_events)
        elif not record.events and record.conversation_id:
            record = _hydrate_persisted_record_detail(record)

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
            "Referrer-Policy": "no-referrer",
            "X-Accel-Buffering": "no",
        },
    )


def _is_safe_run_id(run_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(run_id or "")))


def _record_state(record: SessionRecord) -> dict[str, Any]:
    return record.state if isinstance(record.state, dict) else {}


def _persist_record_state(
    record: SessionRecord,
    req: StartPathScientistSessionRequest | None = None,
) -> None:
    pathscientist_persistence.persist_session_state(
        session_id=record.session_id,
        user_id=record.user_id,
        question=record.question,
        status=record.status,
        stage=record.stage,
        state=_record_state(record),
        max_iterations=req.max_iter if req is not None else None,
        metric=req.metric if req is not None else "",
        model=record.model,
        workspace_path=str(_resolve_session_workspace(record) or ""),
    )


def _sync_pathscientist_manifest_to_pathlab_best_effort(
    record: SessionRecord,
    state: dict[str, Any],
) -> dict[str, Any]:
    try:
        return asyncio.run(_sync_pathscientist_manifest_to_pathlab(record, state))
    except Exception as exc:
        logger.warning("PathScientist PathLab dataset sync failed: %s", exc)
        return {"status": "failed", "reason": str(exc)}


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
        state.get("workspace_path"),
        state.get("workspace_dir"),
        state.get("workspace_root"),
    ]
    grounding = state.get("grounding")
    if isinstance(grounding, dict):
        candidates.extend([
            grounding.get("workspace_path"),
            grounding.get("workspace_dir"),
            grounding.get("workspace_root"),
        ])
    summary = state.get("persisted_summary")
    if isinstance(summary, dict):
        candidates.extend([
            summary.get("workspace_path"),
            summary.get("workspace_dir"),
            (summary.get("research_session") or {}).get("workspace_path")
            if isinstance(summary.get("research_session"), dict)
            else "",
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




def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _preferred_external_run_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    history = state.get("run_history")
    entries = [entry for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []
    if not entries:
        return []
    ordered: list[dict[str, Any]] = []
    best_run_id = str(state.get("best_run_id") or "").strip()
    if best_run_id:
        ordered.extend(entry for entry in entries if str(entry.get("run_id") or "") == best_run_id)
    ordered.extend(entry for entry in reversed(entries) if bool(entry.get("committed")))
    ordered.extend(reversed(entries))
    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in ordered:
        marker = id(entry)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(entry)
    return deduped


def _external_metrics_record_from_run(
    *,
    workspace: Path,
    run_entry: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(run_entry.get("run_id") or "").strip()
    if not run_id or not _is_safe_run_id(run_id):
        return {}
    run_dir = workspace / "output" / "runs" / run_id
    metrics = {}
    report = _read_json_file(run_dir / "external_test_report.json")
    report_metrics = report.get("external_test")
    if isinstance(report_metrics, dict) and report_metrics:
        metrics = dict(report_metrics)
    if not metrics:
        metrics_payload = _read_json_file(run_dir / "metrics.json")
        nested_external = metrics_payload.get("external_test")
        if isinstance(nested_external, dict) and nested_external:
            metrics = dict(nested_external)
    if not metrics:
        history_metrics = run_entry.get("metrics")
        nested_history_external = history_metrics.get("external_test") if isinstance(history_metrics, dict) else None
        if isinstance(nested_history_external, dict) and nested_history_external:
            metrics = dict(nested_history_external)
    if not metrics:
        return {}

    pathlab = run_entry.get("pathlab") if isinstance(run_entry.get("pathlab"), dict) else {}
    record: dict[str, Any] = {
        "run_id": run_id,
        "status": str(run_entry.get("external_test_status") or run_entry.get("status") or "completed"),
        "committed": bool(run_entry.get("committed")),
        "run_dir": str(run_dir),
        "metrics": metrics,
    }
    model_path = str(run_entry.get("model_path") or pathlab.get("model_path") or "").strip()
    if model_path:
        record["model_path"] = model_path
    for key in ("features_dir", "splits_file"):
        value = str(report.get(key) or "").strip()
        if value:
            record[key] = value
    return record


def _external_test_from_workspace(record: SessionRecord) -> dict[str, Any]:
    state = _record_state(record)
    workspace = _resolve_session_workspace(record)
    if workspace is None:
        return {}
    for run_entry in _preferred_external_run_entries(state):
        external = _external_metrics_record_from_run(workspace=workspace, run_entry=run_entry)
        if external:
            return external
    return {}


def _session_detail_state(record: SessionRecord) -> dict[str, Any]:
    state = dict(_record_state(record))
    has_external = bool(state.get("external_test"))
    history = state.get("external_test_history")
    has_external_history = bool(history) if isinstance(history, list) else False
    if not has_external and not has_external_history:
        external = _external_test_from_workspace(record)
        if external:
            state["external_test"] = external
    return state


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


def _latest_training_log(workspace: Path) -> Path | None:
    runs_dir = workspace / "output" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates: list[Path] = []
    try:
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            log_path = run_dir / "training.log"
            if log_path.is_file():
                candidates.append(log_path)
    except OSError:
        return None
    if not candidates:
        return None

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return mtime, str(path)

    return max(candidates, key=sort_key)


def _parse_training_metric_value(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _parse_training_epoch_line(line: str) -> dict[str, Any] | None:
    epoch_match = _TRAINING_EPOCH_RE.search(line)
    if not epoch_match:
        return None
    metrics: dict[str, float] = {}
    for name, raw_value in _TRAINING_METRIC_RE.findall(line):
        parsed = _parse_training_metric_value(raw_value)
        if parsed is not None:
            metrics[name] = parsed
    return {
        "current_epoch": int(epoch_match.group(1)),
        "total_epochs": int(epoch_match.group(2)),
        "current_metrics": metrics,
    }


def _training_progress_from_log(log_path: Path) -> dict[str, Any]:
    current: dict[str, Any] | None = None
    best_val_auc: float | None = None
    best_epoch: int | None = None
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = _parse_training_epoch_line(line)
                if parsed is None:
                    continue
                current = parsed
                val_auc = parsed["current_metrics"].get("val_auc")
                if isinstance(val_auc, float) and (best_val_auc is None or val_auc > best_val_auc):
                    best_val_auc = val_auc
                    best_epoch = int(parsed["current_epoch"])
    except OSError:
        return {}
    if current is None:
        return {}
    progress = dict(current)
    current_metrics = progress.get("current_metrics")
    if isinstance(current_metrics, dict):
        val_auc = current_metrics.get("val_auc")
        if isinstance(val_auc, float):
            progress["current_val_auc"] = val_auc
        val_loss = current_metrics.get("val_loss")
        if isinstance(val_loss, float):
            progress["current_val_loss"] = val_loss
        val_acc = current_metrics.get("val_acc")
        if isinstance(val_acc, float):
            progress["current_val_acc"] = val_acc
    if best_val_auc is not None:
        progress["best_val_auc"] = best_val_auc
    if best_epoch is not None:
        progress["best_epoch"] = best_epoch
    progress["run_id"] = log_path.parent.name
    try:
        progress["log_path"] = str(log_path.resolve())
        progress["updated_at"] = int(log_path.stat().st_mtime)
    except OSError:
        progress["log_path"] = str(log_path)
    return progress


def _training_progress_summary(record: SessionRecord) -> dict[str, Any]:
    workspace = _resolve_session_workspace(record)
    if workspace is None:
        return {}
    log_path = _latest_training_log(workspace)
    if log_path is None:
        return {}
    progress = _training_progress_from_log(log_path)
    if not progress:
        return {}
    run_id = str(progress.get("run_id") or "")
    run_entry = _run_history_entry(record.state, run_id) if isinstance(record.state, dict) else {}
    metadata = _run_metadata_entry(log_path.parent)
    if metadata:
        if "quick_check" in metadata:
            progress["quick_check"] = bool(metadata.get("quick_check"))
        run_kind = metadata.get("run_kind")
        if run_kind:
            progress["run_kind"] = str(run_kind)
    if run_entry:
        if "quick_check" in run_entry:
            progress["quick_check"] = bool(run_entry.get("quick_check"))
        run_kind = run_entry.get("run_kind")
        if run_kind:
            progress["run_kind"] = str(run_kind)
    return progress


def _run_metadata_entry(run_dir: Path) -> dict[str, Any]:
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _workspace_has_recent_training_log(workspace: Path | None, *, now: float | None = None) -> bool:
    if workspace is None:
        return False
    log_path = _latest_training_log(workspace)
    if log_path is None:
        return False
    now = time.time() if now is None else now
    try:
        age_seconds = max(0.0, now - log_path.stat().st_mtime)
    except OSError:
        return False
    return age_seconds <= TRAINING_LOG_ACTIVE_SECONDS


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
    base_dir = _resolve_pathscientist_base_dir().resolve(strict=False)
    allowed_roots = [workspace.resolve(strict=False)]
    if data_output_dir:
        data_root = Path(data_output_dir).expanduser().resolve(strict=False)
        if _path_under(data_root, workspace) or _path_under(data_root, base_dir):
            allowed_roots.append(data_root)
    if not any(_path_under(candidate, root) for root in allowed_roots):
        return None
    return candidate if candidate.is_file() else None


def _build_session_artifact_zip(record: SessionRecord, workspace: Path) -> str:
    """Create a zip containing session metadata, events, and workspace files."""
    workspace = workspace.resolve(strict=False)
    base_dir = _resolve_pathscientist_base_dir().resolve(strict=False)
    if workspace != base_dir and not workspace.is_relative_to(base_dir):
        raise FileNotFoundError("Workspace is outside PathScientist base dir")

    tmp = tempfile.NamedTemporaryFile(
        prefix=f"pathscientist-{record.session_id}-",
        suffix=".zip",
        delete=False,
    )
    tmp.close()
    existing: set[str] = set()
    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _zip_writestr_json(
            archive,
            "session.json",
            {
                **record.summary(),
                "state": _record_state(record),
                "events": record.events,
            },
        )
        if workspace.is_dir():
            for path in sorted(workspace.rglob("*")):
                if not path.is_file() or not _path_under(path, workspace):
                    continue
                rel = path.relative_to(workspace).as_posix()
                _add_file_to_zip(archive, existing, path, f"workspace/{rel}")
    return tmp.name


def _build_run_artifact_zip(record: SessionRecord, workspace: Path, run_id: str) -> str:
    """Create a zip containing one iteration's results and model artifacts."""
    workspace = workspace.resolve(strict=False)
    base_dir = _resolve_pathscientist_base_dir().resolve(strict=False)
    if workspace != base_dir and not workspace.is_relative_to(base_dir):
        raise FileNotFoundError("Workspace is outside PathScientist base dir")

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
