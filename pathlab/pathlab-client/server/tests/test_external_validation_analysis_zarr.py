from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest


_analysis_mod = import_module("gateway.routes.external_validation_analysis")
_result_store_mod = import_module("backend.ai.result_store")

AIResultStore = _result_store_mod.AIResultStore


def _seed_result(store, task_id: str, wsi_id: str, result: dict[str, object]):
    store.write_wsi_result(task_id=task_id, wsi_id=wsi_id, result=result)


def test_load_extval_task_result_payloads_reads_bundle_only_and_filters_validation_task_id(
    tmp_path, monkeypatch
):
    task_id = "extval-task-1"
    store = AIResultStore(tmp_path)

    _seed_result(
        store,
        task_id,
        "wsi-ok",
        {
            "wsi_id": "wsi-ok",
            "validation_task_id": task_id,
            "pred": "A",
            "ground_truth": "A",
        },
    )
    _seed_result(
        store,
        task_id,
        "wsi-no-field",
        {
            "wsi_id": "wsi-no-field",
            "pred": "B",
            "ground_truth": "B",
        },
    )
    _seed_result(
        store,
        task_id,
        "wsi-other-task",
        {
            "wsi_id": "wsi-other-task",
            "validation_task_id": "another-task",
            "pred": "C",
            "ground_truth": "C",
        },
    )

    monkeypatch.setattr(_analysis_mod.Config, "get_uploads_dir", lambda: tmp_path)

    payloads = _analysis_mod._load_extval_task_result_payloads(task_id)
    payload_ids = sorted(item["wsi_id"] for item in payloads)
    assert payload_ids == ["wsi-no-field", "wsi-ok"]


def test_collect_segmentation_results_from_payloads_preserves_expected_fields():
    payloads = [
        {
            "wsi_id": "seg-1",
            "validation_task_id": "extval-seg",
            "task_type": "patch_segmentation",
            "metrics": {"iou": 0.7},
            "has_ground_truth": True,
            "num_classes": 3,
            "class_names": ["tumor", "normal", "stroma"],
        }
    ]

    image_results, num_classes, class_names = (
        _analysis_mod._collect_segmentation_results_from_payloads(payloads)
    )

    assert len(image_results) == 1
    assert image_results[0]["wsi_id"] == "seg-1"
    assert num_classes == 3
    assert class_names == ["tumor", "normal", "stroma"]


def test_collect_classification_results_from_payloads_preserves_expected_fields():
    payloads = [
        {
            "wsi_id": "cls-1",
            "pred": "A",
            "ground_truth": "A",
            "probs": {"A": 0.9, "B": 0.1},
            "case_id": "case-1",
            "is_kfold": True,
            "num_folds": 5,
            "aggregation_level": "case",
        }
    ]

    (
        predictions,
        labels,
        probs_list,
        wsi_results,
        is_kfold,
        num_folds,
        aggregation_level,
    ) = _analysis_mod._collect_classification_results_from_payloads(payloads)

    assert predictions == ["A"]
    assert labels == ["A"]
    assert probs_list == [{"A": 0.9, "B": 0.1}]
    assert wsi_results[0]["wsi_id"] == "cls-1"
    assert wsi_results[0]["case_id"] == "case-1"
    assert is_kfold is True
    assert num_folds == 5
    assert aggregation_level == "case"


def test_collect_survival_results_from_payloads_preserves_expected_fields():
    payloads = [
        {
            "wsi_id": "surv-1",
            "case_id": "case-surv-1",
            "risk_score": 0.42,
            "event_time": 24,
            "event_status": 1,
            "surv_probs": [0.9, 0.8],
            "bin_edges": [0, 12, 24],
            "is_kfold": True,
            "num_folds": 4,
            "aggregation_level": "case",
        }
    ]

    (
        risks,
        times,
        events,
        surv_probs,
        wsi_results,
        bin_edges,
        is_kfold,
        num_folds,
        aggregation_level,
    ) = _analysis_mod._collect_survival_results_from_payloads(payloads)

    assert risks == [0.42]
    assert times == [24]
    assert events == [1]
    assert surv_probs == [[0.9, 0.8]]
    assert wsi_results[0]["wsi_id"] == "surv-1"
    assert wsi_results[0]["case_id"] == "case-surv-1"
    assert bin_edges == [0, 12, 24]
    assert is_kfold is True
    assert num_folds == 4
    assert aggregation_level == "case"


def test_external_validation_analysis_has_no_legacy_extval_scan_patterns():
    assert _analysis_mod.__file__ is not None
    module_source = Path(_analysis_mod.__file__).read_text(encoding="utf-8")

    assert 'f"extval_{task_id}_result.json"' not in module_source
    assert 'Config.get_uploads_dir() / "ai_results"' not in module_source
