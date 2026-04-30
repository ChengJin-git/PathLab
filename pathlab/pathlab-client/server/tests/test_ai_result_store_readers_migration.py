from importlib import import_module

import numpy as np

AIResultStore = import_module("backend.ai.result_store").AIResultStore
training_utils = import_module("backend.ai.tasks.training_utils")
results_routes = import_module("gateway.routes.results")


def test_kfold_metrics_reads_finalized_bundle_when_split_map_known(tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-kfold-bundle"
    classes = ["A", "B"]

    store.write_wsi_result(
        task_id=task_id,
        wsi_id="wsi-1",
        fold_key="fold_0",
        result={
            "task_id": task_id,
            "wsi_id": "wsi-1",
            "fold_key": "fold_0",
            "pred": "A",
            "ground_truth": "A",
            "probs": {"A": 0.9, "B": 0.1},
        },
    )
    store.write_wsi_result(
        task_id=task_id,
        wsi_id="wsi-2",
        fold_key="fold_0",
        result={
            "task_id": task_id,
            "wsi_id": "wsi-2",
            "fold_key": "fold_0",
            "pred": "B",
            "ground_truth": "B",
            "probs": {"A": 0.1, "B": 0.9},
        },
    )

    aggregated, per_fold = training_utils.calculate_kfold_classification_metrics(
        uploads_root=tmp_path,
        task_id=task_id,
        fold_keys=["fold_0"],
        classes=classes,
        splits_map={"fold_0": ["wsi-1", "wsi-2"]},
    )

    assert per_fold["fold_0"]["precision"] == 1.0
    assert per_fold["fold_0"]["sensitivity"] == 1.0
    assert per_fold["fold_0"]["specificity"] == 1.0
    assert per_fold["fold_0"]["f1"] == 1.0
    assert per_fold["fold_0"]["auc"] == 1.0
    assert aggregated["precision"]["mean"] == 1.0


def test_kfold_metrics_without_split_map_does_not_scan_legacy_files(tmp_path):
    task_id = "task-kfold-no-scan"
    classes = ["A", "B"]
    result_dir = tmp_path / "ai_results" / "wsi-legacy"
    result_dir.mkdir(parents=True)
    (result_dir / f"train_{task_id}_fold_0_result.json").write_text(
        '{"task_id":"task-kfold-no-scan","fold_key":"fold_0","pred":"A","ground_truth":"A"}',
        encoding="utf-8",
    )

    aggregated, per_fold = training_utils.calculate_kfold_classification_metrics(
        uploads_root=tmp_path,
        task_id=task_id,
        fold_keys=["fold_0"],
        classes=classes,
        splits_map=None,
    )

    assert per_fold == {}
    assert aggregated == {}


def test_collect_missing_artifacts_accepts_bundle_backed_result(monkeypatch, tmp_path):
    store = AIResultStore(tmp_path)
    task_id = "task-artifacts"
    wsi_id = "wsi-artifacts"

    store.write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result={"task_id": task_id, "wsi_id": wsi_id, "pred": "A"},
        arrays={"attention": np.array([0.2, 0.8], dtype=np.float32)},
    )

    monkeypatch.setattr(results_routes.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(results_routes, "find_any_cached_coords_for_wsi", lambda *_a, **_k: tmp_path / "coords.h5")

    missing_count, missing_artifacts = results_routes._collect_missing_ai_result_artifacts(
        task_id=task_id,
        task_type="classification",
        data_type="wsi",
        wsi_id=wsi_id,
        extra_metadata={"attention_type": "single"},
    )

    assert missing_count == 0
    assert missing_artifacts == []


def test_collect_missing_artifacts_rejects_legacy_only_train_artifacts(monkeypatch, tmp_path):
    task_id = "task-legacy-only"
    wsi_id = "wsi-legacy-only"
    legacy_dir = tmp_path / "ai_results" / wsi_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / f"train_{task_id}_result.json").write_text(
        '{"task_id":"task-legacy-only","wsi_id":"wsi-legacy-only"}',
        encoding="utf-8",
    )
    np.save(legacy_dir / f"train_{task_id}_attention.npy", np.array([0.2, 0.8]))

    monkeypatch.setattr(results_routes.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        results_routes,
        "find_any_cached_coords_for_wsi",
        lambda *_a, **_k: tmp_path / "coords.h5",
    )

    missing_count, missing_artifacts = results_routes._collect_missing_ai_result_artifacts(
        task_id=task_id,
        task_type="classification",
        data_type="wsi",
        wsi_id=wsi_id,
        extra_metadata={"attention_type": "single"},
    )

    assert missing_count == 2
    assert {item["artifact"] for item in missing_artifacts} == {
        "result_file",
        "attention_file",
    }
