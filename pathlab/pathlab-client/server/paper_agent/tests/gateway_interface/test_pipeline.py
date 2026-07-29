"""Pipeline scaffold tests."""

from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.pipeline import initialize_paper_run
from pathlab_paper_agent.schemas import (
    PaperConfig,
    PaperManifest,
    PaperRunStage,
    PaperRunStatus,
    SourceTaskRef,
    TaskRole,
    TemplateId,
)
from pathlab_paper_agent.storage import PaperRunPaths


def _make_config(paper_id: str = "paper_pipe") -> PaperConfig:
    return PaperConfig(
        paper_id=paper_id,
        title="Test",
        paper_type="research_paper",
        language="en",
        source_tasks=[SourceTaskRef(task_id="tsk_main", role=TaskRole.main)],
        selected_templates=[TemplateId.miccai, TemplateId.nature_scientific_reports],
        include_external_validation=True,
        user_idea="hello",
    )


@pytest.mark.asyncio
async def test_initialize_paper_run_creates_root_and_subdirs(db_session) -> None:
    config = _make_config()
    paths = await initialize_paper_run(db_session, config)

    assert isinstance(paths, PaperRunPaths)
    assert paths.root.is_dir()
    for sub in paths.all_subdirs():
        assert sub.is_dir(), f"Missing subdirectory: {sub}"


@pytest.mark.asyncio
async def test_initialize_paper_run_writes_config_json(db_session) -> None:
    config = _make_config("paper_cfg")
    paths = await initialize_paper_run(db_session, config)

    assert paths.config.is_file()
    data = json.loads(paths.config.read_text())
    assert data["paper_id"] == "paper_cfg"
    assert data["title"] == "Test"
    assert data["selected_templates"] == ["miccai", "nature_scientific_reports"]
    assert data["source_tasks"][0]["task_id"] == "tsk_main"
    assert data["source_tasks"][0]["role"] == "main"


@pytest.mark.asyncio
async def test_initialize_paper_run_writes_initial_manifest(db_session) -> None:
    config = _make_config("paper_man")
    paths = await initialize_paper_run(db_session, config)

    assert paths.manifest.is_file()
    data = json.loads(paths.manifest.read_text())
    assert data["paper_id"] == "paper_man"
    assert data["status"] == "pending"
    assert data["current_stage"] == "created"
    assert data["error_message"] is None
    assert data["finished_at"] is None
    assert "manifest.json" in data["artifact_index"]
    assert "config.json" in data["artifact_index"]
    assert len(data["stage_log"]) >= 1


@pytest.mark.asyncio
async def test_initialize_paper_run_idempotent(db_session) -> None:
    """Re-running initialize should not crash; later state may overwrite."""
    config = _make_config("paper_idem")
    paths1 = await initialize_paper_run(db_session, config)
    paths2 = await initialize_paper_run(db_session, config)
    assert paths1.root == paths2.root
    assert paths2.manifest.is_file()


def test_run_render_export_replays_only_render_and_export(monkeypatch) -> None:
    from pathlab_paper_agent import pipeline

    calls: list[tuple[str, str, str | None]] = []

    def fake_run_stage(paper_id: str, stage, **kwargs):  # noqa: ANN001, ANN003
        stage_value = stage.value if hasattr(stage, "value") else str(stage)
        calls.append((paper_id, stage_value, kwargs.get("message")))
        return {"paper_id": paper_id, "stage": stage_value}

    monkeypatch.setattr(pipeline, "run_stage", fake_run_stage)

    result = pipeline.run_render_export(
        "paper_render_export",
        uploads_dir="/tmp/uploads",
        config_path="/tmp/config.json",
    )

    assert result == {"paper_id": "paper_render_export", "stage": "completed"}
    assert calls == [
        ("paper_render_export", "rendering", None),
        ("paper_render_export", "exporting", None),
        ("paper_render_export", "completed", "Standalone paper-agent render/export completed."),
    ]


def test_run_from_stage_replays_suffix_and_records_attempt(monkeypatch, tmp_path) -> None:
    from pathlab_paper_agent import pipeline

    calls: list[str] = []
    now = pipeline.utc_now()
    manifest = PaperManifest(
        paper_id="paper_suffix",
        status=PaperRunStatus.completed,
        current_stage=PaperRunStage.completed,
        created_at=now,
        updated_at=now,
        finished_at=now,
        stage_log=[
            {"stage": "collecting", "status": "completed", "ts": now.isoformat()},
            {"stage": "building_evidence", "status": "completed", "ts": now.isoformat()},
            {"stage": "outlining", "status": "completed", "ts": now.isoformat()},
        ],
    )

    def fake_load_manifest(paper_id: str, **kwargs):  # noqa: ANN001, ANN003
        assert paper_id == "paper_suffix"
        return manifest

    def fake_save_manifest(next_manifest, **kwargs):  # noqa: ANN001, ANN003
        return PaperRunPaths.for_paper(next_manifest.paper_id)

    def fake_run_stage(paper_id: str, stage, **kwargs):  # noqa: ANN001, ANN003
        stage_value = stage.value if hasattr(stage, "value") else str(stage)
        calls.append(stage_value)
        manifest.current_stage = PaperRunStage(stage_value)
        manifest.stage_log.append({"stage": stage_value, "status": "completed", "ts": now.isoformat()})
        if stage_value == "completed":
            manifest.status = PaperRunStatus.completed
        return manifest

    monkeypatch.setattr(pipeline, "load_manifest", fake_load_manifest)
    monkeypatch.setattr(pipeline, "save_manifest", fake_save_manifest)
    monkeypatch.setattr(pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(pipeline, "_ensure_run_from_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.PaperRunPaths, "for_paper", lambda paper_id: PaperRunPaths(paper_id=paper_id, root=tmp_path / paper_id))

    result = pipeline.run_from_stage("paper_suffix", "section_writing", uploads_dir=tmp_path)

    assert result is manifest
    assert calls == ["section_writing", "validating", "refining", "rendering", "exporting", "completed"]
    attempt = manifest.stage_attempts[-1]
    assert attempt["stage"] == "section_writing"
    assert attempt["status"] == "completed"
    assert attempt["input_attempts"]


def test_run_stage_failure_keeps_real_failed_stage(monkeypatch, tmp_path) -> None:
    from pathlab_paper_agent import pipeline

    paper_id = "paper_fail_stage"
    paths = tmp_path / "paper_generation" / paper_id
    paths.mkdir(parents=True)
    now = pipeline.utc_now()
    manifest = PaperManifest(
        paper_id=paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        created_at=now,
        updated_at=now,
        finished_at=None,
    )
    (paths / "manifest.json").write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("section failed")

    monkeypatch.setattr(pipeline, "run_section_writing", boom)

    with pytest.raises(RuntimeError, match="section failed"):
        pipeline.run_stage(paper_id, "section_writing", uploads_dir=tmp_path)

    data = json.loads((paths / "manifest.json").read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["current_stage"] == "section_writing"
    assert data["stage_log"][-1]["stage"] == "section_writing"


def test_run_stage_pause_after_stage_discards_current_stage_outputs(monkeypatch) -> None:
    from pathlab_paper_agent import pipeline
    from pathlab_paper_agent.stages.common import write_json

    paper_id = "paper_pause_discard"
    paths = PaperRunPaths.for_paper(paper_id)
    paths.ensure_dirs()
    now = pipeline.utc_now()
    original_section = paths.sections_dir / "abstract.tex"
    original_section.write_text("original section", encoding="utf-8")
    manifest = PaperManifest(
        paper_id=paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        created_at=now,
        updated_at=now,
        finished_at=None,
        artifact_index={
            "drafts/sections/abstract.tex": {
                "status": "ready",
                "visibility": "public",
                "downloadable": True,
                "label": "Original abstract",
            }
        },
    )
    write_json(paths.manifest, manifest.model_dump(mode="json"))

    def write_temp_outputs(next_paths, next_manifest):  # noqa: ANN001
        original_section.write_text("temporary rewrite", encoding="utf-8")
        new_section = next_paths.sections_dir / "methods.tex"
        new_section.write_text("temporary methods", encoding="utf-8")
        next_manifest.artifact_index["drafts/sections/abstract.tex"] = {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "label": "Temporary abstract",
        }
        next_manifest.artifact_index["drafts/sections/methods.tex"] = {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "label": "Temporary methods",
        }
        next_paths.pause_request.write_text("pause", encoding="utf-8")

    monkeypatch.setattr(pipeline, "run_section_writing", write_temp_outputs)

    result = pipeline.run_stage(paper_id, "section_writing")

    assert result.status == PaperRunStatus.paused
    assert result.current_stage == PaperRunStage.section_writing
    assert original_section.read_text(encoding="utf-8") == "original section"
    assert not (paths.sections_dir / "methods.tex").exists()
    assert result.artifact_index["drafts/sections/abstract.tex"]["label"] == "Original abstract"
    assert "drafts/sections/methods.tex" not in result.artifact_index
    assert result.stage_log[-1]["status"] == PaperRunStatus.paused.value
    assert "discarded" in result.stage_log[-1]["message"]
    assert not any(
        entry["stage"] == PaperRunStage.section_writing.value and entry["status"] == "completed"
        for entry in result.stage_log
    )
