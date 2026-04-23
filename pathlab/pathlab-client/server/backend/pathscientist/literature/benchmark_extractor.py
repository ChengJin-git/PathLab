"""LLM-driven extraction of (method, dataset, metric, value) from abstracts.

Used when the Papers-with-Code leaderboard has no entry for a dataset. Takes a
set of OpenAlex PaperRecords, asks the LLM to pull structured rows from
abstracts that mention the target dataset+metric, and returns
ExtractedBenchmark objects.

Design choices:
- The caller passes in ``llm_parser: Callable[[str], str]`` so this module has
  zero knowledge of litellm / model routing. Orchestrator wires it via
  runtime.metric_parser.build_llm_metric_parser.
- Malformed LLM output is silently dropped — worse to raise into the
  orchestrator mid-grounding than to return [] and let the caller fall
  through.
- ``max_abstracts`` bounds prompt size; default 10 covers the typical
  top-k from OpenAlex without blowing a 16K context.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from .types import ExtractedBenchmark, PaperRecord

logger = logging.getLogger(__name__)

_PROMPT = """Read the paper abstract(s) below. Extract only results that:
- report {metric} on the {dataset} dataset (or a close alias)
- describe a {task_type} task
- are numeric (ignore qualitative claims like "state-of-the-art")

Return ONLY a JSON array of objects with exact keys:
[
  {{"method": "...", "dataset": "{dataset}", "metric_name": "{metric}",
    "metric_value": 0.0, "evidence": "<direct quote from abstract>",
    "confidence": "high|medium|low"}}
]

If no qualifying result appears, return [].

Abstracts:
{abstracts}
"""


class BenchmarkExtractor:
    def __init__(
        self,
        llm_parser: Callable[[str], str] | None,
        max_abstracts: int = 10,
    ):
        self._llm = llm_parser
        self._max = max_abstracts

    def extract(
        self,
        *,
        papers: list[PaperRecord],
        dataset: str,
        task_type: str,
        metric: str,
    ) -> list[ExtractedBenchmark]:
        if self._llm is None or not papers:
            return []
        clipped = papers[: self._max]
        blob = "\n\n".join(
            f"[paper {p.paper_id}] {p.title}\nabstract: {p.abstract}"
            for p in clipped
        )
        prompt = _PROMPT.format(
            dataset=dataset, task_type=task_type, metric=metric,
            abstracts=blob,
        )
        try:
            raw = self._llm(prompt) or ""
        except Exception as e:
            logger.warning("BenchmarkExtractor LLM call failed: %s", e)
            return []

        raw = raw.strip()
        # Strip common markdown fencing the LLM may add.
        if raw.startswith("```"):
            raw = raw.strip("`")
            # after stripping, may have "json\n..." prefix
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            rows = json.loads(raw)
        except Exception:
            logger.debug("BenchmarkExtractor non-JSON output: %s", raw[:200])
            return []
        if not isinstance(rows, list):
            return []

        # Index papers by paper_id for attribution
        by_id: dict[str, str] = {p.paper_id: p.paper_id for p in clipped}

        out: list[ExtractedBenchmark] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                value = float(row.get("metric_value"))
            except (TypeError, ValueError):
                continue
            # LLM may not attribute to a specific paper_id; try to match by
            # method name mentioned in the evidence string, else use the
            # first paper as best-effort attribution.
            pid = clipped[0].paper_id if clipped else ""
            for p in clipped:
                if p.paper_id in (row.get("evidence") or ""):
                    pid = p.paper_id
                    break
            out.append(ExtractedBenchmark(
                paper_id=pid,
                method=str(row.get("method", "?")),
                dataset=str(row.get("dataset", dataset)),
                metric_name=str(row.get("metric_name", metric)).lower(),
                metric_value=value,
                evidence=str(row.get("evidence", "")),
                confidence=str(row.get("confidence", "medium")),
            ))
        return out
