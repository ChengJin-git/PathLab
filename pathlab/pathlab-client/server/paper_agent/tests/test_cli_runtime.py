from __future__ import annotations

import json
import zipfile

import pytest

from pathlab_paper_agent.pipeline import complete_run, create_dev_run, run_stage


@pytest.mark.asyncio
async def test_create_dev_run_and_run_stage(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_test", uploads_dir=tmp_path)
    assert paper_id == "paper_test"
    assert paths.manifest.is_file()
    assert paths.config.is_file()

    manifest = run_stage("paper_test", "collecting", uploads_dir=tmp_path)
    assert manifest.current_stage.value == "collecting"
    assert manifest.status.value == "running"
    assert paths.source_tasks.is_file()

    data = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert data["current_stage"] == "collecting"
    assert data["artifact_index"]["inputs/source_tasks.json"]["visibility"] == "private_backend_only"
    stage_entry = data["stage_log"][-1]
    assert stage_entry["stage"] == "collecting"
    assert stage_entry["status"] == "completed"
    assert stage_entry["started_at"]
    assert stage_entry["finished_at"]
    assert stage_entry["ts"] == stage_entry["finished_at"]
    assert isinstance(stage_entry["duration_ms"], int)
    assert stage_entry["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_complete_run_writes_scaffold_artifacts_and_exports(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_full", uploads_dir=tmp_path)

    manifest = complete_run(paper_id, uploads_dir=tmp_path, bypass_approval=True)

    assert manifest.status.value == "completed"
    assert manifest.current_stage.value == "completed"
    assert paths.experimental_log.is_file()
    assert paths.evidence_public.is_file()
    assert paths.evidence_lock_private.is_file()
    assert paths.outline_json.is_file()
    assert (paths.sections_dir / "methods.tex").is_file()
    assert (paths.final_for_template("miccai") / "main.tex").is_file()
    assert (paths.exports_dir / "miccai_bundle.zip").is_file()
    assert not (paths.exports_dir / "nature_scientific_reports_bundle.zip").exists()

    artifact_index = json.loads(paths.manifest.read_text(encoding="utf-8"))["artifact_index"]
    assert artifact_index["evidence/evidence_public.json"]["visibility"] == "public"
    assert artifact_index["evidence/evidence_lock.private.json"]["visibility"] == "private_backend_only"
    assert "drafts/sections/abstract.tex" in artifact_index
    assert "exports/miccai_bundle.zip" in artifact_index

    with zipfile.ZipFile(paths.exports_dir / "miccai_bundle.zip") as archive:
        names = set(archive.namelist())
    assert "main.tex" in names
    assert "sections/abstract.tex" in names
    assert "locked_blocks/method_block.tex" in names
    assert "evidence/evidence_lock.private.json" not in names


@pytest.mark.asyncio
async def test_run_stage_can_bootstrap_from_config(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_config", uploads_dir=tmp_path)
    config_copy = tmp_path / "saved_config.json"
    config_copy.write_text(paths.config.read_text(encoding="utf-8"), encoding="utf-8")

    # Simulate reproducing a worker run from only config.json.
    import shutil

    shutil.rmtree(paths.root)
    assert not paths.manifest.exists()

    manifest = run_stage(
        paper_id,
        "collecting",
        uploads_dir=tmp_path,
        config_path=config_copy,
    )

    assert manifest.current_stage.value == "collecting"
    assert paths.manifest.is_file()
    assert paths.source_tasks.is_file()
