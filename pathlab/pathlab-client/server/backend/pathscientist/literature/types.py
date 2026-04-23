"""Literature data model — papers, baselines, and citations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaselineEntry:
    """One metric result reported in a paper."""
    method: str
    metric_name: str
    metric_value: float
    dataset: str
    context: str = ""
    paper_id: str = ""
    paper_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "dataset": self.dataset,
            "context": self.context,
            "paper_id": self.paper_id,
            "paper_title": self.paper_title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineEntry:
        return cls(**data)


@dataclass
class PaperRecord:
    """Structured representation of a scientific paper."""
    paper_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 0
    abstract: str = ""
    venue: str = ""
    source: str = "local"
    url: str = ""
    methods: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    baselines: list[BaselineEntry] = field(default_factory=list)
    organ: str = ""
    task_type: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "venue": self.venue,
            "source": self.source,
            "url": self.url,
            "methods": self.methods,
            "datasets": self.datasets,
            "baselines": [b.to_dict() for b in self.baselines],
            "organ": self.organ,
            "task_type": self.task_type,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperRecord:
        baselines = [BaselineEntry.from_dict(b) for b in data.get("baselines", [])]
        return cls(
            paper_id=data["paper_id"],
            title=data["title"],
            authors=data.get("authors", []),
            year=data.get("year", 0),
            abstract=data.get("abstract", ""),
            venue=data.get("venue", ""),
            source=data.get("source", "local"),
            url=data.get("url", ""),
            methods=data.get("methods", []),
            datasets=data.get("datasets", []),
            baselines=baselines,
            organ=data.get("organ", ""),
            task_type=data.get("task_type", ""),
            tags=data.get("tags", []),
        )


@dataclass
class CitationRecord:
    """A citation used in one durable PathScientist conversation."""
    paper_id: str
    cited_in: str
    context: str
    conversation_id: str
    run_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    section: str = ""
    quote_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "paper_id": self.paper_id,
            "cited_in": self.cited_in,
            "context": self.context,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
        }
        if self.chunk_id is not None:
            d["chunk_id"] = self.chunk_id
        if self.page is not None:
            d["page"] = self.page
        if self.section:
            d["section"] = self.section
        if self.quote_snippet:
            d["quote_snippet"] = self.quote_snippet
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CitationRecord:
        return cls(
            paper_id=data["paper_id"],
            cited_in=data["cited_in"],
            context=data["context"],
            conversation_id=data["conversation_id"],
            run_id=data.get("run_id"),
            chunk_id=data.get("chunk_id"),
            page=data.get("page"),
            section=data.get("section", ""),
            quote_snippet=data.get("quote_snippet", ""),
        )


# --- Passage-level retrieval contracts ---


@dataclass
class PassageChunk:
    """One chunk of full-text paper content with provenance."""
    paper_id: str
    chunk_id: str
    text: str
    page: int | None = None
    section: str = ""
    char_start: int = 0
    char_end: int = 0
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "page": self.page,
            "section": self.section,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PassageChunk:
        return cls(
            paper_id=data["paper_id"],
            chunk_id=data["chunk_id"],
            text=data["text"],
            page=data.get("page"),
            section=data.get("section", ""),
            char_start=data.get("char_start", 0),
            char_end=data.get("char_end", 0),
            token_count=data.get("token_count", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PassageHit:
    """A retrieved passage with score breakdown."""
    paper_id: str
    chunk_id: str
    text: str
    score: float
    sparse_score: float = 0.0
    dense_score: float = 0.0
    page: int | None = None
    section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": self.score,
            "sparse_score": self.sparse_score,
            "dense_score": self.dense_score,
            "page": self.page,
            "section": self.section,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PassageHit:
        return cls(**data)


@dataclass
class ExtractedBenchmark:
    """One (method, dataset, metric, value) row extracted from a paper.

    Intermediate representation consumed by SotaLookup to build a SotaTarget.
    """
    paper_id: str
    method: str
    dataset: str
    metric_name: str
    metric_value: float
    evidence: str
    confidence: str


@dataclass
class SotaTarget:
    """Published state-of-the-art for a (dataset, task_type, metric) triple."""
    dataset: str
    task_type: str
    metric_name: str
    metric_value: float
    paper_id: str
    paper_title: str
    paper_url: str
    source: str
    confidence: str
    retrieved_at: str
    raw_evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset, "task_type": self.task_type,
            "metric_name": self.metric_name, "metric_value": self.metric_value,
            "paper_id": self.paper_id, "paper_title": self.paper_title,
            "paper_url": self.paper_url, "source": self.source,
            "confidence": self.confidence, "retrieved_at": self.retrieved_at,
            "raw_evidence": self.raw_evidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SotaTarget":
        return cls(
            dataset=d.get("dataset", ""),
            task_type=d.get("task_type", ""),
            metric_name=d.get("metric_name", ""),
            metric_value=float(d.get("metric_value", 0.0) or 0.0),
            paper_id=d.get("paper_id", ""),
            paper_title=d.get("paper_title", ""),
            paper_url=d.get("paper_url", ""),
            source=d.get("source", ""),
            confidence=d.get("confidence", ""),
            retrieved_at=d.get("retrieved_at", ""),
            raw_evidence=d.get("raw_evidence", ""),
        )
