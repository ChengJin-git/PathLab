import numpy as np
import pytest

from backend.preprocessing import heatmap_routes
from backend.ai.result_store import AIResultStore, ATTENTION_ARTIFACT, PRED_MASK_ARTIFACT
from backend.database.models import TrainingTask
from test_viewer_workspace import workspace


def test_heatmap_artifact_selection_requires_bundle_artifacts(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"

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


def test_heatmap_artifact_selection_discovers_actual_fold_keys(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    store = AIResultStore(uploads_dir)
    store.write_wsi_result(
        task_id="task-folded",
        wsi_id="wsi-folded",
        fold_key="fold_12",
        result={"task_id": "task-folded", "fold_key": "fold_12"},
        arrays={ATTENTION_ARTIFACT: np.array([12.0], dtype=np.float32)},
    )

    monkeypatch.setattr(heatmap_routes, "_uploads_dir", lambda: uploads_dir)

    assert heatmap_routes._select_artifact_target(
        store,
        "wsi-folded",
        ATTENTION_ARTIFACT,
        task_id="task-folded",
        fold_key=None,
    ) == ("task-folded", "fold_12")


@pytest.mark.asyncio
async def test_available_heatmaps_uses_canonical_patch_segmentation_for_masks(workspace):
    w=workspace
    async with w.db() as db:
        db.add(TrainingTask(task_id='task-1',task_name='Tumor segmentation',group_id='g',user_id=str(w.people[0].id),status='completed'));await db.commit()
    AIResultStore(w.root).write_wsi_result(
        task_id="task-1",
        wsi_id="slide",
        fold_key="fold_0",
        result={
            "task_id": "task-1",
            "task_type": "patch_segmentation",
            "task_name": "Tumor segmentation",
            "fold_key": "fold_0",
            "num_classes": 2,
            "class_names": ["background", "tumor"],
        },
        arrays={
            PRED_MASK_ARTIFACT: np.ones((2, 4, 4), dtype=np.uint8),
        },
    )

    response = (await w.client.get('/heatmap/wsi/slide/available')).json()

    assert response["heatmaps"][0]["task_type"] == "patch_segmentation"
    assert response["heatmaps"][0]["data_type"] == "patch"


@pytest.mark.asyncio
@pytest.mark.parametrize('task_type', ['patch_detection', 'patch_classification'])
async def test_viewer_lists_saved_results_without_cam(workspace, task_type):
    w=workspace
    async with w.db() as db:
        db.add(TrainingTask(task_id='task',task_name='Result',group_id='g',user_id=str(w.people[0].id),status='completed'));await db.commit()
    AIResultStore(w.root).write_wsi_result('task', 'slide', result={
        'task_id': 'task', 'task_type': task_type, 'class_names': ['cell'],
        'image_size': [40, 30], 'pred': 'cell', 'probs': {'cell': 1},
    }, arrays={})
    result = (await w.client.get('/heatmap/wsi/slide/available')).json()
    assert len(result['heatmaps']) == 1
    assert result['heatmaps'][0]['task_type'] == task_type
    assert result['heatmaps'][0]['has_heatmap'] is False
