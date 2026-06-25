"""Download progress sidecar helpers for dataset acquisition."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable


Clock = Callable[[], float]

DOWNLOAD_PROGRESS_FILENAME = "download_progress.json"


def download_progress_path_for_workspace(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".dataset" / DOWNLOAD_PROGRESS_FILENAME


def _coerce_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class DownloadProgressReporter:
    """Write a compact JSON progress sidecar during provider downloads."""

    def __init__(
        self,
        path: Path,
        *,
        dataset_id: str,
        provider: str,
        raw_root: Path,
        clock: Clock | None = None,
        min_interval_seconds: float = 1.0,
        min_bytes_delta: int = 16 << 20,
    ):
        self.path = Path(path)
        self.dataset_id = dataset_id
        self.provider = provider
        self.raw_root = str(raw_root)
        self._clock = clock or time.time
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._min_bytes_delta = max(0, int(min_bytes_delta))
        self._payload: dict[str, Any] = {}
        self._started_at = 0.0
        self._last_write_at = 0.0
        self._last_write_bytes = 0
        self._completed_bytes = 0
        self._current_bytes = 0

    def start(
        self,
        *,
        files_total: int | None = None,
        bytes_total: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        now = self._clock()
        if not self._started_at:
            self._started_at = now
        self._payload.update({
            "status": "downloading",
            "dataset_id": self.dataset_id,
            "provider": self.provider,
            "raw_root": self.raw_root,
            "files_done": _coerce_int(self._payload.get("files_done")),
            "files_total": _coerce_int(files_total),
            "downloaded_bytes": self._completed_bytes + self._current_bytes,
            "bytes_total": _coerce_int(bytes_total),
            "current_file": str(self._payload.get("current_file") or ""),
            "current_file_index": _coerce_int(self._payload.get("current_file_index")),
            "current_bytes": self._current_bytes,
            "current_total_bytes": _coerce_int(self._payload.get("current_total_bytes")),
            "speed_bps": 0.0,
            "eta_seconds": None,
            "started_at": self._started_at,
            "updated_at": now,
        })
        if extra:
            self._payload.update(extra)
        self._write(force=True)

    def start_file(
        self,
        name: str,
        *,
        file_index: int | None = None,
        file_size: int | None = None,
    ) -> None:
        self._current_bytes = 0
        self._payload.update({
            "status": "downloading",
            "current_file": str(name or ""),
            "current_file_index": _coerce_int(file_index),
            "current_bytes": 0,
            "current_total_bytes": _coerce_int(file_size),
            "downloaded_bytes": self._completed_bytes,
        })
        self._write(force=True)

    def update_file(self, bytes_delta: int) -> None:
        self._current_bytes += _coerce_int(bytes_delta)
        self._payload["current_bytes"] = self._current_bytes
        self._payload["downloaded_bytes"] = self._completed_bytes + self._current_bytes
        self._write()

    def finish_file(self, *, bytes_written: int | None = None) -> None:
        if bytes_written is not None:
            self._current_bytes = _coerce_int(bytes_written)
        self._completed_bytes += self._current_bytes
        self._payload["files_done"] = _coerce_int(self._payload.get("files_done")) + 1
        self._payload["current_bytes"] = self._current_bytes
        self._payload["downloaded_bytes"] = self._completed_bytes
        self._write(force=True)
        self._current_bytes = 0

    def finish(self, status: str, *, reason: str = "") -> None:
        now = self._clock()
        self._payload["status"] = status
        self._payload["reason"] = reason
        self._payload["updated_at"] = now
        self._payload["finished_at"] = now
        self._write(force=True)

    def _write(self, *, force: bool = False) -> None:
        now = self._clock()
        downloaded = _coerce_int(self._payload.get("downloaded_bytes"))
        if not force:
            if (
                now - self._last_write_at < self._min_interval
                and downloaded - self._last_write_bytes < self._min_bytes_delta
            ):
                return
        elapsed = max(0.0, now - (self._started_at or now))
        speed = float(downloaded / elapsed) if elapsed > 0 else 0.0
        total = _coerce_int(self._payload.get("bytes_total"))
        remaining = max(0, total - downloaded) if total else 0
        eta = float(math.ceil(remaining / speed)) if speed > 0 and remaining else None
        self._payload["speed_bps"] = speed
        self._payload["eta_seconds"] = eta
        self._payload["updated_at"] = now

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._last_write_at = now
        self._last_write_bytes = downloaded
