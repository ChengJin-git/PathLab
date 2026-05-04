"""Evidence-building stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import load_config, register_artifact, source_task_lines, write_json, write_text


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
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

{source_task_lines(config)}

## Evidence Status

This is a deterministic standalone scaffold. It preserves the v1 artifact
layout, PHI boundary, and agent handoff contract. Real PathLab DB metrics,
cohort counts, model configuration, and analysis provenance are added by the
collector and evidence milestones.

## PHI Policy

Only scrubbed identifiers may appear in LLM-facing artifacts. Private source
paths and identifier mappings stay in `evidence_lock.private.json`.
"""
    write_text(paths.experimental_log, experimental_log)

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
    write_json(paths.evidence_lock_private, private_lock)
    write_json(paths.evidence_public, public_evidence)

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
    write_text(paths.tables_dir / "table_1_dataset.tex", table_1)
    write_json(
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

    write_text(
        paths.locked_blocks_dir / "dataset_block.tex",
        "\\paragraph{Dataset scaffold.} Source task metadata has been collected; cohort statistics await the collector stage.\n",
    )
    write_text(
        paths.locked_blocks_dir / "method_block.tex",
        "\\paragraph{Method scaffold.} Model and preprocessing configuration will be rendered deterministically from PathLab task records.\n",
    )
    write_text(
        paths.locked_blocks_dir / "results_block.tex",
        "\\paragraph{Results scaffold.} No metric values are written until evidence-locked analysis summaries are available.\n",
    )
    write_text(
        paths.locked_blocks_dir / "metrics_macros.tex",
        "% Metric macros are intentionally empty in the scaffold.\n",
    )

    register_artifact(
        manifest,
        "evidence/experimental_log.md",
        label="Experimental log",
        content_type="text/markdown",
    )
    register_artifact(
        manifest,
        "evidence/evidence_public.json",
        label="Public evidence",
        content_type="application/json",
    )
    register_artifact(
        manifest,
        "evidence/evidence_lock.private.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Private evidence lock",
        content_type="application/json",
    )
    register_artifact(
        manifest,
        "tables/manifest.json",
        label="Tables manifest",
        content_type="application/json",
    )
    register_artifact(
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
        register_artifact(
            manifest,
            f"locked_blocks/{name}",
            visibility="private_backend_only",
            downloadable=False,
            label=f"Locked block: {name}",
            content_type="text/x-tex",
        )
