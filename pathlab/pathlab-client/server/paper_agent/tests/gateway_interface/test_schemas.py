"""Pydantic schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pathlab_paper_agent.schemas import (
    CreatePaperRequest,
    FigureManifest,
    GuardResultSummary,
    OutlineDocument,
    PaperConfig,
    PaperManifest,
    PaperRunStage,
    PaperRunStatus,
    PaperStageLogEntry,
    SourceTaskRef,
    TaskRole,
    TemplateId,
    ValidationSummary,
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


def test_frontend_contract_summary_models_accept_current_shapes() -> None:
    now = utc_now()
    entry = PaperStageLogEntry.model_validate(
        {
            "stage": "outlining",
            "status": "completed",
            "ts": now.isoformat(),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "duration_ms": 12,
            "message": "done",
        }
    )
    validation = ValidationSummary(
        m10_guards=[
            GuardResultSummary(
                guard="metric_guard",
                status="pass",
                path="validation/metric_guard.json",
            )
        ],
        hybrid_score=17.0,
        warnings_md_path="validation/warnings.md",
    )

    assert entry.duration_ms == 12
    assert validation.m10_guards[0].guard == "metric_guard"


def test_outline_document_schema_accepts_current_agent_output_shape() -> None:
    outline = OutlineDocument.model_validate(
        {
            "plotting_plan": [
                {
                    "figure_id": "fig:main_results",
                    "kind": "empirical",
                    "source": "experimental_log",
                    "design_objective": "summarize locked performance evidence",
                    "backend": "deterministic_plotting",
                    "plot_spec": {
                        "generator": "per_fold_roc",
                        "data_ref": "evidence/plot_data/main_roc.json",
                    },
                }
            ],
            "macro_lit_search": ["whole slide image computational pathology validation"],
            "micro_lit_clusters": [
                {
                    "cluster": "multiple instance learning for WSI",
                    "queries": ["attention MIL whole slide images"],
                }
            ],
            "section_plan": [
                {
                    "section": "Methods",
                    "goal": "explain the model and cohort without private identifiers",
                    "evidence_inputs": ["evidence_public"],
                    "citation_hints": ["weakly supervised WSI"],
                    "locked_block_inputs": ["locked_blocks/method_block.tex"],
                }
            ],
            "pathlab_extensions": {
                "templates": ["miccai"],
                "claim_plan": [{"claim": "locked evidence supports the main result"}],
                "table_plan": [],
                "guard_requirements": ["metric", "identifier"],
                "template_styles": [{"template_id": "miccai"}],
            },
            "input_summary": {"template_ids": ["miccai"]},
        }
    )

    assert outline.plotting_plan[0].figure_id == "fig:main_results"
    assert outline.pathlab_extensions.templates == ["miccai"]


def test_figure_manifest_schema_accepts_generated_and_revision_items() -> None:
    manifest = FigureManifest.model_validate(
        {
            "figures": [
                {
                    "figure_id": "fig:roc",
                    "path": "figures/fig_roc.png",
                    "status": "ready",
                    "source": "evidence:plot_data/main_roc.json",
                    "generator": "per_fold_roc",
                    "caption": "Per-fold ROC curves from locked evidence.",
                    "content_type": "image/png",
                    "kind": "empirical",
                    "backend": "deterministic_plotting",
                },
                {
                    "figure_id": "fig:overview",
                    "path": None,
                    "status": "requires_user_revision",
                    "source": "outline.plotting_plan",
                    "generator": "paperbanana",
                    "caption": "Conceptual figure requires user revision.",
                    "kind": "conceptual",
                    "backend": "paperbanana",
                },
            ]
        }
    )

    assert manifest.figures[0].path == "figures/fig_roc.png"
    assert manifest.figures[1].status == "requires_user_revision"


def test_create_paper_request_invalid_template_rejected() -> None:
    with pytest.raises(ValidationError):
        CreatePaperRequest.model_validate({
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["cvpr"],  # not in v1 enum
        })
