"""Optional LLM dataset extractor for discovery.

Phase D T10 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

Pattern follows ``literature/benchmark_extractor.py``:
- Caller injects ``llm_parser: Callable[[str], str] | None`` — typically
  built by ``runtime/metric_parser.build_llm_text_caller(config)``.
- ``llm_parser=None`` (no chat LLM configured) → ``extract()`` returns ``[]``.
- Malformed JSON / LLM exception → ``[]``. Heuristic path stays the source
  of truth when the LLM is unavailable.
- Prompt size bounded by clipping individual texts and the count of texts.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Iterable

from .discovery_types import (
    DatasetDiscoveryEvidence,
    DatasetDiscoveryRecord,
    ProviderHint,
)

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are extracting candidate dataset names from histopathology paper text.

Task profile:
- task_type: {task_type}
- organ: {organ}
- prediction_target: {prediction_target}

For each text snippet, identify dataset names that look like benchmarks
(e.g. "CRC-MSI", "PANDA", "BRACS", "TCGA-CRC", "SICAPv2"). Return a JSON
array. Each element MUST have:
- "name" (required, non-empty)
- "aliases" (list of strings, optional)
- "confidence" ("low" | "medium" | "high")
- "access" ("public" | "manual" | "gated", optional, default "manual")
- "provider_hints" (list of {{"provider", "url", "remote_id"}}, optional)
- "evidence_quote" (a short quote from the text, optional)

Return ONLY the JSON array, no commentary.

Texts:
{texts_block}
"""

_DEFAULT_MAX_TEXTS = 8
_DEFAULT_MAX_TEXT_LEN = 600


# Allow cheap fence-stripping for models that wrap JSON in ```json ... ```.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _coerce_json_array(raw: str) -> list[Any]:
    """Best-effort: extract a JSON array from a model response.

    Handles bare arrays, fenced blocks, and arrays embedded in prose.
    Returns ``[]`` on any failure.
    """
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    m = _JSON_ARRAY_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


_VALID_CONFIDENCE = {"low", "medium", "high"}


def _row_to_record(row: dict[str, Any], profile) -> DatasetDiscoveryRecord | None:
    if not isinstance(row, dict):
        return None
    name = (row.get("name") or "").strip()
    if not name:
        return None
    confidence = (row.get("confidence") or "low").lower()
    if confidence not in _VALID_CONFIDENCE:
        confidence = "low"
    access = (row.get("access") or "manual").lower()
    if access not in {"public", "manual", "gated"}:
        access = "manual"
    aliases_raw = row.get("aliases") or []
    aliases = [a for a in aliases_raw if isinstance(a, str) and a.strip()]
    hints_raw = row.get("provider_hints") or []
    provider_hints: list[ProviderHint] = []
    for h in hints_raw:
        if not isinstance(h, dict):
            continue
        provider_hints.append(ProviderHint(
            provider=(h.get("provider") or "").strip(),
            remote_id=(h.get("remote_id") or "").strip(),
            url=(h.get("url") or "").strip(),
            confidence=confidence,  # inherit row-level
        ))
    quote = (row.get("evidence_quote") or "").strip()
    evidence = [DatasetDiscoveryEvidence(source="llm_hint", quote=quote)]

    record = DatasetDiscoveryRecord(
        name=name,
        aliases=aliases,
        access=access,
        confidence=confidence,
        evidence=evidence,
        provider_hints=provider_hints,
    )
    if profile is not None:
        if getattr(profile, "task_type", ""):
            record.task_types = [profile.task_type]
        if getattr(profile, "input_modality", ""):
            record.asset_types = [profile.input_modality]
        if getattr(profile, "organ", ""):
            record.organs = [profile.organ]
        if getattr(profile, "required_label_keywords", None):
            record.label_keywords = list(profile.required_label_keywords)
        if getattr(profile, "prediction_target", ""):
            record.prediction_target = profile.prediction_target
    return record


class DatasetDiscoveryLLMExtractor:
    """Optional LLM-driven dataset extraction.

    Inject the parser at construction. ``parser=None`` is a deliberate
    no-op so callers can pass ``build_llm_text_caller(config)`` (which
    returns ``None`` when no chat LLM is configured) without branching.
    """

    def __init__(
        self,
        *,
        llm_parser: Callable[[str], str] | None,
        max_texts: int = _DEFAULT_MAX_TEXTS,
        max_text_len: int = _DEFAULT_MAX_TEXT_LEN,
    ):
        self._parser = llm_parser
        self._max_texts = max_texts
        self._max_text_len = max_text_len

    def extract(
        self,
        *,
        texts: Iterable[dict[str, Any]] | None,
        profile,
    ) -> list[DatasetDiscoveryRecord]:
        if self._parser is None:
            return []
        rows = list(texts or [])
        if not rows:
            return []
        clipped = rows[: self._max_texts]
        # Build texts_block, clipping each text to a bounded length.
        text_lines: list[str] = []
        for i, item in enumerate(clipped):
            if not isinstance(item, dict):
                continue
            t = (item.get("text") or "")[: self._max_text_len].replace("\n", " ").strip()
            if not t:
                continue
            paper_id = item.get("paper_id", "")
            text_lines.append(f"[{i}] paper_id={paper_id}: {t}")
        if not text_lines:
            return []
        prompt = _PROMPT_TEMPLATE.format(
            task_type=getattr(profile, "task_type", "") if profile else "",
            organ=getattr(profile, "organ", "") if profile else "",
            prediction_target=getattr(profile, "prediction_target", "") if profile else "",
            texts_block="\n".join(text_lines),
        )
        try:
            raw = self._parser(prompt)
        except Exception as e:
            logger.warning("LLM dataset extractor call failed: %s", e)
            return []
        rows_out = _coerce_json_array(raw)
        records: list[DatasetDiscoveryRecord] = []
        for row in rows_out:
            rec = _row_to_record(row, profile)
            if rec is not None:
                records.append(rec)
        return records
