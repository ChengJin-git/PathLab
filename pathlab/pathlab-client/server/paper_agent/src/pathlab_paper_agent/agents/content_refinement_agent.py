"""Content Refinement Agent derived from PaperOrchestra Appendix F.5."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from . import _common  # noqa: E402
from ..evidence.phi import PhiScrubber  # noqa: E402
from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient  # noqa: E402
from ..process_logging import (  # noqa: E402
    EventSink,
    elapsed_ms,
    emit_event,
    emit_llm_failure,
    emit_llm_request,
    emit_llm_response,
    now_counter,
)
from ..renderers.citation_renderer import (  # noqa: E402
    CitationRenderError,
    extract_citation_placeholders,
    render_citation_placeholders,
)
from ..validators.citation_guard import parse_cites  # noqa: E402
from ..validators.metric_guard import (  # noqa: E402
    load_evidence_lock,
    metric_entries,
    render_metric_placeholders,
)

RUBRIC_DIMENSIONS = (
    "medical_accuracy",
    "statistical_rigor",
    "clinical_relevance",
    "technical_novelty",
    "presentation",
)
_CRITIC_PROMPT_NAME = "refinement_critic_v1.txt"
_REVISE_PROMPT_NAME = "refinement_revise_v1.txt"
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_RAW_CITE_RE = re.compile(r"\\cite\w*(?:\[[^\]]*\])*\{([^}]+)\}")
_METRIC_PLACEHOLDER_RE = re.compile(r"\{\{\s*m:([A-Za-z0-9_.:-]+)\s*\}\}")
_METRIC_LIKE_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:p\s*[<=>]\s*)?(?:0?\.\d+|\d+\.\d+|\d+(?:\.\d+)?%)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
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
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
}


class ContentRefinementAgentError(RuntimeError):
    """Raised when refinement output violates PathLab contracts."""


@dataclass(frozen=True)
class CriticReview:
    """Structured PathLab tuned critic review."""

    scores: dict[str, int]
    reasons: dict[str, str]
    overall_reason: str = ""
    reported_overall: int | None = None
    revise_sections: tuple[str, ...] = ()
    actionable_feedback: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.scores.get(dimension, 0) for dimension in RUBRIC_DIMENSIONS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": {dimension: self.scores.get(dimension, 0) for dimension in RUBRIC_DIMENSIONS},
            "reasons": {dimension: self.reasons.get(dimension, "") for dimension in RUBRIC_DIMENSIONS},
            "total": self.total,
            "reported_overall": self.reported_overall,
            "overall_reason": self.overall_reason,
            "revise_sections": list(self.revise_sections),
            "actionable_feedback": list(self.actionable_feedback),
        }


@dataclass(frozen=True)
class RevisionResult:
    """Rendered section updates returned by the revise call."""

    sections: dict[str, str]
    raw_sections: dict[str, str]
    worklog: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_sections": sorted(self.sections),
            "raw_changed_sections": sorted(self.raw_sections),
            "worklog": self.worklog,
        }


@dataclass(frozen=True)
class RefinementInputs:
    """Inputs consumed by one refinement iteration."""

    sections: dict[str, str]
    evidence_lock: dict[str, Any]
    selected_refs: tuple[dict[str, Any], ...]
    required_cites: tuple[dict[str, Any], ...]
    validation_reports: tuple[dict[str, Any], ...] = ()
    outline: dict[str, Any] = field(default_factory=dict)
    figures_manifest: dict[str, Any] = field(default_factory=dict)
    experimental_log: str = ""
    private_source_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    private_identifiers: tuple[str, ...] = field(default_factory=tuple, repr=False)
    iteration: int = 1

    @classmethod
    def from_paths(
        cls,
        paths: PaperRunPaths,
        *,
        sections: Mapping[str, str] | None = None,
        validation_reports: Sequence[Mapping[str, Any]] = (),
        iteration: int = 1,
    ) -> "RefinementInputs":
        evidence_lock = load_evidence_lock(paths)
        config = _read_json_object_or_default(paths.config, {})
        return cls(
            sections=dict(sections) if sections is not None else _read_sections(paths),
            evidence_lock=evidence_lock,
            selected_refs=tuple(_load_reference_items(paths.citations_dir / "selected_refs.json")),
            required_cites=tuple(_load_reference_items(paths.citations_dir / "required_cites.json")),
            validation_reports=tuple(dict(report) for report in validation_reports),
            outline=_read_json_object_or_default(paths.outline_json, {}),
            figures_manifest=_read_json_object_or_default(paths.figures_manifest, {"figures": []}),
            experimental_log=_read_text_or_default(paths.experimental_log, ""),
            private_source_ids=tuple(_private_source_ids_from_config_and_lock(config, evidence_lock)),
            private_identifiers=tuple(_private_identifiers_from_lock(evidence_lock)),
            iteration=iteration,
        )


class ContentRefinementAgent:
    """Run critic and revision LLM calls for one M11 refinement iteration."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        critic_prompt_template: str | None = None,
        revise_prompt_template: str | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.llm_client = llm_client or _default_llm_client()
        self.critic_prompt_template = critic_prompt_template or _load_prompt_template(_CRITIC_PROMPT_NAME)
        self.revise_prompt_template = revise_prompt_template or _load_prompt_template(_REVISE_PROMPT_NAME)
        self.event_sink = event_sink

    def critique(self, inputs: RefinementInputs) -> CriticReview:
        self._emit(
            "critique_start",
            iteration=inputs.iteration,
            section_count=len(inputs.sections),
            validation_report_count=len(inputs.validation_reports),
        )
        try:
            prompt = self.build_critic_prompt(inputs)
            self._emit("critic_prompt_built", iteration=inputs.iteration, prompt_length=len(prompt))
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Content Refinement critic. Return only JSON with the five rubric scores."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]
            response_format = {"type": "json_object"}
            emit_llm_request(
                self.event_sink,
                "refinement_critic",
                messages=messages,
                temperature=0.2,
                response_format=response_format,
            )
            started = now_counter()
            try:
                response = self.llm_client.complete(
                    messages,
                    temperature=0.2,
                    response_format=response_format,
                )
            except Exception as exc:
                emit_llm_failure(self.event_sink, "refinement_critic", started=started, error=exc)
                raise
            emit_llm_response(
                self.event_sink,
                "refinement_critic",
                response,
                duration_ms=elapsed_ms(started),
            )
            review = parse_critic_review(_response_text(response))
        except Exception as exc:
            self._emit(
                "critique_failed",
                iteration=inputs.iteration,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        self._emit(
            "critique_completed",
            iteration=inputs.iteration,
            total=review.total,
            revise_sections=list(review.revise_sections),
        )
        return review

    def revise(self, inputs: RefinementInputs, review: CriticReview) -> RevisionResult:
        self._emit(
            "revise_start",
            iteration=inputs.iteration,
            requested_sections=list(review.revise_sections),
        )
        try:
            prompt = self.build_revise_prompt(inputs, review)
            self._emit("revise_prompt_built", iteration=inputs.iteration, prompt_length=len(prompt))
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Content Refinement reviser. Return only JSON section updates. "
                        "Use [CITE:key] and {{m:key}} placeholders in changed sections."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]
            response_format = {"type": "json_object"}
            emit_llm_request(
                self.event_sink,
                "refinement_revise",
                messages=messages,
                temperature=0.25,
                response_format=response_format,
            )
            started = now_counter()
            try:
                response = self.llm_client.complete(
                    messages,
                    temperature=0.25,
                    response_format=response_format,
                )
            except Exception as exc:
                emit_llm_failure(self.event_sink, "refinement_revise", started=started, error=exc)
                raise
            emit_llm_response(
                self.event_sink,
                "refinement_revise",
                response,
                duration_ms=elapsed_ms(started),
            )
            raw_sections, worklog = parse_revision_json(_response_text(response))
            rendered = render_revised_sections(raw_sections, inputs)
        except Exception as exc:
            self._emit(
                "revise_failed",
                iteration=inputs.iteration,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        result = RevisionResult(sections=rendered, raw_sections=raw_sections, worklog=worklog)
        self._emit(
            "revise_completed",
            iteration=inputs.iteration,
            changed_sections=sorted(result.sections),
            raw_changed_sections=sorted(result.raw_sections),
        )
        return result

    def build_critic_prompt(self, inputs: RefinementInputs) -> str:
        payload = _safe_prompt_payload(_base_payload(inputs), inputs, context="refinement critic prompt payload")
        payload["task_kind"] = "critic"
        return self.critic_prompt_template.replace("{{INPUT_PAYLOAD_JSON}}", _json_dumps(payload))

    def build_revise_prompt(self, inputs: RefinementInputs, review: CriticReview) -> str:
        payload = _safe_prompt_payload(_base_payload(inputs), inputs, context="refinement revise prompt payload")
        payload["task_kind"] = "revise"
        payload["critic_review"] = review.to_dict()
        _assert_no_private_source_identifiers(
            payload,
            inputs.private_source_ids,
            context="refinement revise prompt payload",
        )
        _assert_no_private_identifiers(payload, context="refinement revise prompt payload")
        _assert_no_known_private_identifiers(
            payload,
            inputs.private_identifiers,
            context="refinement revise prompt payload",
        )
        return self.revise_prompt_template.replace("{{INPUT_PAYLOAD_JSON}}", _json_dumps(payload))

    def _emit(self, event: str, **payload: Any) -> None:
        emit_event(self.event_sink, event, **payload)


class _NoNetworkContentRefinementLLMClient:
    """CI safeguard so refinement tests never call a real provider."""

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
        if payload.get("task_kind") == "revise":
            content: dict[str, Any] = {
                "worklog": {"actions_taken": ["No-network fixture left sections unchanged."]},
                "sections": {},
            }
        else:
            content = {
                "rubric": {
                    dimension: {"score": 3, "reason": "No-network fixture review."}
                    for dimension in RUBRIC_DIMENSIONS
                },
                "overall": {"score": 15, "reason": "No-network fixture overall."},
                "revise_sections": [],
                "actionable_feedback": [],
            }
        return LLMResponse(
            content=json.dumps(content),
            model="no-network-refinement-fixture",
            provider="ci_no_network",
        )


def parse_critic_review(text: str) -> CriticReview:
    payload = _parse_json_object(text, error_label="critic review")
    rubric = payload.get("rubric") if isinstance(payload.get("rubric"), Mapping) else payload
    scores: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for dimension in RUBRIC_DIMENSIONS:
        raw_item = rubric.get(dimension) if isinstance(rubric, Mapping) else None
        if isinstance(raw_item, Mapping):
            score = raw_item.get("score")
            reason = raw_item.get("reason") or raw_item.get("rationale") or ""
        else:
            score = raw_item if raw_item is not None else payload.get(dimension)
            reason = ""
        scores[dimension] = _score_int(score)
        reasons[dimension] = _one_line(reason)
    reported_overall, overall_reason = _overall(payload.get("overall"))
    revise_sections = tuple(
        slug
        for item in _as_string_list(payload.get("revise_sections") or payload.get("sections_to_revise"))
        if (slug := section_slug(item))
    )
    actionable = tuple(_as_string_list(payload.get("actionable_feedback") or payload.get("feedback") or []))
    return CriticReview(
        scores=scores,
        reasons=reasons,
        overall_reason=overall_reason,
        reported_overall=reported_overall,
        revise_sections=revise_sections,
        actionable_feedback=actionable,
        raw=dict(payload),
    )


def parse_revision_json(text: str) -> tuple[dict[str, str], dict[str, Any]]:
    payload = _parse_json_object(text, error_label="revision")
    raw_sections = payload.get("sections", {})
    if isinstance(raw_sections, list):
        sections = _sections_from_list(raw_sections)
    elif isinstance(raw_sections, Mapping):
        sections = _sections_from_mapping(raw_sections)
    elif raw_sections in (None, ""):
        sections = {}
    else:
        raise ContentRefinementAgentError("Revision response `sections` must be an object, list, or empty")
    worklog = payload.get("worklog") if isinstance(payload.get("worklog"), Mapping) else {}
    return sections, dict(worklog)


def render_revised_sections(sections: Mapping[str, str], inputs: RefinementInputs) -> dict[str, str]:
    allowed_keys = _ref_keys(inputs.selected_refs)
    metric_keys = set(metric_entries(inputs.evidence_lock))
    _assert_no_private_identifiers(sections, context="refinement output")
    _assert_no_known_private_identifiers(sections, inputs.private_identifiers, context="refinement output")
    _assert_no_private_source_identifiers(sections, inputs.private_source_ids, context="refinement output")
    _assert_no_private_source_placeholders(sections, context="refinement output")
    rendered: dict[str, str] = {}
    for slug, text in sections.items():
        if slug not in inputs.sections:
            raise ContentRefinementAgentError(
                f"Revised section {slug} is not an existing draft section; refinement must return changed sections only"
            )
        _assert_structural_contract(slug, inputs.sections[slug], text)
        _assert_revision_contract(slug, text, allowed_keys, metric_keys)
        try:
            with_citations = render_citation_placeholders(text, allowed_keys)
        except CitationRenderError as exc:
            raise ContentRefinementAgentError(str(exc)) from exc
        try:
            with_metrics = render_metric_placeholders(with_citations, inputs.evidence_lock)
        except KeyError as exc:
            key = exc.args[0] if exc.args else "unknown"
            raise ContentRefinementAgentError(
                f"Metric placeholder {key!r} is not present in evidence_lock.private.json"
            ) from exc
        rendered[slug] = _ensure_trailing_newline(with_metrics)
    _assert_no_private_source_identifiers(rendered, inputs.private_source_ids, context="rendered refinement output")
    _assert_no_private_source_placeholders(rendered, context="rendered refinement output")
    _assert_no_known_private_identifiers(rendered, inputs.private_identifiers, context="rendered refinement output")
    return rendered


def section_slug(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    raw = re.sub(r"^\\(?:sub)*section\*?\{", "", raw).rstrip("}")
    lowered = raw.casefold().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if not lowered:
        return None
    return _SECTION_ALIASES.get(lowered, lowered)


def parse_final_cite_keys(sections: Mapping[str, str]) -> set[str]:
    return parse_cites("\n".join(sections.values()))


def _assert_revision_contract(slug: str, text: str, allowed_keys: set[str], metric_keys: set[str]) -> None:
    if _RAW_CITE_RE.search(text):
        raise ContentRefinementAgentError(
            f"Revised section {slug} contains raw \\cite{{}}; use [CITE:paperId] before rendering"
        )
    citation_placeholders = extract_citation_placeholders(text)
    unknown_cites = citation_placeholders - allowed_keys
    if unknown_cites:
        raise ContentRefinementAgentError(
            "Citation key(s) outside selected_refs.json: " + ", ".join(sorted(unknown_cites))
        )
    metric_placeholders = set(_METRIC_PLACEHOLDER_RE.findall(text))
    unknown_metrics = metric_placeholders - metric_keys
    if unknown_metrics:
        raise ContentRefinementAgentError(
            "Metric placeholder(s) missing from evidence_lock.private.json: " + ", ".join(sorted(unknown_metrics))
        )
    stripped = _METRIC_PLACEHOLDER_RE.sub("", _INCLUDEGRAPHICS_RE.sub("", text))
    match = _METRIC_LIKE_NUMBER_RE.search(stripped)
    if match:
        raise ContentRefinementAgentError(
            f"Revised section {slug} contains raw metric-like value {match.group(0)!r}; use {{{{m:metric_key}}}}"
        )


def _base_payload(inputs: RefinementInputs) -> dict[str, Any]:
    selected_keys = sorted(_ref_keys(inputs.selected_refs))
    required_keys = sorted(_ref_keys(inputs.required_cites))
    return {
        "iteration": inputs.iteration,
        "sections": inputs.sections,
        "validation_reports": list(inputs.validation_reports),
        "outline": inputs.outline,
        "figures_manifest": inputs.figures_manifest,
        "experimental_log_md": inputs.experimental_log,
        "citation_contract": {
            "allowed_cite_keys": selected_keys,
            "required_cite_keys": required_keys,
            "placeholder_syntax": "[CITE:paperId]",
        },
        "metric_contract": {
            "allowed_metric_keys": sorted(metric_entries(inputs.evidence_lock)),
            "placeholder_syntax": "{{m:metric_key}}",
        },
        "pathlab_constraints": {
            "max_iterations": 3,
            "do_not_request_new_experiments": True,
            "do_not_modify_locked_blocks": True,
            "changed_sections_only": True,
        },
    }


def _safe_prompt_payload(payload: Mapping[str, Any], inputs: RefinementInputs, *, context: str) -> dict[str, Any]:
    safe_payload = _redact_private_source_identifiers(dict(payload), inputs.private_source_ids)
    _assert_no_private_source_identifiers(safe_payload, inputs.private_source_ids, context=context)
    _assert_no_private_identifiers(safe_payload, context=context)
    _assert_no_known_private_identifiers(safe_payload, inputs.private_identifiers, context=context)
    return safe_payload


def _assert_structural_contract(slug: str, original: str, revised: str) -> None:
    checks = (
        ("locked block input(s)", _prefixed_inputs(original, "locked_blocks/"), _prefixed_inputs(revised, "locked_blocks/")),
        ("table input(s)", _prefixed_inputs(original, "tables/"), _prefixed_inputs(revised, "tables/")),
        ("figure graphic(s)", _graphics(original), _graphics(revised)),
        ("figure/table label(s)", _figure_table_labels(original), _figure_table_labels(revised)),
    )
    for label, before, after in checks:
        if before == after:
            continue
        missing = before - after
        added = after - before
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if added:
            details.append("added " + ", ".join(sorted(added)))
        raise ContentRefinementAgentError(
            f"Revised section {slug} modifies {label}; refinement may only change narrative text ({'; '.join(details)})"
        )


def _prefixed_inputs(text: str, prefix: str) -> set[str]:
    paths: set[str] = set()
    for match in _INPUT_RE.finditer(text):
        normalized = _normalize_asset_path(match.group(1))
        if not normalized.startswith(prefix):
            continue
        if not Path(normalized).suffix:
            normalized = f"{normalized}.tex"
        paths.add(normalized)
    return paths


def _graphics(text: str) -> set[str]:
    return {_normalize_asset_path(match.group(1)) for match in _INCLUDEGRAPHICS_RE.finditer(text)}


def _figure_table_labels(text: str) -> set[str]:
    labels: set[str] = set()
    for match in _LABEL_RE.finditer(text):
        label = match.group(1).strip()
        if re.match(r"^(?:fig|figure|tab|tbl|table):", label, re.IGNORECASE):
            labels.add(label)
    return labels


def _normalize_asset_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _sections_from_mapping(raw_sections: Mapping[str, Any]) -> dict[str, str]:
    sections: dict[str, str] = {}
    for key, value in raw_sections.items():
        slug = section_slug(str(key))
        if slug is None:
            continue
        if isinstance(value, Mapping):
            value = value.get("latex") or value.get("tex") or value.get("content") or value.get("text")
        if not isinstance(value, str):
            raise ContentRefinementAgentError(f"Revision for section {key!r} must be a string")
        if value.strip():
            sections[slug] = value
    return sections


def _sections_from_list(items: Sequence[Any]) -> dict[str, str]:
    sections: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("section") or item.get("slug") or item.get("name")
        slug = section_slug(str(name)) if name is not None else None
        if slug is None:
            continue
        value = item.get("latex") or item.get("tex") or item.get("content") or item.get("text")
        if not isinstance(value, str):
            raise ContentRefinementAgentError(f"Revision for section {name!r} must be a string")
        if value.strip():
            sections[slug] = value
    return sections


def _parse_json_object(text: str, *, error_label: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ContentRefinementAgentError(f"Empty {error_label} response")
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = _decode_first_json_object(stripped)
    if not isinstance(value, dict):
        raise ContentRefinementAgentError(f"{error_label.title()} response must be a JSON object")
    return value


def _decode_first_json_object(text: str) -> Any:
    value = _common.decode_first_json_object(text)
    if value is None:
        raise ContentRefinementAgentError("LLM response did not contain a JSON object")
    return value


def _score_int(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(5, number))


def _overall(value: Any) -> tuple[int | None, str]:
    if isinstance(value, Mapping):
        score = value.get("score")
        reason = _one_line(value.get("reason") or value.get("rationale") or "")
    else:
        score = value
        reason = ""
    try:
        parsed = int(round(float(score)))
    except (TypeError, ValueError):
        parsed = None
    return parsed, reason


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item).strip()]
    return []


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())[:500]


def _read_sections(paths: PaperRunPaths) -> dict[str, str]:
    if not paths.sections_dir.exists():
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(paths.sections_dir.glob("*.tex"))
        if path.is_file()
    }


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


def _read_json_object_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else dict(default)


def _read_text_or_default(path: Path, default: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return default


_response_text = _common.response_text
_payload_from_prompt = _common.payload_from_prompt


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"


def _private_source_ids_from_config_and_lock(config: Mapping[str, Any], evidence_lock: Mapping[str, Any]) -> list[str]:
    identifiers: set[str] = set()
    source_tasks = config.get("source_tasks", [])
    for source_task in source_tasks or []:
        if isinstance(source_task, Mapping):
            _add_private_source_id(identifiers, source_task.get("task_id"))
    _collect_private_source_ids(evidence_lock, identifiers)
    return sorted(identifiers)


def _private_identifiers_from_lock(evidence_lock: Mapping[str, Any]) -> list[str]:
    identifiers: set[str] = set()

    def add_value(value: Any) -> None:
        if isinstance(value, str) and len(value.strip()) >= 3:
            identifiers.add(value.strip())
        elif isinstance(value, Mapping):
            for key, item in value.items():
                add_value(key)
                add_value(item)
        elif isinstance(value, list | tuple | set):
            for item in value:
                add_value(item)

    for key in (
        "phi_mapping",
        "private_identifiers",
        "raw_identifiers",
        "case_ids",
        "patient_ids",
        "institution_names",
        "raw_paths",
    ):
        if key in evidence_lock:
            add_value(evidence_lock[key])
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
        raise ContentRefinementAgentError(f"Private source identifier(s) detected in {context}: {examples}")


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
        raise ContentRefinementAgentError(f"Private source placeholder(s) leaked into {context}: {examples}")


def _assert_no_known_private_identifiers(value: Any, identifiers: Sequence[str], *, context: str) -> None:
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
        raise ContentRefinementAgentError(f"Private identifier(s) detected in {context}: {examples}")


def _assert_no_private_identifiers(value: Any, *, context: str) -> None:
    scrubber = PhiScrubber()
    scrubber.observe(value)
    identifiers = scrubber.private_identifiers()
    extra_paths = _extra_private_paths(value)
    if extra_paths:
        identifiers["raw_paths"] = sorted(set([*identifiers.get("raw_paths", []), *extra_paths]))
    leaked = {key: identifiers.get(key, []) for key in _PHI_HARD_FAIL_KEYS if identifiers.get(key)}
    if leaked:
        counts = ", ".join(f"{key}={len(items)}" for key, items in sorted(leaked.items()))
        raise ContentRefinementAgentError(f"PHI/private identifiers detected in {context}: {counts}")


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


def _load_prompt_template(filename: str) -> str:
    prompt_ref = resources.files("pathlab_paper_agent") / "prompts" / filename
    return Path(str(prompt_ref)).read_text(encoding="utf-8")


def _default_llm_client() -> LLMClient:
    if _ci_should_disable_network_llm():
        return _NoNetworkContentRefinementLLMClient()
    return OpenAICompatibleLLMClient()


_ci_should_disable_network_llm = _common.ci_should_disable_network_llm
