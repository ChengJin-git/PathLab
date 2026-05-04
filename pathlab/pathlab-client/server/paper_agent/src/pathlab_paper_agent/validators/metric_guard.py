"""Metric guard: metric placeholders and raw numeric leakage checks."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from gateway.paper_generation.storage import PaperRunPaths

from .common import GuardReport, paper_text_files, rel_to_run

_PLACEHOLDER_RE = re.compile(r"\{\{\s*m:([A-Za-z0-9_.:-]+)\s*\}\}")
# Metric-like numbers only: decimals, percentages, and p-value thresholds.
_NUMERIC_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:p\s*[<=>]\s*)?(?:0?\.\d+|\d+\.\d+|\d+(?:\.\d+)?%)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def load_evidence_lock(paths: PaperRunPaths) -> dict[str, Any]:
    if not paths.evidence_lock_private.exists():
        return {}
    return json.loads(paths.evidence_lock_private.read_text(encoding="utf-8"))


def _metric_key(item: dict[str, Any]) -> str | None:
    for key in ("key", "metric_key", "name", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def metric_entries(evidence_lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = evidence_lock.get("metrics") or {}
    if isinstance(raw, dict):
        entries: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                entries[str(key)] = value
            else:
                entries[str(key)] = {"value": value}
        return entries
    if isinstance(raw, list):
        entries = {}
        for item in raw:
            if isinstance(item, dict):
                key = _metric_key(item)
                if key:
                    entries[key] = item
        return entries
    return {}


def _strip_decimal(text: str) -> str:
    if "." not in text:
        return text
    stripped = text.rstrip("0").rstrip(".")
    return stripped or "0"


def _format_decimal(value: Decimal, places: int) -> str:
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return _strip_decimal(format(value.quantize(quant), "f"))


def _as_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _variants_for_value(value: Any) -> set[str]:
    variants: set[str] = set()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            variants.add(stripped)
        numeric_source = stripped.rstrip("%")
    else:
        numeric_source = value

    dec = _as_decimal(numeric_source)
    if dec is None:
        return variants

    for places in (0, 1, 2, 3, 4):
        variants.add(_format_decimal(dec, places))
    pct = dec * Decimal("100")
    for places in (0, 1, 2):
        variants.add(f"{_format_decimal(pct, places)}%")
    return variants


def allowed_metric_strings(entries: dict[str, dict[str, Any]]) -> set[str]:
    allowed: set[str] = set()
    for entry in entries.values():
        for field in (
            "value",
            "formatted",
            "display",
            "text",
            "ci_lower",
            "ci_upper",
            "std",
            "mean",
        ):
            if field in entry:
                allowed.update(_variants_for_value(entry[field]))
        ci = entry.get("ci")
        if isinstance(ci, (list, tuple)):
            for item in ci:
                allowed.update(_variants_for_value(item))
        elif isinstance(ci, dict):
            for item in ci.values():
                allowed.update(_variants_for_value(item))
    return {item for item in allowed if item}


def render_metric_placeholders(text: str, evidence_lock: dict[str, Any]) -> str:
    entries = metric_entries(evidence_lock)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        entry = entries.get(key)
        if entry is None:
            raise KeyError(key)
        for field in ("formatted", "display", "text", "value"):
            if field in entry:
                return str(entry[field])
        raise KeyError(key)

    return _PLACEHOLDER_RE.sub(repl, text)


def _scan_file(path: Path, paths: PaperRunPaths, report: GuardReport, entries: dict[str, dict[str, Any]]) -> None:
    rel = rel_to_run(paths, path)
    text = path.read_text(encoding="utf-8")
    allowed = allowed_metric_strings(entries)

    for match in _PLACEHOLDER_RE.finditer(text):
        key = match.group(1)
        if key not in entries:
            report.error(
                "unknown_metric_placeholder",
                f"Metric placeholder {key!r} is not present in evidence_lock.private.json.",
                path=rel,
                context=match.group(0),
            )
        else:
            report.error(
                "unrendered_metric_placeholder",
                "Metric placeholder is still present in paper-facing text; render it before validation.",
                path=rel,
                context=match.group(0),
            )

    without_placeholders = _PLACEHOLDER_RE.sub("", text)
    for match in _NUMERIC_RE.finditer(without_placeholders):
        token = re.sub(r"^p\s*[<=>]\s*", "", match.group(0), flags=re.IGNORECASE)
        if token not in allowed:
            report.error(
                "unlocked_numeric_value",
                "Metric-like numeric value is not evidence-locked or rendered from a metric placeholder.",
                path=rel,
                context=match.group(0),
            )


def run(paths: PaperRunPaths) -> GuardReport:
    evidence_lock = load_evidence_lock(paths)
    entries = metric_entries(evidence_lock)
    report = GuardReport(
        "metric_guard",
        metadata={
            "metric_count": len(entries),
            "checked_files": [],
        },
    )
    checked = paper_text_files(paths)
    report.metadata["checked_files"] = [rel_to_run(paths, path) for path in checked]
    for path in checked:
        _scan_file(path, paths, report, entries)
    return report
