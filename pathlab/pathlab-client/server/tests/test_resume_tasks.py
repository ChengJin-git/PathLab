import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.schemas.base import TaskStatus


def _make_task(task_id, status, data_type="wsi", task_type="classification"):
    task = MagicMock()
    task.task_id = task_id
    task.task_name = f"Task {task_id}"
    task.status = status
    task.preprocessing_config = {}
    task.model_config = {}
    task.classes = []
    task.data_group = MagicMock()
    task.data_group.data_type = data_type
    task.data_group.task_type = task_type
    return task


@pytest.mark.asyncio
async def test_resume_wsi_extracting_task_skips_patching():
    """WSI task in EXTRACTING state resumes with patching_complete=True."""
    task = _make_task("task_ext", TaskStatus.EXTRACTING, data_type="wsi")

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch(
            "gateway.main.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.main import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_queue.submit.assert_awaited_once()
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete") is True
    mock_patching.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_wsi_patching_task_reruns_patching():
    """WSI task in PATCHING state resumes via pre-queue patching (cache hits = fast)."""
    task = _make_task("task_patch_state", TaskStatus.PATCHING, data_type="wsi")

    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()
    mock_queue.register_patching_task = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch(
            "gateway.main.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
        patch("gateway.main.asyncio") as mock_asyncio,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()
        mock_patching_task = MagicMock()
        mock_asyncio.create_task.return_value = mock_patching_task

        from gateway.main import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_queue.submit.assert_not_awaited()
    mock_queue.register_patching_task.assert_called_once()


@pytest.mark.asyncio
async def test_resume_patch_task_submits_to_queue():
    """Patch task resumes by submitting directly to GPU queue."""
    task = _make_task("task_patch_cls", TaskStatus.TRAINING, data_type="patch")

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["img_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch(
            "gateway.main.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.main import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete", False) is False
