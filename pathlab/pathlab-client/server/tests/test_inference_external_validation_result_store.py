from __future__ import annotations

import inspect
from importlib import import_module

import numpy as np
import pytest


_result_store_mod = import_module("backend.ai.result_store")
_extval_mod = import_module("gateway.routes.inference_external_validation")

AIResultStore = _result_store_mod.AIResultStore
RESULT_ARTIFACT = _result_store_mod.RESULT_ARTIFACT
CAM_ARTIFACT = _result_store_mod.CAM_ARTIFACT
PRED_MASK_ARTIFACT = _result_store_mod.PRED_MASK_ARTIFACT
ATTENTION_ARTIFACT = _result_store_mod.ATTENTION_ARTIFACT
ATTENTION_RAW_ARTIFACT = _result_store_mod.ATTENTION_RAW_ARTIFACT


def test_save_extval_result_bundle_writes_task_level_bundle_without_legacy_files(tmp_path):
    task_id = "extval-task-1"
    wsi_id = "wsi-extval-1"
    uploads_dir = tmp_path

    result_data = {
        "wsi_id": wsi_id,
        "task_id": "model-task-1",
        "task_type": "wsi_classification",
        "pred": "A",
        "probs": {"A": 0.9, "B": 0.1},
    }
    arrays = {
        CAM_ARTIFACT: np.arange(9, dtype=np.float32).reshape(3, 3),
        PRED_MASK_ARTIFACT: np.arange(9, dtype=np.uint8).reshape(3, 3),
        ATTENTION_ARTIFACT: np.arange(4, dtype=np.float32),
        ATTENTION_RAW_ARTIFACT: np.arange(8, dtype=np.float32).reshape(2, 4),
    }

    _extval_mod._save_extval_result_bundle(
        uploads_dir=uploads_dir,
        extval_task_id=task_id,
        wsi_id=wsi_id,
        result_data=result_data,
        arrays=arrays,
    )

    store = AIResultStore(uploads_dir)
    assert store.validate_bundle(task_id)
    assert store.read_result(task_id, wsi_id, strict=True) == result_data
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, CAM_ARTIFACT, strict=True),
        arrays[CAM_ARTIFACT],
    )
    np.testing.assert_array_equal(
        store.read_array(task_id, wsi_id, PRED_MASK_ARTIFACT, strict=True),
        arrays[PRED_MASK_ARTIFACT],
    )
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, ATTENTION_ARTIFACT, strict=True),
        arrays[ATTENTION_ARTIFACT],
    )
    np.testing.assert_allclose(
        store.read_array(task_id, wsi_id, ATTENTION_RAW_ARTIFACT, strict=True),
        arrays[ATTENTION_RAW_ARTIFACT],
    )

    assert not (uploads_dir / "ai_results").exists()


def test_save_extval_result_bundle_does_not_filter_unsupported_artifacts(tmp_path):
    with pytest.raises(ValueError, match="unsupported array artifact"):
        _extval_mod._save_extval_result_bundle(
            uploads_dir=tmp_path,
            extval_task_id="extval-task-unsupported",
            wsi_id="wsi-unsupported",
            result_data={"wsi_id": "wsi-unsupported", "task_id": "model-task-1"},
            arrays={"unsupported_artifact": np.arange(3, dtype=np.float32)},
        )


def test_external_validation_module_has_no_legacy_extval_file_writes():
    module_source = inspect.getsource(_extval_mod)

    assert ' / "ai_results"' not in module_source
    assert "_result.json" not in module_source
    assert "_attention.npy" not in module_source
    assert "_attention_raw.npy" not in module_source
    assert "_cam.npy" not in module_source
    assert "_pred_mask.npy" not in module_source
    assert "np.save(" not in module_source
    assert "json.dump(" not in module_source
