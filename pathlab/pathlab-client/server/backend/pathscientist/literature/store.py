"""Literature store — local JSON-based paper index with keyword search."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .types import BaselineEntry, PaperRecord

logger = logging.getLogger(__name__)


class LiteratureStore:
    """File-based paper index under literature_dir/papers/.

    Storage scope: GLOBAL — one instance per PATHSCIENTIST_BASE_DIR, shared
    across all conversations and sessions.  Initialized once in
    ``runner._build_literature_store()`` under ``{BASE_DIR}/literature/``.

    This store is read-only at runtime after initial seeding.  Per-conversation
    citation tracking is handled separately by ``CitationTracker``.
    """

    def __init__(self, literature_dir: Path):
        self._dir = Path(literature_dir)
        self._papers_dir = self._dir / "papers"
        self._index_path = self._dir / "index.json"
        self._papers_dir.mkdir(parents=True, exist_ok=True)

    def add(self, paper: PaperRecord) -> None:
        """Add or update a paper in the store."""
        paper_path = self._paper_path(paper.paper_id)
        paper_path.write_text(
            json.dumps(paper.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._update_index(paper)

    def get(self, paper_id: str) -> PaperRecord:
        """Load a paper by ID."""
        paper_path = self._paper_path(paper_id)
        if not paper_path.exists():
            raise FileNotFoundError(f"No paper with id={paper_id}")
        data = json.loads(paper_path.read_text(encoding="utf-8"))
        return PaperRecord.from_dict(data)

    def list_papers(self) -> list[PaperRecord]:
        """List all indexed papers."""
        papers = []
        for path in sorted(self._papers_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                papers.append(PaperRecord.from_dict(data))
            except Exception:
                continue
        return papers

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
    ) -> list[PaperRecord]:
        """Keyword + metadata search over the local index."""
        query_terms = query.lower().split()
        results: list[tuple[float, PaperRecord]] = []

        for paper in self.list_papers():
            # Filter by metadata
            if organ and paper.organ and organ.lower() not in paper.organ.lower():
                continue
            if task_type and paper.task_type and task_type.lower() not in paper.task_type.lower():
                continue

            # Score by keyword overlap
            searchable = " ".join([
                paper.title, paper.abstract,
                " ".join(paper.methods), " ".join(paper.datasets),
                " ".join(paper.tags), paper.organ, paper.task_type,
            ]).lower()

            score = sum(1 for term in query_terms if term in searchable)
            if score > 0:
                # Boost recent papers slightly
                recency_bonus = (paper.year - 2020) * 0.1 if paper.year > 2020 else 0
                results.append((score + recency_bonus, paper))

        results.sort(key=lambda x: x[0], reverse=True)
        return [paper for _, paper in results[:top_k]]

    def get_baselines(
        self,
        dataset: str | None = None,
        task_type: str | None = None,
    ) -> list[BaselineEntry]:
        """Collect baselines across all papers, optionally filtered."""
        baselines = []
        for paper in self.list_papers():
            if task_type and paper.task_type and task_type.lower() not in paper.task_type.lower():
                continue
            for b in paper.baselines:
                if dataset and b.dataset.lower() != dataset.lower():
                    continue
                baselines.append(BaselineEntry(
                    method=b.method,
                    metric_name=b.metric_name,
                    metric_value=b.metric_value,
                    dataset=b.dataset,
                    context=b.context,
                    paper_id=paper.paper_id,
                    paper_title=paper.title,
                ))
        # Sort by metric value descending
        baselines.sort(key=lambda b: b.metric_value, reverse=True)
        return baselines

    def resolve(self, any_id: str) -> str | None:
        """Phase 3 / Task 3: resolve any alias (canonical_id, paper_id,
        DOI, OpenAlex ID, arXiv ID, etc.) to the store's primary
        ``paper_id`` key. Returns ``None`` when unknown.

        Cross-references are scanned per-paper because we don't maintain
        an alias index on disk yet — Phase 3 Task 6 (PaperRegistry-as-
        store) will replace this linear scan when migration lands.
        """
        if not any_id:
            return None
        from .id_resolver import to_canonical_id
        target = to_canonical_id(any_id)
        # Direct paper_id hit: legacy callers still key by paper_id.
        try:
            paper = self.get(any_id)
            return paper.paper_id
        except FileNotFoundError:
            pass
        # Scan papers for alias / canonical match.
        for paper in self.list_papers():
            if paper.canonical_id == target:
                return paper.paper_id
            if target in paper.aliases:
                return paper.paper_id
            # Try matching against paper_id auto-canonicalized too —
            # covers legacy stores that hit list_papers without yet
            # having explicit canonical_id files (auto-derived in
            # from_dict).
            if to_canonical_id(paper.paper_id) == target:
                return paper.paper_id
        return None

    def _update_index(self, paper: PaperRecord) -> None:
        """Update index.json with paper summary."""
        index = self._read_index()
        index = [r for r in index if r.get("paper_id") != paper.paper_id]
        index.append({
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "organ": paper.organ,
            "task_type": paper.task_type,
            "methods": paper.methods,
            "datasets": paper.datasets,
            "n_baselines": len(paper.baselines),
        })
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_index(self) -> list[dict[str, Any]]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _paper_path(self, paper_id: str) -> Path:
        """Map a paper id to a filesystem-safe JSON path."""
        safe_id = quote(paper_id, safe="")
        return self._papers_dir / f"{safe_id}.json"
