"""Section-scoped grounding — binds claims, runs, papers, and metrics to each report section."""
from __future__ import annotations

from .types import ClaimRecord, GroundedSectionInput, ResearchReport

_SECTION_GOALS: dict[str, str] = {
    "abstract": "Summarize objective, method, key result, and scope. Do not overclaim.",
    "experimental_setup": "Describe the experimental platform and iteration budget.",
    "results": "Present metrics and comparisons grounded in committed runs only.",
    "limitations": "Acknowledge failures, error modes, and scope limitations.",
    "reproducibility": "State session metadata and iteration counts for reproducibility.",
    "references": "List cited prior work with paper IDs.",
    # Terse goal for the integrity_issues section. Paired with a condensed
    # ``source_report_section`` below so the LLM does not spend the paper's
    # prose budget defending a warning. See Finding 7 of
    # docs/review/2026-04-22-pathscientist-latest-run-review.md.
    "integrity_issues": (
        "Briefly acknowledge any integrity warnings in one or two sentences. "
        "Do NOT expand into multiple paragraphs. Do NOT add defensive framing "
        "such as 'This does not indicate a flaw' or 'It should be noted'. "
        "The facts below are exhaustive — report them plainly, then stop."
    ),
}

_CAUTION_SECTIONS: set[str] = {"limitations", "abstract", "conclusion"}

# Max characters for the integrity_issues ``source_report_section`` fed to
# the paper writer. The deterministic report markdown ``## Integrity Issues``
# section can stay longer because it's the canonical record; but the
# paper_writer sees a condensed version so the LLM cannot pad it into a
# Results-eclipsing paragraph. See Finding 7.
_INTEGRITY_GROUNDED_SOURCE_MAX_CHARS = 500


def build_grounded_section_inputs(
    report: ResearchReport,
) -> list[GroundedSectionInput]:
    """Build a GroundedSectionInput for each report section.

    Each input constrains what the section writer is allowed to reference:
    only claims, run IDs, paper IDs, and metric facts that are explicitly
    linked to that section through the report's claim model.
    """
    claims_by_id: dict[str, ClaimRecord] = {c.claim_id: c for c in report.claims}
    all_paper_ids: set[str] = {ref.get("paper_id", "") for ref in report.references if ref.get("paper_id")}

    inputs: list[GroundedSectionInput] = []
    for section in report.sections:
        # Bind claims to this section
        section_claims = [claims_by_id[cid] for cid in section.claim_ids if cid in claims_by_id]

        # Extract allowed identifiers from bound claims
        allowed_run_ids: list[str] = []
        allowed_paper_ids: list[str] = []
        for claim in section_claims:
            allowed_run_ids.extend(claim.evidence_run_ids)
            allowed_paper_ids.extend(claim.citation_paper_ids)

        # References section gets all paper IDs
        if section.name == "references":
            allowed_paper_ids.extend(all_paper_ids)

        # Deduplicate while preserving order
        allowed_run_ids = list(dict.fromkeys(allowed_run_ids))
        allowed_paper_ids = list(dict.fromkeys(allowed_paper_ids))

        # Extract allowed metric facts from comparison table
        allowed_run_set = set(allowed_run_ids)
        allowed_metric_facts: list[dict] = []
        if report.best_run_id in allowed_run_set or section.name in ("abstract", "results"):
            allowed_metric_facts.append({
                "metric_name": report.success_metric,
                "metric_value": report.best_metric_value,
            })
        for row in report.comparison_table:
            if row.get("run_id") in allowed_run_set:
                allowed_metric_facts.append({
                    "metric_name": report.success_metric,
                    "metric_value": row.get("primary_metric_value", 0.0),
                })

        # Caution flags for sensitive sections
        caution_flags: list[str] = []
        if section.name in _CAUTION_SECTIONS:
            if report.failure_table:
                caution_flags.append("acknowledge_failures")
            caution_flags.append("scope_limitation")

        # Filter references to those allowed
        allowed_paper_set = set(allowed_paper_ids)
        section_refs = [ref for ref in report.references if ref.get("paper_id") in allowed_paper_set]

        # Integrity section: condense source and add keep-brief caution. The
        # deterministic report.md can show the full bulleted list, but the
        # paper_writer prompt sees at most a one-line summary + the bullet
        # list itself, with an explicit "do not expand" marker so the LLM
        # does not reproduce the warning as multiple defensive paragraphs.
        # See Finding 7 of
        # docs/review/2026-04-22-pathscientist-latest-run-review.md.
        source_text = section.content
        if section.name == "integrity_issues":
            source_text = _condense_integrity_source(section.content, report.integrity_issues)
            caution_flags.append("keep_brief_limitations_only")

        inputs.append(GroundedSectionInput(
            section_name=section.name,
            section_title=section.title,
            section_goal=_SECTION_GOALS.get(section.name, "Write this section based on the report content."),
            source_report_section=source_text,
            allowed_claim_ids=section.claim_ids,
            allowed_run_ids=allowed_run_ids,
            allowed_paper_ids=allowed_paper_ids,
            allowed_metric_facts=allowed_metric_facts,
            required_caution_flags=caution_flags,
            claims=section_claims,
            references=section_refs,
        ))

    return inputs


def _condense_integrity_source(
    section_content: str,
    integrity_issues: list[dict],
) -> str:
    """Produce a terse, paper-writer-safe integrity blurb.

    The deterministic ``report.md`` integrity section is already compact
    (one summary line + one bullet per issue), but we shorten it further
    here before feeding the paper writer: strip long context details in
    issue messages and append an explicit instruction telling the LLM to
    mention this briefly in a Limitations-style paragraph and not to
    expand. This counteracts the LLM's default tendency to turn a
    one-warning list into two paragraphs of apologetic prose.
    """
    issues = integrity_issues or []
    if not issues:
        return section_content

    fatal = sum(1 for i in issues if str(i.get("severity", "")).strip() == "fatal")
    warning = sum(1 for i in issues if str(i.get("severity", "")).strip() == "warning")

    lines: list[str] = [
        f"Integrity: {fatal} fatal, {warning} warning.",
    ]
    for issue in issues:
        severity = str(issue.get("severity", "")).strip() or "unknown"
        code = str(issue.get("code", "")).strip() or "unknown"
        message = str(issue.get("message", "")).replace("\n", " ").strip()
        # Keep the first sentence only — the guard often appends path /
        # context details that add nothing to the paper narrative.
        first_sentence = message.split(". ", 1)[0].rstrip(".")
        lines.append(f"- [{severity}] {code}: {first_sentence}")
    lines.append("")
    lines.append(
        "Mention briefly in a Limitations-style paragraph (one or two sentences). "
        "Do not expand."
    )
    blurb = "\n".join(lines)
    if len(blurb) > _INTEGRITY_GROUNDED_SOURCE_MAX_CHARS:
        blurb = blurb[: _INTEGRITY_GROUNDED_SOURCE_MAX_CHARS].rstrip() + "…"
    return blurb
