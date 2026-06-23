"""Citation data models shared by deterministic M8a modules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

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
    entry_type: Optional[str] = None
    journal: Optional[str] = None
    booktitle: Optional[str] = None
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    arxiv_id: Optional[str] = None
    publication_type: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    s2_paper_id: Optional[str] = None
    openalex_id: Optional[str] = None
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
            entry_type=data.get("entry_type") or data.get("entryType"),
            journal=data.get("journal"),
            booktitle=data.get("booktitle"),
            volume=str(data["volume"]) if data.get("volume") else None,
            number=str(data["number"]) if data.get("number") else None,
            pages=data.get("pages"),
            publisher=data.get("publisher"),
            arxiv_id=data.get("arxiv_id") or data.get("arxivId"),
            publication_type=data.get("publication_type") or data.get("publicationType"),
            doi=data.get("doi") or data.get("DOI"),
            pmid=str(data["pmid"]) if data.get("pmid") else None,
            s2_paper_id=data.get("s2_paper_id") or data.get("paperId"),
            openalex_id=data.get("openalex_id") or data.get("openalexId"),
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
            "entry_type": self.entry_type,
            "journal": self.journal,
            "booktitle": self.booktitle,
            "volume": self.volume,
            "number": self.number,
            "pages": self.pages,
            "publisher": self.publisher,
            "arxiv_id": self.arxiv_id,
            "publication_type": self.publication_type,
            "doi": self.doi,
            "pmid": self.pmid,
            "s2_paper_id": self.s2_paper_id,
            "openalex_id": self.openalex_id,
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
        if self.openalex_id:
            return f"openalex:{self.openalex_id}"
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
    entry_type: Optional[str] = None
    journal: Optional[str] = None
    booktitle: Optional[str] = None
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    arxiv_id: Optional[str] = None
    publication_type: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    s2_paper_id: Optional[str] = None
    openalex_id: Optional[str] = None
    url: Optional[str] = None
    source: str = "manual"
    cluster: Optional[str] = None
    query: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: int = 0
    required: bool = False
    added_by: Literal["agent", "user"] = "agent"

    @classmethod
    def from_candidate(
        cls,
        candidate: CitationCandidate,
        *,
        key: str,
        required: bool = False,
        added_by: Literal["agent", "user"] = "agent",
    ) -> "CitationReference":
        return cls(
            key=key,
            title=candidate.title,
            authors=candidate.authors,
            year=candidate.year,
            venue=candidate.venue,
            entry_type=candidate.entry_type,
            journal=candidate.journal,
            booktitle=candidate.booktitle,
            volume=candidate.volume,
            number=candidate.number,
            pages=candidate.pages,
            publisher=candidate.publisher,
            arxiv_id=candidate.arxiv_id,
            publication_type=candidate.publication_type,
            doi=candidate.doi,
            pmid=candidate.pmid,
            s2_paper_id=candidate.s2_paper_id,
            openalex_id=candidate.openalex_id,
            url=candidate.url,
            source=candidate.source,
            cluster=candidate.cluster,
            query=candidate.query,
            abstract=candidate.abstract,
            citation_count=candidate.citation_count,
            required=required,
            added_by=added_by,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationReference":
        authors_value = data.get("authors") or ()
        if isinstance(authors_value, str):
            authors = (authors_value,)
        else:
            authors = tuple(str(item) for item in authors_value if item)
        added_by = data.get("added_by") if data.get("added_by") in {"agent", "user"} else "agent"
        return cls(
            key=str(data.get("key") or ""),
            title=str(data.get("title") or ""),
            authors=authors,
            year=data.get("year"),
            venue=data.get("venue"),
            entry_type=data.get("entry_type"),
            journal=data.get("journal"),
            booktitle=data.get("booktitle"),
            volume=data.get("volume"),
            number=data.get("number"),
            pages=data.get("pages"),
            publisher=data.get("publisher"),
            arxiv_id=data.get("arxiv_id"),
            publication_type=data.get("publication_type"),
            doi=data.get("doi"),
            pmid=data.get("pmid"),
            s2_paper_id=data.get("s2_paper_id"),
            openalex_id=data.get("openalex_id"),
            url=data.get("url"),
            source=str(data.get("source") or "manual"),
            cluster=data.get("cluster"),
            query=data.get("query"),
            abstract=data.get("abstract"),
            citation_count=int(data.get("citation_count") or 0),
            required=bool(data.get("required", False)),
            added_by=added_by,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "entry_type": self.entry_type,
            "journal": self.journal,
            "booktitle": self.booktitle,
            "volume": self.volume,
            "number": self.number,
            "pages": self.pages,
            "publisher": self.publisher,
            "arxiv_id": self.arxiv_id,
            "publication_type": self.publication_type,
            "doi": self.doi,
            "pmid": self.pmid,
            "s2_paper_id": self.s2_paper_id,
            "openalex_id": self.openalex_id,
            "url": self.url,
            "source": self.source,
            "cluster": self.cluster,
            "query": self.query,
            "abstract": self.abstract,
            "citation_count": self.citation_count,
            "required": self.required,
            "added_by": self.added_by,
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
