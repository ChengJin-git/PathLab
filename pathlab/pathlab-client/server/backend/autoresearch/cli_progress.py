"""Runtime progress ticker for long CLI turns."""
from __future__ import annotations

import os
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, TextIO

from .cli_render import DIM, RESET, format_duration


Clock = Callable[[], float]


def _format_bytes(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f}{unit}"
        number /= 1024
    return f"{number:.1f}TB"


def _workspace_root_from_state(state: Any) -> Path | None:
    session = getattr(state, "session", None)
    workspace_dir = getattr(session, "workspace_dir", "") if session is not None else ""
    if workspace_dir:
        return Path(workspace_dir)
    workspace = getattr(state, "workspace", None)
    root = getattr(workspace, "root", "") if workspace is not None else ""
    return Path(root) if root else None


def _workspace_root_from_conversation_state(conversation_state: Any) -> Path | None:
    if conversation_state is None:
        return None
    try:
        agent_state = getattr(conversation_state, "agent_state", {}) or {}
    except Exception:
        return None
    for container in (agent_state, agent_state.get("research_session", {}) or {}):
        for key in ("workspace_dir", "workspace_root"):
            value = container.get(key) if isinstance(container, dict) else ""
            if value:
                return Path(value)
    return None


def load_download_progress_for_state(
    state: Any,
    conversation_state: Any | None = None,
) -> dict[str, Any]:
    root = _workspace_root_from_state(state)
    if root is None:
        root = _workspace_root_from_conversation_state(conversation_state)
    if root is None:
        return {}
    path = root / ".dataset" / "download_progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def format_download_progress_inline(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    provider = str(payload.get("provider") or "?")
    dataset_id = str(payload.get("dataset_id") or "?")
    files_done = int(payload.get("files_done") or 0)
    files_total = int(payload.get("files_total") or 0)
    downloaded = int(payload.get("downloaded_bytes") or 0)
    total = int(payload.get("bytes_total") or 0)
    current = str(payload.get("current_file") or "")
    current_bytes = int(payload.get("current_bytes") or 0)
    current_total = int(payload.get("current_total_bytes") or 0)
    speed = float(payload.get("speed_bps") or 0.0)
    eta = payload.get("eta_seconds")

    parts = [f"download={provider} {dataset_id}"]
    if files_total:
        parts.append(f"files={files_done}/{files_total}")
    elif files_done:
        parts.append(f"files={files_done}")
    if total:
        parts.append(f"bytes={_format_bytes(downloaded)}/{_format_bytes(total)}")
    elif downloaded:
        parts.append(f"bytes={_format_bytes(downloaded)}")
    if current:
        current_part = f"current={current}"
        if current_total:
            current_part += f" {_format_bytes(current_bytes)}/{_format_bytes(current_total)}"
        elif current_bytes:
            current_part += f" {_format_bytes(current_bytes)}"
        parts.append(current_part)
    if speed > 0:
        parts.append(f"speed={_format_bytes(speed)}/s")
    if eta is not None:
        try:
            parts.append(f"eta={format_duration(float(eta))}")
        except (TypeError, ValueError):
            pass
    return " | ".join(parts)


def format_download_progress_status(payload: dict[str, Any]) -> str:
    inline = format_download_progress_inline(payload)
    if not inline:
        return ""
    if inline.startswith("download="):
        inline = "Download: " + inline[len("download="):]
    status = str(payload.get("status") or "")
    return f"{inline} | status={status}" if status else inline


def _env_enabled() -> bool:
    value = os.environ.get("AUTORESEARCH_PROGRESS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _env_interval() -> float:
    raw = os.environ.get("AUTORESEARCH_PROGRESS_INTERVAL", "10").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 10.0


class ProgressTicker:
    """Print compact progress lines while a blocking CLI turn is running."""

    def __init__(
        self,
        cli_state: Any,
        *,
        stream: TextIO | None = None,
        interval: float | None = None,
        enabled: bool | None = None,
        clock: Clock | None = None,
    ):
        self._cli_state = cli_state
        self._stream = stream or sys.stderr
        self._interval = interval if interval is not None else _env_interval()
        self._enabled = _env_enabled() if enabled is None else enabled
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._label = "run"
        self._started_at = 0.0
        self._event_count = 0
        self._last_event_name = ""
        self._last_event_at = 0.0
        self._conversation_state: Any = None

    def attach_conversation_state(self, conversation_state: Any) -> None:
        """Attach OpenHands conversation state so stage/iteration can be read."""
        with self._lock:
            self._conversation_state = conversation_state

    def start(self, label: str = "run", *, start_thread: bool = True) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._label = label
            self._started_at = self._clock()
            self._stop.clear()
        if start_thread:
            self.emit()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self.emit(final=True)

    def record_event(self, event: Any) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._event_count += 1
            self._last_event_name = event.__class__.__name__
            self._last_event_at = self._clock()

    def emit(self, *, final: bool = False) -> None:
        if not self._enabled:
            return
        line = self.format_snapshot(final=final)
        self._stream.write(f"{DIM}{line}{RESET}\n")
        self._stream.flush()

    def format_snapshot(self, *, final: bool = False) -> str:
        with self._lock:
            now = self._clock()
            started_at = self._started_at or now
            elapsed = max(0.0, now - started_at)
            event_count = self._event_count
            last_event_name = self._last_event_name
            last_event_at = self._last_event_at
            label = self._label
            conversation_state = self._conversation_state

        stage, iteration, max_iterations, run_id = self._read_progress_state(
            conversation_state
        )
        if not stage:
            stage = getattr(getattr(self._cli_state, "research_state", None), "stage", "")
        if not stage:
            stage = "running"

        if iteration is None:
            tracker = getattr(self._cli_state, "tracker", None)
            if tracker is not None:
                iteration = getattr(tracker, "iteration", None)

        parts = [
            "[progress]",
            f"label={label}",
            f"elapsed={format_duration(elapsed)}",
            f"stage={stage}",
        ]
        if iteration is not None:
            if max_iterations:
                parts.append(f"iter={iteration}/{max_iterations}")
            else:
                parts.append(f"iter={iteration}")
        parts.append(f"events={event_count}")
        if last_event_name:
            age = max(0.0, now - last_event_at)
            parts.append(f"last={last_event_name} {format_duration(age)} ago")
        if run_id:
            parts.append(f"run={run_id}")
        download = format_download_progress_inline(
            load_download_progress_for_state(self._cli_state, conversation_state)
        )
        if download:
            parts.append(download)
        if final:
            parts.append("done")
        return " | ".join(parts)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.emit()

    @staticmethod
    def _read_progress_state(
        conversation_state: Any,
    ) -> tuple[str, int | None, int | None, str]:
        if conversation_state is None:
            return "", None, None, ""
        try:
            agent_state = getattr(conversation_state, "agent_state", {}) or {}
        except Exception:
            return "", None, None, ""
        research = agent_state.get("research_session", {}) or {}
        iteration_state = agent_state.get("iteration_state", {}) or {}
        tracker_state = agent_state.get("tracker_state", {}) or {}

        stage = str(research.get("stage", "") or "")
        iteration = research.get("iteration_index", tracker_state.get("iteration"))
        max_iterations = research.get("max_iterations")
        run_id = str(iteration_state.get("last_run_id", "") or "")
        return stage, iteration, max_iterations, run_id


try:
    from openhands.sdk.conversation.visualizer import ConversationVisualizerBase
except Exception:  # pragma: no cover - import availability is environment-specific.
    ConversationVisualizerBase = object  # type: ignore[misc,assignment]


class ProgressVisualizer(ConversationVisualizerBase):
    """Default OpenHands visualizer plus progress ticker event updates."""

    def __init__(self, ticker: ProgressTicker):
        from openhands.sdk.conversation.visualizer import DefaultConversationVisualizer

        self._ticker = ticker
        self._delegate = DefaultConversationVisualizer()

    def initialize(self, state: Any) -> None:
        self._delegate.initialize(state)
        self._ticker.attach_conversation_state(state)

    def on_event(self, event: Any) -> None:
        self._ticker.record_event(event)
        self._delegate.on_event(event)

    def create_sub_visualizer(self, agent_id: str):
        return self._delegate.create_sub_visualizer(agent_id)

    def set_ticker(self, ticker: ProgressTicker) -> None:
        self._ticker = ticker
        state = getattr(self._delegate, "_state", None)
        if state is not None:
            self._ticker.attach_conversation_state(state)
