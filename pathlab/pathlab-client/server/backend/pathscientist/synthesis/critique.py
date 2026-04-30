"""Scientific critique — deterministic heuristic checks for paper quality."""
from __future__ import annotations

import re

from .types import PaperScientificCritiqueResult, ResearchReport, ScientificCritiqueIssue

_OVERCLAIM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bdefinitively\b', re.IGNORECASE),
     "Avoid definitive language; computational experiments have limited scope."),
    (re.compile(r'\bproves?\b', re.IGNORECASE),
     "Use 'demonstrates' or 'suggests' instead of 'proves'."),
    (re.compile(r'\bstate[- ]of[- ]the[- ]art\b', re.IGNORECASE),
     "Only claim SOTA if compared against published benchmarks with identical evaluation."),
    (re.compile(r'\bgeneralizable\b', re.IGNORECASE),
     "Generalizability requires multi-dataset validation."),
    (re.compile(r'\balways\b', re.IGNORECASE),
     "Avoid absolute quantifiers in empirical claims."),
    (re.compile(r'\bnever\b', re.IGNORECASE),
     "Avoid absolute quantifiers in empirical claims."),
    (re.compile(r'\bsuperior(?:ity)?\b', re.IGNORECASE),
     "Use 'outperforms on [metric]' with specific numbers instead of 'superior'."),
    (re.compile(r'\bground[- ]?breaking\b', re.IGNORECASE),
     "Avoid promotional language in scientific writing."),
]

_CAUSAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bcauses?\b', re.IGNORECASE),
     "Use correlational language for observational experiments."),
    (re.compile(r'\bresults? in\b', re.IGNORECASE),
     "Use 'is associated with' instead of 'results in' for observational findings."),
]


def critique_paper_draft(
    report: ResearchReport,
    draft: str,
) -> PaperScientificCritiqueResult:
    """Run deterministic scientific critique heuristics on a paper draft.

    Checks for overclaim language, missing limitations, and causal wording.
    """
    if not draft.strip():
        return PaperScientificCritiqueResult(passed=True, summary="Empty draft.")

    sections = _split_into_sections(draft)
    issues: list[ScientificCritiqueIssue] = []

    # 1. Overclaim scan
    for section_name, section_text in sections:
        for pattern, recommendation in _OVERCLAIM_PATTERNS:
            for match in pattern.finditer(section_text):
                issues.append(ScientificCritiqueIssue(
                    section_name=section_name,
                    category="overclaim",
                    severity="warning",
                    finding=f"Overclaim word '{match.group()}' found.",
                    recommendation=recommendation,
                ))

    # 2. Missing limitations check
    if report.failure_table:
        section_names = {name for name, _ in sections}
        has_limitations = any(
            name in ("failures_and_limitations", "limitations", "failures")
            for name in section_names
        )
        if not has_limitations:
            issues.append(ScientificCritiqueIssue(
                section_name="(document)",
                category="missing_limitations",
                severity="error",
                finding="Report has failed experiments but draft has no Limitations section.",
                recommendation="Add a Limitations section acknowledging failure modes.",
            ))

    # 3. Causal language scan
    for section_name, section_text in sections:
        for pattern, recommendation in _CAUSAL_PATTERNS:
            for match in pattern.finditer(section_text):
                # Avoid false positives in section headers or common phrases
                context = section_text[max(0, match.start() - 20):match.end() + 20]
                if "table" in context.lower() or "section" in context.lower():
                    continue
                issues.append(ScientificCritiqueIssue(
                    section_name=section_name,
                    category="causal_language",
                    severity="warning",
                    finding=f"Causal language '{match.group()}' used in observational context.",
                    recommendation=recommendation,
                ))

    requires_revision = any(i.severity == "error" for i in issues)
    passed = len(issues) == 0
    summary = f"{len(issues)} issue(s) found." if issues else "No issues found."

    return PaperScientificCritiqueResult(
        passed=passed,
        requires_revision=requires_revision,
        issue_count=len(issues),
        issues=issues,
        summary=summary,
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
