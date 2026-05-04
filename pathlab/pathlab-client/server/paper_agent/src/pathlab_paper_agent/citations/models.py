"""Citation data models shared by deterministic M8a modules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

_NON_KEY_CHARS = re.compile(r"[^A-Za-z0-9_:-]+")


def normalize_title(value: str) -> str:
    """Normalize titles for similarity and deduplication."""
    lowered = value.casefold().strip()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def stable_key(value: str) -> str:
    """Return a deterministic BibTeX-safe key fragment."""
    cleaned = _NON_KEY_CHARS.sub("_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "ref"


@dataclass(frozen=True)
class CitationCandidate:
    """A raw paper candidate discovered from S2, PubMed, or manual fixtures."""

    title: str
    source: str = "manual"
    abstract: Optional[str] = None
    authors: tuple[str, ...] = ()
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    s2_paper_id: Optional[str] = None
    url: Optional[str] = None
    citation_count: int = 0
    query: Optional[str] = None
    cluster: Optional[str] = None
    claimed_title: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationCandidate":
        authors_value = data.get("authors") or ()
        if isinstance(authors_value, str):
            authors = (authors_value,)
        else:
            authors = tuple(str(item) for item in authors_value if item)
        year = data.get("year")
        try:
            parsed_year = int(year) if year is not None and year != "" else None
        except (TypeError, ValueError):
            parsed_year = None
        citation_count = data.get("citation_count", data.get("citationCount", 0))
        try:
            parsed_citations = int(citation_count or 0)
        except (TypeError, ValueError):
            parsed_citations = 0
        return cls(
            title=str(data.get("title") or ""),
            source=str(data.get("source") or "manual"),
            abstract=data.get("abstract"),
            authors=authors,
            year=parsed_year,
            venue=data.get("venue") or data.get("journal"),
            doi=data.get("doi") or data.get("DOI"),
            pmid=str(data["pmid"]) if data.get("pmid") else None,
            s2_paper_id=data.get("s2_paper_id") or data.get("paperId"),
            url=data.get("url"),
            citation_count=parsed_citations,
            query=data.get("query"),
            cluster=data.get("cluster"),
            claimed_title=data.get("claimed_title"),
            raw=dict(data.get("raw") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "pmid": self.pmid,
            "s2_paper_id": self.s2_paper_id,
            "url": self.url,
            "citation_count": self.citation_count,
            "query": self.query,
            "cluster": self.cluster,
            "claimed_title": self.claimed_title,
            "raw": self.raw,
        }

    @property
    def dedup_key(self) -> str:
        if self.s2_paper_id:
            return f"s2:{self.s2_paper_id}"
        if self.doi:
            return f"doi:{self.doi.casefold()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        return f"title:{normalize_title(self.title)}"


@dataclass(frozen=True)
class CitationReference:
    """A verified candidate selected for possible manuscript citation."""

    key: str
    title: str
    authors: tuple[str, ...] = ()
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    s2_paper_id: Optional[str] = None
    url: Optional[str] = None
    source: str = "manual"
    cluster: Optional[str] = None
    query: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: int = 0
    required: bool = False

    @classmethod
    def from_candidate(
        cls, candidate: CitationCandidate, *, key: str, required: bool = False
    ) -> "CitationReference":
        return cls(
            key=key,
            title=candidate.title,
            authors=candidate.authors,
            year=candidate.year,
            venue=candidate.venue,
            doi=candidate.doi,
            pmid=candidate.pmid,
            s2_paper_id=candidate.s2_paper_id,
            url=candidate.url,
            source=candidate.source,
            cluster=candidate.cluster,
            query=candidate.query,
            abstract=candidate.abstract,
            citation_count=candidate.citation_count,
            required=required,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationReference":
        authors_value = data.get("authors") or ()
        if isinstance(authors_value, str):
            authors = (authors_value,)
        else:
            authors = tuple(str(item) for item in authors_value if item)
        return cls(
            key=str(data.get("key") or ""),
            title=str(data.get("title") or ""),
            authors=authors,
            year=data.get("year"),
            venue=data.get("venue"),
            doi=data.get("doi"),
            pmid=data.get("pmid"),
            s2_paper_id=data.get("s2_paper_id"),
            url=data.get("url"),
            source=str(data.get("source") or "manual"),
            cluster=data.get("cluster"),
            query=data.get("query"),
            abstract=data.get("abstract"),
            citation_count=int(data.get("citation_count") or 0),
            required=bool(data.get("required", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "pmid": self.pmid,
            "s2_paper_id": self.s2_paper_id,
            "url": self.url,
            "source": self.source,
            "cluster": self.cluster,
            "query": self.query,
            "abstract": self.abstract,
            "citation_count": self.citation_count,
            "required": self.required,
        }


@dataclass(frozen=True)
class VerificationReport:
    """Verifier output including accepted candidates and rejected reasons."""

    verified: tuple[CitationCandidate, ...]
    rejected: tuple[dict[str, Any], ...]
    cutoff_year: Optional[int]
    min_title_similarity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": [item.to_dict() for item in self.verified],
            "rejected": list(self.rejected),
            "cutoff_year": self.cutoff_year,
            "min_title_similarity": self.min_title_similarity,
            "verified_count": len(self.verified),
            "rejected_count": len(self.rejected),
        }
