import types

import pytest
from fastapi import BackgroundTasks

from gateway.models import StartScanDirectoryTaskRequest
from gateway.routes import storage_scan, storage_tasks


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_start_scan_directory_task_creates_storage_task(monkeypatch, tmp_path):
    created = {}
    scheduled = {}
    scan_dir = tmp_path / "patches"
    scan_dir.mkdir()

    async def _fake_create(_db, **kwargs):
        created.update(kwargs)
        return types.SimpleNamespace(task_id=kwargs["task_id"])

    def _fake_add_task(func, *args, **kwargs):
        scheduled["func"] = func
        scheduled["args"] = args
        scheduled["kwargs"] = kwargs

    monkeypatch.setattr(storage_scan.StorageTaskRepository, "create", _fake_create)
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(background_tasks, "add_task", _fake_add_task)

    result = await storage_scan.start_scan_directory_task(
        StartScanDirectoryTaskRequest(
            directory_path=str(scan_dir),
            task_type="patch_classification",
            page_size=250,
        ),
        background_tasks=background_tasks,
        user=types.SimpleNamespace(id="u1"),
        db=FakeSession(),
    )

    assert result["task_id"].startswith("scan_")
    assert result["message"] == "Directory scan task started"
    assert created["task_type"] == "scan_directory"
    assert created["user_id"] == "u1"
    assert created["params"] == {
        "directory_path": str(scan_dir),
        "task_type": "patch_classification",
        "page_size": 250,
    }
    assert scheduled["func"] is storage_scan._run_scan_directory_task
    assert scheduled["args"] == (result["task_id"], "u1", created["params"])


@pytest.mark.asyncio
async def test_scan_directory_task_completes_with_scan_id(monkeypatch, tmp_path):
    updates = []
    scan_dir = tmp_path / "patches"
    scan_dir.mkdir()
    (scan_dir / "a.png").write_bytes(b"patch")

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))
        return True

    def _fake_create_scan_session(**kwargs):
        return {
            "scan_id": "scan-session-1",
            "directory": kwargs["directory"],
            "files": kwargs["files"],
            "created_at": 0,
            "user_id": kwargs["user_id"],
            "annotation_scan_enabled": kwargs["annotation_scan_enabled"],
            "valid_count": 1,
            "total_size": 5,
            "wsi_count": 0,
            "patch_count": 1,
        }

    monkeypatch.setattr(storage_scan, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_scan.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_scan, "create_scan_session", _fake_create_scan_session)

    await storage_scan._run_scan_directory_task(
        "scan_task_1",
        "u1",
        {
            "directory_path": str(scan_dir),
            "task_type": "patch_classification",
            "page_size": 100,
        },
    )

    assert updates[0] == (
        "scan_task_1",
        "processing",
        {"progress": 0, "processed_items": 0},
    )
    assert updates[-1][1] == "completed"
    assert updates[-1][2]["progress"] == 100
    assert updates[-1][2]["processed_items"] == 1
    assert updates[-1][2]["success_count"] == 1
    assert updates[-1][2]["results"] == {
        "scan_id": "scan-session-1",
        "directory": str(scan_dir),
        "total_count": 1,
        "valid_count": 1,
        "wsi_count": 0,
        "patch_count": 1,
        "page_size": 100,
        "annotation_scan_enabled": False,
    }


@pytest.mark.asyncio
async def test_scan_directory_task_marks_failure(monkeypatch, tmp_path):
    updates = []
    scan_dir = tmp_path / "patches"
    scan_dir.mkdir()

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))
        return True

    def _fake_scan_directory_for_wsi(_directory, *, include_annotation_json=False):
        raise RuntimeError("disk error")

    monkeypatch.setattr(storage_scan, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_scan.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_scan, "_scan_directory_for_wsi", _fake_scan_directory_for_wsi)

    await storage_scan._run_scan_directory_task(
        "scan_task_1",
        "u1",
        {
            "directory_path": str(scan_dir),
            "task_type": "patch_classification",
            "page_size": 100,
        },
    )

    assert updates[-1][1] == "failed"
    assert updates[-1][2]["error_message"] == "disk error"


@pytest.mark.asyncio
async def test_scan_directory_task_preserves_user_cancel_after_scan_finishes(monkeypatch, tmp_path):
    updates = []
    scan_dir = tmp_path / "patches"
    scan_dir.mkdir()
    (scan_dir / "a.png").write_bytes(b"patch")

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))
        return True

    scanned = False

    def _fake_scan_directory(_directory, *, include_annotation_json=False):
        nonlocal scanned
        scanned = True
        return [{"valid": True}]

    def _fake_is_cancelled(task_id):
        return task_id == "scan_task_1" and scanned

    def _fake_clear_cancelled(task_id):
        updates.append((task_id, "clear_cancel", {}))

    monkeypatch.setattr(storage_scan, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_scan.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_scan, "_scan_directory_for_wsi", _fake_scan_directory)
    monkeypatch.setattr(storage_tasks, "is_storage_task_cancelled", _fake_is_cancelled)
    monkeypatch.setattr(storage_tasks, "clear_storage_task_cancellation", _fake_clear_cancelled)

    await storage_scan._run_scan_directory_task(
        "scan_task_1",
        "u1",
        {
            "directory_path": str(scan_dir),
            "task_type": "patch_classification",
            "page_size": 100,
        },
    )

    statuses = [status for _, status, _ in updates]
    assert scanned is True
    assert "cancelled" in statuses
    assert "completed" not in statuses


@pytest.mark.asyncio
async def test_start_unbind_dataset_task_uses_external_sql_lookup(monkeypatch):
    created = {}
    scheduled = {}

    async def _fake_get_external_refs(_db, dataset_ids):
        assert dataset_ids == ["dataset-1"]
        return {
            "dataset-1": [
                {"wsi_id": "external-1", "wsi_path": "/mnt/a.svs"},
                {"wsi_id": "external-2", "wsi_path": "/mnt/b.svs"},
            ]
        }

    async def _fake_create(_db, **kwargs):
        created.update(kwargs)
        return types.SimpleNamespace(task_id=kwargs["task_id"])

    async def _fake_get_by_id(_db, _dataset_id):
        return types.SimpleNamespace(name="External Dataset")

    def _fake_add_task(func, *args, **kwargs):
        scheduled["func"] = func
        scheduled["args"] = args
        scheduled["kwargs"] = kwargs

    monkeypatch.setattr(
        storage_scan.DatasetRepository,
        "get_external_wsi_path_refs_batch",
        _fake_get_external_refs,
    )
    monkeypatch.setattr(
        storage_scan.WSIRepository,
        "get_by_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not load the whole dataset")
        ),
    )
    monkeypatch.setattr(
        storage_scan.DatasetRepository,
        "get_by_id",
        _fake_get_by_id,
    )
    monkeypatch.setattr(storage_scan.StorageTaskRepository, "create", _fake_create)
    monkeypatch.setattr(
        storage_scan.uuid, "uuid4", lambda: types.SimpleNamespace(hex="abc123")
    )
    background_tasks = BackgroundTasks()
    monkeypatch.setattr(background_tasks, "add_task", _fake_add_task)

    result = await storage_scan.start_unbind_dataset_task(
        "dataset-1",
        background_tasks=background_tasks,
        user=types.SimpleNamespace(id="admin-1"),
        db=FakeSession(),
    )

    assert result["task_id"] == "unbind_abc123"
    assert result["total_files"] == 2
    assert created["task_type"] == "unbind_dataset"
    assert created["total_items"] == 2
    assert created["params"]["wsi_ids"] == ["external-1", "external-2"]
    assert scheduled["func"] is storage_tasks._run_delete_external_task
    assert scheduled["args"] == (
        "unbind_abc123",
        "admin-1",
        ["external-1", "external-2"],
    )
