"""Literature-grounded MIL aggregator selection.

The selector mirrors ``FeatureExtractorSelector`` but targets the slide-level
MIL aggregator that consumes frozen WSI feature tensors. The output is a small
contract value that the orchestrator can persist and pass to training.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
DEFAULT_MIL_MODEL = "abmil"
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}

_MODEL_CANONICAL: dict[str, str] = {
    "abmil": "ABMIL",
    "meanmil": "MeanMIL",
    "maxmil": "MaxMIL",
    "dsmil": "DSMIL",
    "dtfdmil": "DTFD-MIL",
    "clam_sb": "CLAM-SB",
    "clam_mb": "CLAM-MB",
    "transmil": "TransMIL",
}

_ALIASES: dict[str, str] = {
    "abmil": "abmil",
    "ab-mil": "abmil",
    "attention mil": "abmil",
    "attention-based mil": "abmil",
    "meanmil": "meanmil",
    "mean-mil": "meanmil",
    "maxmil": "maxmil",
    "max-mil": "maxmil",
    "dsmil": "dsmil",
    "dtfdmil": "dtfdmil",
    "dtfd-mil": "dtfdmil",
    "clam": "clam_sb",
    "clam-sb": "clam_sb",
    "clam_sb": "clam_sb",
    "clam-mb": "clam_mb",
    "clam_mb": "clam_mb",
    "transmil": "transmil",
    "trans-mil": "transmil",
}


@dataclass(frozen=True)
class MILModelSelection:
    name: str
    canonical: str
    reason: str
    source: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "canonical": self.canonical,
            "reason": self.reason,
            "source": self.source,
            "confidence": self.confidence,
        }


def list_mil_models() -> list[str]:
    return list(_MODEL_CANONICAL)


def normalize_mil_model_name(value: str = "") -> str:
    """Return the runtime registry key for a MIL aggregator name."""
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_MIL_MODEL
    key = raw.lower().replace("_", "-")
    return _ALIASES.get(key, key.replace("-", "_"))


def canonical_mil_model_name(value: str = "") -> str:
    key = normalize_mil_model_name(value)
    return _MODEL_CANONICAL.get(key, value or _MODEL_CANONICAL[DEFAULT_MIL_MODEL])


_LLM_PROMPT = """Choose ONE MIL aggregator for this WSI classification task.

Task signal:
  organ: {organ}
  prediction target: {target}
  task type: {task_type}

Grounded literature and benchmarks:
{evidence_block}

Available MIL aggregators:
{catalog_block}

Rules:
1. Return one available aggregator only.
2. Prefer the architecture that appears in the strongest on-task baseline/SOTA.
3. Use ABMIL when evidence is weak because it is stable and interpretable.
4. Do not change the foundation model here; choose only the MIL aggregator.

Return ONLY a JSON object:
{{"name": "<aggregator key or canonical name>", "reason": "<<=25 words>", "confidence": "high|medium|low"}}

No commentary, no markdown.
"""


class MILModelSelector:
    """LLM-backed MIL selector with deterministic fallbacks."""

    def __init__(
        self,
        llm_parser: Callable[[str], str] | None,
        *,
        default_name: str = DEFAULT_MIL_MODEL,
        cache_path: Path | None = None,
    ):
        self._llm = llm_parser
        self._default = normalize_mil_model_name(default_name)
        if self._default not in _MODEL_CANONICAL:
            self._default = DEFAULT_MIL_MODEL
        self._cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict[str, str]] = {}
        self._loaded = False

    def select(
        self,
        *,
        task_profile: dict[str, Any] | None = None,
        papers: list[dict[str, Any]] | None = None,
        baselines: list[dict[str, Any]] | None = None,
        sota_target: dict[str, Any] | None = None,
        env_override: str = "",
    ) -> MILModelSelection:
        env = (env_override or os.environ.get("PATHSCIENTIST_MIL_MODEL", "")).strip()
        if env:
            return self._build_selection(env, source="env", reason="env override")

        organ = str((task_profile or {}).get("organ") or "").strip()
        target = str((task_profile or {}).get("prediction_target") or "").strip()
        task_type = str((task_profile or {}).get("task_type") or "").strip()
        cache_key = self._cache_key(organ, target, task_type)
        cached = self._lookup_cache(cache_key)
        if cached is not None:
            entry = {k: v for k, v in cached.items() if k != "ts"}
            return MILModelSelection(**entry, source="cache")

        if self._llm is not None:
            llm_pick = self._llm_pick(
                organ=organ,
                target=target,
                task_type=task_type,
                papers=papers or [],
                baselines=baselines or [],
                sota_target=sota_target,
            )
            if llm_pick is not None:
                self._cache_put(cache_key, {
                    "name": llm_pick.name,
                    "canonical": llm_pick.canonical,
                    "reason": llm_pick.reason,
                    "confidence": llm_pick.confidence,
                })
                return llm_pick

        return self._build_selection(
            self._default,
            source="default",
            reason=f"no grounded MIL signal; default {self._default}",
            confidence="low",
        )

    def _build_selection(
        self,
        name: str,
        *,
        source: str,
        reason: str,
        confidence: str = "medium",
    ) -> MILModelSelection:
        key = normalize_mil_model_name(name)
        if key not in _MODEL_CANONICAL:
            logger.warning(
                "MILModelSelector: unknown MIL model %r from %s; falling back to %s",
                name,
                source,
                self._default,
            )
            key = self._default
            source = "default"
            reason = f"unknown MIL model refused; reverted to {self._default}"
            confidence = "low"
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "medium"
        return MILModelSelection(
            name=key,
            canonical=_MODEL_CANONICAL[key],
            reason=reason,
            source=source,
            confidence=confidence,
        )

    def _llm_pick(
        self,
        *,
        organ: str,
        target: str,
        task_type: str,
        papers: list[dict[str, Any]],
        baselines: list[dict[str, Any]],
        sota_target: dict[str, Any] | None,
    ) -> MILModelSelection | None:
        try:
            prompt = _LLM_PROMPT.format(
                organ=organ or "(unspecified)",
                target=target or "(unspecified)",
                task_type=task_type or "(unspecified)",
                evidence_block=_format_evidence(papers, baselines, sota_target),
                catalog_block=_format_catalog(),
            )
            raw = self._llm(prompt) or ""
        except Exception as exc:
            logger.warning("MILModelSelector LLM call failed: %s", exc)
            return None

        parsed = _parse_json(raw)
        if not isinstance(parsed, dict):
            logger.debug("MIL selector: unparseable LLM response: %s", raw[:200])
            return None
        key = normalize_mil_model_name(str(parsed.get("name", "")).strip())
        if key not in _MODEL_CANONICAL:
            logger.warning("MIL selector: LLM picked unknown aggregator %r", key)
            return None
        confidence = str(parsed.get("confidence", "medium")).strip().lower()
        reason = str(parsed.get("reason", "")).strip()[:200]
        return self._build_selection(
            key,
            source="llm",
            reason=reason or f"LLM pick for organ={organ}/target={target}",
            confidence=confidence,
        )

    @staticmethod
    def _cache_key(organ: str, target: str, task_type: str) -> str:
        return f"{organ.lower()}|{target.lower()}|{task_type.lower()}"

    def _lookup_cache(self, key: str) -> dict[str, str] | None:
        if self._cache_path is None:
            return None
        if not self._loaded:
            self._load()
        return self._cache.get(key)

    def _cache_put(self, key: str, value: dict[str, str]) -> None:
        if self._cache_path is None:
            return
        if not self._loaded:
            self._load()
        self._cache[key] = {**value, "ts": str(int(time.time()))}
        self._save()

    def _load(self) -> None:
        self._loaded = True
        if self._cache_path is None or not self._cache_path.exists():
            return
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("MIL selector: cache corrupt (%s); discarding", exc)
            return
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return
        entries = payload.get("entries", {})
        if isinstance(entries, dict):
            self._cache = {
                str(k): v
                for k, v in entries.items()
                if isinstance(v, dict)
            }

    def _save(self) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": CACHE_VERSION, "entries": self._cache}
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self._cache_path)
        except Exception as exc:
            logger.warning("MIL selector: cache write failed: %s", exc)


def _format_catalog() -> str:
    return "\n".join(
        f"  - {key}: {_MODEL_CANONICAL[key]}"
        for key in list_mil_models()
    )


def _format_evidence(
    papers: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    sota_target: dict[str, Any] | None,
) -> str:
    parts: list[str] = []
    if sota_target:
        parts.append(
            "  - Published SOTA: "
            f"{sota_target.get('paper_title') or sota_target.get('source') or 'unknown'} | "
            f"{sota_target.get('method', '')} | "
            f"{sota_target.get('metric_name', 'metric')}={sota_target.get('metric_value', '?')}"
        )
    for baseline in (baselines or [])[:5]:
        parts.append(
            f"  - Baseline: {baseline.get('method', '?')} | "
            f"{baseline.get('metric_name', 'metric')}={baseline.get('metric_value', '?')} "
            f"on {baseline.get('dataset', '?')}"
        )
    for paper in (papers or [])[:5]:
        parts.append(
            f"  - Paper: {(paper.get('title', '') or '')[:100]} "
            f"({paper.get('year', '?')})"
        )
    return "\n".join(parts) if parts else "  (no grounded literature signal available)"


def _parse_json(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None
