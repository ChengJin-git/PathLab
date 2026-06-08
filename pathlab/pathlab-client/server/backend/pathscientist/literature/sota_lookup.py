"""End-to-end lookup of published SOTA for a (dataset, task_type, metric) triple.

Order of resolution:
  1. Cache — return immediately on hit.
  2. PapersWithCodeClient — preferred structured leaderboard, human-curated.
  3. FulltextFetcher + BenchmarkExtractor.extract_from_chunks — OA HTML
     full-text + tables-as-markdown + LLM. (FT-T5 of the 2026-05-01 plan.)
     This sits ABOVE the abstract-only path because tables and Results
     sections are far more reliable for pathology benchmarks than the
     OpenAlex inverted-index abstract.
  4. LiteratureStore — local seed baselines, curated offline fallback.
  5. OnlineLiteratureClient + BenchmarkExtractor — OpenAlex abstracts + LLM
     (legacy path; some papers do put numbers in the abstract).
  6. Give up, cache the negative result briefly.

When ``offline=True`` we skip every network leg (PwC / fulltext / OpenAlex)
and fall back to cache + local_store only. local_store is always tried
because it is offline-safe.

The highest metric value within a leg wins; the first non-None leg
returns. Every resolution path returns a SotaTarget with provenance
(source, paper_id, evidence, evidence_chunks) so downstream consumers
can cite it without paraphrasing.
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
        refresh: bool = False,
        policy=None,  # NetworkPolicy | None — avoid import-time circular
        fulltext_fetcher=None,  # FT-T5: optional fulltext+LLM fallback step
    ):
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 5:
        # ``policy`` is the new contract; ``offline`` and ``refresh`` are
        # legacy kwargs. When ``policy=None`` we synthesize one from the
        # legacy kwargs so existing callers (and tests) keep working.
        from ..runtime.network_policy import NetworkLegStatus, NetworkPolicy
        if policy is None:
            policy = NetworkPolicy(
                stage="local" if offline else "auto",
                allow_sota=not offline,
                refresh={"sota"} if refresh else set(),
            )
        self._store = store
        self._cache = cache
        self._pwc = pwc_client
        self._online = online_client
        self._extractor = llm_extractor
        self._fulltext_fetcher = fulltext_fetcher
        self._policy = policy
        self.last_status = "not_started"
        self.last_network_status = NetworkLegStatus(leg="sota", state="not_invoked")

    # Back-compat read-only properties for code that introspected these.
    @property
    def _offline(self) -> bool:
        return not self._policy.allows_network("sota") and not self._policy.is_cache_only()

    @property
    def _refresh(self) -> bool:
        return self._policy.should_refresh("sota")

    def lookup(
        self, *, dataset: str, task_type: str, metric: str,
    ) -> SotaTarget | None:
        self.last_status = "miss"
        if not dataset:
            self.last_status = "no_dataset"
            return None
        metric = metric.lower()

        if not self._refresh:
            cached = self._cache.get(dataset, task_type, metric)
            if cached is not Miss:
                # Plan-2026-04-28 P1 #5: surface retrieved_at + remaining
                # TTL on every cache hit so an operator looking at the
                # session log can tell why no SOTA target appeared
                # (negative cache hit) or how stale the positive value
                # is.
                meta = None
                try:
                    meta = self._cache.get_metadata(dataset, task_type, metric)
                except Exception:
                    meta = None
                meta_suffix = ""
                if meta:
                    meta_suffix = (
                        f" retrieved_at={meta['retrieved_at']}"
                        f" age={meta['age_sec']}s"
                        f" expires_in={meta['expires_in_sec']}s"
                    )
                from ..runtime.network_policy import NetworkLegStatus
                age = float(meta["age_sec"]) if meta and "age_sec" in meta else -1.0
                if cached is None:
                    self.last_status = "cache_negative"
                    self.last_network_status = NetworkLegStatus(
                        leg="sota", state="cached", provider="sota_cache",
                        count=0, cache_age_sec=age,
                    )
                    logger.info(
                        "SotaLookup: negative cache hit for dataset=%s task=%s metric=%s%s",
                        dataset, task_type, metric, meta_suffix,
                    )
                    return None
                self.last_status = "cache_hit"
                self.last_network_status = NetworkLegStatus(
                    leg="sota", state="cached", provider="sota_cache",
                    count=1, cache_age_sec=age,
                )
                logger.info(
                    "SotaLookup: cache hit for dataset=%s task=%s metric=%s source=%s value=%.4f%s",
                    dataset, task_type, metric, cached.source, cached.metric_value, meta_suffix,
                )
                return cached
        else:
            logger.info(
                "SotaLookup: refresh requested; bypassing cache for dataset=%s task=%s metric=%s",
                dataset, task_type, metric,
            )

        # Plan-2026-04-29 P0-3: track granular failure modes so an operator
        # can tell ``miss`` (no SOTA found anywhere) apart from
        # ``pwc_error`` / ``openalex_error`` / ``llm_extractor_error``
        # (network or extractor bug). Pre-fix, every failure looked like
        # ``miss`` and silently masked the parser-signature crash that
        # broke every openalex+llm fallback (session_6bed65f7).
        terminal_error: str | None = None

        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 5:
        # network-gated legs consult the policy. Local store + cache are
        # always available (they're not network).
        from ..runtime.network_policy import (
            NetworkLegStatus, NetworkUnavailableError,
        )
        allow_sota_network = self._policy.allows_network("sota")

        # 1. PwC — preferred structured leaderboard (network-gated).
        if allow_sota_network:
            pwc, pwc_err = self._from_pwc(dataset, metric)
            if pwc is not None:
                self.last_status = "pwc_hit"
                self.last_network_status = NetworkLegStatus(
                    leg="sota", state="ok", provider="pwc", count=1,
                )
                self._cache.put(dataset, task_type, metric, pwc)
                return pwc
            if pwc_err:
                terminal_error = pwc_err

        # 2. Fulltext + LLM (FT-T5) — network-gated; only attempts when a
        # FulltextFetcher is wired AND online_client is available to
        # surface candidate papers. Sits ABOVE local_store because OA
        # fulltext is more authoritative than seed baselines for the
        # long-tail pathology benchmarks PwC doesn't track.
        if allow_sota_network:
            ft, ft_err = self._from_fulltext_llm(dataset, task_type, metric)
            if ft is not None:
                self.last_status = "fulltext_llm_hit"
                self.last_network_status = NetworkLegStatus(
                    leg="sota", state="ok",
                    provider="openalex+fulltext+llm", count=1,
                )
                self._cache.put(dataset, task_type, metric, ft)
                return ft
            if ft_err and not terminal_error:
                terminal_error = ft_err

        # 3. local store — curated offline fallback (always available).
        local = self._from_local_store(dataset, task_type, metric)
        if local is not None:
            self.last_status = "local_store_hit"
            self.last_network_status = NetworkLegStatus(
                leg="sota", state="ok", provider="local_store", count=1,
            )
            self._cache.put(dataset, task_type, metric, local)
            return local

        if not allow_sota_network:
            # Network refused or disabled. Distinguish:
            # - stage=local: leg disabled
            # - stage=cached: cache miss + cache-only → refused
            if self._policy.is_cache_only():
                state = "refused"
            else:
                state = "disabled"
            self.last_network_status = NetworkLegStatus(
                leg="sota", state=state, provider="network",
            )
            logger.info(
                "SotaLookup: network %s for dataset=%s; cache+local miss",
                state, dataset,
            )
            self.last_status = "miss"
            self._cache.put(dataset, task_type, metric, None)
            return None

        # 3. OpenAlex + LLM (network-gated).
        openalex, oa_err = self._from_openalex_llm(dataset, task_type, metric)
        if openalex is not None:
            self.last_status = "openalex_llm_hit"
            self.last_network_status = NetworkLegStatus(
                leg="sota", state="ok", provider="openalex+llm", count=1,
            )
            self._cache.put(dataset, task_type, metric, openalex)
            return openalex
        if oa_err:
            terminal_error = oa_err

        # 4. give up — surface the granular error if any leg raised, else miss.
        self.last_status = terminal_error or "miss"
        if terminal_error:
            self.last_network_status = NetworkLegStatus(
                leg="sota", state="error", provider="network",
                error=terminal_error,
            )
            # fail-hard: convert silent degradation into a hard abort.
            if self._policy.should_fail_hard():
                raise NetworkUnavailableError(
                    f"SOTA lookup failed (policy.stage={self._policy.stage}): "
                    f"{terminal_error}"
                )
        else:
            self.last_network_status = NetworkLegStatus(
                leg="sota", state="ok", provider="pwc/openalex", count=0,
            )
        self._cache.put(dataset, task_type, metric, None)
        return None

    def _from_local_store(
        self, dataset: str, task_type: str, metric: str,
    ) -> SotaTarget | None:
        get_benchmarks = getattr(self._store, "get_benchmarks", None)
        if callable(get_benchmarks):
            try:
                rows = get_benchmarks(
                    dataset=dataset,
                    task_type=task_type,
                    metric_name=metric,
                    verified_only=True,
                )
            except Exception as e:
                logger.warning("local benchmark store lookup failed: %s", e)
                return None
            if not rows:
                return None
            best = max(rows, key=lambda b: b.metric_value)
            evidence = getattr(best, "evidence", {}) or {}
            return SotaTarget(
                dataset=dataset, task_type=task_type, metric_name=metric,
                metric_value=float(best.metric_value),
                paper_id=best.paper_id or "",
                paper_title=getattr(best, "paper_title", "") or "",
                paper_url="",
                source="local_benchmark_store",
                confidence=getattr(best, "confidence", "") or "medium",
                retrieved_at=_now_iso(),
                raw_evidence=str(
                    evidence.get("quote", "") or evidence.get("context", "") or ""
                ),
            )

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

    def _from_pwc(
        self, dataset: str, metric: str,
    ) -> tuple[SotaTarget | None, str | None]:
        """Returns (target_or_None, error_status_or_None).

        ``error_status`` is set when an exception fires (network/parse error)
        — distinct from a clean "no match" which returns (None, None).
        """
        if self._pwc is None:
            return None, None
        try:
            slug = self._pwc.find_dataset(dataset)
        except Exception as e:
            logger.warning("PwC find_dataset failed: %s", e)
            return None, "pwc_error"
        if not slug:
            return None, None
        try:
            rows = self._pwc.leaderboard(slug, metric)
        except Exception as e:
            logger.warning("PwC leaderboard failed: %s", e)
            return None, "pwc_error"
        if not rows:
            return None, None
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
        ), None

    def _from_fulltext_llm(
        self, dataset: str, task_type: str, metric: str,
    ) -> tuple[SotaTarget | None, str | None]:
        """FT-T5: search OpenAlex for candidate papers, fetch HTML
        full-text for each that exposes an OA URL, feed all chunks to
        ``BenchmarkExtractor.extract_from_chunks``.

        Returns ``(target, error_status)``: clean miss is ``(None, None)``;
        a network/extractor exception sets ``error_status`` so the
        outer ``lookup`` can record it on ``last_network_status``.

        Sits ABOVE local_store because OA full-text + tables is the
        most authoritative source for pathology benchmarks PwC doesn't
        track. Falls through (returns None) when any prerequisite is
        missing — fetcher None, online None, extractor None — so existing
        callers that don't wire fulltext continue to work.
        """
        if (
            self._fulltext_fetcher is None
            or self._extractor is None
            or self._online is None
        ):
            return None, None
        if not hasattr(self._extractor, "extract_from_chunks"):
            return None, None

        query = f"{dataset} {metric} {task_type}"
        try:
            papers = self._online.search(
                query=query, top_k=5, task_type=task_type,
            )
        except Exception as e:
            logger.warning("OpenAlex search (fulltext path) failed: %s", e)
            return None, "openalex_error"
        if not papers:
            return None, None

        all_chunks: list = []
        for paper in papers:
            url = (paper.url or "").strip()
            if not url:
                continue
            canonical = (
                getattr(paper, "canonical_id", "") or paper.paper_id
            )
            try:
                doc = self._fulltext_fetcher.fetch(canonical, url)
            except Exception as e:
                logger.warning(
                    "FulltextFetcher.fetch failed for %s: %s",
                    canonical, e,
                )
                continue
            if doc.success and doc.chunks:
                all_chunks.extend(doc.chunks)

        if not all_chunks:
            return None, None

        try:
            benchmarks = self._extractor.extract_from_chunks(
                all_chunks, dataset=dataset, metric=metric,
                task_type=task_type,
            )
        except Exception as e:
            logger.warning(
                "BenchmarkExtractor.extract_from_chunks failed: %s", e,
            )
            return None, "llm_extractor_error"
        benchmarks = [b for b in benchmarks if b.metric_value > 0]
        if not benchmarks:
            return None, None

        best = max(benchmarks, key=lambda b: b.metric_value)
        title = ""
        url = ""
        for p in papers:
            canonical = getattr(p, "canonical_id", "") or p.paper_id
            if canonical == best.paper_id or p.paper_id == best.paper_id:
                title = p.title
                url = p.url
                break

        evidence_chunks = [
            {
                "paper_id": b.paper_id,
                "section": getattr(b, "source_section", "") or "",
                "quote": b.evidence,
                "value": b.metric_value,
            }
            for b in benchmarks
        ]
        return SotaTarget(
            dataset=dataset, task_type=task_type,
            metric_name=metric, metric_value=best.metric_value,
            paper_id=best.paper_id, paper_title=title, paper_url=url,
            source="openalex+fulltext+llm",
            confidence=best.confidence or "medium",
            retrieved_at=_now_iso(),
            raw_evidence=best.evidence,
            evidence_chunks=evidence_chunks,
        ), None

    def _from_openalex_llm(
        self, dataset: str, task_type: str, metric: str,
    ) -> tuple[SotaTarget | None, str | None]:
        """Returns (target_or_None, error_status_or_None).

        Distinguishes ``openalex_error`` (search call failed) from
        ``llm_extractor_error`` (extractor raised — e.g. the parser
        signature bug pre-Plan-2026-04-29 P0-3) so the caller can record
        which leg actually failed.
        """
        if self._online is None or self._extractor is None:
            return None, None
        query = f"{dataset} {metric} {task_type}"
        try:
            papers = self._online.search(query=query, top_k=10,
                                         task_type=task_type)
        except Exception as e:
            logger.warning("OpenAlex search failed: %s", e)
            return None, "openalex_error"
        if not papers:
            return None, None
        try:
            rows = self._extractor.extract(
                papers=papers, dataset=dataset,
                task_type=task_type, metric=metric,
            )
        except Exception as e:
            logger.warning("BenchmarkExtractor failed: %s", e)
            return None, "llm_extractor_error"
        if not rows:
            return None, None
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
        ), None
