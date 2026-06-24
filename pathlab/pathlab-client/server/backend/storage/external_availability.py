"""Persistent last-known availability cache for externally stored WSI files."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.common.config import Config

logger = logging.getLogger(__name__)

CACHE_FILE_NAME = ".external_availability_cache.json"
CACHE_VERSION = 1

UNKNOWN = "unknown"
AVAILABLE = "available"
UNAVAILABLE = "unavailable"
STALE = "stale"

_VALID_STATUSES = {UNKNOWN, AVAILABLE, UNAVAILABLE, STALE}
_lock = threading.RLock()


def _cache_file_path() -> Path:
    return Path(Config.get_uploads_dir()) / CACHE_FILE_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_cache() -> dict[str, Any]:
    return {"version": CACHE_VERSION, "updated_at": None, "wsi": {}, "datasets": {}}


def _default_entry() -> dict[str, Any]:
    return {
        "status": UNKNOWN,
        "reason": None,
        "checked_at": None,
        "checked_by": None,
    }


def _default_dataset_entry() -> dict[str, Any]:
    return {
        "status": UNKNOWN,
        "reason": None,
        "checked_at": None,
        "checked_by": None,
        "total_count": 0,
        "available_count": 0,
        "unavailable_count": 0,
    }


def _load_cache() -> dict[str, Any]:
    cache_file = _cache_file_path()
    if not cache_file.exists():
        return _empty_cache()

    try:
        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load external availability cache: %s", exc)
        return _empty_cache()

    if not isinstance(data, dict):
        return _empty_cache()
    if not isinstance(data.get("wsi"), dict):
        data["wsi"] = {}
    if not isinstance(data.get("datasets"), dict):
        data["datasets"] = {}
    data.setdefault("version", CACHE_VERSION)
    data.setdefault("updated_at", None)
    return data


def _save_cache(cache: dict[str, Any]) -> None:
    cache_file = _cache_file_path()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    tmp_file.replace(cache_file)


def is_external_path(path: str | os.PathLike[str] | None) -> bool:
    """Return true when a WSI path is outside the managed uploads directory."""
    if not path:
        return False

    abs_path = os.path.abspath(os.fspath(path))
    abs_uploads = os.path.abspath(os.fspath(Config.get_uploads_dir()))
    return not (abs_path == abs_uploads or abs_path.startswith(abs_uploads + os.sep))


def get_wsi_availability(wsi_id: str) -> dict[str, Any]:
    """Return cached availability for a WSI, defaulting to unknown."""
    with _lock:
        cache = _load_cache()
        entry = cache.get("wsi", {}).get(str(wsi_id))
        if not isinstance(entry, dict):
            return _default_entry()

        result = _default_entry()
        result.update(entry)
        if result.get("status") not in _VALID_STATUSES:
            result["status"] = UNKNOWN
        return result


def get_dataset_availability(dataset_id: str) -> dict[str, Any]:
    """Return cached dataset availability from the latest admin scan."""
    with _lock:
        cache = _load_cache()
        entry = cache.get("datasets", {}).get(str(dataset_id))
        if not isinstance(entry, dict):
            return _default_dataset_entry()

        result = _default_dataset_entry()
        result.update(entry)
        if result.get("status") not in _VALID_STATUSES:
            result["status"] = UNKNOWN
        return result


def record_wsi_availability(
    wsi_id: str,
    *,
    status: str,
    reason: str | None = None,
    checked_by: str,
) -> dict[str, Any]:
    """Persist last-known availability for one WSI and return the written entry."""
    normalized_status = status if status in _VALID_STATUSES else UNKNOWN
    entry = {
        "status": normalized_status,
        "reason": reason,
        "checked_by": checked_by,
        "checked_at": _now_iso(),
    }

    with _lock:
        cache = _load_cache()
        cache.setdefault("wsi", {})[str(wsi_id)] = entry
        cache["version"] = CACHE_VERSION
        cache["updated_at"] = entry["checked_at"]
        _save_cache(cache)
    return dict(entry)


def record_many_from_scan(result: dict[str, Any]) -> None:
    """Persist availability entries from `/storage/check-external-files` output."""
    dataset_rollups: dict[str, dict[str, Any]] = {}
    wsi_entries: dict[str, dict[str, Any]] = {}
    checked_at = _now_iso()

    for item in result.get("available", []) or []:
        if isinstance(item, dict) and item.get("wsi_id"):
            wsi_entries[str(item["wsi_id"])] = {
                "status": AVAILABLE,
                "reason": None,
                "checked_by": "admin_scan",
                "checked_at": checked_at,
            }
            dataset_id = item.get("dataset_id")
            if dataset_id:
                rollup = dataset_rollups.setdefault(
                    str(dataset_id),
                    {"total_count": 0, "available_count": 0, "unavailable_count": 0, "reason": None},
                )
                rollup["total_count"] += 1
                rollup["available_count"] += 1

    for item in result.get("unavailable", []) or []:
        if isinstance(item, dict) and item.get("wsi_id"):
            reason = str(item.get("reason") or "External storage unavailable")
            wsi_entries[str(item["wsi_id"])] = {
                "status": UNAVAILABLE,
                "reason": reason,
                "checked_by": "admin_scan",
                "checked_at": checked_at,
            }
            dataset_id = item.get("dataset_id")
            if dataset_id:
                rollup = dataset_rollups.setdefault(
                    str(dataset_id),
                    {"total_count": 0, "available_count": 0, "unavailable_count": 0, "reason": None},
                )
                rollup["total_count"] += 1
                rollup["unavailable_count"] += 1
                rollup["reason"] = rollup["reason"] or reason

    if not wsi_entries and not dataset_rollups:
        return

    with _lock:
        cache = _load_cache()
        wsi_cache = cache.setdefault("wsi", {})
        wsi_cache.update(wsi_entries)
        datasets = cache.setdefault("datasets", {})
        for dataset_id, rollup in dataset_rollups.items():
            unavailable_count = int(rollup["unavailable_count"])
            status = UNAVAILABLE if unavailable_count else AVAILABLE
            datasets[dataset_id] = {
                "status": status,
                "reason": rollup["reason"] if status == UNAVAILABLE else None,
                "checked_by": "admin_scan",
                "checked_at": checked_at,
                "total_count": int(rollup["total_count"]),
                "available_count": int(rollup["available_count"]),
                "unavailable_count": unavailable_count,
            }
        cache["version"] = CACHE_VERSION
        cache["updated_at"] = checked_at
        _save_cache(cache)


def _roll_up_ids_from_cache(wsi_ids: Iterable[str], wsi_cache: dict[str, Any]) -> dict[str, Any]:
    ids = [str(wsi_id) for wsi_id in wsi_ids]
    total_count = len(ids)
    available_count = 0
    unavailable_count = 0
    stale_count = 0
    known_count = 0

    for wsi_id in ids:
        entry = wsi_cache.get(wsi_id) if isinstance(wsi_cache, dict) else None
        if isinstance(entry, dict):
            status = entry.get("status")
            if status not in _VALID_STATUSES:
                status = UNKNOWN
        else:
            status = UNKNOWN

        if status == AVAILABLE:
            available_count += 1
            known_count += 1
        elif status == UNAVAILABLE:
            unavailable_count += 1
            known_count += 1
        elif status == STALE:
            stale_count += 1
            known_count += 1

    if unavailable_count:
        status = UNAVAILABLE
    elif stale_count:
        status = STALE
    elif known_count:
        status = AVAILABLE
    else:
        status = UNKNOWN

    return {
        "status": status,
        "total_count": total_count,
        "available_count": available_count,
        "unavailable_count": unavailable_count,
        "unknown_count": total_count - known_count,
        "stale_count": stale_count,
    }


def roll_up_dataset_availability(wsi_ids: Iterable[str]) -> dict[str, Any]:
    """Aggregate cached child WSI availability into a dataset-level status."""
    with _lock:
        cache = _load_cache()
        wsi_cache = cache.get("wsi", {})

    return _roll_up_ids_from_cache(wsi_ids, wsi_cache)


def roll_up_datasets_availability(
    wsi_ids_by_dataset: dict[str, Iterable[str]]
) -> dict[str, dict[str, Any]]:
    """Aggregate cached availability for multiple datasets with one cache read."""
    with _lock:
        cache = _load_cache()
        wsi_cache = cache.get("wsi", {})

    return {
        str(dataset_id): _roll_up_ids_from_cache(wsi_ids, wsi_cache)
        for dataset_id, wsi_ids in wsi_ids_by_dataset.items()
    }


def _parse_checked_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def should_short_circuit_open(wsi_id: str, cooldown_seconds: int = 300) -> bool:
    """Return true when a recent unavailable cache entry should block re-opening."""
    entry = get_wsi_availability(wsi_id)
    if entry.get("status") != UNAVAILABLE:
        return False

    checked_at = _parse_checked_at(entry.get("checked_at"))
    if checked_at is None:
        return True
    return (datetime.now(timezone.utc) - checked_at).total_seconds() < cooldown_seconds
