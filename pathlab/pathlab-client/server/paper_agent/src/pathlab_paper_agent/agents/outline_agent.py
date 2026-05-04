"""Outline Agent derived from PaperOrchestra Appendix F.1."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from ..evidence.phi import PhiScrubber  # noqa: E402
from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient  # noqa: E402
from ..templates import get_template  # noqa: E402

_REQUIRED_OUTLINE_FIELDS = (
    "plotting_plan",
    "macro_lit_search",
    "micro_lit_clusters",
    "section_plan",
    "pathlab_extensions",
)
_LIST_FIELDS = (
    "plotting_plan",
    "macro_lit_search",
    "micro_lit_clusters",
    "section_plan",
)
# Dates are included so cohort-identifying timestamps (e.g. surgery date + hospital
# id) cannot leak into outline prompts even if the M3 scrubber failed to mask them
# upstream. Scrubbed input that already contains "PRIVATE_DATE_001" placeholders is
# unaffected because PhiScrubber only flags raw matches of the date regex.
_PHI_HARD_FAIL_KEYS = ("raw_paths", "case_ids", "institution_names", "dates")
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s,;\"']+")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s,;\"']+\\[^\s,;\"']+")
_POSIX_PATH_RE = re.compile(
    r"(?<![\w:/])/(?:Users|home|private|var|tmp|mnt|data|scratch|nfs|Volumes|workspace|opt|srv)"
    r"(?:/[^\s,;\"']+)+"
)
_DEFAULT_GUARDS = (
    "metric",
    "claim",
    "identifier",
    "consistency",
    "citation",
    "latex",
    "figure_table",
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


class OutlineAgentError(RuntimeError):
    """Raised when the Outline Agent cannot produce a valid outline."""


class PhiLeakError(OutlineAgentError):
    """Raised when private identifiers would reach an LLM prompt or output."""


class PlottingPlanItem(BaseModel):
    """One PaperOrchestra plotting-plan item."""

    model_config = ConfigDict(extra="allow")

    figure_id: str
    kind: str
    source: str
    design_objective: str
    backend: str
    plot_spec: dict[str, Any] = Field(default_factory=dict)


class MicroLitCluster(BaseModel):
    """One focused literature-search cluster."""

    model_config = ConfigDict(extra="allow")

    cluster: str
    queries: list[str] = Field(min_length=1)


class SectionPlanItem(BaseModel):
    """One planned manuscript section."""

    model_config = ConfigDict(extra="allow")

    section: str
    goal: str
    evidence_inputs: list[str] = Field(default_factory=list)
    citation_hints: list[str] = Field(default_factory=list)
    locked_block_inputs: list[str] = Field(default_factory=list)


class PathLabExtensions(BaseModel):
    """PathLab-only outline extensions."""

    model_config = ConfigDict(extra="allow")

    templates: list[str] = Field(default_factory=list)
    claim_plan: list[dict[str, Any]] = Field(default_factory=list)
    table_plan: list[dict[str, Any]] = Field(default_factory=list)
    guard_requirements: list[str] = Field(default_factory=list)
    template_styles: list[dict[str, Any]] = Field(default_factory=list)


class OutlineSchema(BaseModel):
    """Validated PaperOrchestra-compatible outline schema."""

    model_config = ConfigDict(extra="allow")

    plotting_plan: list[PlottingPlanItem]
    macro_lit_search: list[str]
    micro_lit_clusters: list[MicroLitCluster]
    section_plan: list[SectionPlanItem]
    pathlab_extensions: PathLabExtensions


@dataclass(frozen=True)
class OutlineInputs:
    """Inputs consumed by the Outline Agent."""

    idea: str
    experimental_log: str
    evidence_public: dict[str, Any]
    tables_manifest: dict[str, Any]
    template_styles: list[dict[str, Any]]
    figures_manifest: dict[str, Any]
    conference_guidelines: str = ""
    title: str | None = None
    language: str = "en"

    @classmethod
    def from_paths(cls, paths: Any, config: Any) -> "OutlineInputs":
        idea = _read_text_or_default(
            paths.idea,
            str(getattr(config, "user_idea", "") or "").strip()
            or "PathLab paper-generation run. The idea.md input is not available yet.",
        )
        experimental_log = _read_text_or_default(
            paths.experimental_log,
            (
                "# Experimental Log\n\n"
                "- evidence/experimental_log.md is not available yet; do not assert locked metrics.\n"
            ),
        )
        evidence_public = _read_json_object_or_default(
            paths.evidence_public,
            {"status": "not_yet_generated", "metrics": []},
            label="evidence/evidence_public.json",
        )
        tables_manifest = _read_json_object_or_default(
            paths.tables_dir / "manifest.json",
            {"tables": [], "status": "not_yet_generated"},
            label="tables/manifest.json",
        )
        figures_manifest = _read_figures_manifest(paths.figures_manifest)
        styles = [_template_style(_template_id(template)) for template in config.selected_templates]
        return cls(
            idea=idea,
            experimental_log=experimental_log,
            evidence_public=evidence_public,
            tables_manifest=tables_manifest,
            template_styles=styles,
            figures_manifest=figures_manifest,
            conference_guidelines=_read_conference_guidelines(paths),
            title=getattr(config, "title", None),
            language=str(getattr(config, "language", "en") or "en"),
        )


class OutlineAgent:
    """Generate PaperOrchestra-compatible outline JSON with one LLM call."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_client = llm_client or _default_llm_client()
        self.prompt_template = prompt_template or _load_prompt_template()

    def generate(self, inputs: OutlineInputs) -> dict[str, Any]:
        payload = _prompt_payload(inputs)
        prompt = self.build_prompt(inputs)
        _assert_no_private_identifiers(prompt, context="outline prompt")

        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Outline Agent. Return only valid JSON "
                        "matching the requested schema."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw_content = response.content if isinstance(response, LLMResponse) else getattr(response, "content", response)
        content = raw_content if isinstance(raw_content, str) else str(raw_content)
        outline = parse_outline_json(content)
        _assert_no_private_identifiers(outline, context="outline output")
        return validate_outline(outline, inputs, payload)

    def build_prompt(self, inputs: OutlineInputs) -> str:
        payload = _prompt_payload(inputs)
        _assert_no_private_identifiers(payload, context="outline prompt payload")
        payload_json = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        return self.prompt_template.replace("{{INPUT_PAYLOAD_JSON}}", payload_json)


def parse_outline_json(text: str) -> dict[str, Any]:
    """Parse raw LLM text into an outline object."""
    stripped = text.strip()
    if not stripped:
        raise OutlineAgentError("Outline LLM returned an empty response")
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = _decode_first_json_object(stripped)
    if not isinstance(value, dict):
        raise OutlineAgentError("Outline LLM response must be a JSON object")
    return value


def validate_outline(
    outline: Mapping[str, Any],
    inputs: OutlineInputs,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and lightly enrich an outline without changing core fields."""
    repaired = _conservative_repair(outline, inputs)
    try:
        parsed = OutlineSchema.model_validate(repaired)
    except ValidationError as exc:
        raise OutlineAgentError(f"Outline schema validation failed: {exc}") from exc

    normalized = parsed.model_dump(mode="json")
    for key, value in repaired.items():
        if key not in normalized:
            normalized[key] = value

    extensions = dict(normalized["pathlab_extensions"])
    selected_templates = [str(style.get("template_id")) for style in inputs.template_styles if style.get("template_id")]
    extensions.setdefault("templates", selected_templates)
    extensions.setdefault("claim_plan", [])
    extensions.setdefault("table_plan", [])
    extensions.setdefault("guard_requirements", list(_DEFAULT_GUARDS))
    extensions.setdefault("template_styles", _template_style_summaries(inputs.template_styles))
    normalized["pathlab_extensions"] = extensions

    if "template_style" not in normalized and inputs.template_styles:
        normalized["template_style"] = _primary_template_style(inputs.template_styles[0])
    if payload is not None:
        normalized.setdefault("input_summary", payload.get("input_summary", {}))
    return normalized


def _conservative_repair(outline: Mapping[str, Any], inputs: OutlineInputs) -> dict[str, Any]:
    missing = [field for field in _REQUIRED_OUTLINE_FIELDS if field not in outline]
    if missing:
        raise OutlineAgentError(f"Outline missing required field(s): {', '.join(missing)}")
    for field in _LIST_FIELDS:
        if not isinstance(outline.get(field), list):
            raise OutlineAgentError(f"Outline field {field!r} must be a list")
    if not isinstance(outline.get("pathlab_extensions"), Mapping):
        raise OutlineAgentError("Outline field 'pathlab_extensions' must be an object")

    repaired = deepcopy(dict(outline))
    for item in repaired.get("plotting_plan", []):
        if isinstance(item, dict):
            item.setdefault("plot_spec", {})
    for item in repaired.get("section_plan", []):
        if isinstance(item, dict):
            item.setdefault("evidence_inputs", ["idea", "experimental_log"])
            item.setdefault("citation_hints", [])
            item.setdefault("locked_block_inputs", [])
    extensions = dict(repaired["pathlab_extensions"])
    selected_templates = [str(style.get("template_id")) for style in inputs.template_styles if style.get("template_id")]
    extensions.setdefault("templates", selected_templates)
    extensions.setdefault("claim_plan", [])
    extensions.setdefault("table_plan", [])
    extensions.setdefault("guard_requirements", list(_DEFAULT_GUARDS))
    repaired["pathlab_extensions"] = extensions
    return repaired


def _prompt_payload(inputs: OutlineInputs) -> dict[str, Any]:
    return {
        "task": "pathlab_outline_generation",
        "title": inputs.title,
        "language": inputs.language,
        "idea_md": inputs.idea,
        "experimental_log_md": inputs.experimental_log,
        "evidence_public": inputs.evidence_public,
        "tables_manifest": inputs.tables_manifest,
        "template_styles": inputs.template_styles,
        "figures_manifest": inputs.figures_manifest,
        "conference_guidelines_md": inputs.conference_guidelines,
        "input_summary": {
            "template_ids": [
                str(style.get("template_id"))
                for style in inputs.template_styles
                if style.get("template_id")
            ],
            "figure_count": len(inputs.figures_manifest.get("figures", []))
            if isinstance(inputs.figures_manifest.get("figures"), list)
            else 0,
            "table_count": len(inputs.tables_manifest.get("tables", []))
            if isinstance(inputs.tables_manifest.get("tables"), list)
            else 0,
        },
    }


def _default_llm_client() -> LLMClient:
    if _ci_should_disable_network_llm():
        return _NoNetworkOutlineLLMClient()
    return OpenAICompatibleLLMClient()


def _ci_should_disable_network_llm() -> bool:
    """Default to the no-network fixture whenever pytest is running.

    Network calls during tests must be opted into explicitly via
    ``PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1`` so a developer who exports
    ``PAPER_GEN_LLM_BASE_URL`` for smoke testing cannot accidentally let pytest
    reach a real provider.
    """
    if os.environ.get("PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS") == "1":
        return False
    return "PYTEST_CURRENT_TEST" in os.environ


class _NoNetworkOutlineLLMClient:
    """CI safeguard so unrelated tests never call a real provider."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        del temperature, response_format, stream
        payload = _payload_from_prompt(messages[-1].content if messages else "")
        outline = _deterministic_outline_payload(payload)
        return LLMResponse(
            content=json.dumps(outline),
            model="no-network-outline-fixture",
            provider="ci_no_network",
        )


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


def _deterministic_outline_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    styles = payload.get("template_styles") if isinstance(payload.get("template_styles"), list) else []
    template_ids = [
        str(style.get("template_id"))
        for style in styles
        if isinstance(style, Mapping) and style.get("template_id")
    ]
    primary_style = next((style for style in styles if isinstance(style, Mapping)), {})
    section_order = primary_style.get("section_order") if isinstance(primary_style, Mapping) else []
    if not isinstance(section_order, list) or not section_order:
        section_order = [
            "abstract",
            "introduction",
            "related_work",
            "methods",
            "experiments",
            "results",
            "discussion",
            "conclusion",
        ]
    return {
        "plotting_plan": [
            {
                "figure_id": "fig:overview",
                "kind": "conceptual",
                "source": "idea + experimental_log",
                "design_objective": "show the PathLab WSI-to-prediction workflow",
                "backend": "user_revision",
            }
        ],
        "macro_lit_search": [
            "computational pathology whole slide image analysis",
            "AI-assisted pathology clinical validation",
        ],
        "micro_lit_clusters": [
            {
                "cluster": "multiple instance learning for pathology",
                "queries": [
                    "attention multiple instance learning whole slide images",
                    "computational pathology model validation",
                ],
            }
        ],
        "section_plan": [
            {
                "section": str(section).replace("_", " ").title(),
                "goal": "plan this section from locked PathLab evidence",
                "evidence_inputs": ["idea", "experimental_log"],
                "citation_hints": ["computational pathology", "clinical validation"],
                "locked_block_inputs": _default_locked_block_inputs(section),
            }
            for section in section_order
        ],
        "pathlab_extensions": {
            "templates": template_ids,
            "claim_plan": [],
            "table_plan": [],
            "guard_requirements": list(_DEFAULT_GUARDS),
            "llm_mode": "ci_no_network_fixture",
        },
    }


def _assert_no_private_identifiers(value: Any, *, context: str) -> None:
    scrubber = PhiScrubber()
    scrubber.observe(value)
    identifiers = scrubber.private_identifiers()
    windows_paths = _windows_paths(value)
    if windows_paths:
        identifiers.setdefault("raw_paths", [])
        identifiers["raw_paths"] = sorted(set([*identifiers["raw_paths"], *windows_paths]))
    leaked = {
        key: identifiers.get(key, [])
        for key in _PHI_HARD_FAIL_KEYS
        if identifiers.get(key)
    }
    if not leaked:
        return
    counts = ", ".join(f"{key}={len(items)}" for key, items in sorted(leaked.items()))
    raise PhiLeakError(f"PHI/private identifiers detected in {context}: {counts}")


def _windows_paths(value: Any) -> list[str]:
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
    return sorted(matches)


def _default_locked_block_inputs(section: Any) -> list[str]:
    normalized = str(section).lower().replace(" ", "_")
    if normalized in {"methods", "method", "materials_and_methods"}:
        return [
            "locked_blocks/dataset_block.tex",
            "locked_blocks/method_block.tex",
            "locked_blocks/evidence_gaps.tex",
        ]
    if normalized in {"experiments", "results"}:
        return [
            "locked_blocks/results_block.tex",
            "locked_blocks/metrics_macros.tex",
        ]
    if normalized in {"discussion", "conclusion"}:
        return ["locked_blocks/evidence_gaps.tex"]
    return []


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
    raise OutlineAgentError("Outline LLM response did not contain a JSON object")


def _read_text_or_default(path: Path, default: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return default


def _read_figures_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"figures": [], "status": "not_yet_generated"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OutlineAgentError("figures/manifest.json must contain a JSON object")
    payload.setdefault("figures", [])
    return payload


def _read_json_object_or_default(path: Path, default: dict[str, Any], *, label: str) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OutlineAgentError(f"{label} must contain a JSON object")
    return payload


def _read_conference_guidelines(paths: Any) -> str:
    candidates = [
        paths.root / "conference_guidelines.md",
        paths.inputs_dir / "conference_guidelines.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _template_id(template: Any) -> str:
    return str(getattr(template, "value", template))


def _template_style(template_id: str) -> dict[str, Any]:
    return deepcopy(get_template(template_id).style)


def _template_style_summaries(styles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_primary_template_style(style) for style in styles]


def _primary_template_style(style: Mapping[str, Any]) -> dict[str, Any]:
    constraints = style.get("style_constraints")
    if not isinstance(constraints, Mapping):
        constraints = {}
    summary = {
        "template_id": style.get("template_id"),
        "venue": style.get("venue"),
        "format_family": style.get("format_family"),
        "section_order": style.get("section_order", []),
        "required_sections": style.get("required_sections", []),
    }
    max_references = constraints.get("max_references")
    if max_references is not None:
        summary["max_refs"] = max_references
    return summary


def _load_prompt_template() -> str:
    prompt_ref = resources.files("pathlab_paper_agent") / "prompts" / "outline_v1.txt"
    return Path(str(prompt_ref)).read_text(encoding="utf-8")
