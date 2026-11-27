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


def test_delete_training_task_files_removes_zarr_bundle_and_staging(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    staging = store.staging_path("task-101")
    staging.mkdir(parents=True)
    (staging / ".zattrs").write_text("{}", encoding="utf-8")
    result = store.delete_task("task-101")

    assert not store.bundle_path("task-101").exists()
    assert not staging.exists()
    assert "task-101" not in store.catalog.tasks()
    assert store.catalog.image('wsi-a')==[]
    assert str(store.bundle_path("task-101")) in result["deleted_files"]
    assert str(staging) in result["deleted_dirs"]


def test_delete_wsi_ai_results_removes_wsi_from_zarr_bundle(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[
            {
                "wsi_id": "wsi-a",
                "result": {"pred": "A"},
                "arrays": {"attention": np.array([0.1, 0.2])},
            },
            {
                "wsi_id": "wsi-b",
                "result": {"pred": "B"},
                "arrays": {"attention": np.array([0.3, 0.4])},
            },
        ],
    )
    manager = StorageManager(str(tmp_path))

    result = manager.delete_wsi_ai_results("wsi-a", task_id="task-101")

    assert result["failed"] == []
    assert result["deleted_files"]
    assert store.list_results("task-101") == ["wsi-b"]
    assert not store.artifact_exists("task-101", "wsi-a", "result")
    assert not store.artifact_exists("task-101", "wsi-a", "attention")
    assert store.read_result("task-101", "wsi-b") == {"pred": "B"}


def test_storage_stats_include_ai_result_bundles(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-101",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    from backend.storage.inventory import Inventory
    from backend.storage.references import References
    inventory=Inventory(tmp_path)
    stats=inventory.scan(References(owners={'task-101'}))
    item=next(item for item in inventory.page()['items'] if item['path'].endswith('.zarr.zip'))
    assert item['size']==store.bundle_path('task-101').stat().st_size
    assert item['state']=='referenced'


def test_orphan_scan_reports_zarr_bundle_for_missing_task(tmp_path, monkeypatch):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "missing-task",
        items=[{"wsi_id": "wsi-a", "result": {"pred": "A"}, "arrays": {}}],
    )
    from backend.storage.inventory import Inventory
    from backend.storage.references import References
    monkeypatch.setattr('backend.storage.inventory.GRACE_SECONDS',-1)
    inventory=Inventory(tmp_path)
    inventory.scan(References(owners={'task-101'}))
    assert any(item['path']=='ai_results_bundles/missing-task.zarr.zip'
        for item in inventory.page('results','orphaned')['items'])
