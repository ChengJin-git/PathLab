"""Shared metric resolution utilities for orchestrator and tracker."""
from __future__ import annotations

import re


_SYNTHETIC_BOOLEAN_KEYS = {
    "synthetic_data",
    "simulated_data",
    "mock_data",
    "dummy_data",
    "fake_data",
    "demo_data",
    "generated_data",
    "uses_synthetic_data",
    "is_synthetic",
}
_SYNTHETIC_SOURCE_KEYS = {
    "data_source",
    "dataset_source",
    "dataset_origin",
    "data_origin",
    "data_mode",
    "source",
    "dataset",
    "dataset_name",
    "training_data_source",
}
_SYNTHETIC_TOKENS = {
    "synthetic",
    "simulated",
    "simulation",
    "mock",
    "dummy",
    "fake",
    "demo",
}


def _metric_name_variants(metric_name: str) -> list[str]:
    """Generate common key variants for one metric name."""
    raw = metric_name.strip().lower()
    variants: list[str] = []
    for candidate in {
        raw,
        raw.replace("-", "_"),
        raw.replace(" ", "_"),
        raw.replace("-", "").replace(" ", ""),
    }:
        if candidate:
            variants.append(candidate)
    return variants


def _coerce_numeric(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _normalize_key(key) -> str:
    return str(key or "").strip().lower().replace("-", "_").replace(" ", "_")


def _truthy_marker(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _contains_synthetic_token(value: str) -> bool:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if token
    }
    return bool(tokens & _SYNTHETIC_TOKENS)


def is_invalid_synthetic_run(metrics: dict | None) -> bool:
    """Return True when metrics identify a fake/synthetic-data experiment.

    This is a hard scientific-integrity guard. Agents may still create toy
    data for local debugging, but any run whose metrics advertise synthetic,
    mock, dummy, demo, or simulated data must not become a candidate best or
    be committed as a real experiment.
    """
    if not isinstance(metrics, dict) or not metrics:
        return False

    stack = [metrics]
    while stack:
        payload = stack.pop()
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            normalized_key = _normalize_key(key)
            if normalized_key in _SYNTHETIC_BOOLEAN_KEYS and _truthy_marker(value):
                return True
            if (
                normalized_key in _SYNTHETIC_SOURCE_KEYS
                and isinstance(value, str)
                and _contains_synthetic_token(value)
            ):
                return True
            if isinstance(value, dict):
                stack.append(value)
    return False


def resolve_primary_metric(metrics: dict, metric_name: str) -> float:
    """Extract the primary metric value from a metrics dict.

    Handles both flat ({"auc": 0.87}) and nested ({"test": {"auc": 0.87}}) formats.
    Returns 0.0 if not found.
    """
    if not metrics or not isinstance(metrics, dict):
        return 0.0

    variants = _metric_name_variants(metric_name)

    # Preferred order: direct metric -> nested test -> flat test_*
    for key in variants:
        if key in metrics:
            value = _coerce_numeric(metrics[key])
            if value is not None:
                return value

    test_metrics = metrics.get("test", {})
    if isinstance(test_metrics, dict):
        for key in variants:
            value = _coerce_numeric(test_metrics.get(key))
            if value is not None:
                return value

    for prefix in ("test_", "val_", "best_val_", "best_"):
        for key in variants:
            value = _coerce_numeric(metrics.get(f"{prefix}{key}"))
            if value is not None:
                return value

    return 0.0


def is_non_metric_setup_run(
    metrics: dict | None,
    metric_name: str,
    *,
    run_kind: str = "",
    exit_code: int = 0,
    error_type: str = "",
) -> bool:
    """Return True for setup/data-prep runs that must not count as training metrics.

    Feature extraction is a data setup step: it can produce evidence and be
    committed, but it should not consume the scientific iteration budget or
    appear as an AUC row. ``run_kind`` is authoritative for new runs; the
    metric-shape fallback handles older evidence/tracker entries that only
    stored feature-extraction counters.
    """
    normalized_kind = (run_kind or "").strip().lower()
    if normalized_kind == "feature_extraction":
        return True

    if exit_code != 0 or error_type:
        return False
    if resolve_primary_metric(metrics or {}, metric_name) > 0:
        return False

    payload = metrics or {}
    if not isinstance(payload, dict):
        return False
    setup_markers = {
        "patches_extracted",
        "successful_wsi",
        "total_wsi",
        "success_rate",
    }
    if not (setup_markers & set(payload.keys())):
        return False
    status = str(payload.get("status", "") or "").strip().lower()
    return status in {"", "completed", "success", "succeeded"}


def is_external_test_run(*, run_kind: str = "") -> bool:
    """Return True for external evaluation runs that should not optimize best."""
    return (run_kind or "").strip().lower() == "external_test"


def recompute_best_metric_from_history(history: list[dict], metric_name: str) -> float:
    """Recompute the best committed metric from tracker history."""
    best = 0.0
    for entry in history or []:
        if not isinstance(entry, dict) or not entry.get("committed", False):
            continue
        value = resolve_primary_metric(entry.get("metrics", {}), metric_name)
        if value >= best:
            best = value
    return best


def repair_tracker_state_payload(
    tracker_state: dict | None,
    default_metric: str = "auc",
) -> tuple[dict, bool]:
    """Normalize persisted tracker state from possibly stale metric payloads."""
    payload = dict(tracker_state or {})
    history = payload.get("history", [])
    metric_name = payload.get("primary_metric", default_metric) or default_metric
    changed = False

    if history:
        best_value = recompute_best_metric_from_history(history, metric_name)
        if payload.get("best_value", 0.0) != best_value:
            payload["best_value"] = best_value
            changed = True

        last_iteration = max(
            (
                entry.get("iteration", -1)
                for entry in history
                if isinstance(entry, dict)
            ),
            default=-1,
        )
        if last_iteration >= 0 and payload.get("iteration", 0) != last_iteration:
            payload["iteration"] = last_iteration
            changed = True

    return payload, changed
