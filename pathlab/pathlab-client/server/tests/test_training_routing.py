import asyncio
import importlib
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch


def _make_training_logger_mock():
    mock = MagicMock()
    mock.info = AsyncMock()
    mock.error = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_wsi_task_launches_pre_queue_patching():
    """WSI tasks launch run_patching_then_submit and register with queue manager."""
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1", "wsi_2"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = MagicMock()
    mock_queue.register_patching_task = MagicMock()
    mock_queue.submit = AsyncMock()
    mock_training_logger = _make_training_logger_mock()
    real_create_task = asyncio.create_task

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch(
            "gateway.routes.training.run_patching_then_submit",
            new_callable=AsyncMock,
        ) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
        patch("gateway.routes.training.asyncio.create_task") as mock_create_task,
    ):
        mock_repo.update_status = AsyncMock()
        mock_create_task.side_effect = real_create_task

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_wsi",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    mock_queue.submit.assert_not_awaited()
    mock_queue.register_patching_task.assert_called_once()


@pytest.mark.asyncio
async def test_patch_task_submits_directly_to_queue():
    """Patch tasks submit directly to GPU queue without pre-queue patching."""
    pipeline_kwargs = {
        "data_type": "patch",
        "wsi_ids": ["img_1"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = AsyncMock()
    mock_queue.register_patching_task = MagicMock()
    mock_training_logger = _make_training_logger_mock()

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch(
            "gateway.routes.training.run_patching_then_submit",
            new_callable=AsyncMock,
        ) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_patch",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    mock_queue.register_patching_task.assert_not_called()


@pytest.mark.asyncio
async def test_validate_files_and_enqueue_marks_failed_on_blocking_preflight_error():
    mock_training_logger = _make_training_logger_mock()

    with (
        patch(
            "gateway.routes.training._check_file_accessibility",
            side_effect=HTTPException(
                status_code=503, detail="storage root unavailable"
            ),
        ),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        mock_db = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_failed_preflight",
            paths_to_check=[("wsi_1", "/uploads/file.png", "file.png")],
            uploads_dir="/uploads",
            pipeline_kwargs={
                "data_type": "patch",
                "wsi_ids": ["wsi_1"],
                "preprocessing_config": {},
                "model_config": {},
                "training_task_type": "classification",
            },
        )

    mock_repo.update_status.assert_awaited_once()
    mock_training_logger.error.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_files_and_enqueue_marks_failed_when_inaccessible_files_found():
    mock_training_logger = _make_training_logger_mock()

    with (
        patch(
            "gateway.routes.training._check_file_accessibility",
            return_value=["broken_patch_001.png"],
        ),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        mock_db = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_inaccessible_files",
            paths_to_check=[("wsi_1", "/uploads/file.png", "file.png")],
            uploads_dir="/uploads",
            pipeline_kwargs={
                "data_type": "patch",
                "wsi_ids": ["wsi_1"],
                "preprocessing_config": {},
                "model_config": {},
                "training_task_type": "classification",
            },
        )

    mock_repo.update_status.assert_awaited_once()
    mock_training_logger.error.assert_awaited_once()
