"""LLM-driven feature extractor selection — grounded in task + literature.

Pre-fix, ``runner._prepare_data_readiness_and_execution_plan`` just read
``PATHSCIENTIST_FEATURE_EXTRACTOR`` env var (default ``virchow2``) and
locked it into the execution plan. The YAML catalog
(``feature_extraction.yaml`` / ``patch_classification.yaml``) had rich
tiered recommendations and domain-specific mappings (cytology →
SmartCyto, cervical → SmartCCS, vision_language for text-aware tasks)
but they were only used as system-prompt decoration, never consulted at
decision time.

This selector closes that gap:

  1. env override wins (CI / debugging path)
  2. JSON cache by (organ, target, task_type)
  3. LLM picks from the tiered catalog using:
       - task_profile (organ, prediction_target, task_type)
       - grounded papers (so LLM sees what others tried)
       - baseline rows (so LLM sees which extractor reached the best
         metric on the same dataset)
       - SOTA target (the published winner's method, if known)
  4. domain rule fallback (high-specificity pairings like cytology →
     SmartCyto) only when no valid LLM choice is available
  5. fallback: selector default (``Virchow2`` unless configured) — never
     an imagenet baseline

LLM output is validated against the catalog so a hallucinated extractor
name (``"Best4PathologyModel"``) is rejected and we fall through to the
next tier.
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
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}

# Domain rules — fallback mappings. Only fire when both organ and target
# match a high-specificity pairing the catalog already encodes and the LLM
# is unavailable or returned an invalid pick.
# Returns the canonical extractor name (case-sensitive, as in YAML).
_DOMAIN_RULES: list[tuple[Callable[[str, str], bool], str]] = [
    (
        lambda organ, target: "cytology" in (organ + " " + target).lower(),
        "SmartCyto",
    ),
    (
        lambda organ, target: "cervical" in (organ + " " + target).lower()
        or "cervix" in (organ + " " + target).lower(),
        "SmartCCS",
    ),
]


@dataclass(frozen=True)
class ExtractorSelection:
    name: str             # registry key (lowercase, normalized — what runtime uses)
    canonical: str        # display name from YAML (UNI2, CONCH, Virchow2)
    reason: str           # short rationale, surfaced in plan instructions
    source: str           # "env" | "domain_rule" | "cache" | "llm" | "default"
    confidence: str = "medium"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name, "canonical": self.canonical,
            "reason": self.reason, "source": self.source,
            "confidence": self.confidence,
        }


_LLM_PROMPT = """Choose ONE pathology feature extractor for this task.

Task signal:
  organ: {organ}
  prediction target: {target}
  task type: {task_type}

Grounded literature (what other studies used on this task):
{evidence_block}

Available extractors (with tier):
{catalog_block}

Rules:
1. Never pick an imagenet_baseline (ResNet50, ViT-L/16) as the primary extractor.
2. Pick pathology_specialized only when the task matches its declared domain.
3. Pick vision_language only when the task explicitly needs text alignment.
4. Default to pathology_foundation. Among them, prefer extractors that
   appear in the grounded literature with strong reported metrics.

Return ONLY a JSON object:
{{"name": "<canonical name from the catalog>", "reason": "<<=25 words>", "confidence": "high|medium|low"}}

No commentary, no markdown.
"""


class FeatureExtractorSelector:
    """LLM-driven extractor picker with deterministic fallbacks."""

    def __init__(
        self,
        llm_parser: Callable[[str], str] | None,
        *,
        catalog: dict[str, list[dict[str, str]]],
        default_canonical: str = "Virchow2",
        cache_path: Path | None = None,
    ):
        self._llm = llm_parser
        self._catalog = catalog or {}
        self._default = default_canonical
        # Build a case-insensitive lookup from canonical → tier so we can
        # validate LLM output and reject ablation-tier picks.
        self._name_to_tier: dict[str, str] = {}
        for tier, entries in self._catalog.items():
            for entry in entries or []:
                name = entry.get("name") if isinstance(entry, dict) else str(entry)
                if name:
                    self._name_to_tier[name.lower()] = tier
        self._cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict] = {}
        self._loaded = False

    # ---- public API --------------------------------------------------

    def select(
        self,
        *,
        task_profile: dict[str, Any] | None = None,
        papers: list[dict[str, Any]] | None = None,
        baselines: list[dict[str, Any]] | None = None,
        sota_target: dict[str, Any] | None = None,
        env_override: str = "",
    ) -> ExtractorSelection:
        """Return the chosen extractor, threading 5 fallback layers."""
        # 1. env override
        env = (env_override or os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", "")).strip()
        if env:
            return self._build_selection(env, source="env", reason="env override")

        organ = str((task_profile or {}).get("organ") or "").strip()
        target = str((task_profile or {}).get("prediction_target") or "").strip()
        task_type = str((task_profile or {}).get("task_type") or "").strip()

        # 2. Cache lookup. Cache entries are created from validated LLM picks.
        cache_key = self._cache_key(organ, target, task_type)
        cached = self._lookup_cache(cache_key)
        if cached is not None:
            # ``ts`` is a cache-only field; strip before re-hydrating.
            entry = {k: v for k, v in cached.items() if k != "ts"}
            return ExtractorSelection(**entry, source="cache")

        # 3. LLM pick. The LLM is the primary decision maker when configured;
        # keyword/domain rules are only fallbacks for missing or invalid LLM
        # output.
        if self._llm is not None:
            llm_pick = self._llm_pick(
                organ=organ, target=target, task_type=task_type,
                papers=papers or [], baselines=baselines or [],
                sota_target=sota_target,
            )
            if llm_pick is not None:
                # Cache the dataclass-as-dict minus the volatile ``source`` field.
                self._cache_put(cache_key, {
                    "name": llm_pick.name,
                    "canonical": llm_pick.canonical,
                    "reason": llm_pick.reason,
                    "confidence": llm_pick.confidence,
                })
                return llm_pick

        # 4. Domain rules
        for predicate, canonical in _DOMAIN_RULES:
            try:
                if predicate(organ, target):
                    return self._build_selection(
                        canonical,
                        source="domain_rule",
                        reason=f"LLM unavailable/invalid; task matches "
                               f"{canonical}'s declared domain "
                               f"(organ={organ!r}, target={target!r})",
                        confidence="medium",
                    )
            except Exception:
                continue

        # 5. Default
        return self._build_selection(
            self._default,
            source="default",
            reason=f"no LLM/domain signal; catalog default {self._default}",
            confidence="low",
        )

    # ---- internals ---------------------------------------------------

    def _build_selection(
        self,
        canonical_or_key: str,
        *,
        source: str,
        reason: str,
        confidence: str = "medium",
    ) -> ExtractorSelection:
        """Normalize a name to (registry_key, canonical), guarding against
        ablation picks and unknown names."""
        canonical = self._resolve_canonical(canonical_or_key)
        tier = self._name_to_tier.get(canonical.lower(), "")
        if tier == "imagenet_baseline" and source != "env":
            logger.warning(
                "FeatureExtractorSelector: refused ablation-tier %r from %s; "
                "falling back to default %s",
                canonical, source, self._default,
            )
            canonical = self._default
            source = "default"
            reason = f"refused ablation tier; reverted to {self._default}"
            confidence = "low"
        # Late-import to avoid orchestrator import cycle.
        from ..orchestrator.execution_plan import normalize_feature_extractor_name
        registry_key = normalize_feature_extractor_name(canonical)
        return ExtractorSelection(
            name=registry_key,
            canonical=canonical,
            reason=reason,
            source=source,
            confidence=confidence,
        )

    def _resolve_canonical(self, name: str) -> str:
        """Return the YAML-spelled canonical name when the input matches
        any catalog entry case-insensitively; otherwise return the input
        unchanged so the caller's normalization layer can still try."""
        if not name:
            return self._default
        raw = name.strip()
        candidates = [raw]
        without_origin = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        if without_origin and without_origin not in candidates:
            candidates.append(without_origin)
        lows = [candidate.lower() for candidate in candidates if candidate]
        for tier_entries in self._catalog.values():
            for entry in tier_entries or []:
                yaml_name = entry.get("name") if isinstance(entry, dict) else str(entry)
                if not yaml_name:
                    continue
                if yaml_name.lower() in lows:
                    return yaml_name
                if isinstance(entry, dict):
                    origin = str(entry.get("origin") or "").strip()
                    display = f"{yaml_name} ({origin})".lower() if origin else ""
                    if display and display in lows:
                        return yaml_name
        return name

    def _llm_pick(
        self,
        *,
        organ: str,
        target: str,
        task_type: str,
        papers: list[dict[str, Any]],
        baselines: list[dict[str, Any]],
        sota_target: dict[str, Any] | None,
    ) -> ExtractorSelection | None:
        try:
            evidence_block = _format_evidence(papers, baselines, sota_target)
            catalog_block = _format_catalog(self._catalog)
            prompt = _LLM_PROMPT.format(
                organ=organ or "(unspecified)",
                target=target or "(unspecified)",
                task_type=task_type or "(unspecified)",
                evidence_block=evidence_block,
                catalog_block=catalog_block,
            )
            raw = self._llm(prompt) or ""
        except Exception as e:
            logger.warning("FeatureExtractorSelector LLM call failed: %s", e)
            return None

        parsed = _parse_json(raw)
        if not isinstance(parsed, dict):
            logger.debug("Selector: unparseable LLM response: %s", raw[:200])
            return None
        raw_name = str(parsed.get("name", "")).strip()
        canonical = self._resolve_canonical(raw_name)
        reason = str(parsed.get("reason", "")).strip()[:200]
        confidence = str(parsed.get("confidence", "medium")).strip().lower()
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "medium"
        if not canonical or canonical.lower() not in self._name_to_tier:
            logger.warning(
                "Selector: LLM picked unknown extractor %r; falling through",
                raw_name,
            )
            return None
        return self._build_selection(
            canonical, source="llm",
            reason=reason or f"LLM pick for organ={organ}/target={target}",
            confidence=confidence,
        )

    # ---- cache I/O ---------------------------------------------------

    @staticmethod
    def _cache_key(organ: str, target: str, task_type: str) -> str:
        return f"{organ.lower()}|{target.lower()}|{task_type.lower()}"

    def _lookup_cache(self, key: str) -> dict | None:
        if self._cache_path is None:
            return None
        if not self._loaded:
            self._load()
        return self._cache.get(key)

    def _cache_put(self, key: str, value: dict) -> None:
        if self._cache_path is None:
            return
        if not self._loaded:
            self._load()
        self._cache[key] = {**value, "ts": int(time.time())}
        self._save()

    def _load(self) -> None:
        self._loaded = True
        if self._cache_path is None or not self._cache_path.exists():
            return
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Selector: cache corrupt (%s) — discarding", e)
            return
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return
        entries = payload.get("entries", {})
        if isinstance(entries, dict):
            self._cache = {str(k): v for k, v in entries.items() if isinstance(v, dict)}

    def _save(self) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": CACHE_VERSION, "entries": self._cache}
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self._cache_path)
        except Exception as e:
            logger.warning("Selector: cache write failed: %s", e)


# ---- helpers ---------------------------------------------------------


def _format_evidence(
    papers: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    sota: dict[str, Any] | None,
) -> str:
    """Compact evidence block: SOTA first, then top-3 baselines (with
    method + metric), then top-3 paper titles. Keep small — selector
    LLM doesn't need full abstracts."""
    parts: list[str] = []
    if sota:
        sota_method = sota.get("paper_title") or sota.get("source") or "unknown"
        parts.append(
            f"  - Published SOTA: {sota_method} | "
            f"{sota.get('metric_name', 'metric')}={sota.get('metric_value', '?')}"
        )
    for b in (baselines or [])[:3]:
        parts.append(
            f"  - Baseline: {b.get('method', '?')} | "
            f"{b.get('metric_name', 'metric')}={b.get('metric_value', '?')} "
            f"on {b.get('dataset', '?')}"
        )
    for p in (papers or [])[:3]:
        title = (p.get("title", "") or "")[:80]
        parts.append(f"  - Paper: {title} ({p.get('year', '?')})")
    if not parts:
        return "  (no grounded literature signal available)"
    return "\n".join(parts)


def _format_catalog(catalog: dict[str, list[dict[str, str]]]) -> str:
    lines: list[str] = []
    for tier, entries in catalog.items():
        names = []
        for entry in entries or []:
            if isinstance(entry, dict):
                nm = entry.get("name", "")
                if nm:
                    names.append(nm)
            elif entry:
                names.append(str(entry))
        if names:
            lines.append(f"  {tier}: {', '.join(names)}")
    return "\n".join(lines) if lines else "  (catalog empty)"


def _parse_json(raw: str):
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        s = m.group(0)
    try:
        return json.loads(s)
    except Exception:
        return None


def load_catalog_from_skills() -> dict[str, list[dict[str, str]]]:
    """Read ``extractors_available`` from feature_extraction.yaml.

    Falls back to an empty dict when the skill registry can't be loaded
    (test harnesses without the full YAML tree). Production callers
    should pass the loaded catalog explicitly to avoid hidden file IO.
    """
    try:
        from .skills import registry as _skill_registry

        _skill_registry.load_all()
        skill = _skill_registry.get("feature_extraction")
        catalog = getattr(skill, "extractors_available", None) or {}
        return dict(catalog)
    except Exception as e:
        logger.warning("load_catalog_from_skills failed: %s", e)
        return {}
