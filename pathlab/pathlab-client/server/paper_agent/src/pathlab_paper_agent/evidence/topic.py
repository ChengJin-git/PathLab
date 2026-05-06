"""Topic-context extraction for paper evidence bundles."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pathlab_paper_agent.schemas import PaperConfig

from .phi import PhiScrubber

_TOPIC_CONTEXT_RE = re.compile(
    r"\[TOPIC_CONTEXT\]\s*(.*?)\s*\[/TOPIC_CONTEXT\]",
    re.IGNORECASE | re.DOTALL,
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_SPLIT_RE = re.compile(r"\s*(?:,|;|\||/|\bvs\.?\b|\bversus\b)\s*", re.IGNORECASE)

_LIST_FIELDS = {"classes", "sources", "writing_scope", "avoid", "source_task_ids"}
_CONFLICT_FIELDS = {"classes", "task_type", "clinical_endpoint", "prediction_target"}

_KEY_ALIASES = {
    "avoid": "avoid",
    "biomarker": "biomarker",
    "biomarker endpoint": "biomarker_endpoint",
    "clinical endpoint": "clinical_endpoint",
    "clinical endpoint biomarker": "clinical_endpoint",
    "cohort": "cohort",
    "confidence": "confidence",
    "disease": "disease",
    "disease cohort": "disease",
    "endpoint": "clinical_endpoint",
    "method": "method_family",
    "method family": "method_family",
    "modality": "modality",
    "prediction target": "prediction_target",
    "source": "sources",
    "source task": "source_task_ids",
    "source task id": "source_task_ids",
    "source task ids": "source_task_ids",
    "sources": "sources",
    "task type": "task_type",
    "topic": "topic",
    "user goal": "user_goal",
    "user goal from pre training chat": "user_goal",
    "writing scope": "writing_scope",
}

_DISEASE_PATTERNS = (
    (re.compile(r"\bcrc\b|colou?rectal|colon|rectal", re.IGNORECASE), "colorectal cancer"),
    (re.compile(r"\blung\b", re.IGNORECASE), "lung cancer"),
    (re.compile(r"\bbreast\b", re.IGNORECASE), "breast cancer"),
    (re.compile(r"\bprostate\b", re.IGNORECASE), "prostate cancer"),
    (re.compile(r"\bgastric\b|stomach", re.IGNORECASE), "gastric cancer"),
)


def build_topic_context(
    *,
    raw: Mapping[str, Any],
    datasets: list[dict[str, Any]],
    models: list[dict[str, Any]],
    config: PaperConfig,
    idea_text: str,
    scrubber: PhiScrubber,
) -> dict[str, Any]:
    """Build a scrubbed, public-safe topic summary.

    Topic context is user intent, not experimental fact. Explicit user-supplied
    context from ``inputs/idea.md`` wins over deterministic evidence hints; any
    conflicts are recorded so the UI or user can confirm before trusting the
    narrative direction.
    """

    explicit = _topic_from_idea(idea_text)
    evidence = _topic_from_evidence(raw=raw, datasets=datasets, models=models, config=config)
    explicit_has_topic = _has_topic_fields(explicit)

    topic: dict[str, Any] = {}
    sources: set[str] = set()
    conflicts: list[dict[str, Any]] = []

    if explicit:
        sources.add("inputs/idea.md")
        _merge_topic(topic, explicit, overwrite=True)
    if evidence:
        sources.add("pathlab_evidence")
        _merge_topic(topic, evidence, overwrite=False)

    _record_conflicts(conflicts, explicit, evidence)

    explicit_sources = _as_string_list(topic.pop("sources", []))
    sources.update(explicit_sources)
    source_task_ids = [task.task_id for task in config.source_tasks if task.task_id]
    if source_task_ids:
        topic.setdefault("source_task_ids", source_task_ids)
        sources.add("source_tasks")

    if "confidence" not in topic:
        topic["confidence"] = _default_confidence(
            explicit if explicit_has_topic else {},
            evidence,
            conflicts,
        )
    topic["needs_confirmation"] = bool(conflicts) or not explicit_has_topic
    if conflicts:
        topic["conflicts"] = conflicts
    topic["sources"] = sorted(sources)

    return scrubber.scrub(_drop_empty(topic))


def topic_lines(topic: Mapping[str, Any] | None) -> list[str]:
    """Render concise topic lines for ``experimental_log.md``."""

    if not topic:
        return ["- No explicit paper topic context was provided."]

    labels = (
        ("disease", "Disease/cohort"),
        ("cohort", "Cohort"),
        ("biomarker", "Biomarker"),
        ("clinical_endpoint", "Clinical endpoint"),
        ("prediction_target", "Prediction target"),
        ("modality", "Modality"),
        ("task_type", "Task type"),
        ("method_family", "Method family"),
        ("classes", "Classes"),
        ("confidence", "Topic confidence"),
        ("needs_confirmation", "Needs confirmation"),
    )
    lines = []
    for key, label in labels:
        value = topic.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value_text = ", ".join(str(item) for item in value)
        elif isinstance(value, bool):
            value_text = "yes" if value else "no"
        else:
            value_text = str(value)
        lines.append(f"- {label}: {value_text}")
    return lines or ["- Topic context is present but contains no rendered fields."]


def _topic_from_idea(text: str) -> dict[str, Any]:
    block = _topic_from_json_block(text)
    markdown = _topic_from_markdown(text)
    topic: dict[str, Any] = {}
    _merge_topic(topic, markdown, overwrite=True)
    _merge_topic(topic, block, overwrite=True)
    return topic


def _topic_from_json_block(text: str) -> dict[str, Any]:
    match = _TOPIC_CONTEXT_RE.search(text or "")
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"warnings": ["topic_context_block_invalid_json"]}
    if not isinstance(payload, dict):
        return {"warnings": ["topic_context_block_must_be_object"]}
    return _normalize_mapping(payload)


def _topic_from_markdown(text: str) -> dict[str, Any]:
    topic: dict[str, Any] = {}
    section = ""
    for raw_line in (text or "").splitlines():
        heading = _HEADING_RE.match(raw_line)
        if heading:
            section = _normalize_key(heading.group(1))
            continue
        bullet = _BULLET_RE.match(raw_line)
        if not bullet:
            continue
        item = bullet.group(1).strip()
        if not item:
            continue
        if section in {"writing scope", "scope"}:
            topic.setdefault("writing_scope", []).append(item)
            continue
        if section in {"unconfirmed avoid", "avoid", "unconfirmed", "do not"}:
            topic.setdefault("avoid", []).append(item)
            continue
        if section in {"user goal", "user goal from pre training chat"} and ":" not in item:
            topic.setdefault("user_goal", item)
            continue
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        _assign(topic, _canonical_key(key), value.strip())
    return topic


def _topic_from_evidence(
    *,
    raw: Mapping[str, Any],
    datasets: list[dict[str, Any]],
    models: list[dict[str, Any]],
    config: PaperConfig,
) -> dict[str, Any]:
    topic: dict[str, Any] = {}
    task = _primary_task(raw)
    task_type = str(task.get("task_type") or "").strip()
    data_type = str(task.get("data_type") or "").strip()
    task_name = str(task.get("task_name") or "").strip()
    classes = _classes_from_evidence(task, datasets, models)
    evidence_text = " ".join(
        str(item)
        for item in [
            task_name,
            task_type,
            data_type,
            " ".join(classes),
            " ".join(str(row.get("name") or "") for row in datasets),
            " ".join(str(row.get("source_organ") or "") for row in datasets),
        ]
        if item
    )

    if task_type:
        topic["task_type"] = task_type
    if classes:
        topic["classes"] = classes
    if task_name:
        topic["task_name"] = task_name

    modality = _infer_modality(task_type, data_type)
    if modality:
        topic["modality"] = modality
    method_family = _infer_method_family(models, task_type)
    if method_family:
        topic["method_family"] = method_family

    organs = sorted(
        {
            str(row.get("source_organ")).strip()
            for row in datasets
            if str(row.get("source_organ") or "").strip()
        }
    )
    if len(organs) == 1:
        topic["source_organ"] = organs[0]

    disease = _infer_disease(evidence_text)
    if disease:
        topic["disease"] = disease
    if _looks_like_msi(classes, evidence_text):
        topic.setdefault("biomarker", "microsatellite instability")
        topic.setdefault("clinical_endpoint", "microsatellite instability status")
        topic.setdefault("prediction_target", "MSI vs MSS")

    return topic


def _primary_task(raw: Mapping[str, Any]) -> dict[str, Any]:
    tasks = [item for item in raw.get("task_summaries") or [] if isinstance(item, dict)]
    if not tasks:
        return {}
    for item in tasks:
        if item.get("role") == "main":
            return item
    return tasks[0]


def _classes_from_evidence(
    task: Mapping[str, Any],
    datasets: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> list[str]:
    for value in [
        task.get("classes"),
        *(model.get("classes") for model in models),
        *(list((row.get("label_distribution") or {}).keys()) for row in datasets),
    ]:
        classes = _as_string_list(value)
        if classes:
            return classes
    return []


def _infer_modality(task_type: str, data_type: str) -> str:
    joined = f"{task_type} {data_type}".lower()
    if "wsi" in joined:
        return "whole-slide images"
    if "patch" in joined:
        return "pathology image patches"
    return ""


def _infer_method_family(models: list[dict[str, Any]], task_type: str) -> str:
    aggregators = [
        str(model.get("aggregator") or "").strip()
        for model in models
        if str(model.get("aggregator") or "").strip()
    ]
    if not aggregators:
        return "multiple instance learning" if "wsi" in task_type.lower() else ""
    aggregator = aggregators[0].replace("_", " ")
    if "mil" in aggregator.lower() or "wsi" in task_type.lower():
        return f"{aggregator} multiple instance learning"
    return aggregator


def _infer_disease(text: str) -> str:
    for pattern, disease in _DISEASE_PATTERNS:
        if pattern.search(text):
            return disease
    return ""


def _looks_like_msi(classes: list[str], text: str) -> bool:
    lowered_classes = {item.lower() for item in classes}
    if {"msi", "mss"}.issubset(lowered_classes):
        return True
    return bool(re.search(r"\bmsi\b|microsatellite instability", text, re.IGNORECASE))


def _normalize_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    topic: dict[str, Any] = {}
    for key, value in payload.items():
        _assign(topic, _canonical_key(key), value)
    return topic


def _assign(topic: dict[str, Any], key: str, value: Any) -> None:
    if not key or value in (None, ""):
        return
    if key == "biomarker_endpoint":
        topic.setdefault("biomarker", value)
        topic.setdefault("clinical_endpoint", value)
        return
    if key == "source_task_ids":
        topic[key] = _as_string_list(value)
        return
    if key in _LIST_FIELDS:
        topic[key] = _as_string_list(value)
        return
    if isinstance(value, list):
        topic[key] = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, dict):
        topic[key] = _normalize_mapping(value)
    else:
        topic[key] = str(value).strip()


def _merge_topic(target: dict[str, Any], source: Mapping[str, Any], *, overwrite: bool) -> None:
    for key, value in source.items():
        if value in (None, "", [], {}):
            continue
        if overwrite or key not in target or target[key] in (None, "", [], {}):
            target[key] = value


def _record_conflicts(
    conflicts: list[dict[str, Any]],
    explicit: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    for key in _CONFLICT_FIELDS:
        if key not in explicit or key not in evidence:
            continue
        if _normalized_compare(explicit[key]) == _normalized_compare(evidence[key]):
            continue
        conflicts.append(
            {
                "field": key,
                "topic_context": explicit[key],
                "evidence": evidence[key],
            }
        )


def _default_confidence(
    explicit: Mapping[str, Any],
    evidence: Mapping[str, Any],
    conflicts: list[dict[str, Any]],
) -> str:
    if conflicts:
        return "needs_confirmation"
    if explicit and any(explicit.get(key) for key in ("disease", "clinical_endpoint", "prediction_target")):
        return "high"
    if evidence and any(evidence.get(key) for key in ("task_type", "classes", "modality")):
        return "medium"
    return "low"


def _has_topic_fields(topic: Mapping[str, Any]) -> bool:
    return any(
        bool(topic.get(key))
        for key in (
            "disease",
            "cohort",
            "biomarker",
            "clinical_endpoint",
            "prediction_target",
            "modality",
            "task_type",
            "method_family",
            "classes",
        )
    )


def _as_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        parts = [part.strip() for part in _SPLIT_RE.split(stripped) if part.strip()]
        return parts or [stripped]
    return [str(value).strip()]


def _canonical_key(key: Any) -> str:
    normalized = _normalize_key(str(key))
    return _KEY_ALIASES.get(normalized, normalized.replace(" ", "_"))


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"[_:/-]+", " ", key.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _normalized_compare(value: Any) -> str:
    if isinstance(value, list | tuple | set):
        return "|".join(sorted(_normalized_compare(item) for item in value))
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: _drop_empty(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_drop_empty(item) for item in value if item not in (None, "", [], {})]
    return value
