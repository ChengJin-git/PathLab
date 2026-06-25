"""LLM-driven extraction of (method, dataset, metric, value) rows.

Two paths are supported:

1. ``extract`` (legacy): feeds OpenAlex abstracts only. Used when no OA
   HTML is available or fulltext fetch is gated off.
2. ``extract_from_chunks`` (FT-T4): feeds full-text chunks (abstract +
   tables-as-markdown + section text) produced by ``FulltextFetcher``.
   Tables matter — many pathology benchmarks live there, not in the
   abstract.

Design choices:
- The caller passes in ``llm_parser: Callable[[str], str]`` so this module
  has zero knowledge of litellm / model routing. Orchestrator wires it
  via ``runtime.metric_parser.build_llm_metric_parser``.
- Malformed LLM output is silently dropped — worse to raise mid-grounding
  than to return ``[]`` and let SotaLookup fall through.
- ``max_chunks_per_prompt`` bounds prompt size; default 12 covers a
  typical 3-paper top_k (each yielding abstract + few tables + few
  sections) without blowing context.
- Hallucination guard: rows whose ``paper_id`` is not in the input chunks
  are dropped (the LLM occasionally invents citations).
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Callable

from .types import ExtractedBenchmark, PaperRecord

if TYPE_CHECKING:  # pragma: no cover
    from .fulltext_types import FulltextChunk

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


_CHUNKS_PROMPT = """You are extracting reported benchmark numbers from scientific paper text.

Target benchmark:
- dataset: {dataset}
- metric: {metric}
- task_type: {task_type}

Each chunk below is identified by its source paper_id and section. Some
chunks are markdown tables (rows separated by `|`).

Rules:
1. Extract ONLY values that are EXPLICITLY present in the text. Do not
   estimate, average, or guess.
2. Each result MUST cite the paper_id from the chunk it came from.
3. Use the highest reported value per paper if multiple are reported
   (e.g. multiple folds → cite the mean if explicit, else max).
4. If a value is reported as "X ± Y", report X.
5. If the chunk reports a baseline that is not the chunk's own paper
   (e.g. "[12] reported AUC=0.85"), set source_section to
   "comparison_table" and set paper_id to the cited reference's id only
   if you can identify it; otherwise drop the row.

Chunks:
{chunks_block}

Return ONLY a JSON array. Each element MUST have:
- "paper_id": string
- "dataset": string (matching the target if possible)
- "metric_name": string (matching the target if possible)
- "metric_value": float
- "evidence": string (a short literal quote from the chunk)
- "source_section": string (the section field from the source chunk)

Return [] if no values match. No commentary, no markdown, no preamble.
"""


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    return s


class BenchmarkExtractor:
    def __init__(
        self,
        llm_parser: Callable[[str], str] | None,
        max_abstracts: int = 10,
        *,
        max_chunks_per_prompt: int = 12,
    ):
        self._llm = llm_parser
        self._max = max_abstracts
        self._max_chunks = max(1, int(max_chunks_per_prompt))

    # ---- legacy: abstract-only path ------------------------------------

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

        raw = _strip_fence(raw)
        try:
            rows = json.loads(raw)
        except Exception:
            logger.debug("BenchmarkExtractor non-JSON output: %s", raw[:200])
            return []
        if not isinstance(rows, list):
            return []

        out: list[ExtractedBenchmark] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                value = float(row.get("metric_value"))
            except (TypeError, ValueError):
                continue
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

    # ---- FT-T4: full-text chunks path ----------------------------------

    def extract_from_chunks(
        self,
        chunks: list["FulltextChunk"],
        *,
        dataset: str,
        metric: str,
        task_type: str = "",
    ) -> list[ExtractedBenchmark]:
        """Feed all chunks (abstract + tables + section text) to the LLM.

        Tables come pre-rendered as markdown so headers survive. The
        ``source_section`` field on each ``ExtractedBenchmark`` records
        which chunk the number came from.

        Hallucination guard: any row whose ``paper_id`` is not present in
        the input chunks is dropped.
        """
        if self._llm is None or not chunks:
            return []

        clipped = chunks[: self._max_chunks]
        known_ids = {c.paper_id for c in clipped if c.paper_id}

        chunks_block_lines: list[str] = []
        for c in clipped:
            chunks_block_lines.append(
                f"[paper={c.paper_id} section={c.section} "
                f"is_table={'yes' if c.is_table else 'no'}]"
            )
            chunks_block_lines.append(c.text or "")
            chunks_block_lines.append("")

        prompt = _CHUNKS_PROMPT.format(
            dataset=dataset, metric=metric, task_type=task_type,
            chunks_block="\n".join(chunks_block_lines),
        )
        try:
            raw = self._llm(prompt) or ""
        except Exception as e:
            logger.warning(
                "BenchmarkExtractor.extract_from_chunks LLM call failed: %s", e,
            )
            return []

        raw = _strip_fence(raw)
        try:
            rows = json.loads(raw)
        except Exception:
            logger.debug(
                "BenchmarkExtractor.extract_from_chunks non-JSON: %s",
                raw[:200],
            )
            return []
        if not isinstance(rows, list):
            return []

        out: list[ExtractedBenchmark] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = str(row.get("paper_id", "")).strip()
            if not pid or pid not in known_ids:
                # Hallucination guard.
                continue
            try:
                value = float(row.get("metric_value"))
            except (TypeError, ValueError):
                continue
            out.append(ExtractedBenchmark(
                paper_id=pid,
                method=str(row.get("method", "?")),
                dataset=str(row.get("dataset", dataset)),
                metric_name=str(row.get("metric_name", metric)).lower(),
                metric_value=value,
                evidence=str(row.get("evidence", "")),
                confidence=str(row.get("confidence", "medium")),
                source_section=str(row.get("source_section", "")),
            ))
        return out
