import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.ai.schemas.base import TaskStatus
from gateway.task_queue import TaskType


def _make_task(task_id, status, data_type="wsi", task_type="wsi_classification"):
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


def _make_batch_inference_task(task_id, status, data_type="wsi", task_type="wsi_classification"):
    task = _make_task(task_id, status, data_type=data_type, task_type=task_type)
    task.task_id = task_id if task_id.startswith("binfer_") else f"binfer_{task_id}"
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
        patch("gateway.startup.TrainingTaskRepository", mock_repo),
        patch("gateway.startup.get_task_queue", return_value=mock_queue),
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch(
            "gateway.startup.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.startup.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.startup import resume_interrupted_tasks

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
        patch("gateway.startup.TrainingTaskRepository", mock_repo),
        patch("gateway.startup.get_task_queue", return_value=mock_queue),
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch(
            "gateway.startup.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.startup.get_db") as mock_get_db,
        patch("gateway.startup.asyncio") as mock_asyncio,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()
        mock_patching_task = MagicMock()
        mock_asyncio.create_task.return_value = mock_patching_task

        from gateway.startup import resume_interrupted_tasks

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
        patch("gateway.startup.TrainingTaskRepository", mock_repo),
        patch("gateway.startup.get_task_queue", return_value=mock_queue),
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch(
            "gateway.startup.run_patching_then_submit", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.startup.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.startup import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete", False) is False


@pytest.mark.asyncio
async def test_resume_batch_inference_task():
    """Interrupted batch_inference task is re-submitted with TaskType.BATCH_INFERENCE."""
    task = _make_batch_inference_task(
        "task_bi_1", TaskStatus.TRAINING, data_type="wsi", task_type="wsi_classification"
    )
    task.model_config = {
        "model_task_id": "src_task_abc",
        "model_id": "model_xyz",
        "dataset_id": "ds_999",
    }

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    mock_run_batch = AsyncMock()

    with (
        patch("gateway.startup.TrainingTaskRepository", mock_repo),
        patch("gateway.startup.get_task_queue", return_value=mock_queue),
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("gateway.routes.inference_batch._run_batch_inference", mock_run_batch),
        patch("gateway.startup.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.startup import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.call_args.kwargs
    assert call_kwargs["task_id"] == "binfer_task_bi_1"
    assert call_kwargs["task_type"] == TaskType.BATCH_INFERENCE
    assert call_kwargs["model_task_id"] == "src_task_abc"
    assert call_kwargs["model_id"] == "model_xyz"
    assert call_kwargs["dataset_id"] == "ds_999"
    mock_repo.get_wsi_ids.assert_not_called()


@pytest.mark.asyncio
async def test_resume_batch_inference_skips_wsi_ids_fetch():
    """Batch inference resume does NOT call TrainingTaskRepository.get_wsi_ids."""
    task = _make_batch_inference_task(
        "task_bi_2", TaskStatus.TRAINING, data_type="wsi", task_type="wsi_classification"
    )
    task.model_config = {"model_task_id": "t", "model_id": "m", "dataset_id": "d"}

    mock_queue = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.get_wsi_ids = AsyncMock(return_value=["should_not_be_called"])

    with (
        patch("gateway.startup.TrainingTaskRepository", mock_repo),
        patch("gateway.startup.get_task_queue", return_value=mock_queue),
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("gateway.startup.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from gateway.startup import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_repo.get_wsi_ids.assert_not_called()
