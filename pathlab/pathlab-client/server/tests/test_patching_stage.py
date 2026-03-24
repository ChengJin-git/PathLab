import pytest
import importlib
from typing import Any, Dict
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_run_patching_stage_processes_all_wsis():
    task_id = "test_task_123"
    wsi_ids = ["wsi_1", "wsi_2", "wsi_3"]
    preprocessing_config: Dict[str, Any] = {}

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
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status="patching"))

        run_patching_stage = importlib.import_module(
            "gateway.pipeline"
        ).run_patching_stage

        await run_patching_stage(task_id, wsi_ids, preprocessing_config)

    assert mock_coords.await_count == 3


@pytest.mark.asyncio
async def test_run_patching_stage_stops_on_cancelled_status():
    task_id = "test_task_456"
    wsi_ids = ["wsi_1", "wsi_2"]
    preprocessing_config: Dict[str, Any] = {}

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
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status="cancelled"))

        run_patching_stage = importlib.import_module(
            "gateway.pipeline"
        ).run_patching_stage
        import asyncio

        with pytest.raises(asyncio.CancelledError):
            await run_patching_stage(task_id, wsi_ids, preprocessing_config)
