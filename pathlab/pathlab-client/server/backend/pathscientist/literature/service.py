"""LiteratureService — unified API for paper / passage / baseline / SOTA retrieval.

Plan-2026-04-29 literature-acquisition Phase 4.

Today grounding calls three independent services (LiteratureRetriever,
HybridLiteratureRetriever, SotaLookup) and reassembles the results.
LiteratureService is the consolidation: one object, six methods, all
the consumers (grounding, synthesis, paper writer, etc.) talk to it.

Stage 1 of Phase 4: thin facade that delegates to the existing classes
without changing their semantics. ``find_passages_enriched()`` is the
only new behaviour — it cross-correlates passage hits with paper-level
baselines so the caller gets a unified view.

The eventual goal (Phase 4 / T6) is for ``ground_objective`` to make
one service call instead of three; until then the old retrievers stay
wired in alongside.

``ingest()`` is the entry point for Phase 5 (online auto-ingestion);
this module declares the signature so Phase 5 can fill it without
shifting the API.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from .citation_spans import CitationSpan, SourceNode
from .types import BaselineEntry, PaperRecord, PassageHit, SotaTarget

logger = logging.getLogger(__name__)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


class LiteratureService:
    """Unified literature retrieval facade.

    All four data layers are optional — passing ``None`` for a component
    just makes the corresponding method return empty results. This keeps
    the service usable in tests and partial deployments.
    """

    def __init__(
        self,
        *,
        literature_retriever=None,
        passage_retriever=None,
        sota_lookup=None,
        paper_registry=None,
        network_policy=None,
    ):
        self._literature = literature_retriever
        self._passages = passage_retriever
        self._sota = sota_lookup
        self._registry = paper_registry
        # Plan-2026-04-29 literature-acquisition Phase 5: gate auto-ingest.
        from ..runtime.network_policy import NetworkPolicy
        self._policy = network_policy or NetworkPolicy()

    # ------------------------------------------------------------------
    # find_papers / find_passages
    # ------------------------------------------------------------------

    def find_papers(
        self,
        query: str,
        *,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 5,
    ) -> list[PaperRecord]:
        if self._literature is None:
            return []
        papers = self._literature.retrieve(
            query=query, organ=organ, task_type=task_type, top_k=top_k,
        )
        # Plan-2026-04-29 literature-acquisition Phase 5 / Task 2:
        # auto-ingest online papers into PaperRegistry so subsequent
        # session-internal lookups can resolve them by canonical ID.
        # Local-sourced papers are already addressable via the
        # LiteratureStore, so we skip them.
        if (
            self._registry is not None
            and self._policy.auto_ingest_enabled()
        ):
            for paper in papers:
                if (paper.source or "").lower() in {"local", "local_seed", ""}:
                    continue
                try:
                    self.ingest(paper, sources={paper.source or "openalex"})
                except Exception as e:
                    logger.warning("auto-ingest failed for %s: %s", paper.paper_id, e)
        return papers

    def find_passages(
        self,
        query: str,
        *,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 3,
        dense_min_score: float = 0.1,
    ) -> list[PassageHit]:
        if self._passages is None:
            return []
        return self._passages.retrieve_passages(
            query=query,
            top_k=top_k,
            organ=organ,
            task_type=task_type,
            dense_min_score=dense_min_score,
        )

    # ------------------------------------------------------------------
    # find_baselines / find_sota
    # ------------------------------------------------------------------

    def find_baselines(
        self,
        *,
        dataset: str | None = None,
        task_type: str | None = None,
        query: str = "",
        top_k: int = 5,
    ) -> list[BaselineEntry]:
        if self._literature is None:
            return []
        return self._literature.get_baselines_for_task(
            query=query, dataset=dataset, task_type=task_type, top_k=top_k,
        )

    def find_sota(
        self,
        *,
        dataset: str,
        task_type: str,
        metric: str,
    ) -> SotaTarget | None:
        if self._sota is None:
            return None
        return self._sota.lookup(
            dataset=dataset, task_type=task_type, metric=metric,
        )

    # ------------------------------------------------------------------
    # T4: cross-correlation — passage + paper-level baselines
    # ------------------------------------------------------------------

    def find_passages_enriched(
        self,
        query: str,
        *,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 3,
        dense_min_score: float = 0.1,
        baselines_dataset: str | None = None,
        baselines_task_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return passage hits with paper-level baselines attached.

        Each result dict has shape::

            {
                "passage": PassageHit,
                "baselines": list[BaselineEntry],  # only entries whose
                                                    # paper_id matches the
                                                    # passage's paper_id
            }

        Pass ``baselines_dataset`` + ``baselines_task_type`` so the
        baseline lookup uses the same filter as the passage retrieval —
        passing different filters can produce inconsistent enrichment.
        """
        passages = self.find_passages(
            query=query,
            organ=organ,
            task_type=task_type,
            top_k=top_k,
            dense_min_score=dense_min_score,
        )
        if not passages:
            return []
        all_baselines: list[BaselineEntry] = []
        if self._literature is not None and (baselines_dataset or baselines_task_type):
            all_baselines = self.find_baselines(
                query=query,
                dataset=baselines_dataset,
                task_type=baselines_task_type,
                top_k=20,
            )
        # Index baselines by paper_id (and by canonical when known).
        by_paper: dict[str, list[BaselineEntry]] = {}
        for b in all_baselines:
            by_paper.setdefault(b.paper_id or "", []).append(b)
            # Also index by canonical_id when the registry can resolve.
            if self._registry is not None:
                canonical = self._registry.resolve(b.paper_id)
                if canonical and canonical != b.paper_id:
                    by_paper.setdefault(canonical, []).append(b)

        enriched: list[dict[str, Any]] = []
        for passage in passages:
            keys = [passage.paper_id]
            if self._registry is not None:
                resolved = self._registry.resolve(passage.paper_id)
                if resolved:
                    keys.append(resolved)
            seen_ids: set[int] = set()
            matched: list[BaselineEntry] = []
            for key in keys:
                for b in by_paper.get(key, []):
                    if id(b) not in seen_ids:
                        matched.append(b)
                        seen_ids.add(id(b))
            enriched.append({"passage": passage, "baselines": matched})
        return enriched

    # ------------------------------------------------------------------
    # T5: find_citation_spans — sentence-level units
    # ------------------------------------------------------------------

    def find_citation_spans(
        self,
        query: str,
        *,
        organ: str | None = None,
        task_type: str | None = None,
        paper_ids: Iterable[str] | None = None,
        top_k: int = 5,
        dense_min_score: float = 0.1,
    ) -> list[SourceNode]:
        """Return sentence-grade citation spans from retrieved passages.

        Splits each passage's text on sentence boundaries and emits one
        ``CitationSpan`` per sentence with offsets back into the chunk.
        ``paper_ids`` (canonical or legacy) filters to spans whose
        passage came from one of the listed papers.
        """
        passages = self.find_passages(
            query=query,
            organ=organ,
            task_type=task_type,
            top_k=top_k,
            dense_min_score=dense_min_score,
        )
        wanted: set[str] = set()
        if paper_ids:
            for pid in paper_ids:
                wanted.add(pid)
                if self._registry is not None:
                    resolved = self._registry.resolve(pid)
                    if resolved:
                        wanted.add(resolved)

        nodes: list[SourceNode] = []
        for passage in passages:
            paper_canonical = passage.paper_id
            if self._registry is not None:
                resolved = self._registry.resolve(passage.paper_id)
                if resolved:
                    paper_canonical = resolved
            if wanted:
                if not (passage.paper_id in wanted or paper_canonical in wanted):
                    continue

            text = passage.text or ""
            if not text.strip():
                continue
            # Split on sentence boundaries; track char offsets.
            cursor = 0
            for sentence in _split_sentences(text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                start = text.find(sentence, cursor)
                if start < 0:
                    start = cursor
                end = start + len(sentence)
                cursor = end
                span = CitationSpan(
                    paper_canonical_id=paper_canonical,
                    chunk_id=passage.chunk_id,
                    quote=sentence,
                    page=passage.page,
                    section=passage.section,
                    span_start=start,
                    span_end=end,
                    provider="rag",
                )
                nodes.append(SourceNode(
                    span=span,
                    score=passage.score,
                    retrieval_method="hybrid",
                ))
        return nodes

    # ------------------------------------------------------------------
    # ingest — Phase 5 entry point
    # ------------------------------------------------------------------

    def ingest(self, paper, *, sources: set[str] | None = None) -> bool:
        """Plan-2026-04-29 literature-acquisition Phase 5 / Task 1:
        register a paper in PaperRegistry (canonical-keyed).

        Returns True on successful registration. Returns False when:
        - ``policy.auto_ingest_enabled()`` is False
        - ``paper`` is None
        - no PaperRegistry was wired

        Idempotent: ingesting the same paper twice merges via
        PaperRegistry.register's alias-overlap merge.

        Phase 5b will extend this to also write the paper's abstract
        into ChunkStore + PassageIndex when the provider's capability
        record (see ``provider_capabilities.py``) declares
        ``has_abstract``. For now metadata-only registration.
        """
        if paper is None:
            return False
        if self._registry is None:
            return False
        if not self._policy.auto_ingest_enabled():
            return False

        # Convert PaperRecord (legacy shape) into Paper (registry shape).
        from .paper_registry import Paper
        if hasattr(paper, "to_dict") and not isinstance(paper, Paper):
            # PaperRecord → Paper via legacy bridge so canonical_id +
            # aliases get derived if absent.
            data = paper.to_dict()
            paper_obj = Paper.from_legacy_dict(data)
            # Preserve existing canonical_id / aliases when the legacy
            # record already had them.
            if getattr(paper, "canonical_id", ""):
                paper_obj.canonical_id = paper.canonical_id
            if getattr(paper, "aliases", None):
                # Make sure canonical itself is excluded from aliases.
                paper_obj.aliases = [
                    a for a in paper.aliases if a != paper_obj.canonical_id
                ]
        elif isinstance(paper, Paper):
            paper_obj = paper
        else:
            return False

        try:
            self._registry.register(paper_obj)
            return True
        except Exception as e:
            logger.warning("PaperRegistry.register failed: %s", e)
            return False


def _split_sentences(text: str) -> list[str]:
    """Coarse sentence splitter. Good enough for citation spans without
    pulling in nltk/spacy."""
    parts = _SENTENCE_RE.split(text)
    # Trailing piece may not end with punctuation but still counts.
    return [p for p in parts if p]
