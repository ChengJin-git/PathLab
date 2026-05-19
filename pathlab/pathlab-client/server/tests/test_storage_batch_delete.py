from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.sql.dml import Delete, Update


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_deletes_related_rows_once_per_table():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id="wsi_1",
            wsi_path="/tmp/wsi_1.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
        SimpleNamespace(
            wsi_id="wsi_2",
            wsi_path="/tmp/wsi_2.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
    ]

    with patch.object(
        storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
    ) as recompute:
        cleanup_items = await storage_tasks._bulk_delete_wsi_records(db, wsis)

    assert [item.wsi_id for item in cleanup_items] == ["wsi_1", "wsi_2"]
    delete_tables = {
        call.args[0].table.name
        for call in db.execute.await_args_list
        if isinstance(call.args[0], Delete)
    }
    assert delete_tables == {
        "training_task_wsi",
        "ai_results",
        "ai_tasks",
        "wsi_slides",
    }
    recompute.assert_awaited_once_with(db, "dataset_1")
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_unlinks_child_wsi_parent_references():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id="parent_wsi",
            wsi_path="/tmp/parent_wsi.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        )
    ]

    with patch.object(
        storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
    ):
        await storage_tasks._bulk_delete_wsi_records(db, wsis)

    statements = [call.args[0] for call in db.execute.await_args_list]
    parent_unlink_updates = [
        statement
        for statement in statements
        if isinstance(statement, Update) and statement.table.name == "wsi_slides"
    ]
    assert len(parent_unlink_updates) == 1


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_recomputes_each_dataset_once():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id="wsi_1",
            wsi_path="/tmp/wsi_1.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
        SimpleNamespace(
            wsi_id="wsi_2",
            wsi_path="/tmp/wsi_2.svs",
            dataset_id="dataset_2",
            user_id="user_1",
        ),
        SimpleNamespace(
            wsi_id="wsi_3",
            wsi_path="/tmp/wsi_3.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
    ]

    with patch.object(
        storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
    ) as recompute:
        await storage_tasks._bulk_delete_wsi_records(db, wsis)

    assert recompute.await_count == 2
    recomputed_dataset_ids = {call.args[1] for call in recompute.await_args_list}
    assert recomputed_dataset_ids == {"dataset_1", "dataset_2"}


@pytest.mark.asyncio
async def test_resolve_deletable_wsies_rejects_missing_before_authorization():
    from fastapi import HTTPException
    from gateway.routes import storage_tasks

    db = AsyncMock()
    user = SimpleNamespace(id="user_1", is_admin=lambda: False)
    wsi = SimpleNamespace(wsi_id="wsi_1", user_id="other_user")

    with patch.object(
        storage_tasks.WSIRepository,
        "get_by_ids",
        new=AsyncMock(return_value={"wsi_1": wsi}),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await storage_tasks._resolve_deletable_wsies(db, ["wsi_1", "missing"], user)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_deletable_wsies_rejects_non_owner():
    from fastapi import HTTPException
    from gateway.routes import storage_tasks

    db = AsyncMock()
    user = SimpleNamespace(id="user_1", is_admin=lambda: False)
    wsi = SimpleNamespace(wsi_id="wsi_1", user_id="other_user")

    with patch.object(
        storage_tasks.WSIRepository,
        "get_by_ids",
        new=AsyncMock(return_value={"wsi_1": wsi}),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await storage_tasks._resolve_deletable_wsies(db, ["wsi_1"], user)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_deletable_wsies_allows_admin():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    user = SimpleNamespace(id="admin_1", is_admin=lambda: True)
    wsi = SimpleNamespace(wsi_id="wsi_1", user_id="other_user")

    with patch.object(
        storage_tasks.WSIRepository,
        "get_by_ids",
        new=AsyncMock(return_value={"wsi_1": wsi}),
    ):
        resolved = await storage_tasks._resolve_deletable_wsies(db, ["wsi_1"], user)

    assert resolved == [wsi]


@pytest.mark.asyncio
async def test_delete_dataset_task_uses_bulk_delete_once():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    dataset = SimpleNamespace(dataset_id="dataset_1", name="Dataset 1", user_id="user_1")
    wsis = [
        SimpleNamespace(
            wsi_id="wsi_1",
            wsi_path="/tmp/wsi_1.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
        SimpleNamespace(
            wsi_id="wsi_2",
            wsi_path="/tmp/wsi_2.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
    ]
    cleanup_items = [
        storage_tasks.WSICleanupItem(w.wsi_id, w.wsi_path, w.dataset_id, w.user_id)
        for w in wsis
    ]

    class SessionFactory:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch.object(storage_tasks, "async_session", return_value=SessionFactory()),
        patch.object(
            storage_tasks.DatasetRepository,
            "get_by_id",
            new=AsyncMock(return_value=dataset),
        ),
        patch.object(
            storage_tasks.DatasetRepository,
            "get_wsi_ids",
            new=AsyncMock(return_value=["wsi_1", "wsi_2"]),
        ),
        patch.object(
            storage_tasks.WSIRepository,
            "get_by_ids",
            new=AsyncMock(return_value={"wsi_1": wsis[0], "wsi_2": wsis[1]}),
        ),
        patch.object(
            storage_tasks,
            "_bulk_delete_wsi_records",
            new=AsyncMock(return_value=cleanup_items),
        ) as bulk_delete,
        patch.object(
            storage_tasks,
            "_cleanup_deleted_wsi_files",
            new=AsyncMock(return_value=([], 2, 0)),
        ),
        patch.object(
            storage_tasks.DatasetRepository, "delete", new=AsyncMock(return_value=True)
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ),
        patch.object(storage_tasks, "invalidate_chat_context", new=AsyncMock()),
    ):
        await storage_tasks._run_delete_dataset_task(
            "task_1", "user_1", "dataset_1", "standard"
        )

    bulk_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_delete_dataset_task_does_not_materialize_wsi_ids_before_returning():
    from gateway.models import DeletionMode, StartDeleteDatasetRequest
    from gateway.routes import storage_tasks

    db = AsyncMock()
    user = SimpleNamespace(id="user_1")
    dataset = SimpleNamespace(dataset_id="dataset_1", name="Dataset 1", user_id="user_1")
    background_tasks = SimpleNamespace(add_task=lambda *args, **kwargs: None)

    with (
        patch.object(
            storage_tasks,
            "get_dataset_with_access",
            new=AsyncMock(return_value=dataset),
        ),
        patch.object(
            storage_tasks.DatasetRepository,
            "get_wsi_ids",
            new=AsyncMock(side_effect=AssertionError("must not load every WSI ID")),
        ) as get_wsi_ids,
        patch.object(
            storage_tasks.DatasetStatsRepository,
            "get_by_dataset_id",
            new=AsyncMock(return_value=SimpleNamespace(file_count=250000)),
        ) as get_stats,
        patch.object(
            storage_tasks.StorageTaskRepository,
            "create",
            new=AsyncMock(),
        ) as create_task,
        patch.object(storage_tasks.uuid, "uuid4", return_value=SimpleNamespace(hex="abc123")),
    ):
        response = await storage_tasks.start_delete_dataset_task(
            StartDeleteDatasetRequest(dataset_id="dataset_1", mode=DeletionMode.STANDARD),
            background_tasks,
            user,
            db,
        )

    get_wsi_ids.assert_not_awaited()
    get_stats.assert_awaited_once_with(db, "dataset_1")
    create_task.assert_awaited_once()
    assert create_task.await_args is not None
    assert create_task.await_args.kwargs["total_items"] == 250000
    assert response["total_items"] == 250000
