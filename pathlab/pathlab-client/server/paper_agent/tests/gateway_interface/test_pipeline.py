"""Pipeline scaffold tests."""

from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.pipeline import initialize_paper_run
from pathlab_paper_agent.schemas import (
    PaperConfig,
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
