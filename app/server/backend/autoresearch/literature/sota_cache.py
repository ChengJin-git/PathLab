"""JSON-backed cache for SotaTarget lookups.

Key = (dataset.lower(), task_type.lower(), metric.lower()). Value = SotaTarget
or None (negative cache). Positive entries live for ttl_days; negative entries
live for neg_ttl_hours (shorter so a new PwC leaderboard can be picked up sooner).

Designed to fail open: a corrupted cache file becomes an empty cache, not an
exception — the worst case is one extra online lookup.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .types import SotaTarget

logger = logging.getLogger(__name__)

# Sentinel: "this key was never looked up" (distinct from "we looked up and
# there is no published SOTA", which stores an explicit None).
class _MissType:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __repr__(self) -> str:
        return "Miss"
    def __bool__(self) -> bool:
        return False

Miss = _MissType()


class SotaCache:
    def __init__(self, path: Path, ttl_days: int = 30, neg_ttl_hours: int = 24):
        self._path = Path(path)
        self._ttl = timedelta(days=ttl_days)
        self._neg_ttl = timedelta(hours=neg_ttl_hours)

    @staticmethod
    def _key(dataset: str, task_type: str, metric: str) -> str:
        return f"{dataset.lower()}::{task_type.lower()}::{metric.lower()}"

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception as e:
            logger.warning("SotaCache load failed (%s); treating as empty", e)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))

    def get(self, dataset: str, task_type: str, metric: str):
        data = self._load()
        row = data.get(self._key(dataset, task_type, metric))
        if row is None:
            return Miss
        retrieved_at = row.get("retrieved_at", "")
        try:
            when = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except Exception:
            return Miss
        age = datetime.now(timezone.utc) - when
        is_negative = row.get("target") is None
        ttl = self._neg_ttl if is_negative else self._ttl
        if age > ttl:
            return Miss
        if is_negative:
            return None
        return SotaTarget.from_dict(row["target"])

    def put(self, dataset: str, task_type: str, metric: str,
            target: SotaTarget | None) -> None:
        data = self._load()
        data[self._key(dataset, task_type, metric)] = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "target": target.to_dict() if target is not None else None,
        }
        self._save(data)

    def get_metadata(self, dataset: str, task_type: str, metric: str) -> dict[str, Any] | None:
        """Plan-2026-04-28 P1 #5: expose cache-row metadata so callers
        (in particular ``SotaLookup`` log lines) can report
        ``retrieved_at`` + remaining TTL when a hit fires.

        Returns None when the row is absent or unparseable. Returns a
        dict with keys ``retrieved_at``, ``age_sec``, ``ttl_sec``,
        ``expires_in_sec``, ``is_negative`` otherwise. ``age_sec`` is
        always non-negative; a negative ``expires_in_sec`` would
        indicate the row has expired (the ``get()`` API treats that as
        Miss, so callers logging metadata before get() may see this).
        """
        data = self._load()
        row = data.get(self._key(dataset, task_type, metric))
        if row is None:
            return None
        retrieved_at = row.get("retrieved_at", "")
        try:
            when = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except Exception:
            return None
        is_negative = row.get("target") is None
        ttl = self._neg_ttl if is_negative else self._ttl
        age = datetime.now(timezone.utc) - when
        return {
            "retrieved_at": retrieved_at,
            "age_sec": int(age.total_seconds()),
            "ttl_sec": int(ttl.total_seconds()),
            "expires_in_sec": int((ttl - age).total_seconds()),
            "is_negative": is_negative,
        }
