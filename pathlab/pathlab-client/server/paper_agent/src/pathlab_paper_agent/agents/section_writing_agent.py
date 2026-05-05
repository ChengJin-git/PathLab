"""Section Writing Agent derived from PaperOrchestra Appendix F.4."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..evidence.phi import PhiScrubber  # noqa: E402
from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient  # noqa: E402
from ..renderers.citation_renderer import (  # noqa: E402
    CitationRenderError,
    extract_citation_placeholders,
    render_citation_placeholders,
)
from ..templates import get_template  # noqa: E402
from ..validators.metric_guard import (  # noqa: E402
    load_evidence_lock,
    metric_entries,
    render_metric_placeholders,
)

_DEFAULT_SECTION_ORDER = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)
_PROMPT_NAME = "section_writing_v1.txt"
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_RAW_CITE_RE = re.compile(r"\\cite\w*(?:\[[^\]]*\])*\{([^}]+)\}")
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_METRIC_LIKE_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:p\s*[<=>]\s*)?(?:0?\.\d+|\d+\.\d+|\d+(?:\.\d+)?%)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s,;\"']+")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s,;\"']+\\[^\s,;\"']+")
_POSIX_PATH_RE = re.compile(
    r"(?<![\w:/])/(?:Users|home|private|var|tmp|mnt|data|scratch|nfs|Volumes|workspace|opt|srv)"
    r"(?:/[^\s,;\"']+)+"
)
_PRIVATE_PLACEHOLDER_RE = re.compile(r"PRIVATE_(?:PATH|CASE|INSTITUTION|DATE)_\d+")
_PRIVATE_SOURCE_PLACEHOLDER_RE = re.compile(r"PRIVATE_SOURCE_ID_\d{3}")
_PHI_HARD_FAIL_KEYS = ("raw_paths", "case_ids", "institution_names", "dates")
_PRIVATE_SOURCE_ID_FIELDS = {"task_id", "analysis_id", "source_model_task_id"}
_GENERIC_PRIVATE_SOURCE_IDS = {"task", "analysis", "main", "none", "unknown", "external_validation"}
_PUBLIC_FIGURE_STATUSES = {"ready"}
_SECTION_TITLES = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "related_work": "Related Work",
    "methods": "Methods",
    "experiments": "Experimental Setup",
    "results": "Results",
    "discussion": "Discussion",
    "conclusion": "Conclusion",
}
_SECTION_ALIASES = {
    "abstract": "abstract",
    "summary": "abstract",
    "introduction": "introduction",
    "intro": "introduction",
    "related_work": "related_work",
    "related_works": "related_work",
    "related_literature": "related_work",
    "background": "related_work",
    "methods": "methods",
    "method": "methods",
    "materials_and_methods": "methods",
    "methodology": "methods",
    "experiments": "experiments",
    "experiment": "experiments",
    "experimental_setup": "experiments",
    "experimental_design": "experiments",
    "evaluation": "experiments",
    "results": "results",
    "result": "results",
    "findings": "results",
    "discussion": "discussion",
    "limitations": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
}
_DEFAULT_LOCKED_BLOCKS_BY_SECTION = {
    "methods": ("locked_blocks/method_block.tex",),
    "experiments": ("locked_blocks/dataset_block.tex",),
    "results": ("locked_blocks/results_block.tex",),
}


class SectionWritingAgentError(RuntimeError):
    """Raised when the Section Writing Agent cannot safely produce sections."""


class SectionCitationContractError(SectionWritingAgentError):
    """Raised when the A2 citation contract is violated."""


class SectionMetricContractError(SectionWritingAgentError):
    """Raised when metric placeholders cannot be rendered deterministically."""


class SectionFigureTableContractError(SectionWritingAgentError):
    """Raised when figures or tables are omitted or invented."""


class SectionPhiLeakError(SectionWritingAgentError):
    """Raised when private identifiers would reach an LLM prompt or output."""


@dataclass(frozen=True)
class SectionWritingInputs:
    """Inputs consumed by the M9 Section Writing Agent."""

    title: str | None
    language: str
    outline: dict[str, Any]
    intro_rw_draft: dict[str, str]
    figures_manifest: dict[str, Any]
    refs_bib: str
    selected_refs: tuple[dict[str, Any], ...]
    required_cites: tuple[dict[str, Any], ...]
    locked_blocks: tuple[dict[str, str], ...]
    tables: tuple[dict[str, str], ...]
    experimental_log: str
    idea: str
    template_styles: tuple[dict[str, Any], ...]
    evidence_lock: dict[str, Any] = field(repr=False)
    private_source_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_paths(cls, paths: PaperRunPaths, config: Any) -> "SectionWritingInputs":
        outline = _read_json_object_or_default(paths.outline_json, {})
        evidence_lock = load_evidence_lock(paths)
        return cls(
            title=getattr(config, "title", None),
            language=str(getattr(config, "language", "en") or "en"),
            outline=outline,
            intro_rw_draft=_read_intro_rw_drafts(paths),
            figures_manifest=_read_json_object_or_default(paths.figures_manifest, {"figures": []}),
            refs_bib=_read_text_or_default(paths.refs_bib, ""),
            selected_refs=tuple(_load_reference_items(paths.citations_dir / "selected_refs.json")),
            required_cites=tuple(_load_reference_items(paths.citations_dir / "required_cites.json")),
            locked_blocks=tuple(_read_named_tex_files(paths.locked_blocks_dir, prefix="locked_blocks")),
            tables=tuple(_read_named_tex_files(paths.tables_dir, prefix="tables")),
            experimental_log=_read_text_or_default(paths.experimental_log, ""),
            idea=_read_text_or_default(paths.idea, str(getattr(config, "user_idea", "") or "")),
            template_styles=tuple(_template_styles(config)),
            evidence_lock=evidence_lock,
            private_source_ids=tuple(_private_source_ids_from_config_and_lock(config, evidence_lock)),
        )


@dataclass(frozen=True)
class SectionWritingResult:
    """Rendered section files plus raw LLM sections for tests/debugging."""

    sections: dict[str, str]
    raw_sections: dict[str, str]
    used_citations: tuple[str, ...]


class SectionWritingAgent:
    """Generate all manuscript sections with one LLM call and deterministic renderers."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        prompt_template: str | None = None,
        min_selected_coverage: float = 0.9,
    ) -> None:
        self.llm_client = llm_client or _default_llm_client()
        self.prompt_template = prompt_template or _load_prompt_template()
        self.min_selected_coverage = min_selected_coverage

    def generate(self, inputs: SectionWritingInputs) -> SectionWritingResult:
        prompt = self.build_prompt(inputs)
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Section Writing Agent. Return only JSON sections. "
                        "Use [CITE:key] and {{m:key}} placeholders; never raw \\cite{} or metric numbers."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.25,
            response_format={"type": "json_object"},
        )
        raw_sections = parse_sections_json(_response_text(response))
        required_sections = required_section_slugs(inputs)
        normalized = normalize_sections(raw_sections, required_sections)
        _assert_no_private_identifiers(normalized, context="section-writing output")
        _assert_no_private_source_identifiers(
            normalized,
            inputs.private_source_ids,
            context="section-writing output",
        )
        _assert_no_private_source_placeholders(normalized, context="section-writing output")
        _assert_no_raw_cites(normalized)
        _assert_no_raw_metric_values(normalized)
        used = _assert_citation_contract(normalized, inputs, self.min_selected_coverage)
        _assert_locked_block_contract(normalized, inputs)
        _assert_figure_table_contract(normalized, inputs)
        rendered = _render_sections(normalized, inputs)
        _assert_no_private_source_identifiers(
            rendered,
            inputs.private_source_ids,
            context="rendered section-writing output",
        )
        _assert_no_private_source_placeholders(rendered, context="rendered section-writing output")
        return SectionWritingResult(
            sections=rendered,
            raw_sections=normalized,
            used_citations=tuple(sorted(used)),
        )

    def build_prompt(self, inputs: SectionWritingInputs) -> str:
        payload = _redact_private_source_identifiers(_prompt_payload(inputs), inputs.private_source_ids)
        _assert_no_private_source_identifiers(
            payload,
            inputs.private_source_ids,
            context="section-writing prompt payload",
        )
        _assert_no_private_identifiers(payload, context="section-writing prompt payload")
        payload_json = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        return self.prompt_template.replace("{{INPUT_PAYLOAD_JSON}}", payload_json)


class _NoNetworkSectionWritingLLMClient:
    """CI safeguard so section-writing tests never call a real provider."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        del temperature, response_format, stream
        prompt = messages[-1].content if messages else ""
        payload = _payload_from_prompt(prompt)
        sections = _deterministic_sections_payload(payload)
        return LLMResponse(
            content=json.dumps({"sections": sections}),
            model="no-network-section-writing-fixture",
            provider="ci_no_network",
        )


def parse_sections_json(text: str) -> dict[str, str]:
    """Parse raw LLM text into a section-slug-to-LaTeX mapping."""
    stripped = text.strip()
    if not stripped:
        raise SectionWritingAgentError("Section Writing LLM returned an empty response")
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = _decode_first_json_object(stripped)
    if not isinstance(value, dict):
        raise SectionWritingAgentError("Section Writing LLM response must be a JSON object")
    raw_sections = value.get("sections", value)
    if isinstance(raw_sections, list):
        return _sections_from_list(raw_sections)
    if not isinstance(raw_sections, Mapping):
        raise SectionWritingAgentError("Section Writing LLM response must contain a sections object")
    sections: dict[str, str] = {}
    for key, item in raw_sections.items():
        slug = section_slug(str(key))
        if slug is None:
            continue
        if isinstance(item, Mapping):
            item = item.get("latex") or item.get("tex") or item.get("content") or item.get("text")
        if not isinstance(item, str) or not item.strip():
            raise SectionWritingAgentError(f"Section {key!r} must contain non-empty LaTeX text")
        sections[slug] = item
    if not sections:
        raise SectionWritingAgentError("Section Writing LLM returned no valid sections")
    return sections


def normalize_sections(sections: Mapping[str, str], required_slugs: Sequence[str]) -> dict[str, str]:
    """Ensure all required sections exist and carry expected LaTeX headings."""
    normalized: dict[str, str] = {}
    for slug in required_slugs:
        text = sections.get(slug)
        if not isinstance(text, str) or not text.strip():
            raise SectionWritingAgentError(f"Section Writing LLM omitted required section: {slug}")
        normalized[slug] = _ensure_latex_heading(slug, text)
    for slug, text in sections.items():
        if slug in normalized:
            continue
        normalized[slug] = _ensure_latex_heading(slug, text)
    return normalized


def required_section_slugs(inputs: SectionWritingInputs) -> list[str]:
    """Return the section files M9 must write for the selected templates."""
    slugs: list[str] = []
    section_plan = inputs.outline.get("section_plan") if isinstance(inputs.outline, Mapping) else None
    if isinstance(section_plan, list):
        for item in section_plan:
            candidate: Any
            if isinstance(item, Mapping):
                candidate = item.get("section") or item.get("slug") or item.get("name")
            else:
                candidate = item
            slug = section_slug(str(candidate)) if candidate is not None else None
            if slug:
                _append_unique(slugs, slug)
    for style in inputs.template_styles:
        order = style.get("section_order") if isinstance(style, Mapping) else None
        if isinstance(order, list):
            for item in order:
                slug = section_slug(str(item))
                if slug:
                    _append_unique(slugs, slug)
    if not slugs:
        slugs.extend(_DEFAULT_SECTION_ORDER)
    return slugs


def section_slug(value: str) -> str | None:
    """Normalize a section title or key to the renderer's file slug."""
    raw = value.strip()
    if not raw:
        return None
    raw = re.sub(r"^\\(?:sub)*section\*?\{", "", raw).rstrip("}")
    lowered = raw.casefold().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if not lowered:
        return None
    return _SECTION_ALIASES.get(lowered, lowered)


def _sections_from_list(items: Sequence[Any]) -> dict[str, str]:
    sections: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("section") or item.get("slug") or item.get("name")
        slug = section_slug(str(name)) if name is not None else None
        if not slug:
            continue
        text = item.get("latex") or item.get("tex") or item.get("content") or item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SectionWritingAgentError(f"Section {name!r} must contain non-empty LaTeX text")
        sections[slug] = text
    if not sections:
        raise SectionWritingAgentError("Section Writing LLM returned no valid sections")
    return sections


def _prompt_payload(inputs: SectionWritingInputs) -> dict[str, Any]:
    selected_keys = sorted(_ref_keys(inputs.selected_refs))
    required_keys = sorted(_ref_keys(inputs.required_cites))
    metrics = _metric_placeholder_catalog(inputs.evidence_lock)
    return {
        "paper_title": inputs.title,
        "language": inputs.language,
        "outline": inputs.outline,
        "idea_md": inputs.idea,
        "experimental_log_md": inputs.experimental_log,
        "template_styles": list(inputs.template_styles),
        "section_contract": {
            "required_section_slugs": required_section_slugs(inputs),
            "write_destination": "drafts/sections",
            "intro_rw_draft_is_input_only": True,
            "metric_placeholder_syntax": "{{m:metric_key}}",
            "allowed_metric_keys": [item["key"] for item in metrics],
            "citation_placeholder_syntax": "[CITE:paperId]",
            "allowed_cite_keys": selected_keys,
            "required_cite_keys": required_keys,
            "min_selected_citation_coverage": 0.9,
            "locked_block_paths": [item["path"] for item in inputs.locked_blocks],
            "table_paths": [item["path"] for item in inputs.tables],
        },
        "drafts_intro_rw_draft": _placeholder_safe_intro_rw(inputs.intro_rw_draft),
        "figures_manifest": inputs.figures_manifest,
        "citations": {
            "selected_refs": list(inputs.selected_refs),
            "required_cites": list(inputs.required_cites),
            "refs_bib": inputs.refs_bib,
        },
        "metric_placeholders": metrics,
        "locked_blocks": list(inputs.locked_blocks),
        "tables": list(inputs.tables),
    }


def _render_sections(sections: Mapping[str, str], inputs: SectionWritingInputs) -> dict[str, str]:
    allowed_keys = _ref_keys(inputs.selected_refs)
    evidence_lock = inputs.evidence_lock
    rendered: dict[str, str] = {}
    for slug, text in sections.items():
        try:
            with_citations = render_citation_placeholders(text, allowed_keys)
        except CitationRenderError as exc:
            raise SectionCitationContractError(str(exc)) from exc
        try:
            with_metrics = render_metric_placeholders(with_citations, evidence_lock)
        except KeyError as exc:
            key = exc.args[0] if exc.args else "unknown"
            raise SectionMetricContractError(
                f"Metric placeholder {key!r} is not present in evidence_lock.private.json"
            ) from exc
        if "[CITE:" in with_metrics:
            raise SectionCitationContractError(f"Unrendered citation placeholder remains in {slug}")
        if "{{m:" in with_metrics:
            raise SectionMetricContractError(f"Unrendered metric placeholder remains in {slug}")
        rendered[slug] = _ensure_trailing_newline(_normalize_includegraphics_options(with_metrics))
    return rendered


def _assert_citation_contract(
    sections: Mapping[str, str],
    inputs: SectionWritingInputs,
    min_selected_coverage: float,
) -> set[str]:
    text = "\n".join(sections.values())
    used = extract_citation_placeholders(text)
    selected = _ref_keys(inputs.selected_refs)
    required = _ref_keys(inputs.required_cites)
    unknown = used - selected
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise SectionCitationContractError(f"Citation key(s) outside selected_refs.json: {keys}")
    missing = required - used
    if missing:
        keys = ", ".join(sorted(missing))
        raise SectionCitationContractError(f"Required citation key(s) missing from final sections: {keys}")
    if selected:
        coverage = len(used & selected) / len(selected)
        if coverage < min_selected_coverage:
            raise SectionCitationContractError(
                f"Selected citation coverage {coverage:.3f} is below {min_selected_coverage:.3f}"
            )
    elif used:
        keys = ", ".join(sorted(used))
        raise SectionCitationContractError(f"Citation key(s) used without selected_refs.json: {keys}")
    return used


def _assert_locked_block_contract(sections: Mapping[str, str], inputs: SectionWritingInputs) -> None:
    available = {item["path"] for item in inputs.locked_blocks if item.get("path")}
    if not available:
        return
    section_plan_requirements = _locked_block_requirements_from_outline(inputs.outline)
    for slug, defaults in _DEFAULT_LOCKED_BLOCKS_BY_SECTION.items():
        for path in defaults:
            if path in available:
                section_plan_requirements.setdefault(slug, set()).add(path)
    for slug, paths in section_plan_requirements.items():
        if slug not in sections:
            continue
        text = sections[slug]
        missing = [path for path in sorted(paths) if path in available and _input_command(path) not in text]
        if missing:
            missing_paths = ", ".join(missing)
            raise SectionWritingAgentError(f"Section {slug} is missing locked block input(s): {missing_paths}")


def _assert_figure_table_contract(sections: Mapping[str, str], inputs: SectionWritingInputs) -> None:
    text = "\n".join(sections.values())
    ready_figures = _ready_figure_entries(inputs.figures_manifest)
    used_graphics = {_normalize_asset_path(match.group(1)) for match in _INCLUDEGRAPHICS_RE.finditer(text)}
    used_graphics.discard("")
    allowed_graphics = _asset_aliases(
        str(item["path"])
        for item in ready_figures
        if isinstance(item.get("path"), str) and item.get("path")
    )
    unknown_graphics = used_graphics - allowed_graphics
    if unknown_graphics:
        paths = ", ".join(sorted(unknown_graphics))
        raise SectionFigureTableContractError(f"Figure path(s) are not ready manifest files: {paths}")

    missing_figures: list[str] = []
    for item in ready_figures:
        figure_id = str(item.get("figure_id") or "").strip()
        path = str(item.get("path") or "").strip()
        has_path = bool(path and _asset_aliases([path]) & used_graphics)
        has_id = bool(figure_id and figure_id in text)
        if not (has_path and has_id):
            missing_figures.append(figure_id or path)
    if missing_figures:
        names = ", ".join(sorted(missing_figures))
        raise SectionFigureTableContractError(f"Ready figure(s) missing from final sections: {names}")

    allowed_tables = {str(item["path"]) for item in inputs.tables if item.get("path")}
    used_tables = {
        _normalize_table_input_path(match.group(1))
        for match in _INPUT_RE.finditer(text)
        if _normalize_asset_path(match.group(1)).startswith("tables/")
    }
    used_tables.discard("")
    unknown_tables = used_tables - allowed_tables
    if unknown_tables:
        paths = ", ".join(sorted(unknown_tables))
        raise SectionFigureTableContractError(f"Table input(s) are not present in tables/: {paths}")


def _locked_block_requirements_from_outline(outline: Mapping[str, Any]) -> dict[str, set[str]]:
    requirements: dict[str, set[str]] = {}
    section_plan = outline.get("section_plan") if isinstance(outline, Mapping) else None
    if not isinstance(section_plan, list):
        return requirements
    for item in section_plan:
        if not isinstance(item, Mapping):
            continue
        slug = section_slug(str(item.get("section") or item.get("slug") or ""))
        if not slug:
            continue
        raw_inputs = item.get("locked_block_inputs") or []
        if not isinstance(raw_inputs, list):
            continue
        for raw_path in raw_inputs:
            path = str(raw_path).strip().replace("\\", "/")
            if path.startswith("locked_blocks/") and path.endswith(".tex"):
                requirements.setdefault(slug, set()).add(path)
    return requirements


def _assert_no_raw_cites(sections: Mapping[str, str]) -> None:
    for slug, text in sections.items():
        match = _RAW_CITE_RE.search(text)
        if match:
            raise SectionCitationContractError(
                f"Section {slug} contains raw \\cite{{}}; use [CITE:paperId] placeholders before rendering"
            )


def _assert_no_raw_metric_values(sections: Mapping[str, str]) -> None:
    for slug, text in sections.items():
        without_placeholders = _strip_non_metric_latex_fragments(
            re.sub(r"\{\{\s*m:[A-Za-z0-9_.:-]+\s*\}\}", "", text)
        )
        match = _METRIC_LIKE_NUMBER_RE.search(without_placeholders)
        if match:
            raise SectionMetricContractError(
                f"Section {slug} contains raw metric-like value {match.group(0)!r}; use {{{{m:metric_key}}}}"
            )


def _strip_non_metric_latex_fragments(text: str) -> str:
    return _INCLUDEGRAPHICS_RE.sub("", text)


def _normalize_includegraphics_options(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return rf"\includegraphics[width=\linewidth]{{{match.group(1)}}}"

    return _INCLUDEGRAPHICS_RE.sub(repl, text)


def _ensure_latex_heading(slug: str, text: str) -> str:
    stripped = text.strip()
    if slug == "abstract":
        if re.search(r"\\begin\{abstract\}", stripped):
            return _ensure_trailing_newline(stripped)
        return f"\\begin{{abstract}}\n{stripped}\n\\end{{abstract}}\n"
    if re.match(r"^\s*\\section\*?\{", stripped):
        return _ensure_trailing_newline(stripped)
    title = _SECTION_TITLES.get(slug, slug.replace("_", " ").title())
    return f"\\section{{{title}}}\n{stripped}\n"


def _placeholder_safe_intro_rw(drafts: Mapping[str, str]) -> dict[str, str]:
    return {key: _raw_cites_to_placeholders(value) for key, value in drafts.items()}


def _raw_cites_to_placeholders(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        keys = [key.strip() for key in match.group(1).split(",") if key.strip()]
        return " ".join(f"[CITE:{key}]" for key in keys)

    return _RAW_CITE_RE.sub(repl, text)


def _input_command(path: str) -> str:
    return rf"\input{{{path}}}"


def _metric_placeholder_catalog(evidence_lock: Mapping[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for key, item in sorted(metric_entries(dict(evidence_lock)).items()):
        catalog.append(
            {
                "key": key,
                "name": item.get("name"),
                "role": item.get("role"),
            }
        )
    return catalog


def _deterministic_sections_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    contract = payload.get("section_contract") if isinstance(payload.get("section_contract"), Mapping) else {}
    slugs = contract.get("required_section_slugs") if isinstance(contract.get("required_section_slugs"), list) else []
    if not slugs:
        slugs = list(_DEFAULT_SECTION_ORDER)
    selected_keys = [str(key) for key in contract.get("allowed_cite_keys") or [] if str(key)]
    required_keys = [str(key) for key in contract.get("required_cite_keys") or [] if str(key)]
    ordered_cites = _ordered_unique([*required_keys, *selected_keys])
    metric_keys = [str(key) for key in contract.get("allowed_metric_keys") or [] if str(key)]
    primary_metric = metric_keys[0] if metric_keys else None
    available_blocks = {str(path) for path in contract.get("locked_block_paths") or []}
    table_paths = [str(path) for path in contract.get("table_paths") or [] if str(path).endswith(".tex")]
    figures = _ready_figure_entries(payload.get("figures_manifest") if isinstance(payload, Mapping) else {})
    title = str(payload.get("paper_title") or "PathLab study")
    sections: dict[str, str] = {}
    for raw_slug in slugs:
        slug = section_slug(str(raw_slug)) or str(raw_slug)
        if slug == "abstract":
            metric_sentence = (
                f" The primary locked metric is reported as {{{{m:{primary_metric}}}}}."
                if primary_metric
                else ""
            )
            sections[slug] = (
                "\\begin{abstract}\n"
                f"This manuscript summarizes {title} using PathLab evidence-locked artifacts."
                f"{metric_sentence} All dataset, model, and result facts are delegated to deterministic locked blocks.\n"
                "\\end{abstract}\n"
            )
        elif slug == "introduction":
            citation_text = _cite_placeholders(ordered_cites[: max(1, len(ordered_cites) // 2)])
            sections[slug] = (
                "\\section{Introduction}\n"
                "Computational pathology manuscripts require tight coupling between narrative claims and reproducible evidence. "
                "PathLab assembles the final manuscript around deterministic artifacts rather than free-form metric transcription"
                f"{citation_text}.\n"
            )
        elif slug == "related_work":
            remaining = ordered_cites[max(1, len(ordered_cites) // 2) :] if ordered_cites else []
            if not remaining:
                remaining = ordered_cites
            citation_text = _cite_placeholders(remaining)
            sections[slug] = (
                "\\section{Related Work}\n"
                "Prior work motivates evidence-grounded computational pathology reporting and validated model comparison"
                f"{citation_text}.\n"
            )
        elif slug == "methods":
            inputs = _existing_inputs(
                [
                    "locked_blocks/dataset_block.tex",
                    "locked_blocks/method_block.tex",
                    "locked_blocks/evidence_gaps.tex",
                ],
                available_blocks,
            )
            sections[slug] = (
                "\\section{Methods}\n"
                + _join_inputs(inputs)
                + "The prose in this section frames the deterministic method block without rewriting locked configuration facts.\n"
            )
        elif slug == "experiments":
            inputs = _existing_inputs(
                [
                    "locked_blocks/dataset_block.tex",
                    "locked_blocks/results_block.tex",
                    "locked_blocks/metrics_macros.tex",
                ],
                available_blocks,
            )
            sections[slug] = (
                "\\section{Experimental Setup}\n"
                + _join_inputs(inputs)
                + "The experimental setup follows the scrubbed cohort and split evidence exposed by PathLab.\n"
            )
        elif slug == "results":
            inputs = _existing_inputs(
                ["locked_blocks/results_block.tex", "locked_blocks/metrics_macros.tex"],
                available_blocks,
            )
            table_inputs = [rf"\input{{{path}}}" for path in table_paths if "table_2" in path or "main_results" in path]
            figure_blocks = _figure_latex_blocks(figures)
            metric_sentence = (
                f"The headline result is rendered from {{{{m:{primary_metric}}}}} and cross-checked against the locked results block.\n"
                if primary_metric
                else "The headline result is cross-checked against the locked results block.\n"
            )
            sections[slug] = (
                "\\section{Results}\n"
                + _join_inputs([*inputs, *table_inputs])
                + _join_inputs(figure_blocks)
                + metric_sentence
            )
        elif slug == "discussion":
            inputs = _existing_inputs(["locked_blocks/evidence_gaps.tex"], available_blocks)
            sections[slug] = (
                "\\section{Discussion}\n"
                + _join_inputs(inputs)
                + "The discussion limits interpretation to evidence available in the locked PathLab run and avoids unsupported clinical generalization.\n"
            )
        elif slug == "conclusion":
            inputs = _existing_inputs(["locked_blocks/evidence_gaps.tex"], available_blocks)
            sections[slug] = (
                "\\section{Conclusion}\n"
                + _join_inputs(inputs)
                + "PathLab produces a manuscript draft whose factual claims are connected to deterministic evidence, locked blocks, and selected citations.\n"
            )
        else:
            title_text = _SECTION_TITLES.get(slug, slug.replace("_", " ").title())
            sections[slug] = f"\\section{{{title_text}}}\nThis section is generated from the PathLab outline and locked evidence.\n"
    return sections


def _cite_placeholders(keys: Sequence[str]) -> str:
    cleaned = [key for key in keys if key]
    if not cleaned:
        return ""
    return " " + " ".join(f"[CITE:{key}]" for key in cleaned)


def _existing_inputs(paths: Sequence[str], available: set[str]) -> list[str]:
    return [rf"\input{{{path}}}" for path in paths if path in available]


def _join_inputs(inputs: Sequence[str]) -> str:
    if not inputs:
        return ""
    return "\n".join(inputs) + "\n"


def _figure_latex_blocks(figures: Sequence[Mapping[str, Any]]) -> list[str]:
    blocks: list[str] = []
    for item in figures:
        figure_id = str(item.get("figure_id") or "").strip()
        path = str(item.get("path") or "").strip()
        if not figure_id or not path:
            continue
        blocks.append(
            "\\begin{figure}[t]\n"
            "\\centering\n"
            rf"\includegraphics[width=\linewidth]{{{path}}}" + "\n"
            rf"\caption{{PathLab generated figure for {figure_id}.}}" + "\n"
            rf"\label{{{figure_id}}}" + "\n"
            "\\end{figure}\n"
        )
    return blocks


def _ordered_unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _payload_from_prompt(prompt: str) -> dict[str, Any]:
    marker = "Input payload:"
    if marker not in prompt:
        return {}
    raw = prompt.split(marker, 1)[1].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _ref_keys(items: Sequence[Mapping[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for item in items:
        key = _ref_key(item)
        if key:
            keys.add(key)
    return keys


def _ref_key(item: Mapping[str, Any]) -> str | None:
    for field_name in ("bib_key", "key", "paper_id", "paperId", "id"):
        value = item.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _load_reference_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("items") if isinstance(payload, dict) else payload
    items: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, str) and item.strip():
            items.append({"key": item.strip()})
        elif isinstance(item, Mapping):
            normalized = dict(item)
            key = _ref_key(normalized)
            if key:
                normalized.setdefault("key", key)
                items.append(normalized)
    return items


def _read_intro_rw_drafts(paths: PaperRunPaths) -> dict[str, str]:
    return {
        "introduction": _read_text_or_default(paths.intro_rw_draft_dir / "introduction.tex", ""),
        "related_work": _read_text_or_default(paths.intro_rw_draft_dir / "related_work.tex", ""),
    }


def _read_named_tex_files(directory: Path, *, prefix: str) -> list[dict[str, str]]:
    if not directory.exists():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.tex")):
        if not path.is_file():
            continue
        items.append({"path": f"{prefix}/{path.name}", "content": path.read_text(encoding="utf-8")})
    return items


def _ready_figure_entries(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, Mapping):
        return []
    raw = manifest.get("figures")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "").strip()
        path = str(item.get("path") or "").strip()
        figure_id = str(item.get("figure_id") or "").strip()
        if status not in _PUBLIC_FIGURE_STATUSES or not path or not figure_id:
            continue
        if not path.startswith("figures/"):
            continue
        entries.append(dict(item))
    return entries


def _normalize_asset_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def _normalize_table_input_path(path: str) -> str:
    normalized = _normalize_asset_path(path)
    if normalized.startswith("tables/") and not Path(normalized).suffix:
        return f"{normalized}.tex"
    return normalized


def _asset_aliases(paths: Iterable[str]) -> set[str]:
    aliases: set[str] = set()
    for path in paths:
        normalized = _normalize_asset_path(path)
        if not normalized:
            continue
        aliases.add(normalized)
        suffix = Path(normalized).suffix
        if suffix:
            aliases.add(normalized[: -len(suffix)])
    return aliases


def _read_text_or_default(path: Path, default: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return default


def _read_json_object_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SectionWritingAgentError(f"{path} must contain a JSON object")
    return payload


def _template_styles(config: Any) -> list[dict[str, Any]]:
    selected = getattr(config, "selected_templates", []) or []
    if not selected:
        selected = ["miccai"]
    styles: list[dict[str, Any]] = []
    for template in selected:
        template_id = str(getattr(template, "value", template))
        styles.append(dict(get_template(template_id).style))
    return styles


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"


def _response_text(response: LLMResponse | Any) -> str:
    raw_content = response.content if isinstance(response, LLMResponse) else getattr(response, "content", response)
    return raw_content if isinstance(raw_content, str) else str(raw_content)


def _decode_first_json_object(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise SectionWritingAgentError("Section Writing LLM response did not contain a JSON object")


def _private_source_ids_from_config_and_lock(config: Any, evidence_lock: Mapping[str, Any]) -> list[str]:
    identifiers: set[str] = set()
    source_tasks = getattr(config, "source_tasks", None)
    if source_tasks is None and isinstance(config, Mapping):
        source_tasks = config.get("source_tasks", [])
    for source_task in source_tasks or []:
        if isinstance(source_task, Mapping):
            _add_private_source_id(identifiers, source_task.get("task_id"))
        else:
            _add_private_source_id(identifiers, getattr(source_task, "task_id", None))
    _collect_private_source_ids(evidence_lock, identifiers)
    return sorted(identifiers)


def _collect_private_source_ids(value: Any, identifiers: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PRIVATE_SOURCE_ID_FIELDS:
                _add_private_source_values(identifiers, item)
            else:
                _collect_private_source_ids(item, identifiers)
    elif isinstance(value, list | tuple | set):
        for item in value:
            _collect_private_source_ids(item, identifiers)


def _add_private_source_values(identifiers: set[str], value: Any) -> None:
    if isinstance(value, str):
        _add_private_source_id(identifiers, value)
    elif isinstance(value, list | tuple | set):
        for item in value:
            _add_private_source_values(identifiers, item)
    elif isinstance(value, Mapping):
        for item in value.values():
            _add_private_source_values(identifiers, item)


def _add_private_source_id(identifiers: set[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    stripped = value.strip()
    if len(stripped) < 3:
        return
    if stripped.casefold() in _GENERIC_PRIVATE_SOURCE_IDS:
        return
    if stripped.startswith("PRIVATE_"):
        return
    identifiers.add(stripped)


def _redact_private_source_identifiers(value: Any, identifiers: Sequence[str]) -> Any:
    replacements = {
        raw: f"PRIVATE_SOURCE_ID_{index + 1:03d}"
        for index, raw in enumerate(sorted(set(identifiers), key=len, reverse=True))
    }

    def redact_text(text: str) -> str:
        redacted = text
        for raw, replacement in replacements.items():
            redacted = redacted.replace(raw, replacement)
        return redacted

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(redact_text(str(key))): _redact_private_source_identifiers(item, identifiers)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_private_source_identifiers(item, identifiers) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_private_source_identifiers(item, identifiers) for item in value)
    return value


def _assert_no_private_source_identifiers(value: Any, identifiers: Sequence[str], *, context: str) -> None:
    found: set[str] = set()

    def observe(item: Any) -> None:
        if isinstance(item, str):
            for identifier in identifiers:
                if identifier and identifier in item:
                    found.add(identifier)
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                observe(key)
                observe(nested)
        elif isinstance(item, list | tuple | set):
            for nested in item:
                observe(nested)

    observe(value)
    if found:
        examples = ", ".join(sorted(found)[:5])
        raise SectionPhiLeakError(f"Private source identifier(s) detected in {context}: {examples}")


def _assert_no_private_source_placeholders(value: Any, *, context: str) -> None:
    placeholders: set[str] = set()

    def observe(item: Any) -> None:
        if isinstance(item, str):
            placeholders.update(_PRIVATE_SOURCE_PLACEHOLDER_RE.findall(item))
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                observe(key)
                observe(nested)
        elif isinstance(item, list | tuple | set):
            for nested in item:
                observe(nested)

    observe(value)
    if placeholders:
        examples = ", ".join(sorted(placeholders)[:5])
        raise SectionPhiLeakError(f"Private source placeholder(s) leaked into {context}: {examples}")


def _assert_no_private_identifiers(value: Any, *, context: str) -> None:
    scrubber = PhiScrubber()
    scrubber.observe(value)
    identifiers = scrubber.private_identifiers()
    extra_paths = _extra_private_paths(value)
    if extra_paths:
        identifiers["raw_paths"] = sorted(set([*identifiers.get("raw_paths", []), *extra_paths]))
    leaked = {
        key: identifiers.get(key, [])
        for key in _PHI_HARD_FAIL_KEYS
        if identifiers.get(key)
    }
    if not leaked:
        return
    counts = ", ".join(f"{key}={len(items)}" for key, items in sorted(leaked.items()))
    raise SectionPhiLeakError(f"PHI/private identifiers detected in {context}: {counts}")


def _extra_private_paths(value: Any) -> list[str]:
    matches: set[str] = set()

    def observe(item: Any) -> None:
        if isinstance(item, str):
            matches.update(_WINDOWS_PATH_RE.findall(item))
            matches.update(_UNC_PATH_RE.findall(item))
            matches.update(_POSIX_PATH_RE.findall(item))
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                observe(key)
                observe(nested)
        elif isinstance(item, list | tuple | set):
            for nested in item:
                observe(nested)

    observe(value)
    return sorted(match for match in matches if not _PRIVATE_PLACEHOLDER_RE.search(match))


def _load_prompt_template() -> str:
    prompt_ref = resources.files("pathlab_paper_agent") / "prompts" / _PROMPT_NAME
    return Path(str(prompt_ref)).read_text(encoding="utf-8")


def _default_llm_client() -> LLMClient:
    if _ci_should_disable_network_llm():
        return _NoNetworkSectionWritingLLMClient()
    return OpenAICompatibleLLMClient()


def _ci_should_disable_network_llm() -> bool:
    if os.environ.get("PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS") == "1":
        return False
    return "PYTEST_CURRENT_TEST" in os.environ
