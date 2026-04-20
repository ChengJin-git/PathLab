"""Draft verification — deterministic check that paper draft only references supported evidence."""
from __future__ import annotations

import re

from .types import DraftVerificationIssue, PaperDraftVerificationResult, ResearchReport


# Canonical run_id shape after Fix 5: ``run_[0-9a-f]{8}``. The verifier
# regex requires the ``run_`` prefix so that bare 8-hex tokens — commit
# shards, UUID shards, dataset hashes — never trip ``unsupported_run_id``.
# This fixes session_b14b074d2268's paper_verification where the 8-char
# shard ``d0df5148`` of conversation UUID
# ``d0df5148-5a12-4cda-9cc8-a899ff810a17`` was flagged as a missing run_id.
_CANONICAL_RUN_ID_RE = re.compile(r"\brun_[0-9a-f]{8}\b", re.IGNORECASE)
_LEGACY_RUN_ID_RE = re.compile(r"\brun_[a-zA-Z0-9]+\b")
_BRACKETED_ID_RE = re.compile(r"\[([^\[\]\s]+)\]")


def verify_paper_draft(
    report: ResearchReport,
    draft: str,
) -> PaperDraftVerificationResult:
    """Verify a paper draft references only evidence from the report.

    Deterministic: regex extraction + set comparison, no LLM.
    """
    if not draft.strip():
        return PaperDraftVerificationResult(passed=True)

    # Build allowed sets from report
    allowed_run_ids: set[str] = {report.best_run_id}
    for claim in report.claims:
        allowed_run_ids.update(claim.evidence_run_ids)
    for row in report.comparison_table:
        allowed_run_ids.add(row.get("run_id", ""))
    for row in report.failure_table:
        allowed_run_ids.add(row.get("run_id", ""))
    allowed_run_ids.discard("")

    allowed_paper_ids: set[str] = set()
    for claim in report.claims:
        allowed_paper_ids.update(claim.citation_paper_ids)
    for ref in report.references:
        allowed_paper_ids.add(ref.get("paper_id", ""))
    allowed_paper_ids.discard("")

    allowed_metrics: set[str] = set()
    allowed_metrics.add(f"{report.best_metric_value:.4f}")
    for row in report.comparison_table:
        val = row.get("primary_metric_value", 0.0)
        if val:
            allowed_metrics.add(f"{val:.4f}")
    for row in report.failure_table:
        val = row.get("primary_metric_value", 0.0)
        if val:
            allowed_metrics.add(f"{val:.4f}")

    # Split draft into sections for issue attribution
    sections = _split_into_sections(draft)

    issues: list[DraftVerificationIssue] = []
    unsupported_run_ids: list[str] = []
    unsupported_paper_ids: list[str] = []
    unsupported_metric_mentions: list[str] = []
    # After Fix 5, run_ids are minted as ``run_[0-9a-f]{8}`` everywhere
    # (runtime.iteration_state, tools.run_experiment, tools.ratchet).
    # The canonical pattern subsumes the legacy ``run_[a-zA-Z0-9]+`` shape,
    # so we use a single pattern that requires the ``run_`` prefix.
    # Bare 8-hex tokens are never treated as run_ids — this is what keeps
    # conversation UUID shards and commit shards from being false-flagged.
    run_patterns = [_CANONICAL_RUN_ID_RE, _LEGACY_RUN_ID_RE]

    for section_name, section_text in sections:
        # Check run IDs
        seen_run_ids: set[str] = set()
        for pattern in run_patterns:
            for match in pattern.finditer(section_text):
                run_id = match.group()
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
                if run_id not in allowed_run_ids:
                    issues.append(DraftVerificationIssue(
                        section_name=section_name,
                        issue_type="unsupported_run_id",
                        severity="error",
                        sentence=_extract_context(section_text, match.start()),
                        detail=f"Run ID '{run_id}' not found in report evidence.",
                    ))
                    if run_id not in unsupported_run_ids:
                        unsupported_run_ids.append(run_id)

        # Check paper ID references in [paper_id] notation.
        for match in _BRACKETED_ID_RE.finditer(section_text):
            paper_id = match.group(1)
            if paper_id not in allowed_paper_ids:
                issues.append(DraftVerificationIssue(
                    section_name=section_name,
                    issue_type="unsupported_paper_id",
                    severity="error",
                    sentence=_extract_context(section_text, match.start()),
                    detail=f"Paper ID '{paper_id}' not found in report references.",
                ))
                if paper_id not in unsupported_paper_ids:
                    unsupported_paper_ids.append(paper_id)

        # Check metric values (decimals with 2+ decimal places)
        for match in re.finditer(r'\b(\d+\.\d{2,})\b', section_text):
            value_str = match.group(1)
            # Only flag if it looks like a metric (0.xx or x.xxxx range)
            try:
                val = float(value_str)
                if 0.0 < val < 2.0:  # plausible metric range
                    formatted = f"{val:.4f}"
                    if formatted not in allowed_metrics:
                        issues.append(DraftVerificationIssue(
                            section_name=section_name,
                            issue_type="unsupported_metric",
                            severity="warning",
                            sentence=_extract_context(section_text, match.start()),
                            detail=f"Metric value '{value_str}' not found in report evidence.",
                        ))
                        if value_str not in unsupported_metric_mentions:
                            unsupported_metric_mentions.append(value_str)
            except ValueError:
                pass

    return PaperDraftVerificationResult(
        passed=len(issues) == 0,
        issue_count=len(issues),
        issues=issues,
        unsupported_run_ids=unsupported_run_ids,
        unsupported_paper_ids=unsupported_paper_ids,
        unsupported_metric_mentions=unsupported_metric_mentions,
    )


def _split_into_sections(draft: str) -> list[tuple[str, str]]:
    """Split draft by ## headings. Returns [(section_name, section_text), ...]."""
    sections: list[tuple[str, str]] = []
    current_name = "preamble"
    current_lines: list[str] = []

    for line in draft.split("\n"):
        if line.startswith("## "):
            if current_lines:
                sections.append((current_name, "\n".join(current_lines)))
            current_name = line[3:].strip().lower().replace(" ", "_")
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_name, "\n".join(current_lines)))

    return sections


def _extract_context(text: str, pos: int, window: int = 80) -> str:
    """Extract a short context window around a match position."""
    start = max(0, pos - window // 2)
    end = min(len(text), pos + window // 2)
    return text[start:end].replace("\n", " ").strip()
