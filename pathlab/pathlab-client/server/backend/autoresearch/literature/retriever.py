"""Literature retriever — combines local store with optional API augmentation."""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Retry settings for provider calls. We keep it short — these run in a
# user-facing grounding call where latency budget is tight. One retry
# with ~0.5s backoff is enough to clear flaky 429/transient TCP errors
# without dragging total latency past the timeout cap.
_PROVIDER_MAX_ATTEMPTS = 2
_PROVIDER_BACKOFF_SEC = 0.5

# Errors that are obviously permanent — don't waste a retry on these.
# We match by stringified status code since clients raise different
# exception types (requests.HTTPError, urllib3, etc.).
def _is_permanent_failure(exc: Exception) -> bool:
    text = str(exc)
    # 4xx except 429 → permanent (bad query, auth issue, not found)
    for code in ("400", "401", "403", "404"):
        if code in text:
            return True
    return False

from .store import LiteratureStore
from .types import BaselineEntry, PaperRecord
from .query_builder import build_literature_search_query

logger = logging.getLogger(__name__)


class LiteratureRetriever:
    """Retrieve papers and baselines from local store (+ optional API clients later).

    Plan-2026-04-29 P1-7: ``last_online_status`` exposes per-call online-
    client telemetry so grounding can surface
    ``online_literature_status`` / ``online_literature_count`` /
    ``online_literature_error`` separately from the merged paper count.
    Pre-fix, ``papers = 5`` looked identical whether OpenAlex returned 0,
    failed, or contributed 2 of the 5.
    """

    def __init__(
        self,
        store: LiteratureStore,
        api_clients: list[Any] | None = None,
        policy=None,  # NetworkPolicy | None — defer import to avoid cycles
        paper_cache=None,  # PaperCache | None — Phase 2
        *,
        reranker=None,  # RelevanceReranker | None — LLM relevance rerank
        alias_resolver=None,  # AliasResolver | None — dataset alias expansion
    ):
        self._store = store
        self._api_clients = api_clients or []
        self._reranker = reranker
        self._alias_resolver = alias_resolver
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 6:
        # ``policy=None`` preserves legacy behavior — auto stage with
        # papers leg gated only by whether api_clients were wired.
        from ..runtime.network_policy import NetworkLegStatus, NetworkPolicy
        if policy is None:
            policy = NetworkPolicy(
                stage="auto" if self._api_clients else "local",
                allow_papers=bool(self._api_clients),
                allow_sota=False,
                allow_rag_dense=False,
            )
        self._policy = policy
        # Plan-2026-04-29 literature-acquisition Phase 2 / Task 3:
        # optional read-through / write-through cache for online results.
        self._cache = paper_cache
        # ``enabled`` is True iff papers leg is logically on AND we have
        # at least one client to call.
        papers_logically_on = (
            self._policy.is_leg_enabled("papers") and bool(self._api_clients)
        )
        self.last_online_status: dict[str, Any] = {
            "enabled": papers_logically_on,
            "local_count": 0,
            "providers": [],
        }
        self.last_network_status = NetworkLegStatus(
            leg="papers",
            state="not_invoked" if papers_logically_on else "disabled",
        )

    def retrieve(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
    ) -> list[PaperRecord]:
        """Retrieve relevant papers. Local store first, online fill when enabled.

        Plan-2026-04-29 literature-acquisition Phase 2 / Tasks 3-5:
        when ``paper_cache`` is wired, online results are served from the
        cache before falling through to network. ``policy.is_cache_only()``
        forbids network on cache miss; ``policy.should_refresh("papers")``
        forces a fresh network call even when cache is hot.
        """
        from ..runtime.network_policy import (
            NetworkLegStatus, NetworkUnavailableError,
        )
        results = self._store.search(query, organ=organ, task_type=task_type, top_k=top_k)
        local_count = len(results)
        provider_status: list[dict[str, Any]] = []
        online_query = build_literature_search_query(
            query,
            organ=organ,
            task_type=task_type,
            alias_resolver=self._alias_resolver,
        )

        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 6:
        # gate online fill on policy.allows_network. local-only / cached
        # stages skip clients but still serve local results.
        leg_enabled = self._policy.is_leg_enabled("papers") and bool(self._api_clients)
        allow_network = (
            leg_enabled and self._policy.allows_network("papers")
        )
        refresh = self._policy.should_refresh("papers")
        cache_hit_provider = ""
        cache_age_sec = -1.0
        cached_provider_names: set[str] = set()

        # Phase 2 / Task 3: cache lookup. Check each provider independently:
        # a negative OpenAlex cache entry must not block S2/EuropePMC.
        if leg_enabled and self._cache is not None and not refresh:
            from .paper_cache import Miss
            seen = _dedup_keys(results)
            for client in self._api_clients:
                provider_name = _provider_name(client)
                try:
                    cached = self._cache.get(
                        query=online_query, organ=organ, task_type=task_type,
                        top_k=top_k, provider=provider_name,
                    )
                except Exception as e:
                    logger.warning("PaperCache.get failed: %s", e)
                    cached = Miss
                if cached is Miss:
                    continue

                cached_provider_names.add(provider_name)
                cache_hit_provider = cache_hit_provider or provider_name
                stat: dict[str, Any] = {
                    "provider": provider_name,
                    "returned": len(cached),
                    "merged": 0,
                    "error": "",
                    "cache": "positive" if cached else "negative",
                }
                for paper in cached:
                    keys = _paper_keys(paper)
                    if keys.isdisjoint(seen):
                        results.append(paper)
                        seen.update(keys)
                        stat["merged"] += 1
                        if len(results) >= top_k:
                            break
                provider_status.append(stat)

                try:
                    meta = self._cache.get_metadata(
                        query=online_query, organ=organ, task_type=task_type,
                        top_k=top_k, provider=provider_name,
                    )
                    if meta:
                        cache_age_sec = max(cache_age_sec, float(meta.get("age_sec", -1)))
                except Exception:
                    pass

                if len(results) >= top_k:
                    self.last_online_status = {
                        "enabled": leg_enabled,
                        "local_count": local_count,
                        "query": online_query,
                        "providers": provider_status,
                    }
                    self.last_network_status = NetworkLegStatus(
                        leg="papers", state="cached",
                        provider=provider_name,
                        count=sum(int(p.get("merged", 0) or 0) for p in provider_status),
                        cache_age_sec=cache_age_sec,
                    )
                    return self._maybe_rerank(
                        results[:top_k], query, organ, task_type,
                    )

            if cached_provider_names and len(cached_provider_names) == len(self._api_clients):
                self.last_online_status = {
                    "enabled": leg_enabled,
                    "local_count": local_count,
                    "query": online_query,
                    "providers": provider_status,
                }
                self.last_network_status = NetworkLegStatus(
                    leg="papers", state="cached",
                    provider=cache_hit_provider,
                    count=sum(int(p.get("merged", 0) or 0) for p in provider_status),
                    cache_age_sec=cache_age_sec,
                )
                return self._maybe_rerank(
                    results[:top_k], query, organ, task_type,
                )

        # Decide network-status state up-front so we can short-circuit cleanly.
        if not leg_enabled:
            network_state = "disabled"
        elif self._policy.is_cache_only():
            # ``cached`` stage: cache miss + no network → refused.
            network_state = "refused"
        else:
            network_state = "not_invoked"

        first_error = ""
        top_provider = ""
        network_called = False
        if allow_network and len(results) < top_k:
            # Plan-2026-05-16: parallel multi-provider fan-out + pooled rerank.
            # Pre-fix the loop short-circuited on the first provider that
            # filled top_k, so high-quality EuropePMC/PubMed results were
            # never seen when OpenAlex happened to return enough papers.
            # Now we fire all non-cached providers in parallel, merge the
            # full candidate pool, dedup, then let RelevanceReranker pick
            # the final top_k. Latency = max(provider_timeout), not sum.
            pending_clients = [
                c for c in self._api_clients
                if _provider_name(c) not in cached_provider_names
            ]
            per_provider_k = top_k  # full ask; rerank does the pruning

            def _search_one(client):
                """Plan-2026-05-16: retry once on transient failures (429,
                connection reset, timeout). Permanent 4xx errors skip retry."""
                provider_name = _provider_name(client)
                stat: dict[str, Any] = {
                    "provider": provider_name,
                    "returned": 0,
                    "merged": 0,
                    "error": "",
                    "attempts": 0,
                }
                last_exc: Exception | None = None
                for attempt in range(1, _PROVIDER_MAX_ATTEMPTS + 1):
                    stat["attempts"] = attempt
                    try:
                        online_papers = client.search(
                            online_query, organ=organ, task_type=task_type,
                            top_k=per_provider_k,
                        )
                        stat["returned"] = len(online_papers)
                        stat["error"] = ""  # clear any prior attempt's error
                        return provider_name, stat, list(online_papers), None
                    except Exception as e:
                        last_exc = e
                        err_text = f"{type(e).__name__}: {str(e)[:200]}"
                        stat["error"] = err_text
                        if attempt < _PROVIDER_MAX_ATTEMPTS and not _is_permanent_failure(e):
                            backoff = _PROVIDER_BACKOFF_SEC * attempt
                            logger.info(
                                "Online client %s attempt %d failed (%s); "
                                "retrying in %.1fs", provider_name, attempt, e, backoff,
                            )
                            time.sleep(backoff)
                            continue
                        logger.warning(
                            "Online client %s failed after %d attempt(s): %s",
                            provider_name, attempt, e,
                        )
                        break
                return provider_name, stat, [], last_exc

            network_called = bool(pending_clients)
            # Preserve api_clients order for deterministic provider_status
            # (helps stable provider attribution in last_network_status).
            order = {_provider_name(c): idx for idx, c in enumerate(pending_clients)}
            futures_map: dict = {}
            with ThreadPoolExecutor(max_workers=max(1, len(pending_clients))) as ex:
                for client in pending_clients:
                    futures_map[ex.submit(_search_one, client)] = client
                pending_stats: list[tuple[int, dict, list, Exception | None]] = []
                for fut in as_completed(futures_map):
                    pname, stat, papers, exc = fut.result()
                    pending_stats.append((order.get(pname, 999), stat, papers, exc))

            # Stable order = api_clients declaration order.
            pending_stats.sort(key=lambda x: x[0])

            seen = _dedup_keys(results)
            for _idx, stat, online_papers, exc in pending_stats:
                if exc is not None:
                    if not first_error:
                        first_error = stat["error"]
                    if self._policy.should_fail_hard():
                        raise NetworkUnavailableError(
                            f"Paper search failed (policy.stage={self._policy.stage}): "
                            f"{stat['error']}"
                        )
                # Merge: dedup against running results AND collect into the
                # candidate pool. We intentionally DON'T early-break here —
                # the reranker downstream picks the best top_k from the pool.
                for paper in online_papers:
                    keys = _paper_keys(paper)
                    if keys.isdisjoint(seen):
                        results.append(paper)
                        seen.update(keys)
                        stat["merged"] += 1
                # Phase 2 / Task 3: write-through cache, per provider.
                if self._cache is not None and exc is None:
                    try:
                        self._cache.put(
                            query=online_query, organ=organ, task_type=task_type,
                            top_k=top_k, provider=stat["provider"],
                            papers=list(online_papers),
                        )
                    except Exception as e:
                        logger.warning("PaperCache.put failed: %s", e)
                provider_status.append(stat)

            # Decide network state from provider results.
            merged_total = sum(int(p.get("merged", 0) or 0) for p in provider_status)
            if not network_called and cached_provider_names:
                network_state = "cached"
                top_provider = cache_hit_provider
            elif first_error and merged_total == 0:
                network_state = "error"
            elif merged_total > 0:
                network_state = "ok"
                top = max(provider_status, key=lambda p: int(p.get("merged", 0) or 0))
                top_provider = top.get("provider", "")
            else:
                # Network ran but returned zero merged papers (clean miss).
                network_state = "ok"
                if provider_status:
                    top_provider = provider_status[0].get("provider", "")

        self.last_online_status = {
            "enabled": leg_enabled,
            "local_count": local_count,
            "query": online_query,
            "providers": provider_status,
        }
        self.last_network_status = NetworkLegStatus(
            leg="papers",
            state=network_state,
            provider=top_provider,
            count=sum(int(p.get("merged", 0) or 0) for p in provider_status),
            error=first_error,
            cache_age_sec=cache_age_sec,
        )
        # Rerank on the FULL pool (cross-provider candidates), then truncate.
        # If we truncated first, EuropePMC's higher-quality 2025 paper would
        # be cut off in favor of an arbitrary OpenAlex hit before rerank
        # ever saw it — defeats the point of going multi-provider.
        reranked = self._maybe_rerank(results, query, organ, task_type)
        return reranked[:top_k]

    def _maybe_rerank(
        self,
        papers: list[PaperRecord],
        query: str,
        organ: str | None,
        task_type: str | None,
    ) -> list[PaperRecord]:
        """Apply LLM relevance rerank when a reranker is wired, else passthrough.

        Errors are caught defensively so a flaky LLM can never poison the
        retrieve() return value — failure modes downgrade to the keyword
        order rather than aborting grounding.
        """
        if self._reranker is None or len(papers) <= 1:
            return papers
        try:
            return self._reranker.rerank(
                papers,
                query=query,
                organ=organ,
                task_type=task_type,
            )
        except Exception as e:
            logger.warning("LiteratureRetriever rerank failed: %s", e)
            return papers

    def has_online_clients(self) -> bool:
        return bool(self._api_clients)

    def get_baselines_for_task(
        self,
        query: str,
        dataset: str | None = None,
        task_type: str | None = None,
        top_k: int = 5,
        organ: str | None = None,
        prediction_target: str | None = None,
        metric_name: str | None = None,
        verified_only: bool = False,
        paper_filter: Iterable[str] | None = None,
    ) -> list[BaselineEntry]:
        """Get the best known baselines for a task/dataset combination.

        When ``paper_filter`` is supplied, baselines whose ``paper_id`` is
        not in the set are dropped. Callers pass the set of paper IDs
        that survived ``retrieve()`` (including LLM rerank) so the
        baseline list stays consistent with the cited paper list — a
        paper the reranker judged off-topic should not contribute its
        baseline numbers to the brief.
        """
        get_benchmarks = getattr(self._store, "get_benchmarks", None)
        # Over-fetch when filtering by paper_id so a small surviving
        # paper set still has room to fill top_k after the prune.
        fetch_k = top_k if paper_filter is None else max(top_k * 3, top_k)
        if callable(get_benchmarks):
            rows = get_benchmarks(
                dataset=dataset,
                task_type=task_type,
                organ=organ,
                prediction_target=prediction_target,
                metric_name=metric_name,
                verified_only=verified_only,
                top_k=fetch_k,
            )
            entries = [_baseline_from_benchmark(row) for row in rows]
        else:
            entries = self._store.get_baselines(
                dataset=dataset, task_type=task_type,
            )[:fetch_k]

        if paper_filter is not None:
            allow = {pid for pid in paper_filter if pid}
            entries = [b for b in entries if b.paper_id in allow]
        return entries[:top_k]


def _provider_name(client) -> str:
    """Canonical provider name for cache keys + status reporting.

    Plan-2026-04-29 literature-acquisition Phase 2 / Task 3: clients can
    declare ``provider_name`` (e.g. ``OpenAlexClient.provider_name =
    "openalex"``); fallback is the class name normalized.
    """
    declared = getattr(client, "provider_name", None)
    if declared:
        return str(declared).lower()
    name = type(client).__name__
    if name.endswith("Client"):
        name = name[: -len("Client")]
    return (name.lower().lstrip("_")) or "unknown"


def _baseline_from_benchmark(row) -> BaselineEntry:
    evidence = getattr(row, "evidence", {}) or {}
    context = str(evidence.get("quote", "") or evidence.get("context", "") or "")
    return BaselineEntry(
        method=row.method,
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        dataset=row.dataset,
        context=context,
        paper_id=row.paper_id,
        paper_title=getattr(row, "paper_title", ""),
    )


def _paper_keys(paper: PaperRecord) -> set[str]:
    """Generate dedup keys for one paper across providers."""
    keys = {paper.paper_id}
    if getattr(paper, "canonical_id", ""):
        keys.add(str(paper.canonical_id).strip().lower())
    for alias in getattr(paper, "aliases", []) or []:
        if alias:
            keys.add(str(alias).strip().lower())
    if paper.url:
        keys.add(paper.url.rstrip("/").lower())
    if paper.title and paper.year:
        keys.add(f"{paper.title.strip().lower()}:{paper.year}")
    return {key for key in keys if key}


def _dedup_keys(papers: list[PaperRecord]) -> set[str]:
    """Build a combined set of dedup keys from a list of papers."""
    seen: set[str] = set()
    for p in papers:
        seen.update(_paper_keys(p))
    return seen
