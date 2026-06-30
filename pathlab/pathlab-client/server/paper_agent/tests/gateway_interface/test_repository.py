"""PaperGenerationRunRepository CRUD + lifecycle helpers."""

from __future__ import annotations

import pytest

from backend.database.repositories.paper_generation import (
    PaperGenerationRunRepository,
)


@pytest.fixture
async def created_run(db_session):
    """Insert a single paper run into the test DB."""
    run = await PaperGenerationRunRepository.create(
        db_session,
        paper_id="paper_aaa",
        user_id="user-1",
        title="Test paper",
        status="pending",
        current_stage="created",
        config_json={"selected_templates": ["miccai"]},
        source_task_ids=["tsk_main"],
        selected_templates=["miccai"],
    )
    await db_session.commit()
    return run


async def test_create_and_get_by_id(created_run, db_session) -> None:
    fetched = await PaperGenerationRunRepository.get_by_id(db_session, "paper_aaa")
    assert fetched is not None
    assert fetched.paper_id == "paper_aaa"
    assert fetched.title == "Test paper"
    assert fetched.status == "pending"
    assert fetched.current_stage == "created"
    assert fetched.source_task_ids == ["tsk_main"]
    assert fetched.selected_templates == ["miccai"]


async def test_get_by_id_returns_none_when_missing(db_session) -> None:
    fetched = await PaperGenerationRunRepository.get_by_id(db_session, "paper_missing")
    assert fetched is None


async def test_mark_started_sets_running(created_run, db_session) -> None:
    updated = await PaperGenerationRunRepository.mark_started(db_session, "paper_aaa")
    assert updated is not None
    assert updated.status == "running"
    assert updated.started_at is not None
    assert updated.error_message is None


async def test_mark_completed_sets_done_stage_and_clears_error(
    created_run, db_session
) -> None:
    # Pretend an earlier failure; mark_completed should clear it.
    await PaperGenerationRunRepository.update(
        db_session, "paper_aaa", error_message="some old failure"
    )
    updated = await PaperGenerationRunRepository.mark_completed(
        db_session, "paper_aaa"
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.current_stage == "completed"
    assert updated.finished_at is not None
    assert updated.error_message is None


async def test_mark_failed_records_truncated_error(
    created_run, db_session
) -> None:
    long_msg = "x" * 10000
    updated = await PaperGenerationRunRepository.mark_failed(
        db_session, "paper_aaa", long_msg
    )
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error_message is not None
    # Repository truncates to 4000 chars to avoid stuffing huge tracebacks.
    assert len(updated.error_message) == 4000


async def test_mark_cancelled(created_run, db_session) -> None:
    updated = await PaperGenerationRunRepository.mark_cancelled(
        db_session, "paper_aaa"
    )
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.finished_at is not None


async def test_update_stage_can_advance(created_run, db_session) -> None:
    updated = await PaperGenerationRunRepository.update_stage(
        db_session, "paper_aaa", "outline"
    )
    assert updated is not None
    assert updated.current_stage == "outline"
    # Status untouched unless explicitly set.
    assert updated.status == "pending"


async def test_update_stage_can_advance_status_too(created_run, db_session) -> None:
    updated = await PaperGenerationRunRepository.update_stage(
        db_session, "paper_aaa", "section_writing", status="running"
    )
    assert updated is not None
    assert updated.current_stage == "section_writing"
    assert updated.status == "running"


async def test_list_for_user_filters_by_user_id(db_session) -> None:
    # Two users, three runs.
    for i, uid in enumerate(["user-1", "user-1", "user-2"]):
        await PaperGenerationRunRepository.create(
            db_session,
            paper_id=f"paper_{i}",
            user_id=uid,
            title=f"Paper {i}",
            status="pending",
            current_stage="created",
            config_json={},
            source_task_ids=[],
            selected_templates=["miccai"],
        )
    await db_session.commit()

    user1, total1 = await PaperGenerationRunRepository.list_for_user(
        db_session, "user-1"
    )
    user2, total2 = await PaperGenerationRunRepository.list_for_user(
        db_session, "user-2"
    )
    everyone, total_all = await PaperGenerationRunRepository.list_for_user(
        db_session, None  # admin view
    )

    assert {r.paper_id for r in user1} == {"paper_0", "paper_1"}
    assert total1 == 2
    assert {r.paper_id for r in user2} == {"paper_2"}
    assert total2 == 1
    assert total_all == 3

async def test_list_for_user_filters_by_source_task_id(db_session) -> None:
    rows = [
        ("paper_main_a", "user-1", ["tsk_main"]),
        ("paper_main_b", "user-1", ["tsk_main", "tsk_ablation"]),
        ("paper_other", "user-1", ["tsk_other"]),
        ("paper_hidden", "user-2", ["tsk_main"]),
    ]
    for paper_id, user_id, source_task_ids in rows:
        await PaperGenerationRunRepository.create(
            db_session,
            paper_id=paper_id,
            user_id=user_id,
            title=paper_id,
            status="pending",
            current_stage="created",
            config_json={},
            source_task_ids=source_task_ids,
            selected_templates=["miccai"],
        )
    await db_session.commit()

    user_rows, user_total = await PaperGenerationRunRepository.list_for_user(
        db_session,
        "user-1",
        source_task_id="tsk_main",
    )
    admin_rows, admin_total = await PaperGenerationRunRepository.list_for_user(
        db_session,
        None,
        source_task_id="tsk_main",
    )

    assert {row.paper_id for row in user_rows} == {"paper_main_a", "paper_main_b"}
    assert user_total == 2
    assert {row.paper_id for row in admin_rows} == {
        "paper_main_a",
        "paper_main_b",
        "paper_hidden",
    }
    assert admin_total == 3


async def test_find_source_task_id_conflicts_is_scoped_to_user(db_session) -> None:
    rows = [
        ("paper_user_a", "user-1", ["tsk_shared", "tsk_a"]),
        ("paper_user_b", "user-1", ["tsk_b"]),
        ("paper_other", "user-2", ["tsk_shared"]),
    ]
    for paper_id, user_id, source_task_ids in rows:
        await PaperGenerationRunRepository.create(
            db_session,
            paper_id=paper_id,
            user_id=user_id,
            title=paper_id,
            status="pending",
            current_stage="created",
            config_json={},
            source_task_ids=source_task_ids,
            selected_templates=["miccai"],
        )
    await db_session.commit()

    user_conflicts = await PaperGenerationRunRepository.find_source_task_id_conflicts(
        db_session,
        "user-1",
        ["tsk_shared", "tsk_missing"],
    )
    other_conflicts = await PaperGenerationRunRepository.find_source_task_id_conflicts(
        db_session,
        "user-2",
        ["tsk_shared", "tsk_a"],
    )

    assert user_conflicts == {"tsk_shared"}
    assert other_conflicts == {"tsk_shared"}


async def test_list_for_user_pagination(db_session) -> None:
    for i in range(5):
        await PaperGenerationRunRepository.create(
            db_session,
            paper_id=f"paper_{i}",
            user_id="user-1",
            title=f"Paper {i}",
            status="pending",
            current_stage="created",
            config_json={},
            source_task_ids=[],
            selected_templates=["miccai"],
        )
    await db_session.commit()

    page1, total = await PaperGenerationRunRepository.list_for_user(
        db_session, "user-1", limit=2, offset=0
    )
    page2, _ = await PaperGenerationRunRepository.list_for_user(
        db_session, "user-1", limit=2, offset=2
    )
    page3, _ = await PaperGenerationRunRepository.list_for_user(
        db_session, "user-1", limit=2, offset=4
    )
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


async def test_delete_by_id_removes_row(created_run, db_session) -> None:
    deleted = await PaperGenerationRunRepository.delete_by_id(
        db_session, "paper_aaa"
    )
    assert deleted is True

    after = await PaperGenerationRunRepository.get_by_id(db_session, "paper_aaa")
    assert after is None
