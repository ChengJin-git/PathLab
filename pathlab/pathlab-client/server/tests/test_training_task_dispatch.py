from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.id = "user_1"
    user.role = role
    user.is_active = True
    user.is_admin = MagicMock(return_value=(role == "admin"))
    user.can_use_gpu = MagicMock(return_value=(role in ("admin", "pathologist")))
    return user


class _SafeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_safe_session_factory(*dbs):
    queue = list(dbs)

    def _factory():
        if not queue:
            raise AssertionError("safe_session called more times than expected")
        return _SafeSessionCtx(queue.pop(0))

    return _factory


@pytest.mark.asyncio
async def test_create_training_task_enqueues_descriptor_and_does_not_run_preflight_locally():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_dispatch_test",
        task_name="dispatch test",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_dispatch_test"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()

    captured_descriptor = None

    async def _capture_enqueue(descriptor):
        nonlocal captured_descriptor
        captured_descriptor = descriptor

    create_task = AsyncMock(return_value=created_task)

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            side_effect=RuntimeError("Gateway must not call _validate_files_and_enqueue"),
        ) as mock_local_preflight,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=training_module.build_task_descriptor,
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=_capture_enqueue),
        ) as mock_enqueue,
    ):
        result = await training_module.create_training_task(req=req, user=user)

    mock_local_preflight.assert_not_called()
    mock_build_descriptor.assert_called_once()
    mock_enqueue.assert_awaited_once()
    assert captured_descriptor is not None

    build_call = mock_build_descriptor.call_args
    assert build_call.kwargs["handler"] == "training.preflight"
    payload = build_call.kwargs["payload"]
    assert payload["task_id"] == "train_dispatch_test"
    assert payload["paths_to_check"] == [["patch_1", "patches/p1.png", "p1.png"]]
    assert payload["uploads_dir"] == "/uploads"
    assert payload["pipeline_kwargs"]["training_task_type"] == "patch_classification"
    assert payload["pipeline_kwargs"]["data_type"] == "patch"

    assert result["task_id"] == "train_dispatch_test"
    assert result["status"] == "pending"
    assert result["progress"] == 0


@pytest.mark.asyncio
async def test_create_training_task_returns_503_when_worker_unhealthy():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_unhealthy",
        task_name="unhealthy worker",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_unhealthy"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    create_task = AsyncMock(return_value=created_task)

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            side_effect=RuntimeError("must not be called"),
        ) as mock_local_preflight,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=RuntimeError("must not build descriptor when unhealthy"),
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=RuntimeError("must not enqueue when unhealthy")),
        ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail

    create_task.assert_not_awaited()
    mock_local_preflight.assert_not_called()
    mock_build_descriptor.assert_not_called()
    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_returns_validation_error_before_worker_health_check():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_invalid_before_health",
        task_name="invalid before health",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )

    db_read = AsyncMock()

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(side_effect=RuntimeError("must not check health")),
        ) as mock_health,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 400
    assert "Requested data_type 'patch' does not match dataset data_type 'wsi'" in exc_info.value.detail
    mock_health.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_marks_task_failed_when_descriptor_enqueue_fails():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_enqueue_failure",
        task_name="enqueue failure",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_enqueue_failure"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    db_cleanup = AsyncMock()
    create_task = AsyncMock(return_value=created_task)
    update_status = AsyncMock()

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write, db_cleanup),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.update_status",
            new=update_status,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(side_effect=RuntimeError("must not invalidate after enqueue failure")),
        ) as mock_invalidate,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=training_module.build_task_descriptor,
        ),
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail
    create_task.assert_awaited_once()
    mock_enqueue.assert_awaited_once()
    update_status.assert_awaited_once_with(
        db_cleanup,
        "train_enqueue_failure",
        training_module.TaskStatus.FAILED,
        error_message="Failed to enqueue task descriptor: redis down",
    )
    db_cleanup.commit.assert_awaited_once()
    mock_invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_active_training_task_publishes_cancellation_and_does_not_call_local_queue():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    task = SimpleNamespace(
        task_id="train_delete_active",
        user_id="user_1",
        status=training_module.TaskStatus.TRAINING,
    )
    db = AsyncMock()
    user = _make_user("admin")

    publish_mock = AsyncMock()

    with (
        patch(
            "gateway.routes.training.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=task),
        ),
        patch(
            "gateway.routes.training.TrainedModelRepository.get_by_task_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "gateway.routes.training.AIResultRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.delete",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingLogRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.cancel_ai_service_training",
            new=AsyncMock(),
        ) as mock_cancel_ai,
        patch(
            "gateway.routes.training.get_task_queue",
            side_effect=AssertionError("must not call local queue"),
        ),
        patch(
            "gateway.routes.training.publish_task_cancellation",
            new=publish_mock,
        ),
        patch(
            "gateway.routes.training.PaperGenerationRunRepository.list_for_user",
            new=AsyncMock(),
        ) as list_papers,
    ):
        response = await training_module.delete_training_task(
            task_id="train_delete_active", mode="standard", user=user, db=db
        )

    assert response["task_id"] == "train_delete_active"
    publish_mock.assert_awaited_once_with("train_delete_active")
    mock_cancel_ai.assert_awaited_once_with("train_delete_active")
    list_papers.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_completed_training_task_still_publishes_cancellation_to_stop_postprocessing():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    task = SimpleNamespace(
        task_id="train_delete_completed",
        user_id="user_1",
        status=training_module.TaskStatus.COMPLETED,
    )
    db = AsyncMock()
    user = _make_user("admin")
    publish_mock = AsyncMock()

    with (
        patch(
            "gateway.routes.training.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=task),
        ),
        patch(
            "gateway.routes.training.TrainedModelRepository.get_by_task_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "gateway.routes.training.AIResultRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.delete",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.cancel_ai_service_training",
            new=AsyncMock(),
        ) as mock_cancel_ai,
        patch(
            "gateway.routes.training.publish_task_cancellation",
            new=publish_mock,
        ),
        patch(
            "gateway.routes.training._delete_papers_for_training_task",
            new=AsyncMock(return_value={"status": "completed", "deleted": 2}),
        ) as delete_papers,
    ):
        response = await training_module.delete_training_task(
            task_id="train_delete_completed", mode="complete", user=user, db=db
        )

    assert response["task_id"] == "train_delete_completed"
    assert response["paper_cleanup"]["deleted"] == 2
    publish_mock.assert_awaited_once_with("train_delete_completed")
    mock_cancel_ai.assert_awaited_once_with("train_delete_completed")
    delete_papers.assert_awaited_once_with(db, "train_delete_completed", None)
