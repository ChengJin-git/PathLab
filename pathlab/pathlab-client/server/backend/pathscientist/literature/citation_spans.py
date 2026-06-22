"""LlamaIndex-style citation primitives for inline references.

Plan-2026-04-29 literature-acquisition Phase 4 / Task 1.

A ``CitationSpan`` is the smallest piece of evidence: a sentence-grade
quote with full provenance. ``LiteratureService.find_citation_spans()``
splits retrieved chunks into spans so an execution brief or paper draft
can cite sentence-level evidence rather than 512-token chunks.

A ``SourceNode`` wraps a span with retrieval-time metadata (score,
retrieval method) so callers can rank or filter.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CitationSpan:
    """Sentence-level citation unit anchored to a paper + chunk."""

    paper_canonical_id: str = ""
    chunk_id: str = ""
    quote: str = ""

    # Provenance
    page: int | None = None
    section: str = ""
    span_start: int | None = None  # char offset within chunk text
    span_end: int | None = None
    provider: str = ""              # "openalex" / "local_seed" / "rag_corpus"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationSpan":
        return cls(
            paper_canonical_id=data.get("paper_canonical_id", ""),
            chunk_id=data.get("chunk_id", ""),
            quote=data.get("quote", ""),
            page=data.get("page"),
            section=data.get("section", ""),
            span_start=data.get("span_start"),
            span_end=data.get("span_end"),
            provider=data.get("provider", ""),
        )


@dataclass
class SourceNode:
    """A CitationSpan plus retrieval-time metadata.

    LlamaIndex's NodeWithScore inspires this shape — the citation span
    is the literal evidence, the SourceNode adds how confident we are
    and how we got it.
    """

    span: CitationSpan
    score: float = 0.0
    retrieval_method: str = ""  # "hybrid" / "sparse" / "dense" / "cache"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span": self.span.to_dict(),
            "score": self.score,
            "retrieval_method": self.retrieval_method,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceNode":
        return cls(
            span=CitationSpan.from_dict(data.get("span", {}) or {}),
            score=float(data.get("score", 0.0) or 0.0),
            retrieval_method=data.get("retrieval_method", ""),
            extra=dict(data.get("extra", {}) or {}),
        )
