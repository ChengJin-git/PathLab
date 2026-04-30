"""Literature retriever — combines local store with optional API augmentation."""
from __future__ import annotations

import logging
from typing import Any

from .store import LiteratureStore
from .types import BaselineEntry, PaperRecord

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
    ):
        self._store = store
        self._api_clients = api_clients or []
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

        # Phase 2 / Task 3: cache lookup. Try cache only when (a) leg is
        # enabled, (b) we have a cache instance, and (c) the policy didn't
        # request a forced refresh. Cache key uses the *first* api client's
        # provider name as the canonical provider for this leg.
        if leg_enabled and self._cache is not None and not refresh:
            primary_provider = _provider_name(self._api_clients[0])
            try:
                from .paper_cache import Miss
                cached = self._cache.get(
                    query=query, organ=organ, task_type=task_type,
                    top_k=top_k, provider=primary_provider,
                )
            except Exception as e:
                logger.warning("PaperCache.get failed: %s", e)
                cached = Miss
            if cached is not Miss:
                # Merge cached + local (local already populated above).
                seen = _dedup_keys(results)
                for paper in cached:
                    keys = _paper_keys(paper)
                    if keys.isdisjoint(seen):
                        results.append(paper)
                        seen.update(keys)
                        if len(results) >= top_k:
                            break
                cache_hit_provider = primary_provider
                # Surface cache age for diagnostics.
                try:
                    meta = self._cache.get_metadata(
                        query=query, organ=organ, task_type=task_type,
                        top_k=top_k, provider=primary_provider,
                    )
                    if meta:
                        cache_age_sec = float(meta.get("age_sec", -1))
                except Exception:
                    pass
                self.last_online_status = {
                    "enabled": leg_enabled,
                    "local_count": local_count,
                    "providers": [],
                }
                self.last_network_status = NetworkLegStatus(
                    leg="papers", state="cached",
                    provider=primary_provider,
                    count=len(cached),
                    cache_age_sec=cache_age_sec,
                )
                return results[:top_k]

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
        if allow_network and len(results) < top_k:
            remaining = top_k - len(results) + 2  # small over-fetch for dedup
            seen = _dedup_keys(results)
            for client in self._api_clients:
                provider_name = _provider_name(client)
                stat: dict[str, Any] = {
                    "provider": provider_name,
                    "returned": 0,
                    "merged": 0,
                    "error": "",
                }
                try:
                    online_papers = client.search(
                        query, organ=organ, task_type=task_type, top_k=remaining,
                    )
                    stat["returned"] = len(online_papers)
                    for paper in online_papers:
                        keys = _paper_keys(paper)
                        if keys.isdisjoint(seen):
                            results.append(paper)
                            seen.update(keys)
                            stat["merged"] += 1
                            if len(results) >= top_k:
                                break
                    # Phase 2 / Task 3: write-through. Cache the raw
                    # online_papers for this (query, filters, top_k,
                    # provider) so the next call hits cache.
                    if self._cache is not None:
                        try:
                            self._cache.put(
                                query=query, organ=organ, task_type=task_type,
                                top_k=top_k, provider=provider_name,
                                papers=list(online_papers),
                            )
                        except Exception as e:
                            logger.warning("PaperCache.put failed: %s", e)
                except Exception as e:
                    stat["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                    logger.warning(
                        f"Online client {provider_name} failed: {e}",
                    )
                    if not first_error:
                        first_error = stat["error"]
                    if self._policy.should_fail_hard():
                        # fail-hard: surface the failure as a hard abort.
                        raise NetworkUnavailableError(
                            f"Paper search failed (policy.stage={self._policy.stage}): "
                            f"{stat['error']}"
                        )
                provider_status.append(stat)
                if len(results) >= top_k:
                    break

            # Decide network state from provider results.
            merged_total = sum(int(p.get("merged", 0) or 0) for p in provider_status)
            if first_error and merged_total == 0:
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
            "providers": provider_status,
        }
        self.last_network_status = NetworkLegStatus(
            leg="papers",
            state=network_state,
            provider=top_provider,
            count=sum(int(p.get("merged", 0) or 0) for p in provider_status),
            error=first_error,
        )
        return results[:top_k]

    def has_online_clients(self) -> bool:
        return bool(self._api_clients)

    def get_baselines_for_task(
        self,
        query: str,
        dataset: str | None = None,
        task_type: str | None = None,
        top_k: int = 5,
    ) -> list[BaselineEntry]:
        """Get the best known baselines for a task/dataset combination."""
        baselines = self._store.get_baselines(dataset=dataset, task_type=task_type)
        return baselines[:top_k]


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


def _paper_keys(paper: PaperRecord) -> set[str]:
    """Generate dedup keys for one paper (paper_id, url, normalized title+year)."""
    keys = {paper.paper_id}
    if paper.url:
        keys.add(paper.url.rstrip("/").lower())
    if paper.title and paper.year:
        keys.add(f"{paper.title.strip().lower()}:{paper.year}")
    return keys


def _dedup_keys(papers: list[PaperRecord]) -> set[str]:
    """Build a combined set of dedup keys from a list of papers."""
    seen: set[str] = set()
    for p in papers:
        seen.update(_paper_keys(p))
    return seen
