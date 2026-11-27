import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from gateway.models import DatasetPropertiesRequest
from gateway.routes import wsi, training
from backend.common import chat_context_cache


async def test_dataset_properties_validate_combination_before_writing(monkeypatch):
    dataset = SimpleNamespace(
        data_type="wsi", tasks=[SimpleNamespace(task_type="wsi_classification")], aggregation_level="case", revision=1
    )
    monkeypatch.setattr('gateway.routes.dataset_catalog.require_write_scope', AsyncMock(return_value=dataset))
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await wsi.update_dataset_properties(
            "ds",
            DatasetPropertiesRequest(
                name="new", task_types=["patch_segmentation"], aggregation_level="file"
            ),
            SimpleNamespace(),
            db,
        )
    assert error.value.status_code == 422
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_dataset_properties_single_commit_and_skip_unchanged_slide_fields(
    monkeypatch,
):
    group = SimpleNamespace(
        group_id="g",
        data_type="patch",
        task_type="patch_classification",
        aggregation_level="file",
    )
    dataset = SimpleNamespace(
        dataset_id="ds",
        name="old",
        data_type='patch', aggregation_level='file', tasks=[group], revision=1,
        user_id="u",
        is_public=False,
    )
    dataset.to_dict = lambda: {"name": dataset.name}
    check = AsyncMock(return_value=dataset)
    monkeypatch.setattr('gateway.routes.dataset_catalog.require_write_scope', check)
    monkeypatch.setattr(wsi, "invalidate_chat_context", AsyncMock())
    db = AsyncMock()
    db.scalar.return_value = None
    result = await wsi.update_dataset_properties(
        "ds", DatasetPropertiesRequest(name="new"), SimpleNamespace(id="u"), db
    )
    check.assert_awaited_once_with(
        db, SimpleNamespace(id="u"), "ds", None
    )
    db.commit.assert_awaited_once()
    db.execute.assert_not_awaited()
    assert result["dataset"]["name"] == "new"


async def test_revision_invalidation_is_batched_and_bounded(monkeypatch):
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock()
    monkeypatch.setattr(
        chat_context_cache,
        "get_redis",
        lambda: SimpleNamespace(pipeline=lambda **kwargs: pipe),
    )
    await chat_context_cache.invalidate_all_user_chat_contexts(["u", "v", "u"])
    assert pipe.incr.call_count == 3  # users plus shared scope revision
    pipe.execute.assert_awaited_once()
    started = asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    pipe.execute.side_effect = blocked
    await asyncio.wait_for(chat_context_cache.invalidate_chat_context("u"), 0.8)
    assert started.is_set()


async def test_delete_publishes_cancellation_before_commit_and_defers_http(monkeypatch):
    events = []
    task = SimpleNamespace(user_id="u")
    monkeypatch.setattr(
        training.TrainingTaskRepository, "get_by_id", AsyncMock(return_value=task)
    )
    monkeypatch.setattr(
        training.TrainedModelRepository, "get_by_task_id", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(training.AIResultRepository, "delete_by_task_id", AsyncMock())
    monkeypatch.setattr(training.TrainingTaskRepository, "delete", AsyncMock())

    async def publish(_):
        events.append("cancel")

    monkeypatch.setattr(training, "publish_task_cancellation", publish)
    notify = AsyncMock()
    monkeypatch.setattr(training, "cancel_ai_service_training", notify)
    monkeypatch.setattr(training, "invalidate_chat_context", AsyncMock())

    async def enqueue(*args, **kwargs):
        events.append('outbox')
        return SimpleNamespace(task_id='cleanup')
    monkeypatch.setattr('backend.storage.deletion.enqueue', enqueue)

    async def commit():
        events.append("commit")

    response = await training.delete_training_task(
        "fixture",
        SimpleNamespace(id="u", is_admin=lambda: False),
        SimpleNamespace(commit=commit),
    )
    assert events == ["cancel", "outbox", "commit"]
    notify.assert_not_awaited()
    assert response["storage_cleanup"]["status"] == "scheduled"


async def test_progress_only_fetches_visible_tasks_and_tolerates_invalid_values(
    monkeypatch,
):
    from backend.common import progress_store

    mget = AsyncMock(return_value=["0", "95", "bad", None])
    monkeypatch.setattr(progress_store, "get_redis", lambda: SimpleNamespace(mget=mget))
    result = await progress_store.get_progress_batch(["a", "b", "c", "d"])
    assert result == {"a": 0, "b": 95}
    mget.assert_awaited_once_with(
        ["pathlab:progress:" + task for task in ["a", "b", "c", "d"]]
    )


async def test_dataset_properties_still_enforce_ownership(monkeypatch):
    from backend.auth.dependencies import get_dataset_with_access

    monkeypatch.setattr(wsi, "get_dataset_with_access", get_dataset_with_access)
    monkeypatch.setattr(
        wsi.DatasetRepository,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(user_id="someone-else")),
    )
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await wsi.update_dataset_properties(
            "ds",
            DatasetPropertiesRequest(name="not allowed"),
            SimpleNamespace(id="u", is_admin=lambda: False),
            db,
        )
    assert error.value.status_code == 403
    db.commit.assert_not_awaited()


async def test_missing_task_cannot_enqueue_file_deletion(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(training, "publish_task_cancellation", publish)
    db = AsyncMock()
    monkeypatch.setattr(training.TrainingTaskRepository,'get_by_id',AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        await training.delete_training_task("fixture", SimpleNamespace(), db)
    assert error.value.status_code == 404
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_cancellation_timeout_does_not_report_deleted_or_modify_rows(monkeypatch):
    monkeypatch.setattr(
        training.TrainingTaskRepository,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(user_id="u")),
    )
    monkeypatch.setattr(
        training, "publish_task_cancellation", AsyncMock(side_effect=TimeoutError())
    )
    remove = AsyncMock()
    monkeypatch.setattr(training.TrainingTaskRepository, "delete", remove)
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await training.delete_training_task(
            "fixture", SimpleNamespace(id="u", is_admin=lambda: False), db
        )
    assert error.value.status_code == 503
    remove.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_visibility_change_still_stops_non_owner_tasks(monkeypatch):
    from gateway.routes import dataset_visibility

    stop = AsyncMock(return_value={"other": ["active-task"]})
    monkeypatch.setattr(dataset_visibility, "stop_non_owner_training_tasks", stop)
    dataset = SimpleNamespace(dataset_id="ds", user_id="owner", is_public=True)
    db = AsyncMock()
    effects = await dataset_visibility.apply_dataset_visibility(db, dataset, False)
    stop.assert_awaited_once_with(db, "ds", "owner")
    assert dataset.is_public is False
    assert effects["revoked_training_tasks"] == 1
