"""TTL-bounded JSON cache for ``FulltextDoc``.

FT-T2 of docs/plans/2026-05-01-autoresearch-fulltext-sota-extraction-plan.md.

Layout:

    <root>/
      papers/
        <paper_id_safe>/        # ":" / "/" / "\\" → "_"
          fulltext.json         # FulltextDoc.to_dict()

One file per paper keeps invalidation trivial (``clear(paper_id)`` =
``unlink``) and avoids contention on a single index file when concurrent
sessions write to the same persistence root.

TTL: ``success_ttl_days`` for ``success=True``, ``failure_ttl_days`` for
``success=False`` so we don't keep retrying broken URLs but freshly OA'd
papers retry sooner. Both default to the plan's recommended values.

Defensive read: corrupt JSON / unparseable timestamps return ``None`` so
the fetcher refetches rather than raising.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fulltext_types import FulltextDoc

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[/:\\\s]+")


def _safe_id(paper_id: str) -> str:
    """Filesystem-safe form of a canonical paper id.

    ``doi:10.1038/s41591-019-0462-y`` → ``doi_10.1038_s41591-019-0462-y``.
    Empty / whitespace ids fall back to the literal ``"_unknown"`` so the
    caller still gets a stable path (the fetcher should refuse those, but
    the cache mustn't crash).
    """
    s = (paper_id or "").strip()
    if not s:
        return "_unknown"
    safe = _UNSAFE_CHARS.sub("_", s)
    # Strip leading dots so the dir doesn't look like a dotfile dir.
    return safe.lstrip(".") or "_unknown"


class FulltextCache:
    """Per-paper JSON cache for ``FulltextDoc``.

    ``success_ttl_days`` (default 30) governs how long a successful fetch
    is reused; ``failure_ttl_days`` (default 7) governs how long we wait
    before retrying a broken URL. Tests can pass shorter values.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        success_ttl_days: int = 30,
        failure_ttl_days: int = 7,
    ) -> None:
        self._root = Path(root)
        self._success_ttl = timedelta(days=success_ttl_days)
        self._failure_ttl = timedelta(days=failure_ttl_days)

    def _path_for(self, paper_id: str) -> Path:
        return self._root / "papers" / _safe_id(paper_id) / "fulltext.json"

    def get(self, paper_id: str) -> FulltextDoc | None:
        path = self._path_for(paper_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(
                "FulltextCache: corrupt JSON at %s (%s); treating as miss",
                path, e,
            )
            return None
        if not isinstance(payload, dict):
            return None
        try:
            doc = FulltextDoc.from_dict(payload)
        except Exception as e:
            logger.warning(
                "FulltextCache: from_dict failed for %s (%s); treating as miss",
                paper_id, e,
            )
            return None

        # TTL check.
        when = _parse_iso(doc.fetched_at)
        if when is None:
            return None
        ttl = self._success_ttl if doc.success else self._failure_ttl
        if datetime.now(timezone.utc) - when > ttl:
            return None
        return doc

    def put(self, doc: FulltextDoc) -> None:
        path = self._path_for(doc.paper_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(doc.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def clear(self, paper_id: str) -> None:
        path = self._path_for(paper_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("FulltextCache.clear failed for %s: %s", paper_id, e)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp; tolerate trailing 'Z' (UTC)."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when
