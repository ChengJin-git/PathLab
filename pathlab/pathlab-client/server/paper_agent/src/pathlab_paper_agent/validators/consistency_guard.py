"""Consistency guard: detect split/scope crosstalk in section prose."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from gateway.paper_generation.storage import PaperRunPaths

from ..renderers.locked_block_renderer import latex_cmd_key
from .common import GuardReport, rel_to_run, tex_files_under
from .metric_guard import load_evidence_lock, metric_entries

_MACRO_RE = re.compile(r"\\(metric[A-Za-z]+)\b")
_EXTERNAL_CONTEXT_RE = re.compile(r"\b(?:external\s+validation|external\s+cohort|independent\s+cohort)\b", re.IGNORECASE)
_TEST_CONTEXT_RE = re.compile(r"\b(?:test\s+set|test\s+cohort|held[-\s]+out\s+test|internal\s+test|on\s+the\s+test)\b", re.IGNORECASE)
_VAL_CONTEXT_RE = re.compile(r"\b(?:validation\s+set|validation\s+cohort|\bval\b|on\s+the\s+validation)\b", re.IGNORECASE)
_INTERNAL_CONTEXT_RE = re.compile(r"\b(?:internal\s+cohort|internal\s+test|internal\s+validation)\b", re.IGNORECASE)
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_SPLIT_PATTERNS = {
    "external": re.compile(r"(?:^|[_.:\-])(?:external|extval|independent)(?:[_.:\-]|$)", re.IGNORECASE),
    "val": re.compile(r"(?:^|[_.:\-])(?:val|valid|validation)(?:[_.:\-]|$)", re.IGNORECASE),
    "test": re.compile(r"(?:^|[_.:\-])test(?:[_.:\-]|$)", re.IGNORECASE),
    "train": re.compile(r"(?:^|[_.:\-])train(?:[_.:\-]|$)", re.IGNORECASE),
}


@dataclass(frozen=True)
class MetricReference:
    """One evidence-lock metric plus reverse renderer lookup data."""

    key: str
    macro: str
    split: str
    scope: str
    variants: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class MetricOccurrence:
    """One concrete metric mention in prose."""

    reference: MetricReference
    start: int
    end: int


@dataclass(frozen=True)
class TextSpan:
    """A local sentence span within a paragraph."""

    start: int
    end: int
    text: str


def run(paths: PaperRunPaths) -> GuardReport:
    evidence_lock = load_evidence_lock(paths)
    metrics = _build_metric_references(evidence_lock)
    tex_files = tex_files_under(paths.sections_dir)
    report = GuardReport(
        "consistency_guard",
        metadata={
            "metric_count": len(metrics),
            "macro_count": len([metric for metric in metrics if metric.macro]),
            "checked_files": [rel_to_run(paths, path) for path in tex_files],
        },
    )
    macro_index = {metric.macro: metric for metric in metrics}
    value_index = _value_index(metrics)
    for path in tex_files:
        _scan_file(path, paths, macro_index, value_index, report)
    return report


def _build_metric_references(evidence_lock: Mapping[str, Any]) -> list[MetricReference]:
    entries = metric_entries(dict(evidence_lock))
    seen: set[str] = set()
    refs: list[MetricReference] = []
    for key, entry in entries.items():
        base = latex_cmd_key(key)
        cmd = base
        suffix = 0
        while cmd in seen:
            suffix += 1
            cmd = f"{base}{_letters_suffix(suffix)}"
        seen.add(cmd)
        split = _classify_split(key, entry)
        scope = "external" if split == "external" or _role(entry) == "external_validation" else "internal"
        refs.append(
            MetricReference(
                key=key,
                macro=f"metric{cmd}",
                split=split,
                scope=scope,
                variants=frozenset(_metric_value_variants(entry)),
            )
        )
    return refs


def _scan_file(
    path: Path,
    paths: PaperRunPaths,
    macro_index: Mapping[str, MetricReference],
    value_index: Mapping[str, tuple[MetricReference, ...]],
    report: GuardReport,
) -> None:
    rel = rel_to_run(paths, path)
    text = _strip_latex_comments(path.read_text(encoding="utf-8"))
    for paragraph in _paragraphs(text):
        spans = _sentence_spans(paragraph)
        for occurrence in _metric_occurrences_in_paragraph(paragraph, macro_index, value_index):
            context, local_text = _context_for_occurrence(paragraph, spans, occurrence)
            if not context:
                continue
            _check_reference_context(report, rel, local_text, context, occurrence.reference)


def _check_reference_context(
    report: GuardReport,
    rel: str,
    paragraph: str,
    context: set[str],
    reference: MetricReference,
) -> None:
    if "external" in context and reference.scope == "internal":
        _emit_crosstalk(
            report,
            rel,
            "external paragraph references internal metric",
            reference,
            paragraph,
        )
    if "test" in context and (reference.scope == "external" or reference.split in {"val", "external"}):
        _emit_crosstalk(
            report,
            rel,
            "test paragraph references validation/external metric",
            reference,
            paragraph,
        )
    if "val" in context and (reference.scope == "external" or reference.split in {"test", "external"}):
        _emit_crosstalk(
            report,
            rel,
            "validation paragraph references test/external metric",
            reference,
            paragraph,
        )
    if "internal" in context and reference.scope == "external":
        _emit_crosstalk(
            report,
            rel,
            "internal paragraph references external metric",
            reference,
            paragraph,
        )


def _emit_crosstalk(
    report: GuardReport,
    rel: str,
    message: str,
    reference: MetricReference,
    paragraph: str,
) -> None:
    report.error(
        "metric_context_crosstalk",
        f"Metric scope/split crosstalk detected: {message}.",
        path=rel,
        context=f"metric={reference.key}; split={reference.split}; scope={reference.scope}; paragraph={_short_context(paragraph)}",
    )


def _metric_occurrences_in_paragraph(
    paragraph: str,
    macro_index: Mapping[str, MetricReference],
    value_index: Mapping[str, tuple[MetricReference, ...]],
) -> list[MetricOccurrence]:
    occurrences: list[MetricOccurrence] = []
    for match in _MACRO_RE.finditer(paragraph):
        metric = macro_index.get(match.group(1))
        if metric is not None:
            occurrences.append(MetricOccurrence(metric, match.start(), match.end()))
    for value, metrics in value_index.items():
        # A raw rendered value is only actionable when it uniquely identifies a
        # metric. Equal test/val scores are common enough that multi-matches
        # would otherwise produce false crosstalk failures.
        if len(metrics) != 1:
            continue
        for match in _value_pattern(value).finditer(paragraph):
            occurrences.append(MetricOccurrence(metrics[0], match.start(), match.end()))
    return sorted(occurrences, key=lambda item: (item.start, item.end, item.reference.key))


def _paragraph_context(paragraph: str) -> set[str]:
    contexts: set[str] = set()
    external = bool(_EXTERNAL_CONTEXT_RE.search(paragraph))
    if external:
        contexts.add("external")
    if _TEST_CONTEXT_RE.search(paragraph):
        contexts.add("test")
        contexts.add("internal")
    if not external and _VAL_CONTEXT_RE.search(paragraph):
        contexts.add("val")
        contexts.add("internal")
    if not external and _INTERNAL_CONTEXT_RE.search(paragraph):
        contexts.add("internal")
    return contexts


def _context_for_occurrence(
    paragraph: str,
    spans: list[TextSpan],
    occurrence: MetricOccurrence,
) -> tuple[set[str], str]:
    span_index = _span_index_for_position(spans, occurrence.start)
    if span_index is None:
        return _paragraph_context(paragraph), paragraph
    span = spans[span_index]
    direct = _paragraph_context(span.text)
    if direct:
        return direct, span.text

    # If the metric sentence itself has no scope word, inherit a single adjacent
    # sentence context. Ambiguous neighbors are intentionally skipped.
    candidates: list[tuple[set[str], str]] = []
    for neighbor_index in (span_index - 1, span_index + 1):
        if neighbor_index < 0 or neighbor_index >= len(spans):
            continue
        neighbor = spans[neighbor_index]
        context = _paragraph_context(neighbor.text)
        if context:
            candidates.append((context, f"{neighbor.text} {span.text}"))
    if len(candidates) == 1:
        return candidates[0]
    return set(), span.text


def _classify_split(key: str, entry: Mapping[str, Any]) -> str:
    explicit = _explicit_split(entry)
    if explicit:
        return explicit
    haystack = " ".join(
        str(value)
        for value in (
            key,
            entry.get("key"),
            entry.get("name"),
            entry.get("metric_key"),
            entry.get("split"),
            entry.get("analysis_id"),
            entry.get("role"),
            entry.get("task_id"),
        )
        if value is not None
    )
    for split, regex in _SPLIT_PATTERNS.items():
        if regex.search(haystack):
            return split
    return "unknown"


def _explicit_split(entry: Mapping[str, Any]) -> str | None:
    for field_name in ("split", "dataset_split", "phase", "set"):
        value = entry.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.casefold().replace(" ", "_")
        if "external" in normalized:
            return "external"
        if normalized in {"val", "valid", "validation", "dev"}:
            return "val"
        if normalized == "test":
            return "test"
        if normalized == "train":
            return "train"
    return None


def _role(entry: Mapping[str, Any]) -> str:
    return str(entry.get("role") or "").strip().casefold()


def _metric_value_variants(entry: Mapping[str, Any]) -> set[str]:
    variants: set[str] = set()
    for field_name in ("formatted", "display", "text"):
        value = entry.get(field_name)
        if isinstance(value, str) and _is_metric_value_text(value):
            variants.add(value.strip())
    value = entry.get("value")
    variants.update(_numeric_variants(value))
    for field_name in ("ci_lower", "ci_upper", "std", "mean"):
        variants.update(_numeric_variants(entry.get(field_name)))
    ci = entry.get("ci")
    if isinstance(ci, Mapping):
        for item in ci.values():
            variants.update(_numeric_variants(item))
    elif isinstance(ci, list | tuple):
        for item in ci:
            variants.update(_numeric_variants(item))
    return {variant for variant in variants if _is_metric_value_text(variant)}


def _numeric_variants(value: Any) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return {str(value).strip()} if isinstance(value, str) else set()
    variants: set[str] = set()
    for places in (0, 1, 2, 3, 4):
        variants.add(_strip_decimal(format(number.quantize(Decimal("1").scaleb(-places)), "f")))
    pct = number * Decimal("100")
    for places in (0, 1, 2):
        variants.add(f"{_strip_decimal(format(pct.quantize(Decimal('1').scaleb(-places)), 'f'))}%")
    return variants


def _value_index(metrics: list[MetricReference]) -> dict[str, tuple[MetricReference, ...]]:
    mapping: dict[str, list[MetricReference]] = {}
    for metric in metrics:
        for variant in metric.variants:
            mapping.setdefault(variant, []).append(metric)
    return {key: tuple(value) for key, value in mapping.items()}


def _value_pattern(value: str) -> re.Pattern[str]:
    escaped = re.escape(value[:-1]) + r"\\?%" if value.endswith("%") else re.escape(value)
    return re.compile(rf"(?<![A-Za-z0-9_.]){escaped}(?![A-Za-z0-9_%])")


def _is_metric_value_text(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and ("." in stripped or "%" in stripped or re.match(r"p\s*[<=>]", stripped, re.IGNORECASE)))


def _strip_decimal(text: str) -> str:
    if "." not in text:
        return text
    stripped = text.rstrip("0").rstrip(".")
    return stripped or "0"


def _letters_suffix(index: int) -> str:
    if index <= 0:
        raise ValueError("suffix index must be positive")
    chars: list[str] = []
    value = index
    while value:
        value -= 1
        chars.append(chr(ord("A") + value % 26))
        value //= 26
    return "".join(reversed(chars))


def _paragraphs(text: str) -> list[str]:
    return [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]


def _sentence_spans(paragraph: str) -> list[TextSpan]:
    spans: list[TextSpan] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(paragraph):
        end = match.start()
        text = paragraph[start:end].strip()
        if text:
            spans.append(TextSpan(start=start, end=end, text=text))
        start = match.end()
    text = paragraph[start:].strip()
    if text:
        spans.append(TextSpan(start=start, end=len(paragraph), text=text))
    return spans or [TextSpan(start=0, end=len(paragraph), text=paragraph)]


def _span_index_for_position(spans: list[TextSpan], position: int) -> int | None:
    for index, span in enumerate(spans):
        if span.start <= position <= span.end:
            return index
    return None


def _short_context(paragraph: str, limit: int = 180) -> str:
    compact = " ".join(paragraph.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "..."


def _strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        escaped = False
        kept: list[str] = []
        for char in line:
            if char == "\\" and not escaped:
                escaped = True
                kept.append(char)
                continue
            if char == "%" and not escaped:
                break
            escaped = False
            kept.append(char)
        lines.append("".join(kept))
    return "\n".join(lines)
