"""Plotting Agent orchestration layer for empirical and conceptual figures."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from . import _common  # noqa: E402
from ..evidence.phi import PhiScrubber  # noqa: E402
from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient  # noqa: E402
from ..plotting import generate_figure  # noqa: E402
from ..plotting.types import FigureOutput  # noqa: E402
from ..plotting.utils import slugify  # noqa: E402

_DEFAULT_PLAN = [
    {
        "figure_id": "fig:overview",
        "kind": "conceptual",
        "source": "scaffold",
        "design_objective": "show the PathLab WSI-to-prediction workflow",
        "backend": "user_revision",
    }
]
_PROMPT_NAME = "plotting_caption_v1.txt"
_PATHLIKE_RE = re.compile(
    r"(?:[A-Za-z]:\\|\\\\|/(?:Users|home|private|var|tmp|mnt|data|scratch|nfs|Volumes|workspace))"
)
_FIGURE_PREFIX_RE = re.compile(r"^\s*(?:Figure|Fig\.)\s*\d+[A-Za-z]?\s*[:.-]\s*", re.IGNORECASE)
_SAFE_FIGURE_ID_RE = re.compile(r"[^A-Za-z0-9:_-]+")
_PRIVATE_PLACEHOLDER_RE = re.compile(r"PRIVATE_(?:PATH|CASE|INSTITUTION|DATE)_\d+")
_PLOT_DATA_PREFIXES = (
    "evidence/plot_data/",
    "evidence/raw_collected/",
)
_CHART_SOURCE_PREFIXES = (
    "figures/source_charts/",
    "figures/raw/",
)
_PUBLIC_FIGURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf"}


class PlottingAgentError(RuntimeError):
    """Raised when the Plotting Agent cannot create a valid manifest."""


@dataclass(frozen=True)
class PlottingAgentResult:
    """Result returned by the Plotting Agent stage adapter."""

    figures_manifest: dict[str, Any]
    generated_figures: tuple[FigureOutput, ...]
    errors: tuple[str, ...] = ()


class PlottingAgent:
    """Dispatch outline plotting-plan items to M6a generators and caption LLM calls."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_client = llm_client or _default_llm_client()
        self.prompt_template = prompt_template or _load_prompt_template()

    def generate(self, paths: PaperRunPaths) -> PlottingAgentResult:
        """Generate figures and return the final public figures manifest."""
        plan = _load_plotting_plan(paths)
        entries: list[dict[str, Any]] = []
        generated: list[FigureOutput] = []
        errors: list[str] = []
        seen_figure_ids: set[str] = set()
        seen_figure_slugs: set[str] = set()
        for index, raw_item in enumerate(plan):
            spec = _normalize_plan_item(raw_item, index)
            spec["figure_id"] = _unique_figure_id(
                str(spec["figure_id"]),
                seen_figure_ids,
                seen_figure_slugs,
            )
            try:
                entry, output = self._dispatch_one(paths, spec)
            except Exception as exc:
                if not _is_deterministic_plot(spec):
                    raise
                entry = _pending_generation_entry(spec, exc)
                output = None
                errors.append(f"{spec['figure_id']}: {_safe_error_message(exc)}")
            entry["caption"] = self.caption_figure(spec, entry)
            entry = _public_manifest_entry(paths, entry)
            entries.append(entry)
            if output is not None:
                generated.append(output)

        return PlottingAgentResult(
            figures_manifest={"figures": entries},
            generated_figures=tuple(generated),
            errors=tuple(errors),
        )

    def caption_figure(self, spec: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
        """Call the caption LLM once for a figure and normalize the short response."""
        payload = _caption_payload(spec, entry)
        prompt = self.build_caption_prompt(payload)
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You write short, factual captions for PathLab paper figures. "
                        "Never invent metrics or private identifiers."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.1,
        )
        raw_content = response.content if isinstance(response, LLMResponse) else getattr(response, "content", response)
        return _normalize_caption(raw_content, fallback=_fallback_caption(spec, entry))

    def build_caption_prompt(self, payload: Mapping[str, Any]) -> str:
        payload_json = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        return self.prompt_template.replace("{{INPUT_PAYLOAD_JSON}}", payload_json)

    def _dispatch_one(
        self,
        paths: PaperRunPaths,
        spec: Mapping[str, Any],
    ) -> tuple[dict[str, Any], FigureOutput | None]:
        backend = _backend(spec)
        if _is_deterministic_plot(spec):
            evidence_spec = _materialize_evidence_backed_spec(paths, spec)
            output = generate_figure(paths.figures_dir, evidence_spec)
            entry = output.to_manifest_entry()
            entry["source"] = _manifest_source(evidence_spec)
            entry["kind"] = str(spec.get("kind", "empirical"))
            entry["backend"] = backend or "deterministic_plotting"
            return entry, output
        if backend == "user_revision":
            return _user_revision_entry(spec), None
        if backend == "paperbanana":
            return _paperbanana_fallback_entry(spec), None
        if str(spec.get("kind", "")).lower() == "conceptual":
            return _paperbanana_fallback_entry({**spec, "backend": "paperbanana"}), None
        return _user_revision_entry(spec), None


def _load_plotting_plan(paths: PaperRunPaths) -> list[dict[str, Any]]:
    if not paths.outline_json.exists():
        return list(_DEFAULT_PLAN)
    try:
        outline = json.loads(paths.outline_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlottingAgentError(f"drafts/outline.json is not valid JSON: {exc}") from exc
    if not isinstance(outline, dict):
        raise PlottingAgentError("drafts/outline.json must contain a JSON object")
    plan = outline.get("plotting_plan")
    if not isinstance(plan, list) or not plan:
        return list(_DEFAULT_PLAN)
    items = [item for item in plan if isinstance(item, dict)]
    return items or list(_DEFAULT_PLAN)


def _normalize_plan_item(raw_item: Mapping[str, Any], index: int) -> dict[str, Any]:
    item = dict(raw_item)
    item["figure_id"] = _safe_figure_id(item.get("figure_id"), fallback=f"fig:auto_{index + 1}")
    item.setdefault("kind", "empirical" if _has_generator(item) else "conceptual")
    item.setdefault("source", "outline.plotting_plan")
    item.setdefault("design_objective", "render the planned paper figure")
    if "plot_spec" not in item or not isinstance(item.get("plot_spec"), dict):
        item["plot_spec"] = {}
    return item


def _backend(spec: Mapping[str, Any]) -> str:
    return str(spec.get("backend") or "").strip().lower()


def _has_generator(spec: Mapping[str, Any]) -> bool:
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), Mapping) else {}
    return bool(
        spec.get("generator")
        or spec.get("plot_type")
        or plot_spec.get("generator")
        or plot_spec.get("plot_type")
        or plot_spec.get("kind")
    )


def _is_deterministic_plot(spec: Mapping[str, Any]) -> bool:
    backend = _backend(spec)
    if backend == "deterministic_plotting":
        return True
    if backend in {"paperbanana", "user_revision"}:
        return False
    return str(spec.get("kind", "")).lower() == "empirical" and _has_generator(spec)


def _paperbanana_fallback_entry(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "figure_id": str(spec.get("figure_id", "fig:overview")),
        "path": spec.get("path"),
        "status": "requires_user_revision",
        "source": _manifest_source(spec),
        "generator": "paperbanana",
        "kind": str(spec.get("kind", "conceptual")),
        "backend": "paperbanana",
    }


def _user_revision_entry(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "figure_id": str(spec.get("figure_id", "fig:user_revision")),
        "path": spec.get("path"),
        "status": "user_provided",
        "source": _manifest_source(spec),
        "generator": str(spec.get("generator") or "user_revision"),
        "kind": str(spec.get("kind", "conceptual")),
        "backend": "user_revision",
    }


def _pending_generation_entry(spec: Mapping[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "figure_id": str(spec.get("figure_id", "fig:empirical_pending")),
        "path": None,
        "status": "pending_generation",
        "source": _manifest_source(spec),
        "generator": _generator_name(spec),
        "kind": str(spec.get("kind", "empirical")),
        "backend": _backend(spec) or "deterministic_plotting",
        "error": _safe_error_message(error),
    }


def _generator_name(spec: Mapping[str, Any]) -> str:
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), Mapping) else {}
    return str(
        spec.get("generator")
        or spec.get("plot_type")
        or plot_spec.get("generator")
        or plot_spec.get("plot_type")
        or plot_spec.get("kind")
        or "unknown"
    )


def _manifest_source(spec: Mapping[str, Any]) -> str:
    source = spec.get("source") or "outline.plotting_plan"
    if _contains_pathlike(source):
        return "evidence_artifact"
    return _scrub_manifest_text(source)


def _caption_payload(spec: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "figure_id": _safe_caption_value(entry.get("figure_id") or spec.get("figure_id")),
        "kind": _safe_caption_value(entry.get("kind") or spec.get("kind", "figure")),
        "status": _safe_caption_value(entry.get("status", "planned")),
        "source": _safe_caption_value(entry.get("source") or spec.get("source")),
        "generator": _safe_caption_value(entry.get("generator") or _generator_name(spec)),
        "design_objective": _safe_caption_value(spec.get("design_objective", "")),
        "plot_spec_summary": _plot_spec_summary(spec),
    }


def _plot_spec_summary(spec: Mapping[str, Any]) -> dict[str, Any]:
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), Mapping) else {}
    data = plot_spec.get("data") if isinstance(plot_spec.get("data"), Mapping) else spec.get("data")
    summary: dict[str, Any] = {
        "generator": _generator_name(spec),
        "title": _safe_caption_value(spec.get("title") or plot_spec.get("title")),
    }
    if isinstance(data, Mapping):
        summary["evidence_fields"] = sorted(str(key) for key in data.keys())[:8]
    return {
        key: value
        for key, value in summary.items()
        if value is not None and value != "" and value != "unknown"
    }


def _safe_caption_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if _contains_pathlike(text):
        return "evidence artifact"
    return _scrub_manifest_text(text)[:500]


def _contains_pathlike(value: Any) -> bool:
    return isinstance(value, str) and bool(_PATHLIKE_RE.search(value))


def _normalize_caption(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = lines[0] if lines else text
    text = text.strip('"\'` ')
    text = re.sub(r"^caption\s*[:.-]\s*", "", text, flags=re.IGNORECASE).strip()
    text = _FIGURE_PREFIX_RE.sub("", text).strip()
    text = _scrub_manifest_text(text)
    if len(text) > 320:
        text = text[:317].rstrip() + "..."
    return text or fallback


def _scrub_public_text(value: Any) -> str:
    text = "" if value is None else str(value)
    scrubber = PhiScrubber()
    scrubber.observe(text)
    return scrubber.scrub_text(text)


def _scrub_manifest_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _PATHLIKE_RE.sub("[private path]", text)
    scrubbed = _scrub_public_text(text)
    return _PRIVATE_PLACEHOLDER_RE.sub("[private identifier]", scrubbed)


def _safe_error_message(error: Exception) -> str:
    return _scrub_manifest_text(error)[:1000]


def _safe_figure_id(value: Any, *, fallback: str) -> str:
    raw = "" if value is None else str(value).strip()
    if _contains_pathlike(raw):
        return fallback
    scrubbed = _scrub_public_text(raw)
    if _PRIVATE_PLACEHOLDER_RE.search(scrubbed):
        return fallback
    cleaned = _SAFE_FIGURE_ID_RE.sub("_", scrubbed).strip("_:-")
    return cleaned or fallback


def _unique_figure_id(figure_id: str, seen_ids: set[str], seen_slugs: set[str]) -> str:
    if figure_id not in seen_ids and slugify(figure_id) not in seen_slugs:
        seen_ids.add(figure_id)
        seen_slugs.add(slugify(figure_id))
        return figure_id
    suffix = 2
    while f"{figure_id}_{suffix}" in seen_ids or slugify(f"{figure_id}_{suffix}") in seen_slugs:
        suffix += 1
    unique = f"{figure_id}_{suffix}"
    seen_ids.add(unique)
    seen_slugs.add(slugify(unique))
    return unique


def _public_manifest_entry(paths: PaperRunPaths, entry: Mapping[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in entry.items():
        if key == "path":
            public[key] = _safe_manifest_figure_path(paths, value)
        elif isinstance(value, str):
            public[key] = _scrub_manifest_text(value)
        else:
            public[key] = value
    return public


def _safe_manifest_figure_path(paths: PaperRunPaths, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        rel_path = _safe_run_relative_path(
            paths,
            value.strip(),
            allowed_prefixes=("figures/",),
            must_exist=False,
        )
    except PlottingAgentError:
        return None
    if Path(rel_path).suffix.lower() not in _PUBLIC_FIGURE_SUFFIXES:
        return None
    return rel_path


def _safe_run_relative_path(
    paths: PaperRunPaths,
    value: Any,
    *,
    allowed_prefixes: tuple[str, ...],
    must_exist: bool,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlottingAgentError("expected a relative paper-run path")
    raw = value.strip().replace("\\", "/")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise PlottingAgentError("paper-run path must be relative and stay inside the run")
    rel_text = rel.as_posix()
    if not any(rel_text.startswith(prefix) for prefix in allowed_prefixes):
        allowed = ", ".join(allowed_prefixes)
        raise PlottingAgentError(f"paper-run path must start with one of: {allowed}")
    full_path = (paths.root / rel_text).resolve()
    try:
        full_path.relative_to(paths.root.resolve())
    except ValueError as exc:
        raise PlottingAgentError("paper-run path escapes the run root") from exc
    if must_exist and not full_path.is_file():
        raise PlottingAgentError(f"paper-run path does not exist: {rel_text}")
    return rel_text


def _load_plot_data_ref(paths: PaperRunPaths, value: Any) -> tuple[str, dict[str, Any]]:
    rel_path = _safe_run_relative_path(
        paths,
        value,
        allowed_prefixes=_PLOT_DATA_PREFIXES,
        must_exist=True,
    )
    try:
        payload = json.loads((paths.root / rel_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlottingAgentError(f"plot data reference is not valid JSON: {rel_path}") from exc
    if not isinstance(payload, dict):
        raise PlottingAgentError(f"plot data reference must contain a JSON object: {rel_path}")
    return rel_path, payload


def _materialize_evidence_backed_spec(
    paths: PaperRunPaths,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    materialized = dict(spec)
    plot_spec = dict(spec.get("plot_spec")) if isinstance(spec.get("plot_spec"), Mapping) else {}
    generator = _generator_name(spec)
    data_ref = plot_spec.get("data_ref") or plot_spec.get("data_path") or spec.get("data_ref")
    has_inline_data = "data" in materialized or "data" in plot_spec

    if generator == "chart_passthrough":
        if data_ref:
            rel_path, data = _load_plot_data_ref(paths, data_ref)
            plot_spec["data"] = _materialize_chart_source_path(paths, data)
            materialized["source"] = materialized.get("source") or f"evidence:{rel_path}"
        elif has_inline_data:
            data = plot_spec.get("data") if isinstance(plot_spec.get("data"), Mapping) else materialized.get("data")
            if not isinstance(data, Mapping):
                raise PlottingAgentError("chart_passthrough inline data must be an object")
            plot_spec["data"] = _materialize_chart_source_path(paths, data)
        else:
            raw_source = plot_spec.get("source_path") or materialized.get("source_path")
            plot_spec["data"] = _materialize_chart_source_path(paths, {"source_path": raw_source})
        materialized.pop("data", None)
        materialized["plot_spec"] = plot_spec
        return materialized

    if has_inline_data:
        raise PlottingAgentError(
            "inline empirical plot data is not permitted; use plot_spec.data_ref "
            "pointing to evidence-backed plot data"
        )
    if not data_ref:
        raise PlottingAgentError(
            "deterministic plotting requires plot_spec.data_ref for evidence-backed data"
        )
    rel_path, data = _load_plot_data_ref(paths, data_ref)
    plot_spec["data"] = data
    materialized["plot_spec"] = plot_spec
    materialized["source"] = materialized.get("source") or f"evidence:{rel_path}"
    return materialized


def _materialize_chart_source_path(paths: PaperRunPaths, data: Mapping[str, Any]) -> dict[str, Any]:
    materialized = dict(data)
    raw_source = materialized.get("source_path")
    rel_path = _safe_run_relative_path(
        paths,
        raw_source,
        allowed_prefixes=_CHART_SOURCE_PREFIXES,
        must_exist=True,
    )
    materialized["source_path"] = str((paths.root / rel_path).resolve())
    return materialized


def _fallback_caption(spec: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    kind = str(entry.get("kind") or spec.get("kind") or "figure")
    generator = str(entry.get("generator") or _generator_name(spec))
    if entry.get("status") == "ready":
        return f"{kind.title()} figure generated deterministically with {generator}."
    if entry.get("status") == "requires_user_revision":
        return f"{kind.title()} figure requires user revision before manuscript submission."
    if entry.get("status") == "user_provided":
        return f"{kind.title()} figure is expected from user-provided artwork."
    return f"{kind.title()} figure is pending deterministic generation."


def _load_prompt_template() -> str:
    prompt_path = resources.files("pathlab_paper_agent") / "prompts" / _PROMPT_NAME
    return prompt_path.read_text(encoding="utf-8")


def _default_llm_client() -> LLMClient:
    if _ci_should_disable_network_llm():
        return _NoNetworkPlottingLLMClient()
    return OpenAICompatibleLLMClient()


_ci_should_disable_network_llm = _common.ci_should_disable_network_llm


class _NoNetworkPlottingLLMClient:
    """CI safeguard so plotting tests never call a real provider."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        del temperature, response_format, stream
        payload = _payload_from_caption_prompt(messages[-1].content if messages else "")
        figure_id = str(payload.get("figure_id") or "planned figure")
        kind = str(payload.get("kind") or "figure")
        generator = str(payload.get("generator") or "PathLab")
        caption = f"{kind.title()} {figure_id} generated or tracked by {generator} from locked evidence."
        return LLMResponse(
            content=caption,
            model="no-network-plotting-fixture",
            provider="ci_no_network",
        )


_payload_from_caption_prompt = _common.payload_from_prompt
