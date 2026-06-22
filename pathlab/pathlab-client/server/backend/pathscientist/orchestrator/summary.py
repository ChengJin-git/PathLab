"""Session summary builder — uses evidence when available."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .types import ResearchSessionState

if TYPE_CHECKING:
    from ..evidence.store import EvidenceStore
    from ..literature.citations import CitationTracker


def build_session_summary(
    state: ResearchSessionState,
    evidence_store: "EvidenceStore | None" = None,
    citation_tracker: "CitationTracker | None" = None,
) -> str:
    """Build a structured markdown summary of a research session.

    If evidence_store is provided, enriches the summary with per-run evidence
    (metrics, diffs, errors). Otherwise falls back to orchestrator-only data.
    """
    # Plan-2026-04-29 P1 #6: when paper_ready=False, the headline must
    # surface that prominently — pre-fix, session_7a23f8edcce9's summary
    # presented normal completion despite paper_verification_passed=False
    # and a heading-only paper_draft.md.
    paper_ready = bool(getattr(state, "paper_ready", False))
    title = (
        "# PathScientist Session Summary"
        if paper_ready
        else "# PathScientist Session Summary — REPORT NOT READY"
    )

    lines = [
        title,
        "",
        f"**Objective:** {state.objective.question}",
        f"**Metric:** {state.objective.success_metric}",
        f"**Iterations:** {len(state.run_history)}",
    ]
    if state.best_run_id:
        lines.append(f"**Best run:** {state.best_run_id} ({state.best_metric_value:.4f})")
    if paper_ready:
        lines.append("**Paper ready:** ✅ true")
    else:
        lines.append("**Paper ready:** ❌ false — synthesis verification did not pass.")
        v_passed = getattr(state, "paper_verification_passed", None)
        v_count = getattr(state, "paper_verification_issue_count", 0) or 0
        if v_passed is False or v_count:
            lines.append(
                f"  - Verification: passed={v_passed!r}, issue_count={v_count}"
            )
        c_count = getattr(state, "paper_critique_issue_count", 0) or 0
        if c_count:
            lines.append(f"  - Critique flagged {c_count} issue(s)")
        lines.append(
            "  - The session completed but the paper draft is not usable. "
            "Inspect ``.reports/<session_id>/paper_verification.json`` and "
            "``paper_critique.json`` for details."
        )
    lines.append("")

    # Try evidence-enriched table first
    if evidence_store and state.run_history:
        lines.extend(_build_evidence_table(state, evidence_store))
    elif state.run_history:
        lines.extend(_build_basic_table(state))

    # References from literature citations
    if citation_tracker:
        conv_id = str(state.conversation_id)
        citations = citation_tracker.get_conversation_citations(conv_id)
        if citations:
            # Prefer richest citation per paper — passage-level wins over paper-level
            richest: dict[str, object] = {}
            for c in citations:
                score = _citation_richness(c)
                existing = richest.get(c.paper_id)
                if existing is None or _citation_richness(existing) < score:
                    richest[c.paper_id] = c

            lines.append("## References")
            lines.append("")
            for paper_id, c in richest.items():
                lines.append(_render_citation(c))
            lines.append("")

            # If any passage-level citations exist, render an Evidence Snippets section
            passage_citations = [c for c in citations if getattr(c, "chunk_id", None)]
            if passage_citations:
                lines.append("## Evidence Snippets")
                lines.append("")
                seen_chunks: set[str] = set()
                for c in passage_citations:
                    if c.chunk_id in seen_chunks:
                        continue
                    seen_chunks.add(c.chunk_id)
                    page_str = f" p.{c.page}" if c.page else ""
                    section_str = f" ({c.section})" if c.section else ""
                    quote = (c.quote_snippet or c.context or "")[:200]
                    lines.append(f"- **[{c.paper_id}#{c.chunk_id}]**{page_str}{section_str}: {quote}")
                lines.append("")

    return "\n".join(lines)


def _citation_richness(c) -> int:
    """Score citation provenance richness. Higher = more specific."""
    score = 0
    if getattr(c, "chunk_id", None):
        score += 4
    if getattr(c, "page", None):
        score += 2
    if getattr(c, "section", ""):
        score += 1
    if getattr(c, "quote_snippet", ""):
        score += 1
    return score


def _render_citation(c) -> str:
    """Render a single citation with all available provenance."""
    parts = [f"[{c.paper_id}]"]
    if getattr(c, "chunk_id", None):
        parts[0] = f"[{c.paper_id}#{c.chunk_id}]"
    if getattr(c, "page", None):
        parts.append(f"p.{c.page}")
    if getattr(c, "section", ""):
        parts.append(f"({c.section})")
    label = " ".join(parts)
    return f"- {label} {c.context}"


def _build_evidence_table(state: ResearchSessionState, store: "EvidenceStore") -> list[str]:
    """Build a run history table enriched with evidence data."""
    lines = [
        "## Run History",
        "",
        f"| # | Run ID | {state.objective.success_metric} | Committed | Error | Diff |",
        "|---|--------|-------|-----------|-------|------|",
    ]
    for r in state.run_history:
        committed = "Yes" if r.committed else "No"
        error = ""
        diff_preview = ""
        metric_display = f"{r.metric_value:.4f}"

        # Enrich from evidence
        try:
            evidence = store.load(r.run_id)
            error = evidence.error_type or ""
            diff_preview = evidence.git_diff[:60].replace("\n", " ") if evidence.git_diff else ""
            metric_display = f"{evidence.primary_metric_value:.4f}"
        except Exception:
            pass

        lines.append(f"| {r.iteration} | {r.run_id} | {metric_display} | {committed} | {error} | {diff_preview} |")

    lines.append("")

    # Failure details
    failures = []
    for r in state.run_history:
        if not r.committed:
            try:
                evidence = store.load(r.run_id)
                if evidence.error_type:
                    failures.append(evidence)
            except Exception:
                pass

    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            lines.append(f"- **{f.run_id}** ({f.error_type}): {f.error_hint[:100]}")
        lines.append("")

    return lines


def _build_basic_table(state: ResearchSessionState) -> list[str]:
    """Build a basic run history table from orchestrator data only."""
    lines = [
        "## Run History",
        "",
        f"| # | Run ID | {state.objective.success_metric} | Committed | Notes |",
        "|---|--------|-------|-----------|-------|",
    ]
    for r in state.run_history:
        committed = "Yes" if r.committed else "No"
        lines.append(f"| {r.iteration} | {r.run_id} | {r.metric_value:.4f} | {committed} | {r.notes} |")
    lines.append("")
    return lines
