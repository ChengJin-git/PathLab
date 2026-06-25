"""JSON-backed cache for online paper-search results.

Plan-2026-04-29 literature-acquisition Phase 2 / Task 2.

Mirrors :class:`autoresearch.literature.sota_cache.SotaCache`:
positive entries live for ``ttl_days``, negative entries (clean upstream
miss) live for the shorter ``neg_ttl_hours`` so a freshly indexed paper
can show up sooner. Designed to fail open — a corrupt file becomes an
empty cache, never an exception.

Key shape: ``(query, organ, task_type, top_k, provider)``. Query and
filters are case-folded and whitespace-collapsed so cosmetic
differences don't fragment the cache.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .types import PaperRecord

logger = logging.getLogger(__name__)


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

_WS_RE = re.compile(r"\s+")


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", value.strip().lower())


class PaperCache:
    """JSON TTL cache for online paper-search results.

    Stage 1 of the cache layer: each consumer (OpenAlex, future
    Semantic Scholar) caches per-(query, filters, top_k) so two
    sessions with the same query reuse one round-trip.
    """

    def __init__(self, path: Path, ttl_days: int = 14, neg_ttl_hours: int = 6):
        self._path = Path(path)
        self._ttl = timedelta(days=ttl_days)
        self._neg_ttl = timedelta(hours=neg_ttl_hours)

    @staticmethod
    def _key(
        query: str,
        organ: str | None,
        task_type: str | None,
        top_k: int,
        provider: str,
    ) -> str:
        return (
            f"{_norm(provider)}::"
            f"{_norm(query)}::"
            f"{_norm(organ)}::"
            f"{_norm(task_type)}::"
            f"k={int(top_k)}"
        )

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("PaperCache load failed (%s); treating as empty", e)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(
        self,
        *,
        query: str,
        organ: str | None,
        task_type: str | None,
        top_k: int,
        provider: str,
    ):
        """Return cached papers, ``Miss`` for unknown key, or ``[]`` for a
        cached negative result."""
        data = self._load()
        row = data.get(self._key(query, organ, task_type, top_k, provider))
        if row is None:
            return Miss
        retrieved_at = row.get("retrieved_at", "")
        try:
            when = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except Exception:
            return Miss
        is_negative = not row.get("papers")
        ttl = self._neg_ttl if is_negative else self._ttl
        if datetime.now(timezone.utc) - when > ttl:
            return Miss
        if is_negative:
            return []
        return [PaperRecord.from_dict(p) for p in row.get("papers", [])]

    def put(
        self,
        *,
        query: str,
        organ: str | None,
        task_type: str | None,
        top_k: int,
        provider: str,
        papers: list[PaperRecord],
    ) -> None:
        data = self._load()
        data[self._key(query, organ, task_type, top_k, provider)] = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "papers": [p.to_dict() for p in papers],
        }
        self._save(data)

    def get_metadata(
        self,
        *,
        query: str,
        organ: str | None,
        task_type: str | None,
        top_k: int,
        provider: str,
    ) -> dict[str, Any] | None:
        """Return per-row metadata for diagnostics: age, TTL, expiry."""
        data = self._load()
        row = data.get(self._key(query, organ, task_type, top_k, provider))
        if row is None:
            return None
        retrieved_at = row.get("retrieved_at", "")
        try:
            when = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except Exception:
            return None
        is_negative = not row.get("papers")
        ttl = self._neg_ttl if is_negative else self._ttl
        age = datetime.now(timezone.utc) - when
        return {
            "retrieved_at": retrieved_at,
            "age_sec": int(age.total_seconds()),
            "ttl_sec": int(ttl.total_seconds()),
            "expires_in_sec": int((ttl - age).total_seconds()),
            "is_negative": is_negative,
        }

    def invalidate(
        self,
        *,
        query: str,
        organ: str | None,
        task_type: str | None,
        top_k: int,
        provider: str,
    ) -> bool:
        """Drop a single cache entry. Returns True if it existed."""
        data = self._load()
        key = self._key(query, organ, task_type, top_k, provider)
        if key in data:
            del data[key]
            self._save(data)
            return True
        return False
