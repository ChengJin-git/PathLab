"""LLM task-profile enrichment for grounding.

The deterministic ``dataset.task_profile.infer_task_profile`` path remains the
offline source of truth. This module only fills missing/uncertain fields from a
structured LLM response and fails open when the LLM is unavailable or malformed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable

from ..structured_output import extract_json
from .organ_resolver import OrganResolver
from .types import TaskProfile

logger = logging.getLogger(__name__)

_ALLOWED_CONFIDENCE = {"", "low", "medium", "high"}
_ALLOWED_TASK_TYPES = {
    "",
    "classification",
    "patch_classification",
    "mil_classification",
    "segmentation",
    "survival",
    "survival_analysis",
    "feature_extraction",
}
_ALLOWED_ASSET_LEVELS = {"", "patch", "slide", "region"}
_ALLOWED_INPUT_MODALITIES = {
    "",
    "patch_images",
    "wsi",
    "features",
    "clinical_table",
    "histology",
}
_ALLOWED_LABEL_GRANULARITY = {"", "patch", "slide", "pixel"}

_CONF_RANK = {"": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class LLMTaskProfileEnrichment:
    """Validated subset of a structured LLM task-profile response."""

    organ: str = ""
    organ_confidence: str = ""
    task_type: str = ""
    task_type_confidence: str = ""
    asset_level: str = ""
    asset_level_confidence: str = ""
    input_modality: str = ""
    input_modality_confidence: str = ""
    label_granularity: str = ""
    label_granularity_confidence: str = ""
    prediction_target: str = ""
    prediction_target_confidence: str = ""
    required_label_keywords: list[str] = field(default_factory=list)
    dataset_hint_candidates: list[dict[str, str]] = field(default_factory=list)
    reason: str = ""

    def is_empty(self) -> bool:
        return not any(
            [
                self.organ,
                self.task_type,
                self.asset_level,
                self.input_modality,
                self.label_granularity,
                self.prediction_target,
                self.required_label_keywords,
                self.dataset_hint_candidates,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _confidence(value: Any) -> str:
    conf = _norm_lower(value)
    return conf if conf in _ALLOWED_CONFIDENCE else ""


def _safe_unknown_organ_slug(value: str) -> str:
    text = _norm_lower(value)
    if text in {"", "unknown", "unclear", "not specified", "n/a", "na", "none", "null"}:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:64]


def _normalize_organ(value: Any) -> str:
    raw = _norm(value)
    if not raw:
        return ""
    resolver = OrganResolver.load_default()
    match = resolver.normalize(raw, source="llm")
    if not match.canonical:
        match = resolver.resolve_text(raw, source="llm")
    return match.canonical or _safe_unknown_organ_slug(raw)


def _clean_keywords(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _norm(item)
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _clean_dataset_candidates(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, str):
            name = _norm(item)
            confidence = "medium"
            reason = ""
        elif isinstance(item, dict):
            name = _norm(item.get("name"))
            confidence = _confidence(item.get("confidence")) or "low"
            reason = _norm(item.get("reason"))
        else:
            continue
        key = name.lower()
        if name and key not in seen:
            out.append({"name": name, "confidence": confidence, "reason": reason})
            seen.add(key)
    return out


def parse_llm_task_profile_response(raw: str) -> LLMTaskProfileEnrichment:
    """Parse and validate the LLM's JSON object. Invalid output returns empty."""
    try:
        data = extract_json(raw or "")
    except Exception:
        return LLMTaskProfileEnrichment()
    if not isinstance(data, dict):
        return LLMTaskProfileEnrichment()

    organ = _normalize_organ(data.get("organ"))
    task_type = _norm_lower(data.get("task_type"))
    if task_type not in _ALLOWED_TASK_TYPES:
        task_type = ""
    asset_level = _norm_lower(data.get("asset_level"))
    if asset_level not in _ALLOWED_ASSET_LEVELS:
        asset_level = ""
    input_modality = _norm_lower(data.get("input_modality"))
    if input_modality not in _ALLOWED_INPUT_MODALITIES:
        input_modality = ""
    label_granularity = _norm_lower(data.get("label_granularity"))
    if label_granularity not in _ALLOWED_LABEL_GRANULARITY:
        label_granularity = ""

    return LLMTaskProfileEnrichment(
        organ=organ,
        organ_confidence=_confidence(data.get("organ_confidence")),
        task_type=task_type,
        task_type_confidence=_confidence(data.get("task_type_confidence")),
        asset_level=asset_level,
        asset_level_confidence=_confidence(data.get("asset_level_confidence")),
        input_modality=input_modality,
        input_modality_confidence=_confidence(data.get("input_modality_confidence")),
        label_granularity=label_granularity,
        label_granularity_confidence=_confidence(data.get("label_granularity_confidence")),
        prediction_target=_norm_lower(data.get("prediction_target")),
        prediction_target_confidence=_confidence(data.get("prediction_target_confidence")),
        required_label_keywords=_clean_keywords(data.get("required_label_keywords")),
        dataset_hint_candidates=_clean_dataset_candidates(data.get("dataset_hint_candidates")),
        reason=_norm(data.get("reason")),
    )


def _conf_at_least(confidence: str, minimum: str = "medium") -> bool:
    return _CONF_RANK.get(confidence, 0) >= _CONF_RANK[minimum]


def _merge_keywords(base: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in [*base, *extra]:
        text = _norm(item)
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _dataset_keywords_from_candidates(
    candidates: list[dict[str, str]],
    label_keywords: list[str],
) -> list[str]:
    keywords: list[str] = []
    for item in candidates:
        name = _norm(item.get("name"))
        if not name:
            continue
        keywords.append(name)
        upper = name.upper()
        for alias in ("LUAD", "LUSC", "NSCLC"):
            if alias in upper:
                keywords.append(alias)
        if upper in {"TCGA-LUAD", "TCGA-LUSC", "TCGA-LUNG"}:
            keywords.append("TCGA")
    keywords.extend(label_keywords)
    return _merge_keywords([], keywords)


def _task_shape_from_enrichment(
    enrichment: LLMTaskProfileEnrichment,
) -> dict[str, Any]:
    """Translate coarse LLM fields into PathScientist's concrete task shape."""
    if not _conf_at_least(enrichment.task_type_confidence):
        return {}

    task_type = enrichment.task_type
    asset_level = enrichment.asset_level
    input_modality = enrichment.input_modality

    if task_type == "survival":
        task_type = "survival_analysis"
    if task_type == "classification":
        if asset_level == "slide" or input_modality == "wsi":
            task_type = "mil_classification"
        elif asset_level == "patch" or input_modality in {"patch_images", "histology"}:
            task_type = "patch_classification"
        else:
            return {}

    if task_type == "mil_classification":
        return {
            "task_type": "mil_classification",
            "asset_level": "slide",
            "input_modality": "wsi",
            "label_granularity": "slide",
            "requires_feature_extraction": True,
            "preferred_skill": "mil_classification",
        }
    if task_type == "patch_classification":
        return {
            "task_type": "patch_classification",
            "asset_level": "patch",
            "input_modality": "patch_images",
            "label_granularity": "patch",
            "requires_feature_extraction": False,
            "preferred_skill": "patch_classification",
        }
    if task_type == "segmentation":
        return {
            "task_type": "segmentation",
            "asset_level": "region",
            "input_modality": "patch_images",
            "label_granularity": "pixel",
            "requires_feature_extraction": False,
            "preferred_skill": "patch_segmentation",
        }
    if task_type == "survival_analysis":
        return {
            "task_type": "survival_analysis",
            "asset_level": "slide",
            "input_modality": "features",
            "label_granularity": "slide",
            "requires_feature_extraction": True,
            "preferred_skill": "survival_analysis",
        }
    if task_type == "feature_extraction":
        return {
            "task_type": "feature_extraction",
            "asset_level": "slide",
            "input_modality": "wsi",
            "label_granularity": "slide",
            "requires_feature_extraction": False,
            "preferred_skill": "feature_extraction",
        }
    return {}


def merge_task_profile_enrichment(
    profile: TaskProfile,
    enrichment: LLMTaskProfileEnrichment,
    *,
    allow_task_shape_override: bool = True,
) -> tuple[TaskProfile, dict[str, Any]]:
    """Merge LLM enrichment into a heuristic profile with conservative rules."""
    updates: dict[str, Any] = {}
    sources: dict[str, Any] = {}

    if enrichment.organ and _conf_at_least(enrichment.organ_confidence):
        if not profile.organ:
            updates["organ"] = enrichment.organ
            sources["organ"] = "llm"
        elif OrganResolver.load_default().organ_matches(profile.organ, [enrichment.organ]):
            sources["organ"] = "heuristic+llm"
        else:
            sources["organ_conflict"] = {
                "heuristic": profile.organ,
                "llm": enrichment.organ,
            }

    # Prediction target from deterministic rules is usually stronger. Use LLM
    # when the rule did not infer one, or when it agrees and adds label aliases.
    if enrichment.prediction_target:
        if not profile.prediction_target:
            updates["prediction_target"] = enrichment.prediction_target
            sources["prediction_target"] = "llm"
        elif profile.prediction_target == enrichment.prediction_target:
            sources.setdefault("prediction_target", "heuristic+llm")

    if enrichment.required_label_keywords:
        merged_keywords = _merge_keywords(
            profile.required_label_keywords,
            enrichment.required_label_keywords,
        )
        if merged_keywords != profile.required_label_keywords:
            updates["required_label_keywords"] = merged_keywords
            sources["required_label_keywords"] = "heuristic+llm"

    # Only let LLM change task shape with medium+ task confidence. This is the
    # path that can turn "Gleason grading" into slide-level MIL when the model
    # explicitly says WSI/slide classification.
    task_updates = _task_shape_from_enrichment(enrichment)
    if task_updates and allow_task_shape_override:
        updates.update(task_updates)
        sources["task_shape"] = "llm"

    if enrichment.dataset_hint_candidates:
        sources["dataset_hint_candidates"] = enrichment.dataset_hint_candidates
        merged_dataset_keywords = _merge_keywords(
            profile.dataset_keywords,
            _dataset_keywords_from_candidates(
                enrichment.dataset_hint_candidates,
                enrichment.required_label_keywords,
            ),
        )
        if merged_dataset_keywords != profile.dataset_keywords:
            updates["dataset_keywords"] = merged_dataset_keywords
            sources["dataset_keywords"] = "heuristic+llm"

    if not updates:
        return profile, sources
    return replace(profile, **updates), sources


def _build_prompt(question: str, heuristic_profile: TaskProfile) -> str:
    return f"""You extract a structured task profile for a computational pathology experiment.
Use domain knowledge, but do not invent user constraints. Return ONLY JSON.

Organ/site: return the most specific human anatomy site as a lowercase canonical term when implied by the task.
Examples: stomach for gastritis/gastric, prostate for Gleason/ISUP, colorectal for CRC/MSI,
brain_cns for glioma, liver for HCC, pancreas for PDAC. If uncertain, return "" and explain in reason.
Allowed task_type values: classification, patch_classification, mil_classification, segmentation, survival_analysis, feature_extraction.
Allowed asset_level values: patch, slide, region.
Allowed input_modality values: patch_images, wsi, features, clinical_table, histology.
Confidence values: high, medium, low.

For implicit domain knowledge, include confidence and reason. Example:
"Gleason grading" usually means prostate cancer Gleason/ISUP grading.
For TCGA NSCLC subtype tasks, identify LUAD vs LUSC and include dataset hints
TCGA-LUAD and TCGA-LUSC; use prediction_target "nsclc_subtype".

Schema:
{{
  "organ": "",
  "organ_confidence": "high|medium|low",
  "task_type": "",
  "task_type_confidence": "high|medium|low",
  "asset_level": "",
  "asset_level_confidence": "high|medium|low",
  "input_modality": "",
  "input_modality_confidence": "high|medium|low",
  "label_granularity": "",
  "label_granularity_confidence": "high|medium|low",
  "prediction_target": "",
  "prediction_target_confidence": "high|medium|low",
  "required_label_keywords": [],
  "dataset_hint_candidates": [
    {{"name": "", "confidence": "high|medium|low", "reason": ""}}
  ],
  "reason": ""
}}

Question: {question}
Heuristic profile: {heuristic_profile.to_dict()}
"""


def extract_task_profile_enrichment(
    question: str,
    heuristic_profile: TaskProfile,
    *,
    llm_parser: Callable[[str], str] | None,
) -> LLMTaskProfileEnrichment:
    """Call the LLM once and parse its enrichment response."""
    if llm_parser is None:
        return LLMTaskProfileEnrichment()
    try:
        raw = llm_parser(_build_prompt(question, heuristic_profile))
    except Exception as e:
        logger.warning("LLM task profile enrichment failed: %s", e)
        return LLMTaskProfileEnrichment()
    return parse_llm_task_profile_response(raw)


def infer_task_profile_with_llm(
    question: str,
    heuristic_profile: TaskProfile,
    *,
    llm_parser: Callable[[str], str] | None,
    allow_task_shape_override: bool = True,
) -> tuple[TaskProfile, dict[str, Any]]:
    """Return an enriched TaskProfile plus provenance metadata."""
    enrichment = extract_task_profile_enrichment(
        question,
        heuristic_profile,
        llm_parser=llm_parser,
    )
    if enrichment.is_empty():
        return heuristic_profile, {"llm_task_profile": enrichment.to_dict()}
    merged, sources = merge_task_profile_enrichment(
        heuristic_profile,
        enrichment,
        allow_task_shape_override=allow_task_shape_override,
    )
    sources["llm_task_profile"] = enrichment.to_dict()
    return merged, sources
