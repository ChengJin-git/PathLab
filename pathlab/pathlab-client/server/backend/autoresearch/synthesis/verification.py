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
# Paper ID citation regex. The inner capture matches any bracketed token
# that could be a paper_id (alphanumeric plus common paper_id punctuation
# such as ``.``, ``/``, ``-``, ``_``, and ``:`` — DOI / OpenAlex / slug
# forms). The verifier then filters candidates:
#
# - Alphabetic candidates that look like real paper_id shapes (contain at
#   least one non-digit character) are always checked against
#   ``allowed_paper_ids`` and flagged if missing. This catches LLM
#   hallucinations like ``[smith2023]`` when the references list is empty
#   or doesn't list ``smith2023``.
# - Numeric-only candidates (``[1]``, ``[2]``, ...) are treated as
#   evidence lineage claims ONLY when the draft itself contains a
#   ``## References`` / ``## Bibliography`` / ``## Citations`` heading.
#   When no such heading is present, bare ``[N]`` is LLM boilerplate
#   (decorative), not a citation to a known paper, and MUST NOT trip
#   ``unsupported_paper_id``. When the heading IS present, each ``[N]``
#   must either appear in the references section text or resolve to an
#   entry in ``ResearchReport.references`` / claim.citation_paper_ids.
#
# This fixes Finding 5 of
# docs/review/2026-04-22-autoresearch-latest-run-review.md where
# session_3f1795098784's paper draft contained ``... analyses [1].`` with
# an empty references list and tripped ``unsupported_paper_id``.
_BRACKETED_ID_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9._/:\-]*)\]")
# Heading variants that mark a references / bibliography section in the
# draft. Matched case-insensitively against a line that starts with ``##``.
# Presence of any such heading is what gates the numeric ``[N]`` check.
_REFERENCES_HEADING_RE = re.compile(
    r"(?im)^\s*#{2,}\s+(references|bibliography|citations)\s*$"
)


def _paper_has_references_section(draft: str) -> bool:
    """Return True if the draft contains a ``## References`` / ``## Bibliography``
    / ``## Citations`` heading.

    When False, bare ``[N]`` bracket citations in the draft are treated as
    decorative LLM boilerplate (Finding 5): the paper claims no evidence
    lineage against a reference list, so the verifier must not demand
    ``[N]`` resolve to anything.
    """
    return bool(_REFERENCES_HEADING_RE.search(draft))


def _extract_references_section(draft: str) -> str:
    """Return the text of the references / bibliography / citations section,
    or the empty string if no such heading exists.

    Used to decide whether a numeric ``[N]`` citation is backed by the
    draft's own references list (in addition to the report-level
    ``allowed_paper_ids`` set).
    """
    match = _REFERENCES_HEADING_RE.search(draft)
    if not match:
        return ""
    # Slice from the end of the heading line to the next ``##`` heading (or
    # end of draft). We step through lines to avoid regex gotchas with
    # heading levels.
    after = draft[match.end():]
    out_lines: list[str] = []
    for line in after.split("\n"):
        if line.startswith("## "):
            break
        out_lines.append(line)
    return "\n".join(out_lines)


def verify_paper_draft(
    report: ResearchReport,
    draft: str,
    enforce_substantive_content: bool = False,
) -> PaperDraftVerificationResult:
    """Verify a paper draft references only evidence from the report.

    Deterministic: regex extraction + set comparison, no LLM.

    When ``enforce_substantive_content=True`` (set by the orchestrator
    paper_ready determination per Plan-2026-04-28 P0 #2), additionally
    fail an empty draft and fail drafts where required sections lack
    substantive content (heading-only drafts no longer pass — repros
    session_d162f805e1d7 where ``paper_ready=true`` was set on a
    bare-headings draft).
    """
    issues: list[DraftVerificationIssue] = []

    # Empty / blank draft.
    if not draft.strip():
        if enforce_substantive_content:
            issues.append(DraftVerificationIssue(
                section_name="paper_draft",
                issue_type="empty_draft",
                severity="error",
                sentence="",
                detail="Paper draft is empty.",
            ))
            return PaperDraftVerificationResult(
                passed=False, issue_count=len(issues), issues=issues,
            )
        # Backward-compatible behavior: lineage-only mode treats empty as
        # vacuously valid (nothing to verify against).
        return PaperDraftVerificationResult(passed=True)

    if enforce_substantive_content:
        _REQUIRED_SECTIONS = (
            ("Abstract", ("abstract",)),
            ("Methods", ("methods", "experimental setup", "method", "approach")),
            ("Results", ("results", "result", "experiments")),
            ("Limitations", ("limitations", "limitation", "discussion")),
            ("Reproducibility", ("reproducibility", "reproduction", "implementation details")),
        )
        _MIN_SECTION_CHARS = 80   # ~one substantive sentence

        section_map: dict[str, str] = {}
        for _name, _body in _split_into_sections(draft):
            section_map[_name.strip().lower()] = _body.strip()

        for canonical_name, aliases in _REQUIRED_SECTIONS:
            body = ""
            for alias in aliases:
                if alias in section_map:
                    body = section_map[alias]
                    break
            if not body or len(body) < _MIN_SECTION_CHARS:
                issues.append(DraftVerificationIssue(
                    section_name=canonical_name.lower(),
                    issue_type="empty_section" if not body else "stub_section",
                    severity="error",
                    sentence="",
                    detail=(
                        f"Required section '{canonical_name}' is "
                        f"{'missing or empty' if not body else f'only {len(body)} chars (min {_MIN_SECTION_CHARS})'}. "
                        f"A heading-only draft must not pass paper_ready."
                    ),
                ))

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

    # Detect whether the draft itself contains a ``## References`` /
    # ``## Bibliography`` / ``## Citations`` heading. Only when one is
    # present do numeric ``[N]`` markers count as evidence lineage claims
    # (Finding 5, 2026-04-22). When absent, ``[N]`` is LLM boilerplate in
    # prose (e.g. ``... analyses [1].``) and must not trip
    # ``unsupported_paper_id``.
    draft_has_references = _paper_has_references_section(draft)
    references_section_text = (
        _extract_references_section(draft) if draft_has_references else ""
    )
    # Numeric ids that appear in the draft's own references section — those
    # are backed by the draft even if ``ResearchReport.references`` is
    # empty (e.g. the LLM pasted its own bibliography).
    numeric_ids_in_draft_references: set[str] = set()
    if references_section_text:
        for ref_match in _BRACKETED_ID_RE.finditer(references_section_text):
            candidate = ref_match.group(1)
            if candidate.isdigit():
                numeric_ids_in_draft_references.add(candidate)

    # Split draft into sections for issue attribution
    sections = _split_into_sections(draft)

    # ``issues`` was already initialized above for substantive-content
    # checks (Plan-2026-04-28 P0 #2); accumulate lineage issues into the
    # same list so a draft that's both bare-headings AND has lineage
    # problems reports both.
    unsupported_run_ids: list[str] = []
    unsupported_paper_ids: list[str] = []
    unsupported_metric_mentions: list[str] = []
    # After Fix 5, run_ids are minted as ``run_[0-9a-f]{8}`` everywhere
    # (runtime.iteration_state, tools.run_experiment, tools.ratchet). A
    # single canonical pattern that requires the ``run_`` prefix is enough:
    # bare 8-hex tokens are never treated as run_ids (keeps UUID shards
    # and commit shards safe), and the legacy ``run_[a-zA-Z0-9]+`` shape
    # was removed because it false-flagged prose tokens like
    # ``run_experiment`` / ``run_history`` as unsupported run_ids.

    for section_name, section_text in sections:
        # Check run IDs
        seen_run_ids: set[str] = set()
        for match in _CANONICAL_RUN_ID_RE.finditer(section_text):
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
        #
        # Two candidate shapes arise from the regex:
        #
        # 1. Non-numeric candidates (e.g. ``[smith2023]``, ``[10.1038/...]``)
        #    — canonical paper_id shape in this project is alphabetic. We
        #    flag these against ``allowed_paper_ids`` unconditionally so
        #    hallucinated paper_ids still fail verification.
        # 2. Numeric-only candidates (``[1]``, ``[2]``, ...) — only treated
        #    as evidence lineage claims when the draft itself has a
        #    ``## References`` / ``## Bibliography`` / ``## Citations``
        #    heading (``draft_has_references``). When no such heading
        #    exists, numeric markers are LLM prose decoration (Finding 5)
        #    and are skipped entirely. When the heading IS present, each
        #    ``[N]`` must resolve to either the draft's own references
        #    text or ``ResearchReport.references`` / claim paper_ids.
        # Skip matches inside the draft's own references section — a
        # ``[1]`` entry in the bibliography is definitional, not a claim.
        ref_section_scope = section_name in {"references", "bibliography", "citations"}
        for match in _BRACKETED_ID_RE.finditer(section_text):
            paper_id = match.group(1)
            if ref_section_scope:
                # Entries inside the references section itself define the
                # backing set; they're not citations to be checked.
                continue
            if paper_id.isdigit():
                # Gate numeric brackets on the draft having a References
                # section at all (Option A of Finding 5). Without one,
                # ``[N]`` is decorative.
                if not draft_has_references:
                    continue
                # With a References section, ``[N]`` is backed if it
                # appears there OR in the report-level allowed set.
                if (
                    paper_id in numeric_ids_in_draft_references
                    or paper_id in allowed_paper_ids
                ):
                    continue
                issues.append(DraftVerificationIssue(
                    section_name=section_name,
                    issue_type="unsupported_paper_id",
                    severity="error",
                    sentence=_extract_context(section_text, match.start()),
                    detail=f"Paper ID '{paper_id}' not found in report references.",
                ))
                if paper_id not in unsupported_paper_ids:
                    unsupported_paper_ids.append(paper_id)
                continue
            # Non-numeric candidate: unconditionally checked against the
            # report-level allowed set.
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
