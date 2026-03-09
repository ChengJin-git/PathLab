from __future__ import annotations

import time
import uuid
from math import ceil
from typing import Any, Optional


SCAN_SESSION_TTL_SECONDS = 30 * 60
MAX_SCAN_SESSIONS = 8
_scan_sessions: dict[str, dict[str, Any]] = {}


def _cleanup_expired_sessions() -> None:
    now = time.time()
    expired_ids = [scan_id for scan_id, session in _scan_sessions.items() if now - session["created_at"] > SCAN_SESSION_TTL_SECONDS]
    for scan_id in expired_ids:
        _scan_sessions.pop(scan_id, None)

    if len(_scan_sessions) > MAX_SCAN_SESSIONS:
        oldest = sorted(_scan_sessions.items(), key=lambda item: item[1]["created_at"])
        for scan_id, _ in oldest[:-MAX_SCAN_SESSIONS]:
            _scan_sessions.pop(scan_id, None)


def create_scan_session(*, directory: str, files: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    _cleanup_expired_sessions()

    scan_id = f"scan_{uuid.uuid4().hex[:16]}"
    valid_count = sum(1 for file in files if file.get("valid"))
    total_size = sum(int(file.get("size", 0) or 0) for file in files)
    wsi_count = sum(1 for file in files if file.get("data_type") == "wsi")
    patch_count = sum(1 for file in files if file.get("data_type") == "patch")
    file_map = {file["path"]: file for file in files}

    session = {
        "scan_id": scan_id,
        "directory": directory,
        "files": files,
        "file_map": file_map,
        "valid_count": valid_count,
        "total_size": total_size,
        "wsi_count": wsi_count,
        "patch_count": patch_count,
        "user_id": user_id,
        "created_at": time.time(),
    }
    _scan_sessions[scan_id] = session
    return session


def get_scan_session(scan_id: str, user_id: str) -> Optional[dict[str, Any]]:
    _cleanup_expired_sessions()
    session = _scan_sessions.get(scan_id)
    if session is None or session["user_id"] != user_id:
        return None
    return session


def build_scan_response(session: dict[str, Any], *, page: int, page_size: int) -> dict[str, Any]:
    files = session["files"]
    total_count = len(files)
    total_pages = max(1, ceil(total_count / page_size)) if page_size > 0 else 1
    current_page = min(max(1, page), total_pages)
    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    page_files = files[start_idx:end_idx]

    return {
        "scan_id": session["scan_id"],
        "directory": session["directory"],
        "files": page_files,
        "total_count": total_count,
        "valid_count": session["valid_count"],
        "total_size": session["total_size"],
        "wsi_count": session["wsi_count"],
        "patch_count": session["patch_count"],
        "page": current_page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def resolve_scan_selection(
    session: dict[str, Any],
    *,
    select_all_valid: bool,
    selected_paths: list[str],
    excluded_paths: list[str],
) -> list[dict[str, Any]]:
    if select_all_valid:
        excluded = set(excluded_paths)
        return [file for file in session["files"] if file.get("valid") and file["path"] not in excluded]

    seen: set[str] = set()
    file_map = session["file_map"]
    resolved_files: list[dict[str, Any]] = []
    for path in selected_paths:
        if path in seen:
            continue
        seen.add(path)
        if path in file_map and file_map[path].get("valid"):
            resolved_files.append(file_map[path])
    return resolved_files