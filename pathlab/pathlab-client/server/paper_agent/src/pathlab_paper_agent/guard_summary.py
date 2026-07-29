from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .schemas import GuardIssueSummary, GuardResultSummary


_PUBLIC_ISSUE_SUMMARIES: dict[tuple[str, str], tuple[str, str]] = {
    (
        "claim_guard",
        "unsupported_external_validation_claim",
    ): (
        "claim_evidence_gap",
        "A claim about external validation needs matching evidence before export.",
    ),
    (
        "metric_guard",
        "raw_metric",
    ): (
        "metric_format_review",
        "A reported metric needs reader-ready wording instead of raw locked values.",
    ),
    (
        "metric_guard",
        "rounding",
    ): (
        "metric_format_review",
        "A reported metric needs rounding or presentation review before export.",
    ),
}

_GUARD_FALLBACK_ISSUES: dict[str, tuple[str, str]] = {
    "metric_guard": ("metric_review", "A reported metric needs review before export."),
    "identifier_guard": ("identifier_review", "A protected identifier needs review before export."),
    "latex_guard": ("latex_review", "A LaTeX formatting issue needs review before export."),
    "citation_guard": ("citation_review", "A citation needs review before export."),
    "claim_guard": ("claim_review", "A manuscript claim needs evidence review before export."),
    "consistency_guard": ("consistency_review", "A consistency issue needs review before export."),
}


def _public_issue_location(issue: dict[str, Any]) -> str | None:
    raw_path = issue.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None

    path = PurePosixPath(raw_path)
    parts = path.parts
    try:
        section_index = parts.index("sections")
    except ValueError:
        return None
    if section_index + 1 >= len(parts):
        return None
    stem = PurePosixPath(parts[section_index + 1]).stem
    location = stem.replace("_", " ").replace("-", " ").strip()
    if not location:
        return None
    return location[:1].upper() + location[1:]


def _public_issue_summary(guard: str, issue: dict[str, Any]) -> GuardIssueSummary:
    raw_code = str(issue.get("code") or "unknown")
    public_code, message = _PUBLIC_ISSUE_SUMMARIES.get(
        (guard, raw_code),
        _GUARD_FALLBACK_ISSUES.get(guard, ("guard_review", "A validation issue needs review before export.")),
    )
    return GuardIssueSummary(
        code=public_code,
        message=message,
        severity=str(issue.get("severity") or "error"),
        location=_public_issue_location(issue),
    )


def build_guard_result_summary(
    report: dict[str, Any],
    guard: str,
    *,
    max_sample_issues: int,
) -> GuardResultSummary:
    raw_issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    issues = [issue for issue in raw_issues if isinstance(issue, dict)]
    error_count = sum(1 for issue in issues if str(issue.get("severity") or "error") == "error")
    warning_count = sum(1 for issue in issues if str(issue.get("severity") or "") == "warning")
    public_guard = str(report.get("guard") or guard)
    sample_issues = [
        _public_issue_summary(public_guard, issue)
        for issue in issues[:max_sample_issues]
    ]
    return GuardResultSummary(
        guard=public_guard,
        status=str(report.get("status") or ("fail" if error_count else "pass")),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        sample_issues=sample_issues,
    )
