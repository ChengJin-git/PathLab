"""Pydantic schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pathlab_paper_agent.schemas import (
    CreatePaperRequest,
    PaperConfig,
    PaperManifest,
    PaperRunStage,
    PaperRunStatus,
    SourceTaskRef,
    TaskRole,
    TemplateId,
)
from backend.database.models import utc_now


def test_template_id_has_two_default_templates() -> None:
    assert {t.value for t in TemplateId} == {"miccai", "nature_scientific_reports"}


def test_task_role_covers_main_ablation_baseline_extval() -> None:
    assert {r.value for r in TaskRole} == {
        "main",
        "ablation",
        "baseline",
        "external_validation",
    }


def test_paper_run_stage_includes_pipeline_stages() -> None:
    """Sanity: every milestone stage from §10 has a corresponding label."""
    expected = {
        "created", "collecting", "building_evidence", "outlining",
        "plotting", "literature_review", "section_writing", "validating",
        "refining", "rendering", "exporting", "completed", "failed",
        "cancelled",
    }
    assert expected.issubset({s.value for s in PaperRunStage})


def test_create_paper_request_defaults_to_miccai_template() -> None:
    req = CreatePaperRequest(
        source_tasks=[SourceTaskRef(task_id="tsk_main")],
    )
    assert req.selected_templates == [TemplateId.miccai]
    assert req.include_external_validation is True
    assert req.language == "en"
    assert req.paper_type == "research_paper"


def test_create_paper_request_accepts_user_selected_single_template() -> None:
    req = CreatePaperRequest(
        source_tasks=[SourceTaskRef(task_id="tsk_main")],
        selected_templates=[TemplateId.nature_scientific_reports],
    )
    assert req.selected_templates == [TemplateId.nature_scientific_reports]


def test_source_task_ref_default_role_is_main() -> None:
    ref = SourceTaskRef(task_id="tsk_x")
    assert ref.role == TaskRole.main


def test_source_task_ref_supports_role_tagging() -> None:
    refs = [
        SourceTaskRef(task_id="tsk_main", role=TaskRole.main),
        SourceTaskRef(
            task_id="tsk_ablation",
            role=TaskRole.ablation,
            label="no_attention",
        ),
        SourceTaskRef(
            task_id="tsk_baseline",
            role=TaskRole.baseline,
            label="resnet50",
        ),
        SourceTaskRef(
            task_id="tsk_extval",
            role=TaskRole.external_validation,
            label="hospital_b",
        ),
    ]
    assert [r.role for r in refs] == [
        TaskRole.main,
        TaskRole.ablation,
        TaskRole.baseline,
        TaskRole.external_validation,
    ]


def test_paper_config_round_trip() -> None:
    cfg = PaperConfig(
        paper_id="paper_abc",
        title="Test Paper",
        paper_type="research_paper",
        language="en",
        source_tasks=[SourceTaskRef(task_id="tsk_x")],
        selected_templates=[TemplateId.miccai, TemplateId.nature_scientific_reports],
        include_external_validation=True,
        user_idea="Some idea text",
    )
    dumped = cfg.model_dump(mode="json")
    rebuilt = PaperConfig.model_validate(dumped)
    assert rebuilt == cfg


def test_paper_manifest_initial_state() -> None:
    now = utc_now()
    m = PaperManifest(
        paper_id="paper_abc",
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        created_at=now,
        updated_at=now,
    )
    assert m.stage_log == []
    assert m.artifact_index == {}
    assert m.error_message is None
    assert m.finished_at is None


def test_paper_manifest_accepts_stage_log_entries() -> None:
    now = utc_now()
    m = PaperManifest(
        paper_id="paper_abc",
        status=PaperRunStatus.running,
        current_stage=PaperRunStage.outlining,
        stage_log=[
            {"stage": "created", "ts": now.isoformat(), "message": "init"},
            {"stage": "collecting", "ts": now.isoformat(), "message": "starting"},
        ],
        artifact_index={"manifest.json": "ready"},
        created_at=now,
        updated_at=now,
    )
    assert len(m.stage_log) == 2
    assert m.artifact_index["manifest.json"] == "ready"


def test_create_paper_request_invalid_template_rejected() -> None:
    with pytest.raises(ValidationError):
        CreatePaperRequest.model_validate({
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["cvpr"],  # not in v1 enum
        })
