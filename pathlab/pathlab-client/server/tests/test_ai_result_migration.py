import json

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
