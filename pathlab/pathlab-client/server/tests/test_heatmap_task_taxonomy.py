import json
import types

import pytest

from backend.preprocessing import heatmap_routes


@pytest.mark.asyncio
async def test_available_heatmaps_uses_canonical_patch_segmentation_for_masks(monkeypatch, tmp_path):
    uploads_dir = tmp_path / "uploads"
    result_dir = uploads_dir / "ai_results" / "wsi-1"
    result_dir.mkdir(parents=True)
    mask_file = result_dir / "segmentation_task-1_pred_mask.npy"
    mask_file.write_bytes(b"mask")
    (result_dir / "segmentation_task-1_result.json").write_text(
        json.dumps(
            {
                "task_id": "task-1",
                "task_name": "Tumor segmentation",
                "fold_key": "fold_0",
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
