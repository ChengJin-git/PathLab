"""
Shared File-Based Training Progress Store

Trainers (AI Service) write progress to files under {uploads_dir}/progress/{task_id}.
Gateway SSE reads these files directly — no HTTP call, no DB lock.

Write: atomic (tmpfile + os.rename) to avoid partial reads.
Read: plain file read, returns None if file missing.
Crash recovery: files persist on disk, so last written progress survives process restart.
Cleanup: file deleted when task completes/fails.

Both AI Service and Gateway import this module (lives in backend.common).
"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from backend.common.config import Config

logger = logging.getLogger("progress_store")


def _get_progress_dir() -> Path:
    """Return the shared progress directory: {uploads_dir}/progress/"""
    return Config.get_uploads_dir() / "progress"


def set_progress(task_id: str, progress: int) -> None:
    """Write progress to file (atomic: tmpfile + rename).

    Called by trainers in AI Service process.
    File content is a plain integer string, e.g. "75".
    """
    progress_dir = _get_progress_dir()
    progress_file = progress_dir / task_id
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(progress_dir), prefix=f".{task_id}.")
        os.write(tmp_fd, str(progress).encode())
        os.close(tmp_fd)
        tmp_fd = None  # Mark as closed
        os.rename(tmp_path, str(progress_file))
    except Exception as e:
        logger.warning(f"Failed to write progress file (task={task_id}): {e}")
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def get_progress(task_id: str) -> Optional[int]:
    """Read progress from file.

    Called by Gateway SSE to overlay real-time progress onto DB task data.
    Returns None if file doesn't exist (task not running, or no progress yet).
    """
    try:
        progress_file = _get_progress_dir() / task_id
        content = progress_file.read_text().strip()
        return int(content)
    except (FileNotFoundError, ValueError, OSError):
        return None


def get_all_progress() -> Dict[str, int]:
    """Read progress for all active tasks.

    Scans the progress directory. Called by Gateway SSE /stream endpoint.
    Returns dict mapping task_id -> progress (0-100).
    """
    result: Dict[str, int] = {}
    progress_dir = _get_progress_dir()
    if not progress_dir.exists():
        return result
    try:
        for entry in progress_dir.iterdir():
            if entry.is_file() and not entry.name.startswith("."):
                try:
                    result[entry.name] = int(entry.read_text().strip())
                except (ValueError, OSError):
                    pass
    except OSError:
        pass
    return result


def clear_progress(task_id: str) -> None:
    """Delete progress file when task completes/fails/cancelled.

    Called in cleanup to avoid stale files.
    """
    try:
        (_get_progress_dir() / task_id).unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_all_progress() -> int:
    """Delete ALL progress files. Called on Gateway startup.

    On startup no training is running yet (interrupted tasks are about to be resumed),
    so every file in the progress directory is stale from the previous process lifetime.

    Returns:
        Number of files deleted.
    """
    count = 0
    progress_dir = _get_progress_dir()
    if not progress_dir.exists():
        return count
    try:
        for entry in progress_dir.iterdir():
            try:
                entry.unlink()
                count += 1
            except OSError:
                pass
    except OSError:
        pass
    if count > 0:
        logger.info(f"Cleaned up {count} stale progress file(s)")
    return count

