"""Full-text fetch domain types.

FT-T1 of docs/plans/2026-05-01-pathscientist-fulltext-sota-extraction-plan.md.

These dataclasses are the cache-layer payload for ``FulltextFetcher`` and
the input to ``BenchmarkExtractor.extract_from_chunks``. They are frozen
so cached docs cannot be mutated through aliasing — every transformation
returns a fresh value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FulltextChunk:
    """A single span of paper content (abstract / section / table).

    ``section`` naming convention:
    - ``"abstract"`` (always present when OpenAlex has it)
    - ``"table_<n>"`` (one per ``<table>`` in document order)
    - ``"section_<slug>"`` where ``<slug>`` is the lowercased dash-separated
      heading text (e.g. ``"section_results"``)

    ``text`` is markdown for tables, plain text for sections / abstract.
    ``source_url`` is the URL the HTML came from (kept on each chunk so
    evidence pointers in the brief stay self-contained).
    """

    paper_id: str
    section: str
    text: str
    is_table: bool = False
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "section": self.section,
            "text": self.text,
            "is_table": self.is_table,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FulltextChunk":
        return cls(
            paper_id=data.get("paper_id", ""),
            section=data.get("section", ""),
            text=data.get("text", ""),
            is_table=bool(data.get("is_table", False)),
            source_url=data.get("source_url", ""),
        )


@dataclass(frozen=True)
class FulltextDoc:
    """A full-text fetch result for one paper.

    ``success=False`` is **cached** with a shorter TTL (handled by
    ``FulltextCache``) so we don't keep retrying broken URLs. Successful
    docs get the full TTL.
    """

    paper_id: str
    fetched_at: str            # ISO timestamp (UTC, with trailing 'Z' by convention)
    fetch_url: str             # original oa_url passed in
    success: bool
    error: str = ""            # populated when success=False
    chunks: list[FulltextChunk] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "fetched_at": self.fetched_at,
            "fetch_url": self.fetch_url,
            "success": self.success,
            "error": self.error,
            "chunks": [c.to_dict() for c in self.chunks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FulltextDoc":
        raw_chunks = data.get("chunks") or []
        chunks = [
            FulltextChunk.from_dict(c)
            for c in raw_chunks
            if isinstance(c, dict)
        ]
        return cls(
            paper_id=data.get("paper_id", ""),
            fetched_at=data.get("fetched_at", ""),
            fetch_url=data.get("fetch_url", ""),
            success=bool(data.get("success", False)),
            error=data.get("error", ""),
            chunks=chunks,
        )
