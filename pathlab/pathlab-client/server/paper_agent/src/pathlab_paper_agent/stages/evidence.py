"""Phase 03 PHI scrub and evidence-bundle stage."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..evidence import build_evidence_bundle
from .common import load_config, register_artifact, write_json, write_text

_PUBLIC_EVIDENCE_SUMMARIES = (
    "dataset_summary.public.json",
    "model_summary.public.json",
    "analysis_summary.public.json",
)
_TABLE_LABELS = {
    "table_1_dataset.tex": "Dataset table",
    "table_2_main_results.tex": "Main results table",
    "table_3_per_class.tex": "Split/per-class table",
    "table_4_ablation.tex": "Ablation table",
    "table_5_external_validation.tex": "External validation table",
}
def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    result = build_evidence_bundle(paths, config)

    write_text(paths.experimental_log, result.experimental_log)
    write_json(paths.evidence_lock_private, result.private_lock)
    write_json(paths.evidence_public, result.public_evidence)
    for name, payload in result.public_summaries.items():
        write_json(paths.evidence_dir / name, payload)

    table_manifest = {"tables": []}
    for name, text in result.tables.items():
        write_text(paths.tables_dir / name, text)
        table_manifest["tables"].append(
            {
                "path": f"tables/{name}",
                "label": _TABLE_LABELS.get(name, name),
                "status": "ready",
            }
        )
    write_json(paths.tables_dir / "manifest.json", table_manifest)

    for name, text in result.locked_blocks.items():
        write_text(paths.locked_blocks_dir / name, text)
    for template_id, blocks in result.locked_blocks_by_template.items():
        for name, text in blocks.items():
            write_text(paths.locked_blocks_dir / template_id / name, text)

    _register_artifacts(manifest, result)


def _register_artifacts(manifest: PaperManifest, result) -> None:
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
    for name in _PUBLIC_EVIDENCE_SUMMARIES:
        register_artifact(
            manifest,
            f"evidence/{name}",
            label=name.replace("_", " ").replace(".json", ""),
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
    for name in result.tables:
        register_artifact(
            manifest,
            f"tables/{name}",
            label=_TABLE_LABELS.get(name, name),
            content_type="text/x-tex",
        )
    for name in result.locked_blocks:
        register_artifact(
            manifest,
            f"locked_blocks/{name}",
            visibility="private_backend_only",
            downloadable=False,
            label=f"Locked block: {name}",
            content_type="text/x-tex",
        )
    for template_id, blocks in result.locked_blocks_by_template.items():
        for name in blocks:
            register_artifact(
                manifest,
                f"locked_blocks/{template_id}/{name}",
                visibility="private_backend_only",
                downloadable=False,
                label=f"Locked block ({template_id}): {name}",
                content_type="text/x-tex",
            )
