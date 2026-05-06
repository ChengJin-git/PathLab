"""DB model schema validation."""

from __future__ import annotations

from backend.database.models import Base, PaperGenerationRun


def test_paper_generation_run_is_registered() -> None:
    assert PaperGenerationRun.__tablename__ in Base.metadata.tables


def test_paper_generation_run_required_columns() -> None:
    cols = {c.name for c in PaperGenerationRun.__table__.columns}
    required = {
        "id",
        "paper_id",
        "user_id",
        "title",
        "status",
        "current_stage",
        "error_message",
        "config_json",
        "source_task_ids",
        "selected_templates",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    }
    missing = required - cols
    assert not missing, f"Missing required columns: {missing}"


def test_paper_id_column_is_unique_indexed() -> None:
    col = PaperGenerationRun.__table__.columns["paper_id"]
    assert col.unique is True
    assert col.index is True
    assert col.nullable is False


def test_status_and_current_stage_indexed_for_filters() -> None:
    """list_for_user / status filters need indexes for cheap queries at scale."""
    status_col = PaperGenerationRun.__table__.columns["status"]
    assert status_col.index is True
    assert status_col.nullable is False


def test_to_dict_includes_all_status_fields() -> None:
    """Sanity: to_dict returned fields are stable so the API doesn't drift."""
    run = PaperGenerationRun(
        paper_id="paper_abc",
        user_id="user-1",
        title="Test",
        status="pending",
        current_stage="created",
        config_json={"x": 1},
        source_task_ids=["tsk_a"],
        selected_templates=["miccai"],
    )
    d = run.to_dict()
    expected_keys = {
        "paper_id", "user_id", "title", "status", "current_stage",
        "error_message", "config_json", "source_task_ids",
        "selected_templates", "created_at", "updated_at",
        "started_at", "finished_at",
    }
    assert expected_keys.issubset(d.keys())
