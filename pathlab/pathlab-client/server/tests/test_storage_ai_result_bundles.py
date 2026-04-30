import numpy as np

from backend.ai.result_store import AIResultStore
from backend.storage.manager import StorageManager


def test_training_task_storage_info_counts_zarr_bundle(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[
            {
                "wsi_id": "wsi-a",
                "result": {"pred": "A"},
                "arrays": {"attention": np.array([0.1, 0.2])},
            }
        ],
    )
    manager = StorageManager(str(tmp_path))

    info = manager.get_training_task_storage_info("task-101")

    assert info["ai_results"]["exists"] is True
    assert info["ai_results"]["path"] == str(store.bundle_path("task-101"))
    assert info["ai_results"]["file_count"] == 1
    assert info["ai_results"]["size"] == store.bundle_path("task-101").stat().st_size


def test_delete_training_task_files_removes_zarr_bundle_and_marker(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    marker = tmp_path / "ai_results_bundles" / ".migration_task-101.json"
    marker.write_text("{}", encoding="utf-8")
    manager = StorageManager(str(tmp_path))

    result = manager.delete_training_task_files("task-101")

    assert not store.bundle_path("task-101").exists()
    assert not marker.exists()
    assert str(store.bundle_path("task-101")) in result["deleted_files"]
    assert str(marker) in result["deleted_files"]


def test_storage_stats_include_ai_result_bundles(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    manager = StorageManager(str(tmp_path))

    stats = manager._calculate_storage_stats()

    assert "ai_result_bundles" in stats["breakdown"]
    assert stats["breakdown"]["ai_result_bundles"]["file_count"] == 1
    assert stats["breakdown"]["ai_result_bundles"]["size"] == store.bundle_path(
        "task-101"
    ).stat().st_size


def test_orphan_scan_reports_zarr_bundle_for_missing_task(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "missing-task",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    manager = StorageManager(str(tmp_path))

    result = manager.find_orphaned_files(
        existing_wsi_ids=["wsi-a"],
        existing_task_ids=["task-101"],
        existing_model_ids=[],
    )

    assert any(
        item["path"] == str(store.bundle_path("missing-task"))
        and item["task_id"] == "missing-task"
        and item["type"] == "task_bundle"
        for item in result["orphaned_ai_results"]
    )
