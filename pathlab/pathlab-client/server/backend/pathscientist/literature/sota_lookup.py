"""End-to-end lookup of published SOTA for a (dataset, task_type, metric) triple.

Order of resolution:
  1. Cache — return immediately on hit.
  2. LiteratureStore — local seed baselines (already-curated, no network cost).
  3. PapersWithCodeClient — dataset-specific leaderboard, high confidence.
  4. OnlineLiteratureClient + BenchmarkExtractor — OpenAlex abstracts + LLM.
  5. Give up, cache the negative result briefly.

The highest metric value across sources wins. Every resolution path returns
a SotaTarget with provenance (source, paper_id, evidence) so downstream
consumers can cite it without paraphrasing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from .sota_cache import SotaCache, Miss
from .types import (
    BaselineEntry, ExtractedBenchmark, PaperRecord, SotaTarget,
)

logger = logging.getLogger(__name__)


class _StoreLike(Protocol):
    def get_baselines(
        self, dataset: str | None = None, task_type: str | None = None,
    ) -> list[BaselineEntry]: ...


class _PwcLike(Protocol):
    def find_dataset(self, name: str) -> str | None: ...
    def leaderboard(self, slug: str, metric: str) -> list[ExtractedBenchmark]: ...


class _OnlineLike(Protocol):
    def search(
        self, query: str, top_k: int = 5, organ: str = "", task_type: str = "",
    ) -> list[PaperRecord]: ...


class _ExtractorLike(Protocol):
    def extract(
        self, *, papers: list[PaperRecord],
        dataset: str, task_type: str, metric: str,
    ) -> list[ExtractedBenchmark]: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SotaLookup:
    def __init__(
        self,
        store: _StoreLike,
        cache: SotaCache,
        pwc_client: _PwcLike | None = None,
        online_client: _OnlineLike | None = None,
        llm_extractor: _ExtractorLike | None = None,
        offline: bool = False,
    ):
        self._store = store
        self._cache = cache
        self._pwc = pwc_client
        self._online = online_client
        self._extractor = llm_extractor
        self._offline = offline

    def lookup(
        self, *, dataset: str, task_type: str, metric: str,
    ) -> SotaTarget | None:
        if not dataset:
            return None
        metric = metric.lower()

        cached = self._cache.get(dataset, task_type, metric)
        if cached is not Miss:
            return cached   # may be None (negative cache) or a real target

        # 1. local store
        local = self._from_local_store(dataset, task_type, metric)
        if local is not None:
            self._cache.put(dataset, task_type, metric, local)
            return local

        if self._offline:
            logger.info("SotaLookup offline: no cached / local match for %s",
                        dataset)
            self._cache.put(dataset, task_type, metric, None)
            return None

        # 2. PwC
        pwc = self._from_pwc(dataset, metric)
        if pwc is not None:
            self._cache.put(dataset, task_type, metric, pwc)
            return pwc

        # 3. OpenAlex + LLM
        openalex = self._from_openalex_llm(dataset, task_type, metric)
        if openalex is not None:
            self._cache.put(dataset, task_type, metric, openalex)
            return openalex

        # 4. give up (short TTL negative cache)
        self._cache.put(dataset, task_type, metric, None)
        return None

    def _from_local_store(
        self, dataset: str, task_type: str, metric: str,
    ) -> SotaTarget | None:
        try:
            baselines = self._store.get_baselines(
                dataset=dataset, task_type=task_type,
            )
        except Exception as e:
            logger.warning("local store lookup failed: %s", e)
            return None
        matching = [
            b for b in baselines
            if (b.metric_name or "").lower() == metric
            and (b.dataset or "").lower() == dataset.lower()
        ]
        if not matching:
            return None
        best = max(matching, key=lambda b: b.metric_value)
        return SotaTarget(
            dataset=dataset, task_type=task_type, metric_name=metric,
            metric_value=float(best.metric_value),
            paper_id=best.paper_id or "",
            paper_title=best.paper_title or "",
            paper_url="",
            source="local_store",
            confidence="high",
            retrieved_at=_now_iso(),
            raw_evidence=best.context or "",
        )

    def _from_pwc(self, dataset: str, metric: str) -> SotaTarget | None:
        if self._pwc is None:
            return None
        try:
            slug = self._pwc.find_dataset(dataset)
        except Exception as e:
            logger.warning("PwC find_dataset failed: %s", e)
            return None
        if not slug:
            return None
        try:
            rows = self._pwc.leaderboard(slug, metric)
        except Exception as e:
            logger.warning("PwC leaderboard failed: %s", e)
            return None
        if not rows:
            return None
        best = max(rows, key=lambda r: r.metric_value)
        return SotaTarget(
            dataset=dataset, task_type="",
            metric_name=metric, metric_value=best.metric_value,
            paper_id=best.paper_id, paper_title="",
            paper_url="",
            source="pwc",
            confidence=best.confidence or "high",
            retrieved_at=_now_iso(),
            raw_evidence=best.evidence,
        )

    def _from_openalex_llm(
        self, dataset: str, task_type: str, metric: str,
    ) -> SotaTarget | None:
        if self._online is None or self._extractor is None:
            return None
        query = f"{dataset} {metric} {task_type}"
        try:
            papers = self._online.search(query=query, top_k=10,
                                         task_type=task_type)
        except Exception as e:
            logger.warning("OpenAlex search failed: %s", e)
            return None
        if not papers:
            return None
        try:
            rows = self._extractor.extract(
                papers=papers, dataset=dataset,
                task_type=task_type, metric=metric,
            )
        except Exception as e:
            logger.warning("BenchmarkExtractor failed: %s", e)
            return None
        if not rows:
            return None
        best = max(rows, key=lambda r: r.metric_value)
        title = ""
        url = ""
        for p in papers:
            if p.paper_id == best.paper_id:
                title = p.title; url = p.url; break
        return SotaTarget(
            dataset=dataset, task_type=task_type,
            metric_name=metric, metric_value=best.metric_value,
            paper_id=best.paper_id, paper_title=title, paper_url=url,
            source="openalex+llm",
            confidence=best.confidence or "medium",
            retrieved_at=_now_iso(),
            raw_evidence=best.evidence,
        )
