from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
import numpy as np


_results_mod = import_module("gateway.routes.results")
_result_store_mod = import_module("backend.ai.result_store")
_config_mod = import_module("backend.common.config")

AIResultStore = _result_store_mod.AIResultStore
Config = _config_mod.Config


def test_extval_existing_cache_discovery_uses_result_store_bundle_and_artifact_checks(
    tmp_path: Path,
):
    store = AIResultStore(tmp_path)
    model_task_id = "model-task-1"
    validation_task_id = "extval_task_1"
    wsi_ids = ["wsi-1", "wsi-2"]

    for wsi_id in wsi_ids:
        store.write_wsi_result(
            task_id=validation_task_id,
            wsi_id=wsi_id,
            result={
                "wsi_id": wsi_id,
                "task_id": model_task_id,
                "task_type": "wsi_classification",
                "validation_task_id": validation_task_id,
                "pred": "A",
                "probs": {"A": 0.9, "B": 0.1},
            },
        )

    count, existing_validation_id, incomplete_examples = (
        _results_mod._check_existing_extval_results_from_store(
            uploads_dir=tmp_path,
            wsi_ids=wsi_ids,
            trained_model_task_id=model_task_id,
            model_task_type="wsi_classification",
            model_data_type="wsi",
        )
    )

    assert count == 2
    assert existing_validation_id == validation_task_id
    assert incomplete_examples == []


def test_results_module_has_no_legacy_extval_glob_scan_patterns():
    assert _results_mod.__file__ is not None
    module_source = Path(_results_mod.__file__).read_text(encoding="utf-8")

    assert 'glob("extval_*_result.json")' not in module_source
    assert 'uploads_dir / "ai_results" / wsi_id' not in module_source


def test_extval_existing_cache_discovery_fallback_checks_bundle_artifacts_with_candidate_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = AIResultStore(tmp_path)
    model_task_id = "model-task-2"
    candidate_task_id = "extval_bundle_2"
    logical_validation_task_id = "extval_logical_2"
    wsi_id = "wsi-fallback-1"

    store.write_wsi_result(
        task_id=candidate_task_id,
        wsi_id=wsi_id,
        result={
            "wsi_id": wsi_id,
            "task_id": model_task_id,
            "task_type": "wsi_classification",
            "validation_task_id": logical_validation_task_id,
            "pred": "A",
            "probs": {"A": 0.8, "B": 0.2},
            "attention_file": f"bundle://{candidate_task_id}/{wsi_id}/attention",
        },
        arrays={
            "attention": np.array([[0.1, 0.2]], dtype=np.float32),
        },
    )

    def _raise_prefetch(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced prefetch failure")

    def _coords_path(*_args: object, **_kwargs: object) -> Path:
        return tmp_path / "coords.h5"

    monkeypatch.setattr(
        AIResultStore,
        "task_artifact_presence_for_items",
        _raise_prefetch,
    )
    monkeypatch.setattr(
        _results_mod,
        "find_any_cached_coords_for_wsi",
        _coords_path,
    )
    monkeypatch.setattr(
        Config,
        "get_uploads_dir",
        staticmethod(lambda: tmp_path),
    )

    count, existing_validation_id, incomplete_examples = (
        _results_mod._check_existing_extval_results_from_store(
            uploads_dir=tmp_path,
            wsi_ids=[wsi_id],
            trained_model_task_id=model_task_id,
            model_task_type="wsi_classification",
            model_data_type="wsi",
        )
    )

    assert count == 1
    assert existing_validation_id == logical_validation_task_id
    assert incomplete_examples == []
