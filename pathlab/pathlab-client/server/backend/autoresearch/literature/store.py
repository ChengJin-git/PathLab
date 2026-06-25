"""Literature store — local JSON-based paper index with keyword search."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .benchmark_store import BenchmarkStore
from .scoring import CorpusStats, PaperScorer
from .types import BaselineEntry, BenchmarkRecord, PaperRecord

logger = logging.getLogger(__name__)


class LiteratureStore:
    """File-based paper index under literature_dir/papers/.

    Storage scope: GLOBAL — one instance per AUTORESEARCH_BASE_DIR, shared
    across all conversations and sessions.  Initialized once in
    ``runner._build_literature_store()`` under ``{BASE_DIR}/literature/``.

    This store is read-only at runtime after initial seeding.  Per-conversation
    citation tracking is handled separately by ``CitationTracker``.
    """

    def __init__(self, literature_dir: Path, *, alias_resolver=None):
        self._dir = Path(literature_dir)
        self._papers_dir = self._dir / "papers"
        self._index_path = self._dir / "index.json"
        self._benchmark_store = BenchmarkStore(self._dir)
        self._papers_dir.mkdir(parents=True, exist_ok=True)
        # AliasResolver is optional: when provided, ``search`` expands
        # query terms with dataset/keyword synonyms before scoring.
        self._alias_resolver = alias_resolver
        # PaperScorer + CorpusStats are built lazily on first search and
        # cached for the lifetime of the store. ``papers`` is read-only at
        # runtime so the stats don't need invalidation.
        self._scorer: PaperScorer | None = None
        self._scorer_corpus_size: int = -1

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
        """Keyword + metadata search over the local index.

        Uses a BM25-lite scorer (``PaperScorer``) when the corpus is
        non-empty; falls back to the legacy keyword-count score when the
        scorer can't build stats (empty corpus). When an
        ``AliasResolver`` is wired in, query terms are augmented with
        dataset/keyword synonyms at half weight.
        """
        papers = self.list_papers()
        scorer = self._get_scorer(papers)
        query_terms = query.lower().split()
        expanded_terms = self._expand_query_terms(query_terms)
        # Promote organ/task_type from "hard filter only" to "soft scoring
        # signal" — even when every retained paper passes the filter,
        # papers whose title/abstract actually mention the organ outrank
        # ones that merely tag it in metadata. Half-weight via the BM25
        # ``expanded_terms`` channel keeps the original query dominant.
        hint_terms: list[str] = []
        for hint in (organ, task_type):
            for token in (hint or "").lower().split():
                if len(token) >= 2 and token not in query_terms and token not in expanded_terms:
                    hint_terms.append(token)
        if hint_terms:
            expanded_terms = list(expanded_terms) + hint_terms

        results: list[tuple[float, PaperRecord]] = []
        for paper in papers:
            if organ and paper.organ and not _organ_matches(paper.organ, organ):
                continue
            if task_type and paper.task_type and task_type.lower() not in paper.task_type.lower():
                continue

            if scorer is not None:
                score = scorer.score(paper, query_terms, expanded_terms)
            else:
                score = _legacy_score(paper, query_terms)
            if score > 0:
                results.append((score, paper))

        results.sort(key=lambda x: x[0], reverse=True)
        return [paper for _, paper in results[:top_k]]

    def _get_scorer(self, papers: list[PaperRecord]) -> PaperScorer | None:
        if not papers:
            return None
        if self._scorer is None or self._scorer_corpus_size != len(papers):
            stats = CorpusStats.build(papers)
            self._scorer = PaperScorer(stats)
            self._scorer_corpus_size = len(papers)
        return self._scorer

    def _expand_query_terms(self, query_terms: list[str]) -> list[str]:
        if self._alias_resolver is None or not query_terms:
            return []
        expanded: list[str] = []
        seen: set[str] = set()
        try:
            for term in query_terms:
                for alias in self._alias_resolver.expand(term) or []:
                    for token in alias.lower().split():
                        if len(token) < 2 or token in seen:
                            continue
                        seen.add(token)
                        expanded.append(token)
        except Exception as e:
            logger.warning("LiteratureStore: alias expansion failed: %s", e)
            return []
        return expanded

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

    def get_benchmarks(
        self,
        *,
        dataset: str | None = None,
        task_type: str | None = None,
        organ: str | None = None,
        prediction_target: str | None = None,
        metric_name: str | None = None,
        verified_only: bool = False,
        top_k: int | None = None,
    ) -> list[BenchmarkRecord]:
        """Return structured benchmark rows with strict task/evidence filters.

        Explicit rows from ``literature/benchmarks/index.json`` are merged with
        low-confidence records derived from legacy ``PaperRecord.baselines`` so
        old seed data stays visible as references without becoming verified
        SOTA evidence.
        """
        return self._benchmark_store.query(
            dataset=dataset,
            task_type=task_type,
            organ=organ,
            prediction_target=prediction_target,
            metric_name=metric_name,
            verified_only=verified_only,
            top_k=top_k,
            extra_records=self._legacy_benchmark_records(),
        )

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

    def _legacy_benchmark_records(self) -> list[BenchmarkRecord]:
        rows: list[BenchmarkRecord] = []
        for paper in self.list_papers():
            for idx, baseline in enumerate(paper.baselines):
                organ = self._resolve_dataset_organ(baseline.dataset, paper.organ)
                target = self._resolve_dataset_target(
                    baseline.dataset, paper.task_type,
                )
                rows.append(BenchmarkRecord(
                    benchmark_id=(
                        f"legacy:{paper.paper_id}:"
                        f"{baseline.dataset}:{baseline.metric_name}:{idx}"
                    ),
                    paper_id=paper.paper_id,
                    canonical_paper_id=paper.canonical_id,
                    paper_title=paper.title,
                    method=baseline.method,
                    dataset=baseline.dataset,
                    organ=organ,
                    task_type=paper.task_type,
                    prediction_target=target,
                    metric_name=baseline.metric_name,
                    metric_value=baseline.metric_value,
                    metric_direction="higher_is_better",
                    protocol={
                        "evaluation_level": "slide",
                        "split": "",
                        "cohort": "",
                        "label_definition": "",
                    },
                    evidence={
                        "source": "curated_seed",
                        "paper_id": paper.paper_id,
                        "quote": baseline.context,
                        "table": "",
                    },
                    confidence="low",
                    verification_status="unverified",
                ))
        return rows

    def _resolve_dataset_organ(self, dataset: str, paper_organ: str) -> str:
        """Plan-2026-05-17: prefer AliasResolver's cached ``organ`` field
        (populated by the LLM expansion) before falling back to the
        hardcoded if-elif. New datasets get their organ for free once
        AliasResolver caches them, no code changes needed.
        """
        if self._alias_resolver is not None:
            try:
                meta = self._alias_resolver.metadata(dataset)
            except Exception:
                meta = None
            if meta and meta.get("organ"):
                return str(meta["organ"]).strip().lower()
        return _infer_benchmark_organ(dataset, paper_organ)

    def _resolve_dataset_target(self, dataset: str, task_type: str) -> str:
        """Plan-2026-05-17: prefer AliasResolver's cached ``target`` field
        before falling back to the hardcoded if-elif. Same rationale as
        ``_resolve_dataset_organ``.
        """
        if self._alias_resolver is not None:
            try:
                meta = self._alias_resolver.metadata(dataset)
            except Exception:
                meta = None
            if meta and meta.get("target"):
                return str(meta["target"]).strip().lower()
        return _infer_prediction_target(dataset, task_type)


def _infer_benchmark_organ(dataset: str, paper_organ: str) -> str:
    key = (dataset or "").strip().lower()
    if key in {"panda", "tcga-prad"}:
        return "prostate"
    if key in {"bracs", "camelyon16", "camelyon17", "tcga-brca"}:
        return "breast"
    if key in {"tcga-lung", "tcga-luad", "tcga-lusc"}:
        return "lung"
    if key in {"tcga-coad", "tcga-read", "crc-msi"}:
        return "colorectal"
    return paper_organ or ""


def _legacy_score(paper: PaperRecord, query_terms: list[str]) -> float:
    """Fallback scorer used when ``PaperScorer`` can't build stats.

    Preserves the original keyword-count behavior so empty-corpus paths
    (tests that bypass the index, mocks) keep their semantics.
    """
    if not query_terms:
        return 0.0
    searchable = " ".join([
        paper.title, paper.abstract,
        " ".join(paper.methods), " ".join(paper.datasets),
        " ".join(paper.tags), paper.organ, paper.task_type,
    ]).lower()
    score = sum(1 for term in query_terms if term in searchable)
    if score > 0 and paper.year > 2020:
        score += 0.1 * (paper.year - 2020)
    return float(score)


def _organ_matches(paper_organ: str, requested_organ: str) -> bool:
    paper = (paper_organ or "").strip().lower()
    requested = (requested_organ or "").strip().lower()
    if not requested or not paper:
        return True
    if requested in paper:
        return True
    # General pathology method papers should remain visible for organ-specific
    # tasks; dataset-specific benchmark matching stays strict elsewhere.
    return paper in {"multi-organ", "multi organ", "pan-cancer", "pan cancer", "general"}


def _infer_prediction_target(dataset: str, task_type: str) -> str:
    key = (dataset or "").strip().lower()
    if key == "panda":
        return "gleason_grade"
    if key.startswith("camelyon"):
        return "metastasis_detection"
    if key == "bracs":
        return "breast_subtyping"
    if key == "tcga-lung":
        return "lung_cancer_classification"
    if key == "tcga-brca" and (task_type or "").lower() == "survival":
        return "survival"
    return ""
