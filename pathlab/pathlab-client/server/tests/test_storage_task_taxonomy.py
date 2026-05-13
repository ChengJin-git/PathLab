import types

import pytest

from gateway.models import ScanDirectoryRequest, StartBatchImportRequest
from gateway.routes import storage_scan, storage_tasks


@pytest.mark.asyncio
async def test_scan_directory_canonical_patch_segmentation_enables_annotation_scan(monkeypatch, tmp_path):
    captured = {}
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()

    def _fake_scan_directory_for_wsi(directory, *, include_annotation_json):
        captured["directory"] = directory
        captured["include_annotation_json"] = include_annotation_json
        return []

    monkeypatch.setattr(storage_scan, "_scan_directory_for_wsi", _fake_scan_directory_for_wsi)
    def _fake_create_scan_session(**kwargs):
        return {
            "scan_id": "scan-1",
            "directory": kwargs["directory"],
            "files": kwargs["files"],
            "created_at": 0,
            "user_id": kwargs["user_id"],
            "annotation_scan_enabled": kwargs["annotation_scan_enabled"],
            "valid_count": 0,
            "total_size": 0,
            "wsi_count": 0,
            "patch_count": 0,
        }

    monkeypatch.setattr(storage_scan, "create_scan_session", _fake_create_scan_session)
    monkeypatch.setattr(storage_scan, "get_scan_session", lambda *args, **kwargs: None)

    request = ScanDirectoryRequest(
        directory_path=str(scan_dir),
        task_type="patch_segmentation",
    )

    result = await storage_scan.scan_directory(request, user=types.SimpleNamespace(id="u1"))

    assert result["scan_id"] == "scan-1"
    assert captured["include_annotation_json"] is True


@pytest.mark.asyncio
async def test_batch_import_task_rejects_canonical_patch_segmentation_case_aggregation(monkeypatch):
    updates = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None


    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))

    monkeypatch.setattr(storage_tasks, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_tasks.StorageTaskRepository, "update_status", _fake_update_status)

    request = StartBatchImportRequest(
        task_type="patch_segmentation",
        aggregation_level="file",
    )
    params = storage_tasks._build_batch_import_task_params(
        request=request,
        resolved_files=[],
        resolved_scan_root=None,
    )
    params["aggregation_level"] = "case"

    await storage_tasks._run_batch_import_task("task-1", "u1", params)

    assert updates[-1][1] == "failed"
    assert updates[-1][2]["error_message"] == "Segmentation batch import must use aggregation_level='file'"


def test_build_batch_import_task_params_keeps_scan_session_selection_compact():
    request = StartBatchImportRequest(
        scan_id="scan_patch_1",
        select_all_valid=True,
        excluded_paths=["/patches/skip.png"],
        dataset_name="Patch Dataset",
        task_type="patch_classification",
        aggregation_level="file",
    )

    resolved_files = [
        {"path": f"/patches/{index}.png", "data_type": "patch", "valid": True}
        for index in range(1000)
    ]

    params = storage_tasks._build_batch_import_task_params(
        request=request,
        resolved_files=resolved_files,
        resolved_scan_root="/patches",
    )

    assert params["scan_id"] == "scan_patch_1"
    assert params["select_all_valid"] is True
    assert params["excluded_paths"] == ["/patches/skip.png"]
    assert params["files"] == []


@pytest.mark.asyncio
async def test_batch_import_task_resolves_compact_scan_selection_at_runtime(monkeypatch):
    resolved = {}
    updates = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))

    async def _fake_get_dataset_by_id(_db, dataset_id):
        resolved["dataset_id"] = dataset_id
        return None

    def _fake_resolve_scan_selection(session, **kwargs):
        resolved["session"] = session
        resolved["selection"] = kwargs
        return [{"path": "/patches/1.png", "data_type": "patch", "valid": True}]

    monkeypatch.setattr(storage_tasks, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_tasks.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_tasks.DatasetRepository, "get_by_id", _fake_get_dataset_by_id)
    monkeypatch.setattr(
        storage_tasks,
        "get_scan_session",
        lambda scan_id, user_id: {"scan_id": scan_id, "user_id": user_id},
    )
    monkeypatch.setattr(storage_tasks, "resolve_scan_selection", _fake_resolve_scan_selection)

    params = {
        "files": [],
        "scan_id": "scan_patch_1",
        "select_all_valid": True,
        "selected_paths": [],
        "excluded_paths": ["/patches/skip.png"],
        "dataset_id": "missing-dataset",
        "task_type": "patch_classification",
        "aggregation_level": "file",
    }

    await storage_tasks._run_batch_import_task("task-1", "u1", params)

    assert resolved["session"] == {"scan_id": "scan_patch_1", "user_id": "u1"}
    assert resolved["selection"] == {
        "select_all_valid": True,
        "selected_paths": [],
        "excluded_paths": ["/patches/skip.png"],
    }
    assert resolved["dataset_id"] == "missing-dataset"
    assert updates[-1][1] == "failed"
    assert updates[-1][2]["error_message"] == "Dataset not found: missing-dataset"
