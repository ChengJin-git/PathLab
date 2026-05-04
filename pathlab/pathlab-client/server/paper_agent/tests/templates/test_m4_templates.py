from __future__ import annotations

import json
import os
import zipfile

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.renderers.latex_compiler import compile_with_docker
from pathlab_paper_agent.templates import get_template, list_templates

_THROUGH_RENDERING = (
    "collecting",
    "building_evidence",
    "outlining",
    "plotting",
    "literature_review",
    "section_writing",
    "validating",
    "rendering",
)


def _run_docker_tests() -> bool:
    return os.environ.get("PATHLAB_PAPER_AGENT_RUN_DOCKER_TESTS", "0").lower() in {"1", "true", "yes"}


def _run_stages(paper_id: str, stages: tuple[str, ...], uploads_dir) -> None:
    for stage in stages:
        run_stage(paper_id, stage, uploads_dir=uploads_dir)


def test_template_registry_loads_two_venue_styles() -> None:
    templates = {template.template_id: template for template in list_templates()}
    assert set(templates) == {"miccai", "nature_scientific_reports"}
    assert templates["miccai"].style["format_family"] == "LNCS"
    assert templates["nature_scientific_reports"].style["style_constraints"]["requires_data_availability"] is True
    assert get_template("miccai").main_template.name == "main.tex.j2"


@pytest.mark.asyncio
async def test_rendering_stage_writes_venue_specific_latex_assets(tmp_path) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m4_render", uploads_dir=tmp_path)
    _run_stages(paper_id, _THROUGH_RENDERING, tmp_path)

    miccai = paths.final_for_template("miccai")
    nature = paths.final_for_template("nature_scientific_reports")
    assert (miccai / "main.tex").is_file()
    assert (miccai / "llncs.cls").is_file()
    assert (miccai / "style.json").is_file()
    assert (nature / "main.tex").is_file()
    assert (nature / "sn-jnl.cls").is_file()
    assert (nature / "style.json").is_file()
    assert "\\documentclass[runningheads]{llncs}" in (miccai / "main.tex").read_text(encoding="utf-8")
    assert "\\documentclass[pdflatex,sn-nature]{sn-jnl}" in (nature / "main.tex").read_text(encoding="utf-8")
    assert "Data availability" in (nature / "main.tex").read_text(encoding="utf-8")

    artifact_index = json.loads(paths.manifest.read_text(encoding="utf-8"))["artifact_index"]
    assert "final/miccai/style.json" in artifact_index
    assert "final/nature_scientific_reports/main.compile_summary.txt" in artifact_index

    (miccai / "stale.tmp").write_text("old export payload", encoding="utf-8")
    (miccai / "main.pdf").write_bytes(b"stale pdf")
    manifest_payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest_payload["artifact_index"]["final/miccai/main.pdf"] = {
        "status": "ready",
        "visibility": "public",
        "downloadable": True,
    }
    paths.manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    assert not (miccai / "stale.tmp").exists()
    assert not (miccai / "main.pdf").exists()
    artifact_index = json.loads(paths.manifest.read_text(encoding="utf-8"))["artifact_index"]
    assert "final/miccai/main.pdf" not in artifact_index


@pytest.mark.asyncio
async def test_export_bundle_is_dependency_closed_and_public_only(tmp_path) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m4_export", uploads_dir=tmp_path)
    _run_stages(paper_id, _THROUGH_RENDERING, tmp_path)

    miccai = paths.final_for_template("miccai")
    (miccai / "source_mappings.json").write_text('{"case": "private"}', encoding="utf-8")
    (miccai / "figures" / "phi_mapping.json").write_text('{"case": "private"}', encoding="utf-8")
    (miccai / "debug_notes.json").write_text('{"debug": true}', encoding="utf-8")
    run_stage(paper_id, "exporting", uploads_dir=tmp_path)

    with zipfile.ZipFile(paths.exports_dir / "miccai_bundle.zip") as archive:
        names = set(archive.namelist())
    assert "main.tex" in names
    assert "llncs.cls" in names
    assert "splncs04.bst" in names
    assert "style.json" in names
    assert "sections/abstract.tex" in names
    assert "locked_blocks/method_block.tex" in names
    assert "tables/table_1_dataset.tex" in names
    assert "evidence/evidence_lock.private.json" not in names
    assert "inputs/source_tasks.json" not in names
    assert "source_mappings.json" not in names
    assert "figures/phi_mapping.json" not in names
    assert "debug_notes.json" not in names

    with zipfile.ZipFile(paths.exports_dir / "nature_scientific_reports_bundle.zip") as archive:
        nature_names = set(archive.namelist())
    assert "sn-jnl.cls" in nature_names
    assert "sn-nature.bst" in nature_names


@pytest.mark.docker
@pytest.mark.skipif(
    not _run_docker_tests(),
    reason="Set PATHLAB_PAPER_AGENT_RUN_DOCKER_TESTS=1 to run Docker LaTeX compile test.",
)
@pytest.mark.asyncio
async def test_rendered_templates_compile_with_docker_when_enabled(tmp_path) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m4_pdf", uploads_dir=tmp_path)
    _run_stages(paper_id, _THROUGH_RENDERING, tmp_path)

    miccai_result = compile_with_docker(paths.root, "miccai")
    nature_result = compile_with_docker(paths.root, "nature_scientific_reports")
    assert miccai_result.status == "compiled"
    assert nature_result.status == "compiled"
    assert (paths.final_for_template("miccai") / "main.pdf").is_file()
    assert (paths.final_for_template("nature_scientific_reports") / "main.pdf").is_file()
