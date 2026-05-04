"""Standalone filesystem pipeline helpers for Phase 01.

The standalone agent intentionally starts with deterministic, no-LLM stages.
Each stage writes the paper-run artifact shape promised by the design doc so
Gateway, TaskWorker, and the front-end can integrate against a stable contract
while later milestones replace scaffold content with real collectors/agents.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .bootstrap import configure_uploads_dir, ensure_server_on_path

ensure_server_on_path()

from backend.database.models import utc_now  # noqa: E402
from gateway.paper_generation.pipeline import initialize_paper_run  # noqa: E402
from gateway.paper_generation.schemas import (  # noqa: E402
    CreatePaperRequest,
    PaperConfig,
    PaperManifest,
    PaperRunArtifact,
    PaperRunStage,
    PaperRunStatus,
    PaperRunSummary,
    SourceTaskRef,
)
from gateway.paper_generation.storage import PaperRunPaths, validate_paper_id  # noqa: E402

_STAGE_ORDER: tuple[PaperRunStage, ...] = (
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
    PaperRunStage.section_writing,
    PaperRunStage.validating,
    PaperRunStage.rendering,
    PaperRunStage.exporting,
)

_SECTION_ORDER = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)


# ---------------------------------------------------------------------------
# JSON / manifest helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"Cannot serialize {type(obj).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: Optional[str] = None,
    content_type: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "visibility": visibility,
        "downloadable": downloadable,
    }
    if label is not None:
        payload["label"] = label
    if content_type is not None:
        payload["content_type"] = content_type
    return payload


def _register_artifact(
    manifest: PaperManifest,
    rel_path: str,
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: Optional[str] = None,
    content_type: Optional[str] = None,
) -> None:
    manifest.artifact_index[rel_path] = _artifact(
        status=status,
        visibility=visibility,
        downloadable=downloadable,
        label=label,
        content_type=content_type,
    )


def load_manifest(paper_id: str, uploads_dir: Optional[str | Path] = None) -> PaperManifest:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    if not paths.manifest.exists():
        raise FileNotFoundError(f"manifest.json not found for {paper_id}")
    return PaperManifest.model_validate(_read_json(paths.manifest))


def save_manifest(manifest: PaperManifest, uploads_dir: Optional[str | Path] = None) -> PaperRunPaths:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(manifest.paper_id)
    manifest.updated_at = utc_now()
    _write_json(paths.manifest, manifest.model_dump(mode="json"))
    return paths


def _default_request() -> CreatePaperRequest:
    return CreatePaperRequest(
        title="PathLab Paper Dev Run",
        source_tasks=[SourceTaskRef(task_id="paper_dev_source")],
    )


async def create_dev_run(
    body: Optional[CreatePaperRequest] = None,
    *,
    paper_id: Optional[str] = None,
    uploads_dir: Optional[str | Path] = None,
) -> tuple[str, PaperRunPaths]:
    """Create a filesystem-only paper run for standalone testing."""
    configure_uploads_dir(uploads_dir)
    request = body or _default_request()
    if not request.source_tasks:
        request.source_tasks = [SourceTaskRef(task_id="paper_dev_source")]
    if paper_id is None:
        import uuid

        paper_id = f"paper_{uuid.uuid4().hex[:16]}"
    validate_paper_id(paper_id)

    config = PaperConfig(
        paper_id=paper_id,
        title=request.title,
        paper_type=request.paper_type,
        language=request.language,
        source_tasks=request.source_tasks,
        selected_templates=request.selected_templates,
        include_external_validation=request.include_external_validation,
        user_idea=request.user_idea,
    )
    paths = await initialize_paper_run(None, config)  # type: ignore[arg-type]
    return paper_id, paths


def _ensure_run_from_config(
    paper_id: str,
    config_path: Optional[str | Path],
    *,
    uploads_dir: Optional[str | Path] = None,
) -> None:
    """Bootstrap a run directory from config.json if the manifest is missing.

    Gateway creates the manifest before invoking the worker, but the CLI also
    accepts `--config` so developers can reproduce worker runs from only a
    saved config file.
    """
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    if paths.manifest.exists():
        return
    if config_path is None:
        return

    src = Path(config_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"config file not found: {src}")
    config = PaperConfig.model_validate(_read_json(src))
    if config.paper_id != paper_id:
        raise ValueError(
            f"config paper_id {config.paper_id!r} does not match CLI paper_id {paper_id!r}"
        )

    _initialize_paper_run_sync(config)


def _initialize_paper_run_sync(config: PaperConfig) -> PaperRunPaths:
    """Sync twin of Gateway's M1 initializer for CLI config replay.

    `run_stage()` is intentionally synchronous and is also called inside the
    dev FastAPI app, so it cannot depend on `asyncio.run()`.
    """
    paths = PaperRunPaths.for_paper(config.paper_id)
    paths.ensure_dirs()
    _write_json(paths.config, config.model_dump(mode="json"))
    now = utc_now()
    manifest = PaperManifest(
        paper_id=config.paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        stage_log=[
            {
                "stage": PaperRunStage.created.value,
                "ts": now.isoformat(),
                "message": "Paper run scaffold created from config.",
            }
        ],
        artifact_index={
            "config.json": _artifact(
                label="Run config",
                content_type="application/json",
            ),
            "manifest.json": _artifact(
                label="Run manifest",
                content_type="application/json",
            ),
        },
        created_at=now,
        updated_at=now,
    )
    _write_json(paths.manifest, manifest.model_dump(mode="json"))
    return paths


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _load_config(paths: PaperRunPaths) -> PaperConfig:
    if not paths.config.exists():
        raise FileNotFoundError(f"config.json not found for {paths.paper_id}")
    return PaperConfig.model_validate(_read_json(paths.config))


def _stage_collecting(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    source_tasks = [task.model_dump(mode="json") for task in config.source_tasks]
    _write_json(paths.source_tasks, source_tasks)
    _write_json(
        paths.source_analyses,
        {
            "selection": "latest",
            "note": "Deterministic scaffold; real analysis resolution lands in collector milestones.",
        },
    )
    _write_text(
        paths.idea,
        (config.user_idea or "PathLab paper-generation scaffold run.").strip() + "\n",
    )
    _register_artifact(
        manifest,
        "inputs/source_tasks.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Source task mapping",
        content_type="application/json",
    )
    _register_artifact(
        manifest,
        "inputs/source_analyses.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Source analysis mapping",
        content_type="application/json",
    )
    _register_artifact(
        manifest,
        "inputs/idea.md",
        visibility="private_backend_only",
        downloadable=False,
        label="User idea",
        content_type="text/markdown",
    )


def _source_task_lines(config: PaperConfig) -> str:
    lines = []
    for item in config.source_tasks:
        label = f" ({item.label})" if item.label else ""
        lines.append(f"- {item.task_id}: role={item.role.value}{label}")
    return "\n".join(lines) or "- No source task registered."


def _stage_building_evidence(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    template_values = [template.value for template in config.selected_templates]
    source_tasks = [task.model_dump(mode="json") for task in config.source_tasks]
    has_external_validation = any(
        task.role.value == "external_validation" for task in config.source_tasks
    )

    experimental_log = f"""# Experimental Log

## Run

- Paper ID: `{config.paper_id}`
- Title: {config.title or "Untitled PathLab paper"}
- Language: {config.language}
- Templates: {", ".join(template_values)}

## Source Tasks

{_source_task_lines(config)}

## Evidence Status

This is a deterministic standalone scaffold. It preserves the v1 artifact
layout, PHI boundary, and agent handoff contract. Real PathLab DB metrics,
cohort counts, model configuration, and analysis provenance are added by the
collector and evidence milestones.

## PHI Policy

Only scrubbed identifiers may appear in LLM-facing artifacts. Private source
paths and identifier mappings stay in `evidence_lock.private.json`.
"""
    _write_text(paths.experimental_log, experimental_log)

    private_lock = {
        "paper_id": config.paper_id,
        "source_tasks": source_tasks,
        "selected_templates": template_values,
        "has_external_validation": has_external_validation,
        "has_baseline": any(task.role.value == "baseline" for task in config.source_tasks),
        "has_statistical_test": False,
        "metrics": {},
        "phi_mapping": {},
        "provenance": {
            "mode": "standalone_scaffold",
            "note": "No raw PathLab DB artifacts were read in this deterministic phase.",
        },
    }
    public_evidence = {
        "paper_id": config.paper_id,
        "title": config.title,
        "source_task_count": len(config.source_tasks),
        "selected_templates": template_values,
        "has_external_validation": has_external_validation,
        "phi_scrubbed": True,
        "metrics": [],
        "provenance_mode": "standalone_scaffold",
    }
    _write_json(paths.evidence_lock_private, private_lock)
    _write_json(paths.evidence_public, public_evidence)

    ext_val_requested = "yes" if config.include_external_validation else "no"
    table_1 = f"""% Auto-generated scaffold table. Real cohort counts are filled by M3.
\\begin{{tabular}}{{ll}}
\\toprule
Field & Value \\\\
\\midrule
Source tasks & {len(config.source_tasks)} \\\\
Target templates & {len(template_values)} \\\\
External validation requested & {ext_val_requested} \\\\
\\bottomrule
\\end{{tabular}}
"""
    _write_text(paths.tables_dir / "table_1_dataset.tex", table_1)
    _write_json(
        paths.tables_dir / "manifest.json",
        {
            "tables": [
                {
                    "path": "tables/table_1_dataset.tex",
                    "label": "tab:dataset",
                    "status": "scaffold",
                }
            ]
        },
    )

    _write_text(
        paths.locked_blocks_dir / "dataset_block.tex",
        "\\paragraph{Dataset scaffold.} Source task metadata has been collected; cohort statistics await the collector stage.\n",
    )
    _write_text(
        paths.locked_blocks_dir / "method_block.tex",
        "\\paragraph{Method scaffold.} Model and preprocessing configuration will be rendered deterministically from PathLab task records.\n",
    )
    _write_text(
        paths.locked_blocks_dir / "results_block.tex",
        "\\paragraph{Results scaffold.} No metric values are written until evidence-locked analysis summaries are available.\n",
    )
    _write_text(
        paths.locked_blocks_dir / "metrics_macros.tex",
        "% Metric macros are intentionally empty in the scaffold.\n",
    )

    _register_artifact(
        manifest,
        "evidence/experimental_log.md",
        label="Experimental log",
        content_type="text/markdown",
    )
    _register_artifact(
        manifest,
        "evidence/evidence_public.json",
        label="Public evidence",
        content_type="application/json",
    )
    _register_artifact(
        manifest,
        "evidence/evidence_lock.private.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Private evidence lock",
        content_type="application/json",
    )
    _register_artifact(
        manifest,
        "tables/manifest.json",
        label="Tables manifest",
        content_type="application/json",
    )
    _register_artifact(
        manifest,
        "tables/table_1_dataset.tex",
        label="Dataset table",
        content_type="text/x-tex",
    )
    for name in (
        "dataset_block.tex",
        "method_block.tex",
        "results_block.tex",
        "metrics_macros.tex",
    ):
        _register_artifact(
            manifest,
            f"locked_blocks/{name}",
            visibility="private_backend_only",
            downloadable=False,
            label=f"Locked block: {name}",
            content_type="text/x-tex",
        )


def _stage_outlining(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    outline = {
        "plotting_plan": [
            {
                "figure_id": "fig:overview",
                "kind": "conceptual",
                "source": "idea + method_block",
                "design_objective": "Show the PathLab WSI-to-paper evidence workflow.",
                "backend": "requires_user_revision",
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
                    "computational pathology foundation models validation",
                ],
            }
        ],
        "section_plan": [
            {"section": section.replace("_", " ").title(), "goal": "scaffold"}
            for section in _SECTION_ORDER
        ],
        "pathlab_extensions": {
            "templates": [template.value for template in config.selected_templates],
            "claim_plan": [],
            "guard_requirements": [
                "metric",
                "claim",
                "identifier",
                "consistency",
                "citation",
                "latex",
                "figure_table",
            ],
        },
    }
    _write_json(paths.outline_json, outline)
    _register_artifact(
        manifest,
        "drafts/outline.json",
        label="Outline",
        content_type="application/json",
    )


def _stage_plotting(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    figures_manifest = {
        "figures": [
            {
                "figure_id": "fig:overview",
                "path": None,
                "status": "requires_user_revision",
                "source": "scaffold",
                "caption": "Overview figure placeholder; PaperBanana-style generation lands in M6c.",
            }
        ]
    }
    _write_json(paths.figures_manifest, figures_manifest)
    _register_artifact(
        manifest,
        "figures/manifest.json",
        label="Figures manifest",
        content_type="application/json",
    )


def _stage_literature_review(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    _write_json(paths.citations_dir / "discovery_pool.json", {"items": []})
    _write_json(paths.citations_dir / "verified_pool.json", {"items": []})
    _write_json(paths.citations_dir / "selected_refs.json", {"items": []})
    _write_json(paths.citations_dir / "required_cites.json", {"items": []})
    _write_text(
        paths.refs_bib,
        "% Scaffold bibliography. Verified references are added by the literature review agent.\n",
    )
    _write_json(
        paths.citations_dir / "coverage_report.json",
        {
            "status": "scaffold",
            "selected_ref_count": 0,
            "required_cite_count": 0,
            "coverage": 1.0,
        },
    )
    _write_text(
        paths.intro_rw_draft_dir / "introduction.tex",
        "% Literature Review Agent draft placeholder. Not used directly for final compilation.\n",
    )
    _write_text(
        paths.intro_rw_draft_dir / "related_work.tex",
        "% Literature Review Agent related-work placeholder. Not used directly for final compilation.\n",
    )

    _register_artifact(
        manifest,
        "citations/refs.bib",
        label="BibTeX references",
        content_type="text/x-bibtex",
    )
    _register_artifact(
        manifest,
        "citations/coverage_report.json",
        label="Citation coverage report",
        content_type="application/json",
    )
    for rel_path in (
        "citations/discovery_pool.json",
        "citations/verified_pool.json",
        "citations/selected_refs.json",
        "citations/required_cites.json",
        "drafts/intro_rw_draft/introduction.tex",
        "drafts/intro_rw_draft/related_work.tex",
    ):
        _register_artifact(
            manifest,
            rel_path,
            visibility="private_backend_only",
            downloadable=False,
            label=rel_path,
        )


def _section_text(section: str, config: PaperConfig) -> str:
    title = config.title or "PathLab Paper Draft"
    if section == "abstract":
        return (
            "\\begin{abstract}\n"
            f"This scaffold initializes the paper-generation pipeline for {title}. "
            "Evidence-locked metrics are intentionally omitted until collector output is available.\n"
            "\\end{abstract}\n"
        )
    if section == "introduction":
        idea = (config.user_idea or "PathLab converts completed digital pathology experiments into evidence-locked manuscripts.").strip()
        return f"\\section{{Introduction}}\n{idea}\n"
    if section == "related_work":
        return "\\section{Related Work}\nVerified citations will be inserted by the Literature Review Agent.\n"
    if section == "methods":
        return "\\section{Methods}\n\\input{locked_blocks/method_block.tex}\n"
    if section == "experiments":
        return "\\section{Experimental Setup}\n\\input{locked_blocks/dataset_block.tex}\n"
    if section == "results":
        return "\\section{Results}\n\\input{locked_blocks/results_block.tex}\n\\input{tables/table_1_dataset.tex}\n"
    if section == "discussion":
        return "\\section{Discussion}\nClaim strength is limited to evidence available in the PathLab run.\n"
    if section == "conclusion":
        return "\\section{Conclusion}\nThis scaffold is ready for collector, agent, guard, renderer, and export milestones.\n"
    raise ValueError(f"Unknown section: {section}")


def _stage_section_writing(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    for section in _SECTION_ORDER:
        rel_path = f"drafts/sections/{section}.tex"
        _write_text(paths.sections_dir / f"{section}.tex", _section_text(section, config))
        _register_artifact(
            manifest,
            rel_path,
            label=f"Section: {section.replace('_', ' ').title()}",
            content_type="text/x-tex",
        )


def _stage_validating(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    warnings = """# Validation Warnings

This standalone scaffold completed without LLM calls. Deterministic guards are
not yet enforcing real metrics/citations; M10 adds hard gates.
"""
    _write_text(paths.validation_dir / "warnings.md", warnings)
    _write_json(
        paths.validation_dir / "scaffold_guard.json",
        {"status": "pass", "mode": "standalone_scaffold"},
    )
    _register_artifact(
        manifest,
        "validation/warnings.md",
        label="Validation warnings",
        content_type="text/markdown",
    )
    _register_artifact(
        manifest,
        "validation/scaffold_guard.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Scaffold guard report",
        content_type="application/json",
    )


def _copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _main_tex(template_id: str, config: PaperConfig) -> str:
    title = config.title or "PathLab Paper Draft"
    template_note = (
        "MICCAI/LNCS scaffold" if template_id == "miccai" else "Nature Scientific Reports scaffold"
    )
    section_inputs = "\n".join(
        f"\\input{{sections/{section}.tex}}" for section in _SECTION_ORDER
    )
    return f"""\\documentclass{{article}}
\\usepackage{{booktabs}}
\\usepackage{{graphicx}}
\\title{{{title}}}
\\author{{PathLab Paper Agent}}
\\date{{}}
\\begin{{document}}
\\maketitle
% {template_note}. Venue-specific classes land in M4.
{section_inputs}
\\bibliographystyle{{plain}}
\\bibliography{{refs}}
\\end{{document}}
"""


def _stage_rendering(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        final_dir = paths.final_for_template(template_id)
        final_dir.mkdir(parents=True, exist_ok=True)
        _write_text(final_dir / "main.tex", _main_tex(template_id, config))
        _copy_tree_contents(paths.sections_dir, final_dir / "sections")
        _copy_tree_contents(paths.locked_blocks_dir, final_dir / "locked_blocks")
        _copy_tree_contents(paths.tables_dir, final_dir / "tables")
        _copy_tree_contents(paths.figures_dir, final_dir / "figures")
        if paths.refs_bib.exists():
            shutil.copy2(paths.refs_bib, final_dir / "refs.bib")
        else:
            _write_text(final_dir / "refs.bib", "")
        _register_artifact(
            manifest,
            f"final/{template_id}/main.tex",
            label=f"{template_id} LaTeX main",
            content_type="text/x-tex",
        )


def _stage_exporting(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = _load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        final_dir = paths.final_for_template(template_id)
        if not final_dir.exists():
            raise FileNotFoundError(f"final directory missing for template {template_id}")
        bundle_name = f"{template_id}_bundle.zip"
        bundle_path = paths.exports_dir / bundle_name
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(final_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, arcname=str(file_path.relative_to(final_dir)))
            archive.writestr(
                "README.md",
                "# PathLab Paper Agent Bundle\n\n"
                f"Paper ID: `{config.paper_id}`\n\n"
                f"Template: `{template_id}`\n\n"
                "This is a deterministic scaffold bundle. Private evidence files are excluded.\n",
            )
        _register_artifact(
            manifest,
            f"exports/{bundle_name}",
            label=f"{template_id} submission bundle",
            content_type="application/zip",
        )


def _execute_stage(paths: PaperRunPaths, manifest: PaperManifest, stage: PaperRunStage) -> None:
    if stage == PaperRunStage.collecting:
        _stage_collecting(paths, manifest)
    elif stage == PaperRunStage.building_evidence:
        _stage_building_evidence(paths, manifest)
    elif stage == PaperRunStage.outlining:
        _stage_outlining(paths, manifest)
    elif stage == PaperRunStage.plotting:
        _stage_plotting(paths, manifest)
    elif stage == PaperRunStage.literature_review:
        _stage_literature_review(paths, manifest)
    elif stage == PaperRunStage.section_writing:
        _stage_section_writing(paths, manifest)
    elif stage == PaperRunStage.validating:
        _stage_validating(paths, manifest)
    elif stage == PaperRunStage.rendering:
        _stage_rendering(paths, manifest)
    elif stage == PaperRunStage.exporting:
        _stage_exporting(paths, manifest)
    elif stage in (PaperRunStage.completed, PaperRunStage.failed, PaperRunStage.cancelled):
        return
    else:
        raise ValueError(f"Stage {stage.value!r} is not executable in the standalone scaffold")


# ---------------------------------------------------------------------------
# Public stage API
# ---------------------------------------------------------------------------


def run_stage(
    paper_id: str,
    stage: str | PaperRunStage,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
    message: Optional[str] = None,
) -> PaperManifest:
    """Execute one deterministic stage and update `manifest.json`.

    Later milestones can replace individual `_stage_*` bodies without changing
    the CLI, dev server, TaskWorker subprocess boundary, or front-end polling
    contract.
    """
    configure_uploads_dir(uploads_dir)
    _ensure_run_from_config(paper_id, config_path, uploads_dir=uploads_dir)
    stage_value = stage.value if isinstance(stage, PaperRunStage) else str(stage)
    try:
        stage_enum = PaperRunStage(stage_value)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in PaperRunStage)
        raise ValueError(f"Unknown paper stage {stage_value!r}. Allowed: {allowed}") from exc

    manifest = load_manifest(paper_id)
    paths = PaperRunPaths.for_paper(paper_id)
    now = utc_now()

    try:
        manifest.status = PaperRunStatus.running
        manifest.current_stage = stage_enum
        manifest.updated_at = now
        _execute_stage(paths, manifest, stage_enum)
        if stage_enum == PaperRunStage.completed:
            manifest.status = PaperRunStatus.completed
            manifest.finished_at = now
        elif stage_enum == PaperRunStage.failed:
            manifest.status = PaperRunStatus.failed
            manifest.finished_at = now
        elif stage_enum == PaperRunStage.cancelled:
            manifest.status = PaperRunStatus.cancelled
            manifest.finished_at = now
        manifest.stage_log.append(
            {
                "stage": stage_enum.value,
                "ts": now.isoformat(),
                "message": message or f"Standalone scaffold stage {stage_enum.value} completed.",
            }
        )
    except Exception as exc:
        failed_at = utc_now()
        manifest.status = PaperRunStatus.failed
        manifest.current_stage = PaperRunStage.failed
        manifest.error_message = str(exc)[:4000]
        manifest.finished_at = failed_at
        manifest.stage_log.append(
            {
                "stage": PaperRunStage.failed.value,
                "ts": failed_at.isoformat(),
                "message": f"Stage {stage_enum.value} failed: {exc}",
            }
        )
        save_manifest(manifest)
        raise

    save_manifest(manifest)
    return manifest


def complete_run(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Run all deterministic scaffold stages and mark the paper completed."""
    for stage in _STAGE_ORDER:
        run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent scaffold completed.",
    )


def manifest_artifacts(manifest: PaperManifest) -> list[PaperRunArtifact]:
    artifacts: list[PaperRunArtifact] = []
    for rel_path, raw in manifest.artifact_index.items():
        if isinstance(raw, dict):
            data = {"path": rel_path, **raw}
        else:
            data = {"path": rel_path, "status": str(raw)}
        artifacts.append(PaperRunArtifact.model_validate(data))
    return artifacts


def summarize_manifest(paper_id: str, *, uploads_dir: Optional[str | Path] = None) -> PaperRunSummary:
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    config_data: dict[str, Any] = {}
    if paths.config.exists():
        config_data = _read_json(paths.config)
    return PaperRunSummary(
        paper_id=paper_id,
        status=manifest.status,
        current_stage=manifest.current_stage,
        title=config_data.get("title"),
        selected_templates=config_data.get("selected_templates", []),
        source_task_ids=[item.get("task_id", "") for item in config_data.get("source_tasks", [])],
        created_at=manifest.created_at,
        finished_at=manifest.finished_at,
        error_message=manifest.error_message,
    )
