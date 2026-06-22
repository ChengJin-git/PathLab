import types
from unittest.mock import AsyncMock

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


@pytest.mark.asyncio
async def test_batch_import_task_maps_default_classification_to_patch_classification(monkeypatch, tmp_path):
    captured = {}
    updates = []
    patch_path = tmp_path / "tumor.png"
    patch_path.write_bytes(b"patch")

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))

    async def _fake_get_or_create_data_group(_db, **kwargs):
        captured["data_group"] = kwargs
        return types.SimpleNamespace(
            group_id="group-patch",
            data_type=kwargs["data_type"],
            aggregation_level=kwargs["aggregation_level"],
            task_type=kwargs["task_type"],
        )

    async def _fake_get_or_create_dataset(_db, dataset_name, **kwargs):
        return types.SimpleNamespace(
            dataset_id="dataset-patch",
            name=dataset_name,
            user_id=kwargs.get("user_id"),
            data_group=types.SimpleNamespace(
                data_type="patch",
                aggregation_level="file",
                task_type="patch_classification",
            ),
        )

    async def _fake_align_dataset_data_type_for_file(_db, dataset, **kwargs):
        captured["align"] = kwargs
        return dataset

    async def _fake_get_original_filenames_by_dataset(_db, dataset_id, filenames):
        return set()

    async def _fake_create_wsi(_db, **kwargs):
        captured["wsi"] = kwargs
        return types.SimpleNamespace(**kwargs)

    async def _fake_recompute(_db, dataset_id):
        captured["recompute_dataset_id"] = dataset_id

    monkeypatch.setattr(storage_tasks, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_tasks.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_tasks.DataGroupRepository, "get_or_create", _fake_get_or_create_data_group)
    monkeypatch.setattr(storage_tasks.DatasetRepository, "get_or_create", _fake_get_or_create_dataset)
    monkeypatch.setattr(storage_tasks, "align_dataset_data_type_for_file", _fake_align_dataset_data_type_for_file)
    monkeypatch.setattr(
        storage_tasks.WSIRepository,
        "get_original_filenames_by_dataset",
        _fake_get_original_filenames_by_dataset,
    )
    monkeypatch.setattr(storage_tasks.WSIRepository, "create", _fake_create_wsi)
    monkeypatch.setattr(storage_tasks.DatasetStatsRepository, "recompute", _fake_recompute)
    monkeypatch.setattr(storage_tasks.storage_manager, "save_wsi_metadata", lambda *_args, **_kwargs: None)

    await storage_tasks._run_batch_import_task(
        "task-1",
        "u1",
        {
            "files": [{"path": str(patch_path), "data_type": "patch", "valid": True}],
            "dataset_name": "Patch Dataset",
            "task_type": "wsi_classification",
            "aggregation_level": "file",
            "default_label": "tumor",
        },
    )

    assert captured["data_group"] == {
        "data_type": "patch",
        "aggregation_level": "file",
        "task_type": "patch_classification",
    }
    assert captured["align"]["task_type"] == "patch_classification"
    assert updates[-1][1] == "completed"


@pytest.mark.parametrize(
    ("task_type", "data_type", "aggregation_level", "filename"),
    [
        ("wsi_classification", "wsi", "case", "slide.svs"),
        ("patch_classification", "patch", "file", "patch.png"),
        ("wsi_survival", "wsi", "case", "survival.svs"),
        ("patch_segmentation", "patch", "file", "segmentation.png"),
    ],
)
@pytest.mark.asyncio
async def test_batch_import_task_accepts_all_canonical_task_terms(
    monkeypatch,
    tmp_path,
    task_type,
    data_type,
    aggregation_level,
    filename,
):
    captured = {}
    updates = []
    file_path = tmp_path / filename
    file_path.write_bytes(b"data")
    annotation_path = tmp_path / "segmentation.json"
    annotation_path.write_text('{"images": [], "annotations": [], "categories": []}')

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    async def _fake_update_status(_db, task_id, status, **kwargs):
        updates.append((task_id, status, kwargs))

    async def _fake_get_or_create_data_group(_db, **kwargs):
        captured["data_group"] = kwargs
        return types.SimpleNamespace(
            group_id="group-canonical",
            data_type=kwargs["data_type"],
            aggregation_level=kwargs["aggregation_level"],
            task_type=kwargs["task_type"],
        )

    async def _fake_get_or_create_dataset(_db, dataset_name, **kwargs):
        return types.SimpleNamespace(
            dataset_id="dataset-canonical",
            name=dataset_name,
            user_id=kwargs.get("user_id"),
            data_group=types.SimpleNamespace(
                data_type=data_type,
                aggregation_level=aggregation_level,
                task_type=task_type,
            ),
        )

    async def _fake_align_dataset_data_type_for_file(_db, dataset, **kwargs):
        captured.setdefault("align", []).append(kwargs)
        return dataset

    async def _fake_get_original_filenames_by_dataset(_db, dataset_id, filenames):
        return set()

    async def _fake_create_wsi(_db, **kwargs):
        captured["wsi"] = kwargs
        return types.SimpleNamespace(**kwargs)

    async def _fake_upsert_annotation(_db, **kwargs):
        captured["annotation"] = kwargs

    async def _fake_recompute(_db, dataset_id):
        captured["recompute_dataset_id"] = dataset_id

    def _fake_resolve_file_data_type_and_properties(_file_path, **_kwargs):
        return data_type, {
            "file_size": file_path.stat().st_size,
            "width": 100,
            "height": 200,
            "mpp": None,
            "magnification": None,
            "vendor": None,
        }

    monkeypatch.setattr(storage_tasks, "async_session", lambda: FakeSession())
    monkeypatch.setattr(storage_tasks.StorageTaskRepository, "update_status", _fake_update_status)
    monkeypatch.setattr(storage_tasks.DataGroupRepository, "get_or_create", _fake_get_or_create_data_group)
    monkeypatch.setattr(storage_tasks.DatasetRepository, "get_or_create", _fake_get_or_create_dataset)
    monkeypatch.setattr(storage_tasks, "align_dataset_data_type_for_file", _fake_align_dataset_data_type_for_file)
    monkeypatch.setattr(
        storage_tasks.WSIRepository,
        "get_original_filenames_by_dataset",
        _fake_get_original_filenames_by_dataset,
    )
    monkeypatch.setattr(storage_tasks.WSIRepository, "create", _fake_create_wsi)
    monkeypatch.setattr(storage_tasks.DatasetStatsRepository, "recompute", _fake_recompute)
    monkeypatch.setattr(storage_tasks.storage_manager, "save_wsi_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storage_tasks, "resolve_file_data_type_and_properties", _fake_resolve_file_data_type_and_properties)
    monkeypatch.setattr(storage_tasks, "find_matching_segmentation_annotation_path", lambda _path: annotation_path)
    monkeypatch.setattr(storage_tasks, "load_coco_annotation_file", lambda _path: {"images": [], "annotations": [], "categories": []})
    monkeypatch.setattr(storage_tasks.SegmentationAnnotationRepository, "upsert", _fake_upsert_annotation)
    monkeypatch.setattr(storage_tasks, "rebuild_dataset_annotation_summary_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storage_tasks, "invalidate_chat_context", lambda *_args, **_kwargs: None)

    await storage_tasks._run_batch_import_task(
        "task-1",
        "u1",
        {
            "files": [{"path": str(file_path), "data_type": data_type, "valid": True}],
            "dataset_name": "Canonical Dataset",
            "task_type": task_type,
            "aggregation_level": aggregation_level,
            "default_label": "tumor",
            "default_event_time": 12.5,
            "default_event_status": 1,
        },
    )

    assert captured["data_group"] == {
        "data_type": data_type,
        "aggregation_level": aggregation_level,
        "task_type": task_type,
    }
    assert captured["wsi"]["data_type"] == data_type
    assert captured["align"][-1]["task_type"] == task_type
    assert updates[-1][1] == "completed"
    if task_type == "wsi_survival":
        assert captured["wsi"]["event_time"] == 12.5
        assert captured["wsi"]["event_status"] == 1
    if task_type == "patch_segmentation":
        assert captured["annotation"]["source_dataset_id"] == "dataset-canonical"


@pytest.mark.asyncio
async def test_batch_import_recomputes_dataset_stats_once_after_batch(monkeypatch, tmp_path):
    from gateway.routes import storage_tasks

    file_paths = []
    for index in range(2):
        file_path = tmp_path / f"slide-{index}.svs"
        file_path.write_bytes(b"slide")
        file_paths.append(file_path)

    recomputed = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    async def _fake_update_status(_db, *_args, **_kwargs):
        return True

    async def _fake_get_or_create_data_group(_db, **kwargs):
        return types.SimpleNamespace(group_id="group-wsi", **kwargs)

    async def _fake_get_or_create_dataset(_db, dataset_name, **kwargs):
        return types.SimpleNamespace(
            dataset_id="dataset-import",
            name=dataset_name,
            user_id=kwargs.get("user_id"),
            data_group=types.SimpleNamespace(
                data_type="wsi",
                aggregation_level="case",
                task_type="wsi_classification",
            ),
        )

    async def _fake_align_dataset_data_type_for_file(_db, dataset, **_kwargs):
        return dataset

    async def _fake_create_wsi(_db, **kwargs):
        return types.SimpleNamespace(**kwargs)

    async def _fake_recompute(_db, dataset_id):
        recomputed.append(dataset_id)

    monkeypatch.setattr(storage_tasks, "async_session", lambda: FakeSession())
    monkeypatch.setattr(
        storage_tasks.StorageTaskRepository, "update_status", _fake_update_status
    )
    monkeypatch.setattr(
        storage_tasks.DataGroupRepository,
        "get_or_create",
        _fake_get_or_create_data_group,
    )
    monkeypatch.setattr(
        storage_tasks.DatasetRepository, "get_or_create", _fake_get_or_create_dataset
    )
    monkeypatch.setattr(
        storage_tasks,
        "align_dataset_data_type_for_file",
        _fake_align_dataset_data_type_for_file,
    )
    monkeypatch.setattr(
        storage_tasks.WSIRepository,
        "get_by_dataset",
        AsyncMock(side_effect=AssertionError("must not load whole dataset")),
    )
    monkeypatch.setattr(
        storage_tasks.WSIRepository,
        "get_original_filenames_by_dataset",
        AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(storage_tasks.WSIRepository, "create", _fake_create_wsi)
    monkeypatch.setattr(storage_tasks.DatasetStatsRepository, "recompute", _fake_recompute)
    monkeypatch.setattr(
        storage_tasks.storage_manager,
        "save_wsi_metadata",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        storage_tasks,
        "resolve_file_data_type_and_properties",
        lambda _path, **_kwargs: ("wsi", {"file_size": 1}),
    )

    await storage_tasks._run_batch_import_task(
        "task-1",
        "u1",
        {
            "files": [
                {"path": str(file_path), "data_type": "wsi", "valid": True}
                for file_path in file_paths
            ],
            "dataset_name": "Import Dataset",
            "task_type": "wsi_classification",
            "aggregation_level": "case",
            "default_label": "tumor",
        },
    )

    assert recomputed == ["dataset-import"]
