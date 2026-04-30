"""Papers with Code REST client.

Uses the public JSON endpoints (no API key required):
  - GET /api/v1/datasets/?q=<name>    → dataset search
  - GET /api/v1/datasets/<slug>/evaluations/  → leaderboard rows

Returns ExtractedBenchmark objects. Failures (timeout / non-200 / parse error)
return empty-list / None so SotaLookup can fall through to OpenAlex without
propagating exceptions into the orchestrator.
"""
from __future__ import annotations

import logging

import requests

from .types import ExtractedBenchmark

logger = logging.getLogger(__name__)


class PapersWithCodeClient:
    BASE_URL = "https://paperswithcode.com/api/v1"

    def __init__(self, timeout: int = 15, raise_on_error: bool = False):
        self._timeout = timeout
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 4:
        # raise_on_error=True propagates HTTP failures so fail-hard policy
        # can abort the session instead of pretending PwC said "no match".
        self._raise_on_error = raise_on_error
        self.last_error = ""

    def _record_error(self, label: str, exc: Exception) -> None:
        self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning("PwC %s failed: %s", label, self.last_error)
        if self._raise_on_error:
            raise exc

    def find_dataset(self, name: str) -> str | None:
        try:
            r = requests.get(
                f"{self.BASE_URL}/datasets/",
                params={"q": name}, timeout=self._timeout,
            )
            r.raise_for_status()
            results = (r.json() or {}).get("results", [])
        except Exception as e:
            self._record_error("find_dataset", e)
            return None
        for row in results:
            # Best match: exact (case-insensitive) name match.
            if (row.get("name") or "").lower() == name.lower():
                return row.get("id")
        # Fallback: first result — PwC ranks by relevance.
        return results[0].get("id") if results else None

    def leaderboard(self, dataset_slug: str, metric: str) -> list[ExtractedBenchmark]:
        try:
            r = requests.get(
                f"{self.BASE_URL}/datasets/{dataset_slug}/evaluations/",
                timeout=self._timeout,
            )
            r.raise_for_status()
            results = (r.json() or {}).get("results", [])
        except Exception as e:
            self._record_error("leaderboard", e)
            return []

        out: list[ExtractedBenchmark] = []
        metric_lc = metric.lower()
        for row in results:
            method = row.get("methodology") or "?"
            paper = row.get("paper") or {}
            pid = paper.get("id") or ""
            title = paper.get("title") or ""
            url = paper.get("url_pdf") or ""
            for m in row.get("metrics", []):
                if (m.get("name") or "").lower() != metric_lc:
                    continue
                try:
                    value = float(m.get("value"))
                except (TypeError, ValueError):
                    continue
                out.append(ExtractedBenchmark(
                    paper_id=f"pwc:{pid}" if pid else "",
                    method=method,
                    dataset=dataset_slug,
                    metric_name=metric_lc,
                    metric_value=value,
                    evidence=f"{method} achieves {metric_lc}={value} on {dataset_slug} [PwC]",
                    confidence="high",
                ))
        return out
