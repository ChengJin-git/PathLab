"""Deterministic report builder — assembles structured report from synthesis context."""
from __future__ import annotations

from typing import Any

from .claims import build_claims
from .types import ClaimRecord, ReportSection, ResearchReport


def build_report(
    context: dict[str, Any],
    integrity_report: dict[str, Any] | None = None,
) -> ResearchReport:
    """Build a structured ResearchReport from synthesis context.

    When ``integrity_report`` is provided (typically the serialized output of
    ``runtime.integrity.check_session_integrity``), the builder records every
    issue in ``ResearchReport.integrity_issues`` so downstream consumers
    (paper writer, CLI, verification) see the invariant breakages too. It
    also appends an ``## Integrity Issues`` section to the rendered markdown.
    """
    claims = build_claims(context)
    integrity_report = integrity_report or {}
    integrity_issues = list(integrity_report.get("issues", []) or [])
    sections = _build_sections(context, claims, integrity_report)

    best = context.get("best_run", {})

    return ResearchReport(
        session_id=context.get("reproducibility", {}).get("session_id", ""),
        conversation_id=context.get("reproducibility", {}).get("conversation_id", ""),
        objective=context.get("objective", ""),
        success_metric=context.get("success_metric", "auc"),
        best_run_id=best.get("run_id", ""),
        best_metric_value=best.get("primary_metric_value", 0.0),
        claims=claims,
        sections=sections,
        comparison_table=context.get("comparison_table", []),
        failure_table=context.get("failures", []),
        references=context.get("references", []),
        reproducibility=context.get("reproducibility", {}),
        integrity_issues=integrity_issues,
    )


def render_report_markdown(report: ResearchReport) -> str:
    """Render a structured report to deterministic markdown."""
    lines: list[str] = []

    # Title
    lines.append(f"# Research Report")
    lines.append("")
    lines.append(f"**Objective:** {report.objective}")
    lines.append(f"**Primary Metric:** {report.success_metric}")
    if report.best_run_id:
        lines.append(f"**Best Result:** {report.best_metric_value:.4f} ({report.best_run_id})")
    lines.append("")

    # Sections
    for section in report.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    return "\n".join(lines)


def _build_sections(
    context: dict[str, Any],
    claims: list[ClaimRecord],
    integrity_report: dict[str, Any] | None = None,
) -> list[ReportSection]:
    """Build report sections from context and claims."""
    sections: list[ReportSection] = []
    metric = context.get("success_metric", "auc")

    # Results
    # Abstract
    best = context.get("best_run", {})
    abstract_lines = [f"This report summarizes experiments for: {context.get('objective', '')}. "]
    repro = context.get("reproducibility", {})
    if repro:
        abstract_lines.append(
            f"{repro.get('total_iterations', 0)} iterations were conducted, "
            f"{repro.get('committed_runs', 0)} committed."
        )
    if best:
        abstract_lines.append(
            f"Best result: {metric} = {best.get('primary_metric_value', 0):.4f} ({best.get('run_id', '?')})."
        )
    sections.append(ReportSection(
        name="abstract",
        title="Abstract",
        content=" ".join(abstract_lines),
        claim_ids=[],
    ))

    # Experimental Setup
    setup_lines = ["Experiments were conducted using the PathScientist autonomous research platform."]
    if repro:
        setup_lines.append(f"Iteration budget: {repro.get('max_iterations', '?')}.")
    grounding = context.get("grounding", {}) if "grounding" in context else {}
    if grounding and grounding.get("selected_skill"):
        setup_lines.append(f"Skill template: {grounding['selected_skill']}.")
    sections.append(ReportSection(
        name="experimental_setup",
        title="Experimental Setup",
        content=" ".join(setup_lines),
        claim_ids=[],
    ))

    # Results
    result_claims = [c for c in claims if c.section == "results"]
    results_content = _build_results_content(context, metric)
    sections.append(ReportSection(
        name="results",
        title="Results",
        content=results_content,
        claim_ids=[c.claim_id for c in result_claims],
    ))

    # Limitations
    limitation_claims = [c for c in claims if c.section == "limitations"]
    limitations_content = _build_limitations_content(context)
    if limitations_content:
        sections.append(ReportSection(
            name="limitations",
            title="Failures And Limitations",
            content=limitations_content,
            claim_ids=[c.claim_id for c in limitation_claims],
        ))

    # Reproducibility
    repro_claims = [c for c in claims if c.section == "reproducibility"]
    repro_content = _build_reproducibility_content(context)
    sections.append(ReportSection(
        name="reproducibility",
        title="Reproducibility",
        content=repro_content,
        claim_ids=[c.claim_id for c in repro_claims],
    ))

    # Integrity Issues — render BEFORE References so a broken session is
    # loudly visible near the bottom of the report. Only emit when any
    # issues were detected; a clean session should leave no trace.
    integrity_content = _build_integrity_content(integrity_report or {})
    if integrity_content:
        sections.append(ReportSection(
            name="integrity_issues",
            title="Integrity Issues",
            content=integrity_content,
            claim_ids=[],
        ))

    # References
    refs_content = _build_references_content(context)
    if refs_content:
        sections.append(ReportSection(
            name="references",
            title="References",
            content=refs_content,
            claim_ids=[],
        ))

    return sections


def _build_results_content(context: dict[str, Any], metric: str) -> str:
    lines: list[str] = []
    best = context.get("best_run", {})
    if best:
        lines.append(f"Best committed run: **{best.get('run_id', '?')}** with {metric} = **{best.get('primary_metric_value', 0):.4f}**.")
        lines.append("")

    # Comparison table
    table = context.get("comparison_table", []) or context.get("run_history", [])
    if table:
        lines.append(f"| # | Run ID | {metric} | Committed | Error |")
        lines.append("|---|--------|-------|-----------|-------|")
        for i, row in enumerate(table):
            run_id = row.get("run_id", "?")
            value = row.get("primary_metric_value", row.get("metric_value", 0.0))
            committed = "Yes" if row.get("committed", False) else "No"
            error = row.get("error_type", "")
            lines.append(f"| {i} | {run_id} | {value:.4f} | {committed} | {error} |")
        lines.append("")

    return "\n".join(lines)


def _build_limitations_content(context: dict[str, Any]) -> str:
    failures = context.get("failures", [])
    if not failures:
        return ""
    lines: list[str] = []
    for f in failures:
        run_id = f.get("run_id", "?")
        error = f.get("error_type", "unknown")
        hint = f.get("error_hint", "")
        lines.append(f"- **{run_id}**: {error}. {hint}".strip())
    return "\n".join(lines)


def _build_reproducibility_content(context: dict[str, Any]) -> str:
    repro = context.get("reproducibility", {})
    lines = [
        f"- Session: {repro.get('session_id', '?')}",
        f"- Conversation: {repro.get('conversation_id', '?')}",
        f"- Total iterations: {repro.get('total_iterations', 0)}",
        f"- Committed: {repro.get('committed_runs', 0)}",
        f"- Reverted: {repro.get('reverted_runs', 0)}",
    ]
    return "\n".join(lines)


def _build_references_content(context: dict[str, Any]) -> str:
    refs = context.get("references", [])
    if not refs:
        return ""
    seen = set()
    lines: list[str] = []
    for r in refs:
        pid = r.get("paper_id", "")
        if pid and pid not in seen:
            lines.append(f"- [{pid}] {r.get('context', '')}")
            seen.add(pid)
    return "\n".join(lines)


def _build_integrity_content(integrity_report: dict[str, Any]) -> str:
    """Render integrity issues as a terse one-line preamble + bulleted list.

    Motivated by Finding 7 of
    docs/review/2026-04-22-pathscientist-latest-run-review.md. The previous
    format (multi-row markdown table plus a framing sentence) gave the
    downstream paper_writer LLM an equal prose budget for integrity
    warnings and Results, so a one-warning session produced two long
    defensive paragraphs above a two-sentence Results section. The
    compact format below keeps the section to ≤ ~10 lines regardless of
    the issue count: one summary line stating fatal / warning counts,
    then one bullet per issue of the form ``- [severity] code: first-line
    message``. No defensive prose, no per-issue table row.

    When there are no issues, returns the empty string so the caller can
    skip emitting the section entirely (a clean session leaves no trace
    of integrity plumbing in the report).
    """
    issues = integrity_report.get("issues", []) or []
    if not issues:
        return ""

    fatal_count = int(integrity_report.get("fatal_count", 0) or 0)
    warning_count = int(integrity_report.get("warning_count", 0) or 0)

    lines: list[str] = [
        f"Session-end integrity report: {fatal_count} fatal, {warning_count} warning.",
        "",
    ]
    for issue in issues:
        severity = str(issue.get("severity", "")).strip() or "unknown"
        code = str(issue.get("code", "")).strip() or "unknown"
        # Keep only the first line / first sentence of the message so the
        # bullet stays a single visual row even when the guard emits
        # multi-sentence context.
        raw_message = str(issue.get("message", "")).replace("\n", " ").strip()
        first_line = raw_message.split(". ", 1)[0].rstrip(".")
        lines.append(f"- [{severity}] {code}: {first_line}")
    return "\n".join(lines)
