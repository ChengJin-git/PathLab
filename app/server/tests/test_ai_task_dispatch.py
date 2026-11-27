from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.common.task_dispatch import build_task_descriptor


def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.id = "user_1"
    user.role = role
    user.is_active = True
    user.is_admin = MagicMock(return_value=(role == "admin"))
    user.can_use_gpu = MagicMock(return_value=(role in ("admin", "pathologist")))
    return user


@pytest.mark.asyncio
async def test_create_wsi_classification_enqueues_inference_single_descriptor():
    ai_tasks = __import__("gateway.routes.ai_tasks", fromlist=[""])

    req = ai_tasks.WSIClassifyRequest(
        wsi_id="wsi_1",
        classes=["tumor", "normal"],
        model_id="model_1",
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="wsi_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="/uploads/wsi_1.tiff",
        original_filename="wsi_1.tiff",
    )
    model = SimpleNamespace(model_id="model_1", is_active=True, classes=['tumor','normal'], feature_extractor='conch')

    db = AsyncMock()
    captured_descriptor = None
    local_queue = SimpleNamespace(submit=AsyncMock(side_effect=AssertionError("local queue submit must not be used")))

    async def _capture_enqueue(descriptor):
        nonlocal captured_descriptor
        captured_descriptor = descriptor

    with (
        patch(
            "gateway.routes.ai_tasks.WSIRepository.get_by_id_with_dataset",
            new=AsyncMock(return_value=wsi),
        ),
        patch(
            "gateway.routes.ai_tasks.check_wsi_access_permission",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.ai_tasks.os.path.exists",
            return_value=True,
        ),
        patch(
            "gateway.routes.ai_tasks.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.require_dataset_gpu_permission",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.TrainedModelRepository.get_by_id",
            new=AsyncMock(return_value=model),
        ),
        patch(
            "gateway.routes.ai_tasks.AITaskRepository.create",
            new=AsyncMock(),
        ) as mock_db_create,
        patch(
            "gateway.routes.ai_tasks.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ) as mock_health,
        patch(
            "gateway.routes.ai_tasks.get_task_queue",
            return_value=local_queue,
            create=True,
        ),
        patch(
            "gateway.routes.ai_tasks.build_task_descriptor",
            side_effect=build_task_descriptor,
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.ai_tasks.enqueue_task_descriptor",
            new=AsyncMock(side_effect=_capture_enqueue),
        ) as mock_enqueue,
    ):
        result = await ai_tasks.create_wsi_classification(req=req, user=user, db=db)

    mock_health.assert_awaited_once()
    mock_build_descriptor.assert_called_once()
    mock_enqueue.assert_awaited_once()
    local_queue.submit.assert_not_awaited()
    assert captured_descriptor is not None

    build_call = mock_build_descriptor.call_args
    assert build_call.kwargs["handler"] == "inference.single"
    payload = build_call.kwargs["payload"]
    assert payload["task_id"].startswith("inf_")
    assert payload["wsi_id"] == "wsi_1"
    assert payload["model_id"] == "model_1"

    mock_db_create.assert_awaited_once()
    create_call = mock_db_create.call_args
    assert create_call.args[1]["status"] == "pending"

    assert result["status"] == "pending"
    assert result["task_id"] == payload["task_id"]
    assert "Inference task queued successfully" in result["message"]


@pytest.mark.asyncio
async def test_create_wsi_classification_returns_503_when_worker_unhealthy():
    ai_tasks = __import__("gateway.routes.ai_tasks", fromlist=[""])

    req = ai_tasks.WSIClassifyRequest(
        wsi_id="wsi_1",
        classes=["tumor", "normal"],
        model_id="model_1",
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="wsi_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="/uploads/wsi_1.tiff",
        original_filename="wsi_1.tiff",
    )
    model = SimpleNamespace(model_id="model_1", is_active=True, classes=['tumor','normal'], feature_extractor='conch')

    db = AsyncMock()

    with (
        patch(
            "gateway.routes.ai_tasks.WSIRepository.get_by_id_with_dataset",
            new=AsyncMock(return_value=wsi),
        ),
        patch(
            "gateway.routes.ai_tasks.check_wsi_access_permission",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.ai_tasks.os.path.exists",
            return_value=True,
        ),
        patch(
            "gateway.routes.ai_tasks.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.require_dataset_gpu_permission",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.TrainedModelRepository.get_by_id",
            new=AsyncMock(return_value=model),
        ),
        patch(
            "gateway.routes.ai_tasks.AITaskRepository.create",
            new=AsyncMock(),
        ) as mock_db_create,
            patch(
                "gateway.routes.ai_tasks.is_worker_healthy",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "gateway.routes.ai_tasks.build_task_descriptor",
                side_effect=RuntimeError("must not build when unhealthy"),
            ) as mock_build_descriptor,
            patch(
                "gateway.routes.ai_tasks.enqueue_task_descriptor",
                new=AsyncMock(side_effect=RuntimeError("must not enqueue when unhealthy")),
            ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ai_tasks.create_wsi_classification(req=req, user=user, db=db)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail
    mock_db_create.assert_not_awaited()
    db.commit.assert_not_awaited()
    mock_build_descriptor.assert_not_called()
    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_wsi_classification_validation_error_before_worker_health_check():
    ai_tasks = __import__("gateway.routes.ai_tasks", fromlist=[""])

    req = ai_tasks.WSIClassifyRequest(
        wsi_id="missing_wsi",
        classes=["tumor", "normal"],
        model_id="model_1",
    )
    user = _make_user("admin")
    db = AsyncMock()

    with (
        patch(
            "gateway.routes.ai_tasks.WSIRepository.get_by_id_with_dataset",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gateway.routes.ai_tasks.is_worker_healthy",
            new=AsyncMock(side_effect=RuntimeError("must not check health")),
        ) as mock_health,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ai_tasks.create_wsi_classification(req=req, user=user, db=db)

    assert exc_info.value.status_code == 404
    assert "wsi_id not found" in exc_info.value.detail
    mock_health.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_wsi_classification_marks_task_failed_when_descriptor_enqueue_fails():
    ai_tasks = __import__("gateway.routes.ai_tasks", fromlist=[""])

    req = ai_tasks.WSIClassifyRequest(
        wsi_id="wsi_1",
        classes=["tumor", "normal"],
        model_id="model_1",
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="wsi_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="/uploads/wsi_1.tiff",
        original_filename="wsi_1.tiff",
    )
    model = SimpleNamespace(model_id="model_1", is_active=True, classes=['tumor','normal'], feature_extractor='conch')

    db = AsyncMock()
    db_cleanup = AsyncMock()
    update_status = AsyncMock()

    with (
        patch(
            "gateway.routes.ai_tasks.WSIRepository.get_by_id_with_dataset",
            new=AsyncMock(return_value=wsi),
        ),
        patch(
            "gateway.routes.ai_tasks.check_wsi_access_permission",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.ai_tasks.os.path.exists",
            return_value=True,
        ),
        patch(
            "gateway.routes.ai_tasks.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.require_dataset_gpu_permission",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.ai_tasks.TrainedModelRepository.get_by_id",
            new=AsyncMock(return_value=model),
        ),
        patch(
            "gateway.routes.ai_tasks.AITaskRepository.create",
            new=AsyncMock(),
        ) as mock_db_create,
        patch(
            "gateway.routes.ai_tasks.AITaskRepository.update_status",
            new=update_status,
        ),
        patch(
            "gateway.routes.ai_tasks.invalidate_chat_context",
            new=AsyncMock(side_effect=RuntimeError("must not invalidate after enqueue failure")),
        ) as mock_invalidate,
        patch(
            "gateway.routes.ai_tasks.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.ai_tasks.build_task_descriptor",
            side_effect=build_task_descriptor,
        ),
        patch(
            "gateway.routes.ai_tasks.enqueue_task_descriptor",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ai_tasks.create_wsi_classification(req=req, user=user, db=db)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail
    mock_db_create.assert_awaited_once()
    mock_enqueue.assert_awaited_once()
    update_status.assert_awaited_once()
    mock_invalidate.assert_not_awaited()
