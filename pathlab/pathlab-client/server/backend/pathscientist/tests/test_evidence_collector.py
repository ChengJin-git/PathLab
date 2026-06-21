"""Tests for evidence collection from ratchet finalization."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.evidence.collector import EvidenceCollector
from pathscientist.evidence.store import EvidenceStore


def _make_workspace(tmp_path):
    """Create a minimal workspace with git and train.py."""
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    (ws_dir / "train.py").write_text("print('hello')\n", encoding="utf-8")

    import subprocess
    subprocess.run(["git", "init"], cwd=ws_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=ws_dir, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=ws_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=ws_dir, capture_output=True)

    return ws_dir


def test_collector_captures_commit_evidence(tmp_path):
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")
    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_abc123",
        run_dir="output/runs/run_abc123",
        exit_code=0,
        stdout="training complete",
        stderr="",
        metrics={"auc": 0.87},
        duration=120.0,
    )
    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    assert result.record_path
    record = store.load("run_abc123")
    assert record.committed is True
    assert record.primary_metric_value == 0.87
    assert record.git_commit != ""
    assert record.run_id == "run_abc123"
    assert record.code_snapshot == "print('hello')\n"


def test_collector_captures_revert_evidence_with_metrics(tmp_path):
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")
    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_def456",
        run_dir="output/runs/run_def456",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.75},
        duration=60.0,
    )
    result = collector.finalize(committed=False, iteration=1)
    assert result.skipped is False
    record = store.load("run_def456")
    assert record.committed is False
    assert record.primary_metric_value == 0.75


def test_collector_captures_failed_run_evidence(tmp_path):
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")
    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_fail1",
        run_dir="output/runs/run_fail1",
        exit_code=1,
        stdout="",
        stderr="RuntimeError: CUDA out of memory",
        metrics={},
        duration=5.0,
    )
    result = collector.finalize(committed=False, iteration=0)
    assert result.skipped is False
    record = store.load("run_fail1")
    assert record.exit_code == 1
    assert record.error_type == "CUDA_OOM"


def test_collector_captures_data_output_dir_artifacts(tmp_path):
    """Artifacts from DATA_OUTPUT_DIR should be indexed when it differs from run_dir."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    # Create DATA_OUTPUT_DIR outside the workspace
    data_dir = tmp_path / "data_output"
    data_dir.mkdir()
    (data_dir / "features.h5").write_text("fake features", encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_data1",
        run_dir="output/runs/run_data1",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.80},
        duration=60.0,
        data_output_dir=str(data_dir),
    )
    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    record = store.load("run_data1")
    artifact_names = [a.name for a in record.artifacts]
    assert "features.h5" in artifact_names
    assert record.data_output_dir == str(data_dir)


def test_collector_handles_external_run_dir(tmp_path):
    """When run_dir is outside the workspace (absolute), scanning should not crash."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    # Create run_dir outside workspace
    ext_run_dir = tmp_path / "ext_output" / "runs" / "run_ext1"
    ext_run_dir.mkdir(parents=True)
    (ext_run_dir / "metrics.json").write_text('{"auc": 0.88}', encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_ext1",
        run_dir=str(ext_run_dir),
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.88},
        duration=30.0,
    )
    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    record = store.load("run_ext1")
    assert record.run_id == "run_ext1"
    artifact_names = [a.name for a in record.artifacts]
    assert "metrics.json" in artifact_names


def test_collector_captures_untracked_files(tmp_path):
    """Pre-revert untracked files should be stored in the evidence record."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_untracked",
        run_dir="output/runs/run_untracked",
        exit_code=1,
        stdout="",
        stderr="error",
        metrics={},
        duration=5.0,
    )
    # Simulate pre-revert untracked files (normally set by ratchet revert)
    collector._experiment["_pre_revert_untracked"] = {
        "helper.py": "def helper(): pass",
        "config.yaml": "lr: 0.001",
    }
    result = collector.finalize(committed=False, iteration=0)
    assert result.skipped is False

    # Verify sidecar files were written
    loaded = store.load("run_untracked")
    assert loaded.untracked_files["helper.py"] == "def helper(): pass"
    assert loaded.untracked_files["config.yaml"] == "lr: 0.001"


def test_collector_copies_pre_revert_external_core_artifacts(tmp_path):
    """External-test core outputs must survive revert even when large."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(ws_dir / ".evidence")

    run_dir = ws_dir / "output" / "runs" / "run_external"
    run_dir.mkdir(parents=True)
    predictions = run_dir / "predictions.csv"
    predictions.write_text("sample_id,score\n" + "s,0.5\n" * 10000, encoding="utf-8")
    assert predictions.stat().st_size > 50_000
    expected_predictions = predictions.read_text(encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_external",
        run_dir="output/runs/run_external",
        exit_code=0,
        stdout="",
        stderr="",
        metrics={"auc": 0.72},
        duration=5.0,
        run_kind="external_test",
    )
    staged = tmp_path / "pre_revert_artifacts" / "run_external" / "predictions.csv"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(predictions.read_bytes())
    collector._experiment["_pre_revert_artifacts"] = [str(staged)]

    # Simulate workspace.revert() removing the original untracked run output before
    # evidence finalization. The durable pre-revert copy must still be captured.
    predictions.unlink()

    result = collector.finalize(committed=False, iteration=0)
    assert result.skipped is False

    loaded = store.load("run_external")
    prediction_artifact = next(
        artifact for artifact in loaded.artifacts if artifact.name == "predictions.csv"
    )
    assert prediction_artifact.storage_mode == "copy"
    copied = ws_dir / ".evidence" / "runs" / "run_external" / "artifacts" / "predictions.csv"
    assert copied.read_text(encoding="utf-8") == expected_predictions


def test_collector_deduplicates_same_directory_artifacts(tmp_path):
    """DATA_OUTPUT_DIR pointing at the same directory as run_dir should not duplicate artifacts."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    run_dir = ws_dir / "output" / "runs" / "run_same_dir"
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text('{"auc": 0.91}', encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_same_dir",
        run_dir="output/runs/run_same_dir",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.91},
        duration=30.0,
        data_output_dir=str(run_dir),
    )

    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    record = store.load("run_same_dir")

    metrics_artifacts = [a for a in record.artifacts if a.name == "metrics.json"]
    assert len(metrics_artifacts) == 1


def test_collector_only_keeps_current_run_data_output_artifacts(tmp_path):
    """Shared DATA_OUTPUT_DIR should only keep files explicitly marked as current-run outputs."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    data_dir = tmp_path / "data_output"
    data_dir.mkdir()
    old_file = data_dir / "old_features.pt"
    new_file = data_dir / "new_features.pt"
    old_file.write_text("old", encoding="utf-8")
    new_file.write_text("new", encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_data_filtered",
        run_dir="output/runs/run_data_filtered",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.82},
        duration=60.0,
        data_output_dir=str(data_dir),
        data_output_artifacts=[str(new_file)],
    )

    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    record = store.load("run_data_filtered")

    artifact_names = [a.name for a in record.artifacts]
    assert "new_features.pt" in artifact_names
    assert "old_features.pt" not in artifact_names


def test_collector_empty_data_output_delta_does_not_reindex_historical_files(tmp_path):
    """An explicit empty delta means this run produced no DATA_OUTPUT_DIR artifacts."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    data_dir = tmp_path / "shared_data_output"
    data_dir.mkdir()
    (data_dir / "old_features.pt").write_text("old", encoding="utf-8")

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_data_empty_delta",
        run_dir="output/runs/run_data_empty_delta",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.83},
        duration=60.0,
        data_output_dir=str(data_dir),
        data_output_artifacts=[],
    )

    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False
    record = store.load("run_data_empty_delta")

    artifact_names = [a.name for a in record.artifacts]
    assert "old_features.pt" not in artifact_names


def test_collector_persists_model_path_and_pathlab_linkage(tmp_path):
    """Model-producing runs must keep checkpoint and PathLab linkage in evidence."""
    ws_dir = _make_workspace(tmp_path)
    store = EvidenceStore(tmp_path / ".evidence")

    model_path = ws_dir / "output" / "runs" / "run_model" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    pathlab = {
        "uploads_dir": str(tmp_path / "uploads"),
        "features_dir": str(tmp_path / "uploads" / "features" / "Virchow2"),
        "training_task_id": "task_123",
        "training_dir": str(tmp_path / "uploads" / "training" / "task_123"),
        "model_path": str(model_path),
    }

    collector = EvidenceCollector(
        workspace_root=ws_dir, store=store, session_id="s1", primary_metric="auc"
    )
    collector.record_experiment_output(
        run_id="run_model",
        run_dir="output/runs/run_model",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.94},
        duration=60.0,
        model_path=str(model_path),
        pathlab=pathlab,
    )

    result = collector.finalize(committed=True, iteration=0)
    assert result.skipped is False

    record = store.load("run_model")
    assert record.model_path == str(model_path)
    assert record.pathlab == pathlab

    rows = store.list_runs(committed=True)
    row = next(r for r in rows if r["run_id"] == "run_model")
    assert row["model_path"] == str(model_path)
    assert row["pathlab"]["training_task_id"] == "task_123"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
