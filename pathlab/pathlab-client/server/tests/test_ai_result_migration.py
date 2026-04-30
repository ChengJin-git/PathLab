import json

import numpy as np

from backend.ai.ai_result_migration import migrate_legacy_ai_results
from backend.ai.result_store import AIResultStore
from server.tests.ai_result_fixtures import build_legacy_ai_result_fixtures


def test_migration_dry_run_reports_without_writing_bundle(tmp_path):
    build_legacy_ai_result_fixtures(tmp_path)

    summary = migrate_legacy_ai_results(tmp_path, execute=False, validate=True)

    assert summary["dry_run"] is True
    assert summary["tasks"]["task-101"]["valid_artifacts"] == 12
    assert not (tmp_path / "ai_results_bundles" / "task-101.zarr.zip").exists()
    assert (tmp_path / "ai_results" / "wsi-a" / "train_task-101_result.json").exists()


def test_migration_dry_run_does_not_load_array_payloads(tmp_path, monkeypatch):
    build_legacy_ai_result_fixtures(tmp_path)

    def fail_np_load(path):
        raise AssertionError(f"dry-run loaded array payload {path}")

    monkeypatch.setattr("backend.ai.ai_result_migration.np.load", fail_np_load)

    summary = migrate_legacy_ai_results(tmp_path, execute=False, validate=True)

    assert summary["tasks"]["task-101"]["valid_artifacts"] == 12


def test_migration_execute_writes_bundle_marker_and_rollback_log(tmp_path):
    build_legacy_ai_result_fixtures(tmp_path)
    rollback_log = tmp_path / "rollback.json"

    summary = migrate_legacy_ai_results(
        tmp_path,
        execute=True,
        validate=True,
        rollback_log=rollback_log,
    )

    store = AIResultStore(tmp_path)
    assert summary["dry_run"] is False
    assert summary["tasks"]["task-101"]["migrated_wsi_count"] == 3
    assert store.bundle_path("task-101").exists()
    assert store.validate_bundle("task-101") is True
    assert store.read_result("task-101", "case/with/slash")["pred"] == "C"
    assert (tmp_path / "ai_results" / "wsi-a" / "train_task-101_result.json").exists()
    assert rollback_log.exists()
    assert json.loads(rollback_log.read_text(encoding="utf-8"))["bundles"] == [
        str(store.bundle_path("task-101"))
    ]
    assert (tmp_path / "ai_results_bundles" / ".migration_task-101.json").exists()


def test_migration_is_idempotent(tmp_path):
    build_legacy_ai_result_fixtures(tmp_path)

    first = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)
    second = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)

    assert first["tasks"]["task-101"]["status"] == "migrated"
    assert second["tasks"]["task-101"]["status"] == "already_migrated"


def test_migration_preserves_folded_array_artifacts(tmp_path):
    task_id = "task-folded"
    wsi_id = "wsi-folded"
    legacy_dir = tmp_path / "ai_results" / wsi_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / f"train_{task_id}_fold_0_result.json").write_text(
        json.dumps({"task_id": task_id, "wsi_id": wsi_id, "fold_key": "fold_0"}),
        encoding="utf-8",
    )
    np.save(
        legacy_dir / f"train_{task_id}_fold_0_attention.npy",
        np.array([0.25, 0.75], dtype=np.float32),
    )

    migrate_legacy_ai_results(tmp_path, execute=True, validate=True)

    store = AIResultStore(tmp_path)
    assert store.read_result(task_id, wsi_id, fold_key="fold_0")["fold_key"] == "fold_0"
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, "attention", fold_key="fold_0"),
        np.array([0.25, 0.75], dtype=np.float32),
    )


def test_migration_repairs_marked_bundle_missing_folded_arrays(tmp_path):
    task_id = "task-folded-repair"
    wsi_id = "wsi-folded"
    legacy_dir = tmp_path / "ai_results" / wsi_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / f"train_{task_id}_fold_0_result.json").write_text(
        json.dumps({"task_id": task_id, "wsi_id": wsi_id, "fold_key": "fold_0"}),
        encoding="utf-8",
    )
    np.save(
        legacy_dir / f"train_{task_id}_fold_0_attention.npy",
        np.array([0.1, 0.9], dtype=np.float32),
    )
    store = AIResultStore(tmp_path)
    store.write_task_bundle(
        task_id,
        items=[
            {
                "wsi_id": wsi_id,
                "fold_key": "fold_0",
                "result": {"task_id": task_id, "wsi_id": wsi_id, "fold_key": "fold_0"},
            }
        ],
    )
    (tmp_path / "ai_results_bundles" / f".migration_{task_id}.json").write_text(
        json.dumps({"schema_version": 1, "task_id": task_id}),
        encoding="utf-8",
    )

    summary = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)

    assert summary["tasks"][task_id]["status"] == "migrated"
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, "attention", fold_key="fold_0"),
        np.array([0.1, 0.9], dtype=np.float32),
    )


def _write_legacy_extval_case(
    root,
    *,
    wsi_id="wsi-extval",
    file_task_id="extval_abc123",
    result_task_id=None,
):
    legacy_dir = root / "ai_results" / wsi_id
    legacy_dir.mkdir(parents=True)
    result_payload = {
        "task_id": "train-parent",
        "wsi_id": wsi_id,
        "pred": "positive",
        "validation_task_id": result_task_id if result_task_id is not None else file_task_id,
        "validation_source": "external",
        "task_type": "external_validation",
        "aggregation_level": "case",
        "is_kfold": False,
        "num_folds": 1,
        "case_id": "case-extval-1",
    }
    (legacy_dir / f"extval_{file_task_id}_result.json").write_text(
        json.dumps(result_payload), encoding="utf-8"
    )
    np.save(legacy_dir / f"extval_{file_task_id}_cam.npy", np.array([1, 2], dtype=np.float32))
    np.save(
        legacy_dir / f"extval_{file_task_id}_pred_mask.npy",
        np.array([[0, 1], [1, 0]], dtype=np.uint8),
    )
    np.save(
        legacy_dir / f"extval_{file_task_id}_attention.npy",
        np.array([0.2, 0.8], dtype=np.float32),
    )
    np.save(
        legacy_dir / f"extval_{file_task_id}_attention_raw.npy",
        np.array([0.3, 0.7], dtype=np.float32),
    )
    return legacy_dir, result_payload


def test_extval_execute_migrates_bundle_by_validation_task_id(tmp_path):
    legacy_dir, expected_result = _write_legacy_extval_case(
        tmp_path,
        wsi_id="wsi-extval",
        file_task_id="parsed-task-id",
        result_task_id="extval_abc123",
    )
    wsi_id = "wsi-extval"

    summary = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)

    store = AIResultStore(tmp_path)
    assert summary["tasks"]["extval_abc123"]["status"] == "migrated"
    stored = store.read_result("extval_abc123", wsi_id)
    for field in (
        "validation_task_id",
        "validation_source",
        "task_type",
        "aggregation_level",
        "is_kfold",
        "num_folds",
        "case_id",
    ):
        assert stored[field] == expected_result[field]
    np.testing.assert_allclose(
        store.read_array("extval_abc123", wsi_id, "cam"),
        np.array([1, 2], dtype=np.float32),
    )
    np.testing.assert_array_equal(
        store.read_array("extval_abc123", wsi_id, "pred_mask"),
        np.array([[0, 1], [1, 0]], dtype=np.uint8),
    )
    np.testing.assert_allclose(
        store.read_array("extval_abc123", wsi_id, "attention"),
        np.array([0.2, 0.8], dtype=np.float32),
    )
    np.testing.assert_allclose(
        store.read_array("extval_abc123", wsi_id, "attention_raw"),
        np.array([0.3, 0.7], dtype=np.float32),
    )
    assert not (legacy_dir / "extval_parsed-task-id_result.json").exists()
    assert not (legacy_dir / "extval_parsed-task-id_cam.npy").exists()
    assert not (legacy_dir / "extval_parsed-task-id_pred_mask.npy").exists()
    assert not (legacy_dir / "extval_parsed-task-id_attention.npy").exists()
    assert not (legacy_dir / "extval_parsed-task-id_attention_raw.npy").exists()


def test_extval_dry_run_reports_without_loading_arrays_or_deleting_files(tmp_path, monkeypatch):
    legacy_dir, _ = _write_legacy_extval_case(tmp_path)

    def fail_np_load(path):
        raise AssertionError(f"dry-run loaded extval array payload {path}")

    monkeypatch.setattr("backend.ai.ai_result_migration.np.load", fail_np_load)

    summary = migrate_legacy_ai_results(tmp_path, execute=False, validate=True)

    assert summary["tasks"]["extval_abc123"]["valid_artifacts"] == 5
    assert (legacy_dir / "extval_extval_abc123_result.json").exists()
    assert (legacy_dir / "extval_extval_abc123_cam.npy").exists()
    assert (legacy_dir / "extval_extval_abc123_pred_mask.npy").exists()
    assert (legacy_dir / "extval_extval_abc123_attention.npy").exists()
    assert (legacy_dir / "extval_extval_abc123_attention_raw.npy").exists()


def test_extval_execute_is_idempotent_when_bundle_and_marker_exist(tmp_path):
    _write_legacy_extval_case(tmp_path)

    first = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)
    second = migrate_legacy_ai_results(tmp_path, execute=True, validate=True)

    assert first["tasks"]["extval_abc123"]["status"] == "migrated"
    # No backward compatibility fallback is required; second execute just must not fail.
    assert second["tasks"] == {} or second["tasks"]["extval_abc123"]["status"] in {
        "already_migrated",
        "migrated",
    }
