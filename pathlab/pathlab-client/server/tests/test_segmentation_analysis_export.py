import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from fastapi import HTTPException

from helpers import _make_user


def _segmentation_task() -> MagicMock:
    data_group = MagicMock()
    data_group.task_type = "patch_segmentation"
    task = MagicMock()
    task.task_id = "seg-task-1"
    task.task_name = "Segmentation Task"
    task.user_id = "user-1"
    task.data_group = data_group
    return task


@pytest.mark.asyncio
async def test_start_segmentation_analysis_full_export_creates_async_zip_task(monkeypatch, tmp_path):
    from gateway.routes import results

    user = _make_user("admin")
    db = AsyncMock()
    db.commit = AsyncMock()
    background_tasks = MagicMock()
    created_task = SimpleNamespace(task_id="export-task-1")
    analysis_dir = tmp_path / "logs" / "analysis" / "seg-task-1" / "analysis-1"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "summary.json").write_text('{"task_type":"patch_segmentation"}', encoding="utf-8")
    (analysis_dir / "results.json").write_text('{"task_type":"patch_segmentation","wsi_results":[]}', encoding="utf-8")

    monkeypatch.setattr(results.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        results.TrainingTaskRepository,
        "get_by_id",
        AsyncMock(return_value=_segmentation_task()),
    )
    monkeypatch.setattr(results, "_require_task_access", AsyncMock())
    monkeypatch.setattr(results.ExportTaskRepository, "create", AsyncMock(return_value=created_task))
    monkeypatch.setattr(results.uuid, "uuid4", lambda: "export-task-1")

    response = await results.start_segmentation_analysis_full_export(
        task_id="seg-task-1",
        analysis_id="analysis-1",
        background_tasks=background_tasks,
        user=user,
        db=db,
    )

    assert response == {"task_id": "export-task-1", "status": "pending"}
    results.ExportTaskRepository.create.assert_awaited_once()
    create_kwargs = results.ExportTaskRepository.create.await_args.kwargs
    assert create_kwargs["export_type"] == "segmentation_analysis_full"
    assert create_kwargs["file_format"] == "zip"
    assert create_kwargs["filter_params"] == {
        "task_id": "seg-task-1",
        "analysis_id": "analysis-1",
    }
    background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_segmentation_analysis_full_export_marks_export_cancelled(monkeypatch):
    from gateway.routes import results

    user = _make_user("admin")
    db = AsyncMock()
    db.commit = AsyncMock()
    task = SimpleNamespace(
        task_id="export-task-1",
        user_id=str(user.id),
        export_type="segmentation_analysis_full",
        status="processing",
    )

    monkeypatch.setattr(
        results.ExportTaskRepository,
        "get_by_id",
        AsyncMock(return_value=task),
    )
    monkeypatch.setattr(
        results.ExportTaskRepository,
        "update_status",
        AsyncMock(return_value=True),
    )

    response = await results.cancel_segmentation_analysis_full_export(
        export_task_id="export-task-1",
        user=user,
        db=db,
    )

    assert response == {"cancelled": True, "status": "cancelled"}
    results.ExportTaskRepository.update_status.assert_awaited_once_with(
        db,
        "export-task-1",
        status="cancelled",
        progress=0,
        error_message="Cancelled by user",
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_completed_segmentation_analysis_full_export_is_rejected(monkeypatch):
    from gateway.routes import results

    user = _make_user("admin")
    db = AsyncMock()
    task = SimpleNamespace(
        task_id="export-task-1",
        user_id=str(user.id),
        export_type="segmentation_analysis_full",
        status="completed",
    )

    monkeypatch.setattr(
        results.ExportTaskRepository,
        "get_by_id",
        AsyncMock(return_value=task),
    )

    with pytest.raises(HTTPException) as exc_info:
        await results.cancel_segmentation_analysis_full_export(
            export_task_id="export-task-1",
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_segmentation_analysis_full_export_zip_contains_metadata_and_masks(monkeypatch, tmp_path):
    from gateway.routes import results

    analysis_dir = tmp_path / "logs" / "analysis" / "seg-task-1" / "analysis-1"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "summary.json").write_text(
        json.dumps({"task_type": "patch_segmentation", "num_samples": 1}),
        encoding="utf-8",
    )
    (analysis_dir / "results.json").write_text(
        json.dumps(
            {
                "task_type": "patch_segmentation",
                "results": [{"wsi_id": "wsi-1", "has_ground_truth": True}],
            }
        ),
        encoding="utf-8",
    )

    updates = []
    db = AsyncMock()
    db.commit = AsyncMock()
    session_factory = lambda: _AsyncSessionContext(db)
    pred_mask = np.array([[0, 1], [1, 0]], dtype=np.uint8)
    gt_mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)

    monkeypatch.setattr(results.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        results.TrainingTaskRepository,
        "get_by_id",
        AsyncMock(return_value=_segmentation_task()),
    )
    monkeypatch.setattr(results, "_require_task_access", AsyncMock())
    monkeypatch.setattr(
        results.ExportTaskRepository,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(status="processing")),
    )
    monkeypatch.setattr(
        results.ExportTaskRepository,
        "update_status",
        AsyncMock(side_effect=lambda *args, **kwargs: updates.append((args, kwargs)) or True),
    )
    monkeypatch.setattr(
        results,
        "_load_segmentation_export_pred_mask",
        lambda task_id, wsi_id: pred_mask,
    )
    monkeypatch.setattr(
        results,
        "_load_segmentation_export_gt_mask",
        AsyncMock(return_value=gt_mask),
    )

    await results.process_segmentation_analysis_full_export(
        export_task_id="export-task-1",
        source_task_id="seg-task-1",
        analysis_id="analysis-1",
        user_id="user-1",
        db_session_maker=session_factory,
    )

    completed_update = updates[-1][1]
    assert completed_update["status"] == "completed"
    assert completed_update["progress"] == 100
    zip_path = Path(completed_update["file_path"])
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "summary.json", "results.json"}.issubset(names)
        assert "pred_masks/wsi-1.npy" in names
        assert "gt_masks/wsi-1.npy" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["source_task_id"] == "seg-task-1"
        assert manifest["analysis_id"] == "analysis-1"
        assert manifest["mask_counts"] == {"pred": 1, "gt": 1, "missing_pred": 0, "missing_gt": 0}


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False
