from importlib import import_module
from pathlib import Path

import numpy as np
import pytest

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


def test_collect_missing_artifacts_reports_missing_when_no_bundle_exists(monkeypatch, tmp_path):
    task_id = "task-no-bundle"
    wsi_id = "wsi-no-bundle"

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


def test_collect_missing_artifacts_uses_precomputed_bundle_presence(
    monkeypatch: pytest.MonkeyPatch,
):
    class UnexpectedStoreOpen:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("resource validation should not open bundle per artifact")

    monkeypatch.setattr(results_routes, "AIResultStore", UnexpectedStoreOpen)

    missing_count, missing_artifacts = results_routes._collect_missing_ai_result_artifacts(
        task_id="task-large",
        task_type="classification",
        data_type="patch",
        wsi_id="wsi-fast",
        extra_metadata={},
        artifact_presence={"result": {("wsi-fast", None)}, "cam": {("wsi-fast", None)}},
    )

    assert missing_count == 0
    assert missing_artifacts == []


@pytest.mark.asyncio
async def test_enrich_resources_keeps_existing_ai_results_when_artifacts_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class FakeResult:
        def __init__(self, value: object) -> None:
            self.value = value

        def first(self):
            return self.value

        def all(self):
            return self.value

    class FakeDb:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _query):
            self.calls += 1
            if self.calls == 1:
                return FakeResult(("classification", "wsi"))
            if self.calls == 2:
                return FakeResult([])
            return FakeResult(
                [
                    (
                        "wsi-orphan",
                        {
                            "attention_shape": [4],
                            "fold_key": "fold_0",
                            "result_file": None,
                            "attention_file": None,
                        },
                    )
                ]
            )

    monkeypatch.setattr(results_routes.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        results_routes,
        "find_any_cached_coords_for_wsi",
        lambda *_args, **_kwargs: None,
    )

    resources = await results_routes._enrich_single_task_resources(
        "task-orphan",
        FakeDb(),
        {"has_ai_results": True, "ai_results_count": 1},
    )

    assert resources["has_ai_results"] is True
    assert resources["has_complete_ai_results"] is False
    assert resources["missing_ai_result_artifact_count"] == 3


def test_task_artifact_presence_for_items_checks_requested_items_only(tmp_path: Path):
    store = AIResultStore(tmp_path)
    task_id = "task-requested-presence"

    store.write_wsi_result(
        task_id=task_id,
        wsi_id="wsi-with-cam",
        result={"task_id": task_id, "wsi_id": "wsi-with-cam"},
        arrays={"cam": np.ones((2, 2), dtype=np.float32)},
    )
    store.write_wsi_result(
        task_id=task_id,
        wsi_id="wsi-result-only",
        result={"task_id": task_id, "wsi_id": "wsi-result-only"},
    )

    presence = store.task_artifact_presence_for_items(
        task_id,
        items=[("wsi-with-cam", None), ("wsi-result-only", None), ("wsi-missing", None)],
        artifacts={"result", "cam"},
    )

    assert presence["result"] == {("wsi-with-cam", None), ("wsi-result-only", None)}
    assert presence["cam"] == {("wsi-with-cam", None)}
