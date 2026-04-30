import json
import types

import numpy as np
import pytest

from backend.preprocessing import heatmap_routes
from backend.preprocessing.heatmap_utils import load_result_meta
from backend.ai.result_store import AIResultStore, ATTENTION_ARTIFACT, PRED_MASK_ARTIFACT


def test_heatmap_artifact_selection_requires_bundle_artifacts(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    legacy_dir = uploads_dir / "ai_results" / "wsi-legacy"
    legacy_dir.mkdir(parents=True)
    np.save(legacy_dir / "train_task-legacy_attention.npy", np.array([1.0]))
    (legacy_dir / "train_task-legacy_result.json").write_text(
        json.dumps({"task_id": "task-legacy", "wsi_id": "wsi-legacy"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(heatmap_routes, "_uploads_dir", lambda: uploads_dir)

    assert (
        heatmap_routes._select_artifact_target(
            AIResultStore(uploads_dir),
            "wsi-legacy",
            ATTENTION_ARTIFACT,
            "task-legacy",
            None,
        )
        is None
    )


def test_heatmap_artifact_selection_respects_taskless_fold_key(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    store = AIResultStore(uploads_dir)
    store.write_wsi_result(
        task_id="task-folded",
        wsi_id="wsi-folded",
        fold_key="fold_0",
        result={"task_id": "task-folded", "fold_key": "fold_0"},
        arrays={ATTENTION_ARTIFACT: np.array([0.0], dtype=np.float32)},
    )
    store.write_wsi_result(
        task_id="task-folded",
        wsi_id="wsi-folded",
        fold_key="fold_1",
        result={"task_id": "task-folded", "fold_key": "fold_1"},
        arrays={ATTENTION_ARTIFACT: np.array([1.0], dtype=np.float32)},
    )

    monkeypatch.setattr(heatmap_routes, "_uploads_dir", lambda: uploads_dir)

    assert heatmap_routes._select_artifact_target(
        store,
        "wsi-folded",
        ATTENTION_ARTIFACT,
        task_id=None,
        fold_key="fold_1",
    ) == ("task-folded", "fold_1")


@pytest.mark.asyncio
async def test_available_heatmaps_uses_canonical_patch_segmentation_for_masks(monkeypatch, tmp_path):
    uploads_dir = tmp_path / "uploads"
    AIResultStore(uploads_dir).write_wsi_result(
        task_id="task-1",
        wsi_id="wsi-1",
        fold_key="fold_0",
        result={
            "task_id": "task-1",
            "task_name": "Tumor segmentation",
            "fold_key": "fold_0",
            "num_classes": 2,
            "class_names": ["background", "tumor"],
        },
        arrays={
            PRED_MASK_ARTIFACT: np.ones((2, 4, 4), dtype=np.uint8),
        },
    )

    legacy_dir = uploads_dir / "ai_results" / "wsi-1"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "segmentation_legacy-only_pred_mask.npy").write_bytes(b"ignored")
    (legacy_dir / "segmentation_legacy-only_result.json").write_text(
        json.dumps(
            {
                "task_id": "legacy-only",
                "task_name": "Legacy only",
                "num_classes": 2,
                "class_names": ["background", "tumor"],
            }
        )
    )

    class FakeTrainingTaskRepository:
        @staticmethod
        async def get_by_ids(_db, _task_ids):
            return {
                "task-1": types.SimpleNamespace(
                    task_name="Tumor segmentation",
                    model_id=None,
                )
            }

    monkeypatch.setattr(heatmap_routes, "_uploads_dir", lambda: uploads_dir)
    monkeypatch.setattr(heatmap_routes, "find_any_cached_coords_for_wsi", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        heatmap_routes,
        "import_module",
        lambda name: types.SimpleNamespace(TrainingTaskRepository=FakeTrainingTaskRepository)
        if name == "backend.database.repositories"
        else __import__(name),
    )

    response = await heatmap_routes.get_available_heatmaps("wsi-1", db=object())

    assert response["heatmaps"][0]["task_type"] == "patch_segmentation"
    assert response["heatmaps"][0]["data_type"] == "patch"


def test_load_result_meta_reads_from_ai_result_store_when_json_missing(tmp_path):
    uploads_dir = tmp_path / "uploads"
    result_dir = uploads_dir / "ai_results" / "wsi-2"
    result_dir.mkdir(parents=True)

    task_id = "task-heatmap-meta"
    AIResultStore(uploads_dir).write_wsi_result(
        task_id=task_id,
        wsi_id="wsi-2",
        result={
            "task_id": task_id,
            "wsi_id": "wsi-2",
            "pred": "tumor",
            "classes": ["normal", "tumor"],
        },
    )

    attention_file = result_dir / f"train_{task_id}_attention.npy"
    attention_file.write_bytes(b"placeholder")

    meta = load_result_meta(attention_file, "_attention.npy")

    assert meta["task_id"] == task_id
    assert meta["wsi_id"] == "wsi-2"
