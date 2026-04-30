"""Shared metric resolution utilities for orchestrator and tracker."""
from __future__ import annotations


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
