"""Claim guard: deterministic keyword claims vs evidence support."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway.paper_generation.storage import PaperRunPaths

from .common import GuardReport, rel_to_run, tex_files_under
from .metric_guard import load_evidence_lock, metric_entries


@dataclass(frozen=True)
class ClaimPattern:
    """One claim keyword family and the derived evidence flag it requires."""

    regex: re.Pattern[str]
    code: str
    missing_flag: str
    missing_label: str


_CLAIM_PATTERNS = (
    ClaimPattern(
        re.compile(
            r"\b(?:external\s+validation|independent\s+cohort|generaliz(?:ation|ability)\s+to|"
            r"generalis(?:ation|ability)\s+to|real[-\s]+world\s+deployment)\b",
            re.IGNORECASE,
        ),
        "unsupported_external_validation_claim",
        "has_external_validation",
        "external_validation evidence",
    ),
    ClaimPattern(
        re.compile(
            r"\b(?:outperform(?:s|ed|ing)?|better\s+than|superior\s+to|"
            r"state[-\s]+of[-\s]+the[-\s]+art|sota)\b",
            re.IGNORECASE,
        ),
        "unsupported_baseline_comparison_claim",
        "has_baseline",
        "baseline source task",
    ),
    ClaimPattern(
        re.compile(
            r"\b(?:statistically\s+significant|significant\s+difference|significantly|p\s*[<=>]\s*0?\.\d+)\b",
            re.IGNORECASE,
        ),
        "unsupported_statistical_significance_claim",
        "has_statistical_test",
        "statistical-test metric such as ci_ or p_value",
    ),
)
_NEGATED_EXTERNAL_RE = re.compile(
    r"\b(?:no|without|lacking|lack(?:s|ed)?|not|did\s+not|does\s+not)\b[^.]{0,80}"
    r"\b(?:external\s+validation|independent\s+cohort|real[-\s]+world\s+deployment)\b",
    re.IGNORECASE,
)


def derive_evidence_flags(evidence_lock: Mapping[str, Any]) -> dict[str, bool]:
    """Derive M10b support flags from the existing evidence-lock schema."""
    entries = metric_entries(dict(evidence_lock))
    return {
        "has_external_validation": bool(evidence_lock.get("external_validation")),
        "has_baseline": _has_baseline_source_task(evidence_lock.get("source_tasks")),
        "has_statistical_test": _has_statistical_test(entries),
    }


def run(paths: PaperRunPaths) -> GuardReport:
    evidence_lock = load_evidence_lock(paths)
    flags = derive_evidence_flags(evidence_lock)
    tex_files = tex_files_under(paths.sections_dir)
    report = GuardReport(
        "claim_guard",
        metadata={
            **flags,
            "checked_files": [rel_to_run(paths, path) for path in tex_files],
        },
    )
    for path in tex_files:
        _scan_file(path, paths, flags, report)
    return report


def _scan_file(path: Path, paths: PaperRunPaths, flags: Mapping[str, bool], report: GuardReport) -> None:
    rel = rel_to_run(paths, path)
    text = _strip_latex_comments(path.read_text(encoding="utf-8"))
    for pattern in _CLAIM_PATTERNS:
        if flags.get(pattern.missing_flag):
            continue
        for match in pattern.regex.finditer(text):
            if _is_negated_external_claim(text, match):
                continue
            keyword = " ".join(match.group(0).split())
            report.error(
                pattern.code,
                f"Claim keyword requires {pattern.missing_label}, but evidence_lock does not support it.",
                path=rel,
                context=f"keyword={keyword}; missing={pattern.missing_flag}",
            )


def _has_baseline_source_task(source_tasks: Any) -> bool:
    if not isinstance(source_tasks, list):
        return False
    for task in source_tasks:
        if isinstance(task, Mapping) and str(task.get("role") or "").casefold() == "baseline":
            return True
    return False


def _has_statistical_test(entries: Mapping[str, Mapping[str, Any]]) -> bool:
    for key, entry in entries.items():
        haystack = " ".join(_flatten_text([key, entry])).casefold()
        if "ci_" in haystack or "p_value" in haystack or "pvalue" in haystack or "p-value" in haystack:
            return True
    return False


def _flatten_text(values: Iterable[Any]) -> list[str]:
    flattened: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            flattened.append(value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                visit(key)
                visit(item)
        elif isinstance(value, list | tuple | set):
            for item in value:
                visit(item)

    for value in values:
        visit(value)
    return flattened


def _is_negated_external_claim(text: str, match: re.Match[str]) -> bool:
    if not match.re.pattern.startswith("\\b(?:external"):
        return False
    start = max(0, match.start() - 100)
    end = min(len(text), match.end() + 20)
    return bool(_NEGATED_EXTERNAL_RE.search(text[start:end]))


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
