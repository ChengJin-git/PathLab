"""Paper draft writer — generates narrative from structured report.

Uses LLM when available, falls back to deterministic assembly from report sections.
The LLM path writes one section at a time from a ``GroundedSectionInput`` so
each call is bounded to the run IDs, paper IDs, and metric facts the report
explicitly supports for that section.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from ..config import PathScientistConfig
from ..llm_client import (
    build_chat_llm,
    extract_text,
    has_chat_llm_config,
    invoke_chat_llm,
    make_llm_config,
)
from .title_normalizer import normalize_title
from .types import GroundedSectionInput, ResearchReport


# Orphan-citation scrub regex. Matches bracketed numeric tokens like
# ``[1]`` / ``[23]`` — the academic-citation boilerplate LLMs tack onto
# prose even when prompted not to. Only the numeric form is stripped: we
# deliberately leave non-numeric brackets alone (``[TODO]``, ``[smith2023]``,
# ``[paper_id]``) because those are either real paper_id citations or
# intentional editorial markers. If the captured digits are in
# ``allowed_ids``, the bracket is preserved.
_ORPHAN_BRACKET_RE = re.compile(r"\[(\d+)\]")


def _strip_orphan_citation_brackets(text: str, allowed_ids: set[str]) -> str:
    """Remove ``[N]``-style numeric citation markers that aren't in allowed_ids.

    Motivated by Finding 5 of
    docs/review/2026-04-22-pathscientist-latest-run-review.md: LLMs inject
    ``[1]`` / ``[2]`` academic-citation placeholders into prose even when the
    prompt tells them not to. Post-processing deterministically strips those
    orphan markers so the published draft doesn't carry decorative citations
    pointing at references that don't exist.

    Preserved:
        - ``[N]`` markers where ``N`` literally appears in ``allowed_ids``
          (rare: only when the report numbers its references).
        - Non-numeric brackets (``[smith2023]``, ``[TODO]``, ``[paper_id]``)
          — those are handled by the verifier, not by this scrub.

    Cleans leftover ``"  "`` double spaces and the `` .`` / `` ,`` patterns
    that appear after a marker between a word and its trailing punctuation is
    removed, so "... analyses [1]. More." becomes "... analyses. More."
    """
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        num = match.group(1)
        if num in allowed_ids:
            return match.group(0)  # keep allowed citation
        return ""  # strip orphan

    scrubbed = _ORPHAN_BRACKET_RE.sub(_replace, text)
    # Clean up whitespace/punctuation artefacts left by stripped markers:
    #   "word [1]."  -> "word ."  -> "word."
    #   "word [1] ." -> "word  ." -> "word ."
    #   "word [1]  more" -> "word   more" -> "word more"
    scrubbed = re.sub(r" +([.,;:!?])", r"\1", scrubbed)
    scrubbed = re.sub(r"[ \t]{2,}", " ", scrubbed)
    return scrubbed


def _report_h1(report: ResearchReport) -> str:
    """Build the paper's H1 with path/filler stripping and stable fallback."""
    return "# " + normalize_title(
        report.objective,
        success_metric=report.success_metric,
        dataset_hint=getattr(report, "dataset_hint", ""),
    )

logger = logging.getLogger(__name__)


def build_paper_draft(
    report: ResearchReport,
    writer: Callable | None = None,
    section_writer: Callable | None = None,
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    config: PathScientistConfig | None = None,
) -> str:
    """Generate a paper-ready draft from a structured report.

    Dispatch order:
    1. Legacy ``writer`` callable (backward compat)
    2. Section-scoped ``section_writer`` — called once per GroundedSectionInput
    3. LLM-based section-by-section generation (one call per section, bounded
       to that section's GroundedSectionInput)
    4. Deterministic section-grounded fallback
    """
    if writer is not None:
        return writer(report, llm_model=llm_model, llm_api_key=llm_api_key, llm_base_url=llm_base_url)

    # Section-writer path: call per-section with grounded inputs
    if section_writer is not None:
        from .grounding import build_grounded_section_inputs
        inputs = build_grounded_section_inputs(report)
        sections_md = [section_writer(inp) for inp in inputs]
        return f"{_report_h1(report)}\n\n" + "\n\n".join(sections_md)

    # Try LLM-based generation when config or env resolves to an LLM.
    llm_config = make_llm_config(
        config=config,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
    )
    has_llm = has_chat_llm_config(llm_config)
    if has_llm:
        try:
            return _llm_section_by_section_draft(
                report,
                llm_model,
                llm_api_key,
                llm_base_url,
                config=llm_config,
            )
        except Exception as e:
            logger.warning(f"LLM paper draft failed, using deterministic fallback: {e}")

    # Deterministic fallback — flows through grounded section inputs
    return _grounded_deterministic_draft(report)


def _grounded_deterministic_draft(report: ResearchReport) -> str:
    """Deterministic draft assembled through grounded section inputs."""
    from .grounding import build_grounded_section_inputs
    inputs = build_grounded_section_inputs(report)
    if not inputs:
        return _deterministic_paper_draft(report)
    sections_md = [_deterministic_section_writer(inp) for inp in inputs]
    return f"{_report_h1(report)}\n\n" + "\n\n".join(sections_md)


def _deterministic_section_writer(section_input) -> str:
    """Write one section deterministically from its grounded input."""
    lines = [f"## {section_input.section_title}", ""]
    if section_input.source_report_section:
        lines.append(section_input.source_report_section)
    if section_input.required_caution_flags:
        for flag in section_input.required_caution_flags:
            lines.append(f"\n*Note: {flag}*")
    return "\n".join(lines)


def _deterministic_paper_draft(report: ResearchReport) -> str:
    """Assemble a paper draft from report sections without LLM."""
    lines: list[str] = []

    lines.append(_report_h1(report))
    lines.append("")

    # Abstract
    lines.append("## Abstract")
    lines.append("")
    lines.append(
        f"This study investigates {report.objective.lower()}. "
        f"Through {len(report.comparison_table) or 'multiple'} experimental iterations, "
    )
    if report.best_run_id:
        lines.append(
            f"the best result achieved {report.success_metric} = {report.best_metric_value:.4f} "
            f"({report.best_run_id})."
        )
    lines.append("")

    # Introduction
    lines.append("## Introduction")
    lines.append("")
    lines.append(f"This work addresses the objective: {report.objective}.")
    if report.references:
        lines.append("Prior work in this area includes:")
        for ref in report.references[:3]:
            lines.append(f"- [{ref.get('paper_id', '?')}] {ref.get('context', '')}")
    lines.append("")

    # Methods
    lines.append("## Methods")
    lines.append("")
    lines.append(f"Experiments were conducted using the PathScientist autonomous research platform.")
    repro = report.reproducibility
    if repro:
        lines.append(
            f"A total of {repro.get('total_iterations', 0)} iterations were run, "
            f"of which {repro.get('committed_runs', 0)} were committed as improvements."
        )
    lines.append("")

    # Results
    for section in report.sections:
        if section.name == "results":
            lines.append(f"## Results")
            lines.append("")
            lines.append(section.content)
            lines.append("")

    # Limitations
    for section in report.sections:
        if section.name == "limitations":
            lines.append(f"## Limitations")
            lines.append("")
            lines.append(section.content)
            lines.append("")

    # Conclusion
    lines.append("## Conclusion")
    lines.append("")
    if report.best_run_id:
        lines.append(
            f"The best configuration achieved {report.success_metric} = {report.best_metric_value:.4f}. "
        )
    if report.failure_table:
        lines.append(
            f"{len(report.failure_table)} experiment(s) were reverted due to errors or regressions."
        )
    lines.append("")

    # References
    if report.references:
        lines.append("## References")
        lines.append("")
        seen = set()
        for ref in report.references:
            pid = ref.get("paper_id", "")
            if pid and pid not in seen:
                lines.append(f"- [{pid}] {ref.get('context', '')}")
                seen.add(pid)
        lines.append("")

    return "\n".join(lines)


def _llm_section_by_section_draft(
    report: ResearchReport,
    llm_model: str,
    llm_api_key: str,
    llm_base_url: str,
    config: PathScientistConfig | None = None,
) -> str:
    """Generate the paper draft one section at a time from grounded inputs.

    Each section is written by an LLM call bounded to that section's
    ``GroundedSectionInput`` — the prompt only exposes allowed run IDs,
    paper IDs, and metric facts the report explicitly supports for that
    section. If a single section's LLM call fails, that section falls back
    to the deterministic section writer rather than aborting the whole draft.
    """
    from .grounding import build_grounded_section_inputs

    inputs = build_grounded_section_inputs(report)
    if not inputs:
        return _deterministic_paper_draft(report)

    llm = _build_section_writer_llm(
        llm_model,
        llm_api_key,
        llm_base_url,
        config=config,
    )

    sections_md: list[str] = []
    for inp in inputs:
        try:
            sections_md.append(_llm_section_writer(inp, llm=llm))
        except Exception as e:
            logger.warning(
                f"LLM section '{inp.section_name}' failed, using deterministic fallback: {e}"
            )
            sections_md.append(_deterministic_section_writer(inp))

    return f"{_report_h1(report)}\n\n" + "\n\n".join(sections_md)


def _llm_section_writer(
    section_input: GroundedSectionInput,
    llm=None,
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
    config: PathScientistConfig | None = None,
) -> str:
    """Write one section of the paper draft via LLM, bounded by the section input."""
    from openhands.sdk.llm import Message, TextContent

    if llm is None:
        llm = _build_section_writer_llm(
            llm_model,
            llm_api_key,
            llm_base_url,
            config=config,
        )

    prompt = _build_section_prompt(section_input)
    response = invoke_chat_llm(
        llm,
        messages=[Message(role="user", content=[TextContent(text=prompt)])],
    )
    text = extract_text(response).strip()

    expected_header = f"## {section_input.section_title}"
    if not text.lstrip().startswith(expected_header):
        text = f"{expected_header}\n\n{text}"

    # Strip orphan ``[N]`` academic-citation boilerplate the LLM may have
    # inserted despite the prompt's CITATION RULES. Allowed numeric ids
    # (the rare case where the report numbers its references) are
    # preserved. See ``_strip_orphan_citation_brackets`` docstring.
    text = _strip_orphan_citation_brackets(text, set(section_input.allowed_paper_ids))
    return text


def _build_section_prompt(section_input: GroundedSectionInput) -> str:
    """Build a strict, evidence-bounded prompt for one paper section."""
    si = section_input
    lines: list[str] = [
        "You are a scientific paper writer for computational pathology.",
        "Write ONE section of a grounded research paper. Output markdown only.",
        "",
        f"SECTION: {si.section_title} (name={si.section_name})",
        f"GOAL: {si.section_goal}",
        "",
        "STRICT RULES:",
        "- Use ONLY the allowed run IDs and paper IDs listed below.",
        "- Use ONLY the metric values listed below — do not invent numbers.",
        "- Do not introduce comparisons that are not backed by an allowed claim.",
        "- Cite papers using [paper_id] notation, drawing only from ALLOWED_PAPER_IDS.",
        "- If REQUIRED_CAUTION_FLAGS are present, address them explicitly.",
        "- Prefer cautious wording when claim confidence is medium or low.",
        f"- Begin your output with '{f'## {si.section_title}'}' and write prose only.",
        "",
        "CITATION RULES:",
        "- Do NOT add numeric citation markers like [1], [2], or [3] at the end"
        " of sentences. This project does not use numbered citations.",
        "- If you want to cite a source, use the EXACT paper_id string from"
        " ALLOWED_PAPER_IDS, e.g. [smith2023] or [10.1038/s41591-024-12345].",
        "- If ALLOWED_PAPER_IDS is empty, produce NO citation markers at all."
        " Do not fall back to [1] / [2] / [ref] / [citation needed] style"
        " placeholders — leave the sentence uncited instead.",
        "",
    ]

    lines.append(f"ALLOWED_RUN_IDS: {list(si.allowed_run_ids)}")
    lines.append(f"ALLOWED_PAPER_IDS: {list(si.allowed_paper_ids)}")
    lines.append(f"ALLOWED_METRIC_FACTS: {list(si.allowed_metric_facts)}")
    lines.append(f"REQUIRED_CAUTION_FLAGS: {list(si.required_caution_flags)}")

    if si.claims:
        lines.append("")
        lines.append("ALLOWED_CLAIMS:")
        for c in si.claims:
            lines.append(
                f"- [{c.claim_id}] {c.statement} "
                f"(confidence={c.confidence}, runs={c.evidence_run_ids}, papers={c.citation_paper_ids})"
            )

    if si.references:
        lines.append("")
        lines.append("REFERENCES:")
        for ref in si.references:
            lines.append(
                f"- [{ref.get('paper_id', '?')}] {ref.get('context', '')}"
            )

    if si.source_report_section:
        lines.append("")
        lines.append("SOURCE_REPORT_SECTION (deterministic baseline; refine but do not contradict):")
        lines.append(si.source_report_section)

    lines.append("")
    lines.append(f"Write the {si.section_title} section now:")
    return "\n".join(lines)


def _build_section_writer_llm(
    llm_model: str,
    llm_api_key: str,
    llm_base_url: str,
    config: PathScientistConfig | None = None,
):
    """Construct the OpenHands LLM client used for section drafting."""
    llm_config = make_llm_config(
        config=config,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
    )
    return build_chat_llm(
        llm_config,
        component="paper drafting",
        usage_id="paper_writer_section",
        temperature=0.3,
    )
