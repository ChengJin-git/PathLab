import json
import zipfile
from importlib import import_module

import numpy as np
import pytest

Config = import_module("backend.common.config").Config
_result_store_mod = import_module("backend.ai.result_store")
AIResultStore = _result_store_mod.AIResultStore
IncompleteAIResultBundleError = _result_store_mod.IncompleteAIResultBundleError
ZipStore = _result_store_mod.ZipStore
save_ai_result_artifacts = import_module(
    "backend.ai.tasks.training_utils"
).save_ai_result_artifacts


def test_config_creates_ai_result_bundle_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(tmp_path))

    Config.ensure_directories()

    assert not (tmp_path / "ai_results").exists()
    assert (tmp_path / "ai_results_bundles").is_dir()


def test_write_and_read_classification_result_and_arrays(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-classification"
    wsi_id = "wsi/one"
    result_payload = {
        "wsi_id": wsi_id,
        "task_id": task_id,
        "pred": "A",
        "ground_truth": "B",
        "probs": {"A": 0.8, "B": 0.2},
        "correct": False,
        "classes": ["A", "B"],
        "fold_key": "fold_0",
    }

    store.write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result=result_payload,
        arrays={
            "attention": np.arange(5, dtype=np.float32),
            "attention_raw": np.arange(10, dtype=np.float32).reshape(2, 5),
            "cam": np.arange(16, dtype=np.float32).reshape(4, 4),
            "pred_mask": np.arange(16, dtype=np.uint8).reshape(4, 4),
        },
        fold_key="fold_0",
    )

    assert store.read_result(task_id, wsi_id, fold_key="fold_0") == result_payload
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, "attention", fold_key="fold_0"),
        np.arange(5, dtype=np.float32),
    )
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, "attention_raw", fold_key="fold_0"),
        np.arange(10, dtype=np.float32).reshape(2, 5),
    )
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, "cam", fold_key="fold_0"),
        np.arange(16, dtype=np.float32).reshape(4, 4),
    )
    np.testing.assert_array_equal(
        store.read_array(task_id, wsi_id, "pred_mask", fold_key="fold_0"),
        np.arange(16, dtype=np.uint8).reshape(4, 4),
    )


def test_write_and_read_survival_result_round_trip(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-survival"
    wsi_id = "survival-wsi"
    payload = {
        "wsi_id": wsi_id,
        "task_id": task_id,
        "risk_score": 1.23,
        "event_time": 456.0,
        "event_status": 1,
        "surv_probs": [0.9, 0.7, 0.3],
        "bin_edges": [0.0, 12.0, 24.0],
    }

    store.write_wsi_result(task_id=task_id, wsi_id=wsi_id, result=payload)

    assert store.read_result(task_id, wsi_id) == payload


def test_write_task_bundle_accepts_multiple_items_and_task_type(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-batch"

    bundle_path = store.write_task_bundle(
        task_id,
        items=[
            {
                "wsi_id": "wsi-a",
                "result": {"wsi_id": "wsi-a", "task_id": task_id, "pred": "A"},
                "arrays": {"attention": np.array([1.0, 2.0], dtype=np.float32)},
            },
            {
                "wsi_id": "case/with/slash",
                "result": {
                    "wsi_id": "case/with/slash",
                    "task_id": task_id,
                    "pred": "B",
                },
            },
        ],
        task_type="classification",
    )

    assert bundle_path == store.bundle_path(task_id)
    assert store.list_results(task_id) == ["case/with/slash", "wsi-a"]
    assert store.read_result(task_id, "case/with/slash")["pred"] == "B"
    assert store.artifact_exists(task_id, "wsi-a", "attention")


def test_default_finalized_writes_append_to_existing_task_bundle(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-append"

    store.write_wsi_result(task_id, "wsi-a", {"wsi_id": "wsi-a", "task_id": task_id})
    store.write_wsi_result(task_id, "wsi-b", {"wsi_id": "wsi-b", "task_id": task_id})

    assert store.list_results(task_id) == ["wsi-a", "wsi-b"]
    assert store.read_result(task_id, "wsi-a")["wsi_id"] == "wsi-a"
    assert store.read_result(task_id, "wsi-b")["wsi_id"] == "wsi-b"


def test_bulk_write_saves_wsi_index_once(tmp_path, monkeypatch):
    store = AIResultStore(tmp_path)
    save_calls = 0
    original_save_index = store._save_index_unlocked

    def track_save_index(data):
        nonlocal save_calls
        save_calls += 1
        original_save_index(data)

    monkeypatch.setattr(store, "_save_index_unlocked", track_save_index)
    items = [
        {"wsi_id": f"wsi-{idx}", "result": {"pred": idx}, "arrays": {}}
        for idx in range(5)
    ]

    store.write_task_bundle("task-101", items=items)

    assert save_calls == 1
    assert store.list_results("task-101") == [f"wsi-{idx}" for idx in range(5)]


def test_list_wsi_artifacts_uses_index_to_skip_unrelated_bundles(tmp_path, monkeypatch):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-target",
        items=[
            {
                "wsi_id": "wsi-target",
                "result": {"pred": 1},
                "arrays": {"attention": np.arange(4, dtype=np.float32)},
            }
        ],
    )
    store.write_task_bundle(
        "task-unrelated",
        items=[
            {
                "wsi_id": "wsi-other",
                "result": {"pred": 2},
                "arrays": {"attention": np.arange(4, dtype=np.float32)},
            }
        ],
    )

    visited_task_ids = []
    original_list_task_wsi_artifacts = store.list_task_wsi_artifacts

    def track_task_lookup(task_id, wsi_id):
        visited_task_ids.append(task_id)
        return original_list_task_wsi_artifacts(task_id, wsi_id)

    monkeypatch.setattr(store, "list_task_wsi_artifacts", track_task_lookup)

    artifacts = store.list_wsi_artifacts("wsi-target")

    assert visited_task_ids == ["task-target"]
    assert {item["artifact"] for item in artifacts} == {"result", "attention"}


def test_array_artifacts_are_written_as_single_chunks(tmp_path):
    store = AIResultStore(tmp_path)

    store.write_task_bundle(
        "task-101",
        items=[
            {
                "wsi_id": "wsi-a",
                "result": {"pred": "A"},
                "arrays": {"attention": np.arange(1024, dtype=np.float32)},
            }
        ],
    )

    import zipfile

    with zipfile.ZipFile(store.bundle_path("task-101"), "r") as zf:
        chunk_files = [name for name in zf.namelist() if name.rsplit("/", 1)[-1].isdigit()]

    assert len(chunk_files) == 1


def test_bulk_write_finalizes_directly_without_staging_tree(tmp_path):
    store = AIResultStore(tmp_path)
    finalize_calls = 0

    def track_finalize(task_id):
        nonlocal finalize_calls
        finalize_calls += 1
        raise AssertionError("bulk task bundle must finalize once through direct ZipStore write")

    def fail_staging_group(*args, **kwargs):
        raise AssertionError("bulk task bundle should write directly to ZipStore")

    store._finalize_task_bundle = track_finalize
    store._open_staging_group = fail_staging_group

    store.write_task_bundle(
        "task-101",
        items=[
            {
                "wsi_id": f"wsi-{idx}",
                "result": {"pred": idx},
                "arrays": {"attention": np.arange(16, dtype=np.float32)},
            }
            for idx in range(3)
        ],
    )

    assert store.bundle_path("task-101").exists()
    assert not store.staging_path("task-101").exists()
    assert finalize_calls == 0


def test_training_artifact_helper_can_stage_without_finalizing(tmp_path, monkeypatch):
    store = AIResultStore(tmp_path)
    finalize_calls = 0
    original_finalize = store._finalize_task_bundle

    def track_finalize(task_id):
        nonlocal finalize_calls
        finalize_calls += 1
        return original_finalize(task_id)

    monkeypatch.setattr(store, "_finalize_task_bundle", track_finalize)
    monkeypatch.setattr(
        "backend.ai.tasks.training_utils.AIResultStore",
        lambda uploads_root: store,
    )

    result_path = save_ai_result_artifacts(
        tmp_path,
        "task-staged-helper",
        "wsi-a",
        {"wsi_id": "wsi-a", "task_id": "task-staged-helper"},
        finalize=False,
        update_index=False,
    )

    assert result_path is None
    assert store.staging_path("task-staged-helper").exists()
    assert not store.bundle_path("task-staged-helper").exists()
    assert finalize_calls == 0

    store.write_task_bundle(task_id="task-staged-helper")

    assert store.read_result("task-staged-helper", "wsi-a")["wsi_id"] == "wsi-a"
    assert finalize_calls == 1


def test_staged_writes_defer_wsi_id_aggregation_until_finalize(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-deferred-index"

    store.write_wsi_result(
        task_id,
        "wsi-b",
        {"wsi_id": "wsi-b", "task_id": task_id},
        finalize=False,
        update_index=False,
    )
    store.write_wsi_result(
        task_id,
        "wsi-a",
        {"wsi_id": "wsi-a", "task_id": task_id},
        arrays={"cam": np.ones((2, 2), dtype=np.float32)},
        finalize=False,
        update_index=False,
    )

    root = store._open_staging_group(task_id, overwrite=False)
    assert root.attrs["wsi_ids"] == []

    store.write_task_bundle(task_id=task_id)

    assert store.list_results(task_id) == ["wsi-a", "wsi-b"]


def test_finalize_recovers_corrupt_wsi_index_without_failing_task(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        "task-existing",
        items=[{"wsi_id": "wsi-existing", "result": {"ok": "existing"}}],
    )
    store.index_path.write_text(
        store.index_path.read_text(encoding="utf-8") + '"patch-corrupt-tail"',
        encoding="utf-8",
    )

    store.write_wsi_result(
        "task-new",
        "wsi-new",
        {"wsi_id": "wsi-new", "task_id": "task-new"},
        finalize=False,
        update_index=False,
    )

    store.write_task_bundle(task_id="task-new")

    rebuilt_index = json.loads(store.index_path.read_text(encoding="utf-8"))
    assert rebuilt_index["task-existing"] == ["wsi-existing"]
    assert rebuilt_index["task-new"] == ["wsi-new"]


def test_store_does_not_create_legacy_ai_results_directory(tmp_path):
    AIResultStore(tmp_path)

    assert not (tmp_path / "ai_results").exists()


def test_incomplete_bundle_raises_without_legacy_fallback(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-incomplete"
    wsi_id = "wsi-incomplete"
    staged_payload = {"fallback": False}

    store.write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result=staged_payload,
        finalize=False,
    )

    with pytest.raises(FileNotFoundError):
        store.read_result(task_id, wsi_id)
    with pytest.raises(IncompleteAIResultBundleError):
        store.read_result(task_id, wsi_id, strict=True)


def test_bundle_reads_close_zip_store(tmp_path, monkeypatch):
    store = AIResultStore(tmp_path)
    store.write_wsi_result("task-close", "wsi-close", {"ok": True})
    close_calls = 0

    class TrackingZipStore(ZipStore):
        def close(self):
            nonlocal close_calls
            close_calls += 1
            return super().close()

    monkeypatch.setattr(_result_store_mod, "ZipStore", TrackingZipStore)

    assert store.read_result("task-close", "wsi-close") == {"ok": True}
    assert close_calls == 1


def test_hydrating_bundle_rejects_unsafe_zip_members(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-unsafe-zip"
    outside_path = store.staging_root / "escaped.txt"
    store.bundle_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(store.bundle_path(task_id), "w") as zf:
        zf.writestr("../../escaped.txt", "owned")

    with pytest.raises(ValueError, match="unsafe bundle member"):
        store.write_wsi_result(task_id, "wsi-safe", {"ok": True})

    assert not outside_path.exists()


def test_finalize_creates_zip_and_removes_staging(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-finalize"
    wsi_id = "wsi-finalize"

    store.write_wsi_result(task_id=task_id, wsi_id=wsi_id, result={"ok": True})

    assert store.bundle_path(task_id).is_file()
    assert not store.staging_path(task_id).exists()


def test_slash_wsi_id_no_nested_bundle_groups(tmp_path):
    store = AIResultStore(tmp_path)
    items = [
        {
            "wsi_id": "case/with/slash",
            "result": {"pred": "C"},
            "arrays": {"attention": np.array([0.7, 0.8], dtype=np.float32)},
        }
    ]

    bundle_path = store.write_task_bundle("task-101-migrated", items=items, task_type="classification")
    assert bundle_path.exists()

    import zipfile
    with zipfile.ZipFile(bundle_path, "r") as zf:
        namelist = zf.namelist()

    slash_dirs = [n for n in namelist if "case/" in n or "with/" in n or "slash/" in n]
    assert not slash_dirs, f"Found nested directories from slash WSI ID: {slash_dirs}"
