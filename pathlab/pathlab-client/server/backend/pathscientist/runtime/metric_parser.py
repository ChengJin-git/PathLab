"""Recover structured metrics from experiment logs."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from ..llm_client import build_chat_llm, extract_text, has_chat_llm_config, invoke_chat_llm
from ..orchestrator.metrics_utils import resolve_primary_metric
from ..structured_output import extract_json

logger = logging.getLogger(__name__)


_PAIR_PATTERN = re.compile(
    r"(?P<key>[A-Za-z][A-Za-z0-9_/\- ]{0,40})\s*[:=]\s*"
    r"(?P<value>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
)

_DIRECT_PREFIXES = ("best_val_", "test_", "val_", "train_", "best_")

_METRIC_ALIASES = {
    "auc": "auc",
    "auroc": "auc",
    "roc_auc": "auc",
    "rocauc": "auc",
    "accuracy": "accuracy",
    "acc": "accuracy",
    "f1": "f1",
    "f1_score": "f1",
    "f1score": "f1",
    "precision": "precision",
    "prec": "precision",
    "recall": "recall",
    "rec": "recall",
    "loss": "loss",
    "c_index": "c_index",
    "cindex": "c_index",
    "c_idx": "c_index",
    "c-indx": "c_index",
    "c_idx_score": "c_index",
    "concordance_index": "c_index",
}


def _sanitize_key(raw_key: str) -> str:
    return (
        raw_key.strip()
        .strip("\"'`[](){}")
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


def _normalize_metric_key(raw_key: str, context_split: str = "") -> str | None:
    key = _sanitize_key(raw_key)
    if not key:
        return None

    if key.startswith("best_validation_"):
        key = "best_val_" + key[len("best_validation_"):]
    elif key.startswith("validation_"):
        key = "val_" + key[len("validation_"):]

    prefix = ""
    metric_name = key
    for candidate in _DIRECT_PREFIXES:
        if key.startswith(candidate):
            prefix = candidate
            metric_name = key[len(candidate):]
            break

    normalized_metric = _METRIC_ALIASES.get(metric_name)
    if normalized_metric is None:
        return None

    if prefix:
        return f"{prefix}{normalized_metric}"
    if context_split:
        return f"{context_split}_{normalized_metric}"
    return normalized_metric


def _infer_split_from_text(text: str) -> str:
    lowered = text.lower()
    if "best val" in lowered or "best_val" in lowered or "best validation" in lowered:
        return "best_val"
    if "test:" in lowered or "test set" in lowered or "held-out" in lowered:
        return "test"
    if "validation" in lowered or re.search(r"\bval\b", lowered):
        return "val"
    if "train:" in lowered or re.search(r"\btrain\b", lowered):
        return "train"
    return ""


def _coerce_metric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _parse_metrics_deterministically(text: str) -> dict[str, float]:
    recovered: dict[str, float] = {}
    for line in text.splitlines():
        context_split = _infer_split_from_text(line)
        for match in _PAIR_PATTERN.finditer(line):
            metric_key = _normalize_metric_key(match.group("key"), context_split=context_split)
            if not metric_key:
                continue
            try:
                recovered[metric_key] = float(match.group("value"))
            except ValueError:
                continue
    return recovered


def _normalize_metric_payload(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}

    if isinstance(payload.get("metrics"), dict):
        payload = payload["metrics"]

    normalized: dict[str, float] = {}
    for raw_key, raw_value in payload.items():
        metric_key = _normalize_metric_key(str(raw_key))
        metric_value = _coerce_metric_value(raw_value)
        if metric_key and metric_value is not None:
            normalized[metric_key] = metric_value
    return normalized


def _default_llm_metric_parser(text: str, primary_metric: str, config=None) -> dict[str, float]:
    llm = build_chat_llm(
        config,
        component="metric parsing",
        usage_id="metric_parser",
        temperature=0.0,
    )

    prompt = (
        "You extract numeric experiment metrics from training logs.\n"
        "Return ONLY JSON.\n"
        "Use the schema {\"metrics\": {\"test_auc\": 0.88}}.\n"
        "Normalize keys to one of: test_*, val_*, best_val_*, train_*, or bare metric names.\n"
        "Common metric names: auc, accuracy, f1, precision, recall, loss, c_index.\n"
        "Only include metrics explicitly reported in the log. Do not infer targets or goals.\n"
        f"Primary metric: {primary_metric}\n\n"
        "Log excerpt:\n"
        f"{text[-6000:]}"
    )
    from openhands.sdk.llm import Message, TextContent
    response = invoke_chat_llm(
        llm,
        messages=[Message(role="user", content=[TextContent(text=prompt)])],
    )
    raw_text = extract_text(response)
    return _normalize_metric_payload(extract_json(raw_text))


def recover_metrics_from_logs(
    current_metrics: dict | None,
    primary_metric: str,
    log_texts: Sequence[str],
    llm_parser: Callable[[str, str], dict] | None = None,
) -> dict[str, float]:
    """Merge known metrics with metrics recovered from logs.

    Current metrics always win. Deterministic parsing runs first. LLM fallback
    only runs if the primary metric is still missing afterwards.
    """
    merged = dict(current_metrics or {})
    if resolve_primary_metric(merged, primary_metric) > 0:
        return merged

    for text in log_texts:
        if not text:
            continue
        for key, value in _parse_metrics_deterministically(text).items():
            merged.setdefault(key, value)
        if resolve_primary_metric(merged, primary_metric) > 0:
            return merged

    if llm_parser is None:
        return merged

    combined_text = "\n\n".join(text for text in log_texts if text).strip()
    if not combined_text:
        return merged

    try:
        for key, value in _normalize_metric_payload(llm_parser(combined_text, primary_metric)).items():
            merged.setdefault(key, value)
    except Exception as exc:
        logger.warning("LLM metric parsing failed: %s", exc)

    return merged


def build_llm_metric_parser(config=None) -> Callable[[str, str], dict[str, float]] | None:
    """Create a default LLM-backed metric parser bound to the current config."""
    if config is None:
        return None
    if not has_chat_llm_config(config):
        return None

    def _parser(text: str, primary_metric: str) -> dict[str, float]:
        return _default_llm_metric_parser(text, primary_metric, config=config)

    return _parser


# Plan-2026-04-29 P0-3: BenchmarkExtractor takes a (prompt: str) -> str caller,
# NOT a (text, primary_metric) -> dict metric parser. Wiring it with
# ``build_llm_metric_parser`` raised
# ``_parser() missing 1 required positional argument: 'primary_metric'``
# every time the SOTA fallback reached the LLM extractor (session_6bed65f7).
# This helper is the right shape for raw-text LLM calls.
def build_llm_text_caller(config=None) -> Callable[[str], str] | None:
    """Create a generic (prompt: str) -> str LLM caller bound to the current config.

    Returns ``None`` when no chat LLM config is available so callers can
    cleanly fall through (BenchmarkExtractor treats ``None`` as "extractor
    disabled" and returns []).
    """
    if config is None or not has_chat_llm_config(config):
        return None

    def _caller(prompt: str) -> str:
        from openhands.sdk.llm import Message, TextContent
        llm = build_chat_llm(
            config,
            component="benchmark extraction",
            usage_id="benchmark_extractor",
            temperature=0.0,
        )
        response = invoke_chat_llm(
            llm,
            messages=[Message(role="user", content=[TextContent(text=prompt)])],
        )
        return extract_text(response)

    return _caller
