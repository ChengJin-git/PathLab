import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from backend.ai.schemas.base import TaskStatus


@pytest.mark.asyncio
async def test_run_patching_stage_processes_all_wsis():
    """run_patching_stage iterates over all WSI IDs and calls ensure_coords_ready for each."""
    task_id = "test_task_123"
    wsi_ids = ["wsi_1", "wsi_2", "wsi_3"]
    preprocessing_config = {}

    mock_result = {"num_patches": 100, "cached": False}

    with (
        patch(
            "gateway.pipeline.ensure_coords_ready", return_value=mock_result
        ) as mock_coords,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.PATCHING)
        )

        from gateway.pipeline import run_patching_stage

        await run_patching_stage(task_id, wsi_ids, preprocessing_config)

    assert mock_coords.await_count == 3
    initial_status_call = mock_repo.update_status.call_args_list[0]
    assert initial_status_call.args[2] == TaskStatus.PATCHING
    assert initial_status_call.kwargs.get("progress") == 0


@pytest.mark.asyncio
async def test_run_patching_stage_stops_on_cancelled_status():
    """run_patching_stage raises CancelledError when DB status is CANCELLED."""
    task_id = "test_task_456"
    wsi_ids = ["wsi_1", "wsi_2"]
    preprocessing_config = {}

    with (
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.CANCELLED)
        )

        from gateway.pipeline import run_patching_stage

        with pytest.raises(asyncio.CancelledError):
            await run_patching_stage(task_id, wsi_ids, preprocessing_config)


@pytest.mark.asyncio
async def test_run_patching_stage_empty_wsi_ids_returns_early():
    """run_patching_stage with empty wsi_ids returns without calling ensure_coords_ready."""
    with (
        patch(
            "gateway.pipeline.ensure_coords_ready", new_callable=AsyncMock
        ) as mock_coords,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()

        from gateway.pipeline import run_patching_stage

        await run_patching_stage("task_empty", [], {})

    mock_coords.assert_not_awaited()
    mock_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_patching_stage_single_wsi_progress_reaches_33():
    """Single WSI: final progress update is exactly 33% (int(1/1 * 33))."""
    with (
        patch(
            "gateway.pipeline.ensure_coords_ready",
            return_value={"num_patches": 50, "cached": False},
        ),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.PATCHING)
        )

        from gateway.pipeline import run_patching_stage

        await run_patching_stage("task_single", ["wsi_only"], {})

    progress_values = [
        c.kwargs.get("progress")
        for c in mock_repo.update_status.call_args_list
        if c.kwargs.get("progress") is not None
    ]
    assert 33 in progress_values, (
        f"Expected progress=33 in calls, got: {progress_values}"
    )
