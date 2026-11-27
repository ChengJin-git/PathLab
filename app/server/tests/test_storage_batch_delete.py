from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.sql import visitors
from sqlalchemy.sql.dml import Delete, Update


@pytest.fixture(autouse=True)
def mock_cleanup_outbox(monkeypatch):
    monkeypatch.setattr('backend.storage.deletion.enqueue',AsyncMock())


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
    assert db.flush.await_count >= 1


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
async def test_bulk_delete_wsi_records_chunks_large_id_lists_below_asyncpg_limit():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id=f"patch_{index}",
            wsi_path=f"/tmp/patch_{index}.png",
            dataset_id="dataset_1",
            user_id="user_1",
        )
        for index in range(32768)
    ]

    with patch.object(
        storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
    ):
        await storage_tasks._bulk_delete_wsi_records(db, wsis)

    largest_expanding_bind = 0
    for call in db.execute.await_args_list:
        statement = call.args[0]

        def visit_bindparam(bind):
            nonlocal largest_expanding_bind
            value = getattr(bind, "value", None)
            if isinstance(value, list):
                largest_expanding_bind = max(largest_expanding_bind, len(value))

        visitors.traverse(statement, {}, {"bindparam": visit_bindparam})

    assert largest_expanding_bind <= storage_tasks.WSI_DELETE_DB_BATCH_SIZE
    assert largest_expanding_bind < 32767


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_counts_deleted_items_from_first_db_batch():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id=f"patch_{index}",
            wsi_path=f"/tmp/patch_{index}.png",
            dataset_id="dataset_1",
            user_id="user_1",
        )
        for index in range(3)
    ]

    with (
        patch.object(storage_tasks, "WSI_DELETE_DB_BATCH_SIZE", 2),
        patch.object(
            storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
        ) as recompute,
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
        patch.object(storage_tasks, "is_storage_task_cancelled", return_value=False),
    ):
        await storage_tasks._bulk_delete_wsi_records(
            db,
            wsis,
            task_id="task_1",
            commit_batches=True,
        )

    assert db.execute.await_count == 15
    update_status.assert_any_await(
        db,
        "task_1",
        "processing",
        progress=33,
        processed_items=1,
    )
    update_status.assert_any_await(
        db,
        "task_1",
        "processing",
        progress=66,
        processed_items=2,
    )
    update_status.assert_any_await(
        db,
        "task_1",
        "processing",
        progress=100,
        processed_items=3,
    )
    recompute.assert_awaited_once_with(db, "dataset_1")


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_reports_small_datasets_one_item_at_a_time():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id=f"patch_{index}",
            wsi_path=f"/tmp/patch_{index}.png",
            dataset_id="dataset_1",
            user_id="user_1",
        )
        for index in range(3)
    ]

    with (
        patch.object(storage_tasks, "WSI_DELETE_DB_BATCH_SIZE", 10),
        patch.object(
            storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
        patch.object(storage_tasks, "is_storage_task_cancelled", return_value=False),
    ):
        await storage_tasks._bulk_delete_wsi_records(
            db,
            wsis,
            task_id="task_1",
            commit_batches=True,
        )

    progress_updates = [
        call.kwargs["processed_items"]
        for call in update_status.await_args_list
        if call.args[2] == "processing"
    ]
    assert progress_updates == [1, 2, 3]


@pytest.mark.asyncio
async def test_bulk_delete_wsi_records_stops_after_cancellation_between_batches():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id=f"patch_{index}",
            wsi_path=f"/tmp/patch_{index}.png",
            dataset_id="dataset_1",
            user_id="user_1",
        )
        for index in range(3)
    ]

    with (
        patch.object(storage_tasks, "WSI_DELETE_DB_BATCH_SIZE", 2),
        patch.object(
            storage_tasks.DatasetStatsRepository, "recompute", new=AsyncMock()
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
        patch.object(
            storage_tasks, "is_storage_task_cancelled", side_effect=[False, True]
        ),
        patch.object(storage_tasks, "clear_storage_task_cancellation") as clear_cancel,
    ):
        with pytest.raises(storage_tasks.StorageTaskCancelledError):
            await storage_tasks._bulk_delete_wsi_records(
                db,
                wsis,
                task_id="task_1",
                commit_batches=True,
            )

    assert db.execute.await_count == 5
    update_status.assert_any_await(
        db,
        "task_1",
        "processing",
        progress=33,
        processed_items=1,
    )
    update_status.assert_any_await(
        db,
        "task_1",
        "cancelled",
        progress=33,
        processed_items=1,
        error_message="Task cancelled by user",
    )
    clear_cancel.assert_called_once_with("task_1")


@pytest.mark.asyncio
async def test_cleanup_deleted_wsi_files_does_not_regress_reported_processed_items():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    cleanup_items = [
        storage_tasks.WSICleanupItem(
            wsi_id="patch_1",
            wsi_path="/tmp/patch_1.png",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
        storage_tasks.WSICleanupItem(
            wsi_id="patch_2",
            wsi_path="/tmp/patch_2.png",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
    ]

    with (
        patch.object(storage_tasks, "is_storage_task_cancelled", return_value=False),
        patch.object(
            storage_tasks.storage_manager,
            "get_wsi_storage_info",
            return_value={"failed": [], "summary": "ok"},
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
    ):
        await storage_tasks._cleanup_deleted_wsi_files(
            db,
            "task_1",
            cleanup_items,
            progress_start=100,
            progress_span=0,
            processed_items_floor=len(cleanup_items),
        )

    for call in update_status.await_args_list:
        assert call.kwargs["processed_items"] == len(cleanup_items)
        assert call.kwargs["progress"] == 100


@pytest.mark.asyncio
async def test_completed_storage_task_status_clears_stale_error_message():
    from backend.database.repositories.storage_task import StorageTaskRepository

    db = AsyncMock()
    result = SimpleNamespace(rowcount=1)
    db.execute.return_value = result

    updated = await StorageTaskRepository.update_status(
        db,
        "delete_dataset_task_1",
        "completed",
        progress=100,
        processed_items=10,
        success_count=10,
        failed_count=0,
        error_message=None,
    )

    assert updated is True
    statement = db.execute.await_args.args[0]
    assert isinstance(statement, Update)
    compiled_params = statement.compile().params
    assert "error_message" in compiled_params
    assert compiled_params["error_message"] is None


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
            "task_1", "user_1", "dataset_1"
        )

    bulk_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_external_task_uses_bulk_delete_once():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsis = [
        SimpleNamespace(
            wsi_id="wsi_1",
            wsi_path="/mnt/external/wsi_1.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
        SimpleNamespace(
            wsi_id="wsi_2",
            wsi_path="/mnt/external/wsi_2.svs",
            dataset_id="dataset_1",
            user_id="user_1",
        ),
    ]
    cleanup_items = [
        storage_tasks.WSICleanupItem(w.wsi_id, w.wsi_path, w.dataset_id, w.user_id)
        for w in wsis
    ]
    cleanup_results = [
        {"wsi_id": "wsi_1", "status": "deleted", "message": "cleanup ok"},
        {"wsi_id": "wsi_2", "status": "deleted", "message": "cleanup ok"},
    ]

    class SessionFactory:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch.object(storage_tasks, "async_session", return_value=SessionFactory()),
        patch.object(
            storage_tasks.WSIRepository,
            "get_by_ids",
            new=AsyncMock(return_value={"wsi_1": wsis[0], "wsi_2": wsis[1]}),
        ) as get_by_ids,
        patch.object(
            storage_tasks,
            "_bulk_delete_wsi_records",
            new=AsyncMock(return_value=cleanup_items),
        ) as bulk_delete,
        patch.object(
            storage_tasks,
            "_delete_wsi_record_and_files",
            new=AsyncMock(side_effect=AssertionError("must not delete one row at a time")),
        ) as per_row_delete,
        patch.object(
            storage_tasks,
            "_cleanup_deleted_wsi_files",
            new=AsyncMock(return_value=(cleanup_results, 2, 0)),
        ) as cleanup_files,
        patch.object(
            storage_tasks,
            "_cleanup_empty_dataset_record",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
        patch.object(storage_tasks, "is_storage_task_cancelled", return_value=False),
    ):
        await storage_tasks._run_delete_external_task(
            "task_1", "user_1", ["wsi_1", "wsi_2"]
        )

    get_by_ids.assert_awaited_once_with(db, ["wsi_1", "wsi_2"])
    bulk_delete.assert_awaited_once_with(
        db, wsis, task_id="task_1", commit_batches=True
    )
    cleanup_files.assert_awaited_once()
    cleanup_arg_items = cleanup_files.await_args.args[2]
    assert [item.wsi_path for item in cleanup_arg_items] == ["", ""]
    final_update = update_status.await_args
    assert final_update.kwargs["success_count"] == 2
    assert final_update.kwargs["failed_count"] == 0
    assert final_update.kwargs["results"] == cleanup_results
    per_row_delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_external_task_preserves_cancelled_status():
    from gateway.routes import storage_tasks

    db = AsyncMock()
    wsi = SimpleNamespace(
        wsi_id="wsi_1",
        wsi_path="/mnt/external/wsi_1.svs",
        dataset_id="dataset_1",
        user_id="user_1",
    )

    class SessionFactory:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch.object(storage_tasks, "async_session", return_value=SessionFactory()),
        patch.object(
            storage_tasks.WSIRepository,
            "get_by_ids",
            new=AsyncMock(return_value={"wsi_1": wsi}),
        ),
        patch.object(
            storage_tasks,
            "_bulk_delete_wsi_records",
            new=AsyncMock(side_effect=storage_tasks.StorageTaskCancelledError()),
        ),
        patch.object(
            storage_tasks.StorageTaskRepository, "update_status", new=AsyncMock()
        ) as update_status,
    ):
        await storage_tasks._run_delete_external_task("task_1", "user_1", ["wsi_1"])

    statuses = [call.args[2] for call in update_status.await_args_list]
    assert statuses == ["processing"]


@pytest.mark.asyncio
async def test_start_delete_dataset_task_does_not_materialize_wsi_ids_before_returning():
    from gateway.models import StartDeleteDatasetRequest
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
            StartDeleteDatasetRequest(dataset_id="dataset_1"),
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
