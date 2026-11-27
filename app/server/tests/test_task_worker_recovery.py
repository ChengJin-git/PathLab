from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from backend.ai.schemas.base import TaskStatus


def _make_task(
    task_id: str,
    status: str,
    data_type: str = "wsi",
    task_type: str = "wsi_classification",
    preprocessing_config: dict | None = None,
    model_config: dict | None = None,
    classes: list | None = None,
    progress: int = 0,
):
    task = MagicMock()
    task.task_id = task_id
    task.created_at = datetime(2026, 1, 1)
    task.id = 1
    task.task_name = f"Task {task_id}"
    task.status = status
    task.preprocessing_config = preprocessing_config or {}
    task.model_config = model_config or {}
    task.classes = classes or []
    task.progress = progress
    task.data_group = MagicMock()
    task.data_group.data_type = data_type
    task.data_group.task_type = task_type
    return task


def _assert_training_input_ref_payload(descriptor, task_id: str, wsi_count: int = 1):
    assert descriptor.handler == "training.preflight"
    assert descriptor.payload["task_id"] == task_id
    assert descriptor.payload["paths_to_check"] == []
    assert descriptor.payload["pipeline_kwargs"]["input_ref"] == {
        "kind": "training_task_selection",
        "task_id": task_id,
    }
    assert descriptor.payload["pipeline_kwargs"]["wsi_count"] == wsi_count
    assert "wsi_ids" not in descriptor.payload["pipeline_kwargs"]


@pytest.mark.asyncio
async def test_recovery_builds_batch_inference_descriptor():
    task = _make_task(
        "binfer_abc",
        TaskStatus.TRAINING,
        data_type="wsi",
        task_type="wsi_classification",
        model_config={
            "model_task_id": "src_1",
            "model_id": "m1",
            "dataset_id": "ds1",
        },
    )

    from task_worker.recovery import _build_batch_inference_descriptor

    descriptor = _build_batch_inference_descriptor(task)
    assert descriptor.handler == "inference.batch"
    assert descriptor.payload["task_id"] == "binfer_abc"
    assert descriptor.payload["model_task_id"] == "src_1"
    assert descriptor.payload["model_id"] == "m1"
    assert descriptor.payload["dataset_id"] == "ds1"
    assert descriptor.payload.get("wsi_ids") is None


@pytest.mark.asyncio
async def test_recovery_builds_batch_inference_descriptor_with_wsi_ids():
    task = _make_task(
        "binfer_sel",
        TaskStatus.TRAINING,
        model_config={
            "model_task_id": "src_1",
            "model_id": "m1",
            "dataset_id": "ds1",
            "wsi_ids": ["w1", "w2"],
            "source": "selected_wsi",
        },
    )

    from task_worker.recovery import _build_batch_inference_descriptor

    descriptor = _build_batch_inference_descriptor(task)
    assert descriptor.payload["wsi_ids"] == ["w1", "w2"]


@pytest.mark.asyncio
async def test_recovery_builds_external_validation_descriptor():
    task = _make_task(
        "extval_abc",
        TaskStatus.TRAINING,
        data_type="wsi",
        task_type="wsi_classification",
        model_config={
            "model_task_id": "src_1",
            "model_id": "m1",
            "dataset_id": "ds1",
            "model_task_type": "wsi_classification",
            "model_data_type": "wsi",
        },
        classes=["A", "B"],
    )

    from task_worker.recovery import _build_external_validation_descriptor

    descriptor = _build_external_validation_descriptor(task, wsi_ids=["w1", "w2"])
    assert descriptor.handler == "external_validation.run"
    assert descriptor.payload["task_id"] == "extval_abc"
    assert descriptor.payload["model_task_id"] == "src_1"
    assert descriptor.payload["model_id"] == "m1"
    assert descriptor.payload["dataset_id"] == "ds1"
    assert descriptor.payload["wsi_ids"] == ["w1", "w2"]
    assert descriptor.payload["model_classes"] == ["A", "B"]
    assert descriptor.payload["model_task_type"] == "wsi_classification"
    assert descriptor.payload["model_data_type"] == "wsi"


@pytest.mark.asyncio
async def test_recovery_builds_training_descriptor_for_wsi_patching_stage():
    task = _make_task(
        "task_wsi_1",
        TaskStatus.PATCHING,
        data_type="wsi",
        task_type="wsi_classification",
        preprocessing_config={"foo": "bar"},
        model_config={"epochs": 10},
    )

    from task_worker.recovery import _build_training_descriptor

    descriptor = _build_training_descriptor(task, wsi_count=250000)
    _assert_training_input_ref_payload(descriptor, "task_wsi_1", wsi_count=250000)
    pipeline_kwargs = descriptor.payload["pipeline_kwargs"]
    assert pipeline_kwargs["data_type"] == "wsi"
    assert pipeline_kwargs["preprocessing_config"] == {"foo": "bar"}
    assert pipeline_kwargs["model_config"] == {"epochs": 10}
    assert pipeline_kwargs["training_task_type"] == "wsi_classification"


@pytest.mark.asyncio
async def test_recovery_builds_training_descriptor_for_wsi_gpu_stage():
    task = _make_task(
        "task_wsi_2",
        TaskStatus.EXTRACTING,
        data_type="wsi",
        task_type="wsi_classification",
        preprocessing_config={"foo": "bar"},
        model_config={"epochs": 10},
    )

    from task_worker.recovery import _build_training_descriptor

    descriptor = _build_training_descriptor(task, wsi_count=250000)
    _assert_training_input_ref_payload(descriptor, "task_wsi_2", wsi_count=250000)
    assert descriptor.payload["pipeline_kwargs"].get("patching_complete") is True


@pytest.mark.asyncio
async def test_recovery_builds_training_descriptor_for_patch_task():
    task = _make_task(
        "task_patch_1",
        TaskStatus.TRAINING,
        data_type="patch",
        task_type="patch_classification",
        preprocessing_config={"baz": 1},
        model_config={"epochs": 5},
    )

    from task_worker.recovery import _build_training_descriptor

    descriptor = _build_training_descriptor(task, wsi_count=250000)
    _assert_training_input_ref_payload(descriptor, "task_patch_1", wsi_count=250000)
    assert descriptor.payload["pipeline_kwargs"]["data_type"] == "patch"
    assert descriptor.payload["pipeline_kwargs"].get("patching_complete") is None


@pytest.mark.asyncio
async def test_recovery_resumes_interrupted_tasks_idempotent():
    task = _make_task(
        "task_idem",
        TaskStatus.QUEUED,
        data_type="patch",
        task_type="patch_classification",
    )

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()
    mock_repo.get_wsi_ids = AsyncMock(side_effect=AssertionError("training recovery must not materialize WSI IDs"))
    mock_repo.get_wsi_counts_batch = AsyncMock(return_value={"task_idem": 250000})

    captured_descriptors = []

    async def _capture_enqueue(descriptor):
        captured_descriptors.append(descriptor)

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.get_db") as mock_get_db,
        patch(
            "task_worker.recovery.enqueue_task_descriptor", _capture_enqueue
        ),
        patch("backend.common.service_health.wait_for_services_ready", return_value=True),
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    assert len(captured_descriptors) == 1
    assert captured_descriptors[0].job_id == "task_idem"
    _assert_training_input_ref_payload(captured_descriptors[0], "task_idem", wsi_count=250000)


@pytest.mark.asyncio
async def test_recovery_marks_unrecoverable_no_wsi_ids():
    task = _make_task(
        "task_no_wsi",
        TaskStatus.QUEUED,
        data_type="wsi",
    )

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)
    mock_repo.update_status = AsyncMock()
    mock_repo.get_wsi_ids = AsyncMock(side_effect=AssertionError("training recovery must not materialize WSI IDs"))
    mock_repo.get_wsi_counts_batch = AsyncMock(return_value={"task_no_wsi": 0})

    captured = []

    async def _capture(descriptor):
        captured.append(descriptor)

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.get_db") as mock_get_db,
        patch("task_worker.recovery.enqueue_task_descriptor", _capture),
        patch("backend.common.service_health.wait_for_services_ready", return_value=True),
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    assert len(captured) == 0
    mock_repo.update_status.assert_awaited_once_with(
        db_mock,
        "task_no_wsi",
        TaskStatus.FAILED,
        error_message="No associated WSI IDs found during resume",
    )


@pytest.mark.asyncio
async def test_recovery_skips_already_claimed():
    task = _make_task("task_claimed", TaskStatus.QUEUED)

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=False)

    captured = []

    async def _capture(descriptor):
        captured.append(descriptor)

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.get_db") as mock_get_db,
        patch("task_worker.recovery.enqueue_task_descriptor", _capture),
        patch("backend.common.service_health.wait_for_services_ready", return_value=True),
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        await resume_interrupted_tasks()

    assert len(captured) == 0
    mock_repo.try_claim_for_resume.assert_awaited_once_with(db_mock, "task_claimed")


@pytest.mark.asyncio
async def test_recovery_services_not_ready_preserves_task_for_retry():
    task = _make_task("task_svc", TaskStatus.QUEUED)

    mock_repo = MagicMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.update_status = AsyncMock()

    with (
        patch("task_worker.recovery.TrainingTaskRepository", mock_repo),
        patch("task_worker.recovery.get_db") as mock_get_db,
        patch("backend.common.service_health.wait_for_services_ready", return_value=False),
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()

        async def _db_gen():
            yield db_mock

        mock_get_db.return_value = _db_gen()

        from task_worker.recovery import resume_interrupted_tasks

        assert await resume_interrupted_tasks() is False

    mock_repo.update_status.assert_not_awaited()
    assert task.status == TaskStatus.QUEUED
