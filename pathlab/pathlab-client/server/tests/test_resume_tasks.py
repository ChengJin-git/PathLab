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
    task = _make_task("task_ext", TaskStatus.EXTRACTING, data_type="wsi")

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_enqueue.assert_awaited_once()
    descriptor = mock_enqueue.call_args.args[0]
    assert descriptor.handler == "training.run"
    assert descriptor.payload.get("patching_complete") is True


@pytest.mark.asyncio
async def test_resume_wsi_patching_task_reruns_patching():
    task = _make_task("task_patch_state", TaskStatus.PATCHING, data_type="wsi")

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_enqueue.assert_awaited_once()
    descriptor = mock_enqueue.call_args.args[0]
    assert descriptor.handler == "training.patch_then_run"


@pytest.mark.asyncio
async def test_resume_patch_task_submits_to_queue():
    task = _make_task("task_patch_cls", TaskStatus.TRAINING, data_type="patch")

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["img_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_enqueue.assert_awaited_once()
    descriptor = mock_enqueue.call_args.args[0]
    assert descriptor.handler == "training.run"
    assert descriptor.payload.get("patching_complete", False) is False


@pytest.mark.asyncio
async def test_resume_batch_inference_task():
    task = _make_batch_inference_task(
        "task_bi_1", TaskStatus.TRAINING, data_type="wsi", task_type="wsi_classification"
    )
    task.model_config = {
        "model_task_id": "src_task_abc",
        "model_id": "model_xyz",
        "dataset_id": "ds_999",
    }

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_enqueue.assert_awaited_once()
    descriptor = mock_enqueue.call_args.args[0]
    assert descriptor.job_id == "binfer_task_bi_1"
    assert descriptor.handler == "inference.batch"
    assert descriptor.payload["model_task_id"] == "src_task_abc"
    assert descriptor.payload["model_id"] == "model_xyz"
    assert descriptor.payload["dataset_id"] == "ds_999"
    assert descriptor.payload.get("wsi_ids") is None
    mock_repo.get_wsi_ids.assert_not_called()


@pytest.mark.asyncio
async def test_resume_selected_wsi_batch_inference_preserves_wsi_ids():
    task = _make_batch_inference_task(
        "task_bi_selected", TaskStatus.TRAINING, data_type="wsi", task_type="wsi_classification"
    )
    task.model_config = {
        "model_task_id": "src_task_abc",
        "model_id": "model_xyz",
        "dataset_id": "ds_999",
        "wsi_ids": ["wsi-1", "wsi-2"],
        "source": "selected_wsi",
    }

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_enqueue.assert_awaited_once()
    descriptor = mock_enqueue.call_args.args[0]
    assert descriptor.job_id == "binfer_task_bi_selected"
    assert descriptor.handler == "inference.batch"
    assert descriptor.payload["wsi_ids"] == ["wsi-1", "wsi-2"]
    mock_repo.get_wsi_ids.assert_not_called()


@pytest.mark.asyncio
async def test_resume_batch_inference_skips_wsi_ids_fetch():
    task = _make_batch_inference_task(
        "task_bi_2", TaskStatus.TRAINING, data_type="wsi", task_type="wsi_classification"
    )
    task.model_config = {"model_task_id": "t", "model_id": "m", "dataset_id": "d"}

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.get_wsi_ids = AsyncMock(return_value=["should_not_be_called"])

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.enqueue_task_descriptor") as mock_enqueue,
        patch("gateway.startup.wait_for_services_ready", return_value=True),
        patch("task_worker.recovery.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    mock_repo.get_wsi_ids.assert_not_called()
    mock_enqueue.assert_awaited_once()
