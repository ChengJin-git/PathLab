import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from helpers import _make_user


class _FakeDB:
    def __init__(self) -> None:
        self.commit = AsyncMock()


def _make_app(user_stub, include_gpu: bool = False) -> FastAPI:
    from backend.auth import current_active_user
    from backend.auth.dependencies import require_admin, require_can_use_gpu
    from gateway.routes.queue import router as queue_router

    app = FastAPI()
    app.dependency_overrides[current_active_user] = lambda: user_stub
    app.dependency_overrides[require_admin] = lambda: user_stub
    app.include_router(queue_router)

    if include_gpu:
        from gateway.routes.gpu import router as gpu_router

        app.dependency_overrides[require_can_use_gpu] = lambda: user_stub
        app.include_router(gpu_router)

    return app


@pytest.mark.asyncio
async def test_queue_status_uses_worker_heartbeat_without_local_queue():
    admin = _make_user("admin")
    app = _make_app(admin)

    with (
        patch("gateway.routes.queue.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/queue")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_running"] is True
    assert "max_concurrent" in data
    assert "task_timeout" in data
    assert "running_count" in data
    assert "pending_count" in data
    assert "queue_size" in data
    assert "running_task_ids" in data
    assert "pending_task_ids" in data


@pytest.mark.asyncio
async def test_queue_status_uses_worker_runtime_snapshot_without_local_queue():
    admin = _make_user("admin")
    app = _make_app(admin)

    from datetime import datetime, timezone

    fake_snapshot = {
        "is_running": True,
        "max_concurrent": 3,
        "gpu_count": 6,
        "task_timeout": 300,
        "running_count": 2,
        "pending_count": 1,
        "patching_count": 1,
        "descriptor_processing_count": 2,
        "descriptor_dlq_count": 1,
        "queue_size": 2,
        "running_task_ids": ["run1", "run2"],
        "pending_task_ids": ["pend1"],
        "patching_task_ids": ["patch1"],
        "bad_gpu_ids": [1],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    with (
        patch(
            "gateway.routes.queue.get_runtime_status",
            new=AsyncMock(return_value=fake_snapshot),
        ),
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/queue")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_running"] is True
    assert data["max_concurrent"] == 3
    assert data["gpu_count"] == 6
    assert data["task_timeout"] == 300
    assert data["running_count"] == 2
    assert data["pending_count"] == 1
    assert data["descriptor_processing_count"] == 2
    assert data["descriptor_dlq_count"] == 1
    assert data["queue_size"] == 2
    assert data["running_task_ids"] == ["run1", "run2"]
    assert data["pending_task_ids"] == ["pend1"]
    assert data["patching_count"] == 1
    assert data["patching_task_ids"] == ["patch1"]


@pytest.mark.asyncio
async def test_queue_status_falls_back_to_heartbeat_when_snapshot_missing():
    admin = _make_user("admin")
    app = _make_app(admin)

    with (
        patch(
            "gateway.routes.queue.get_runtime_status",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gateway.routes.queue.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/queue")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_running"] is True
    assert data["gpu_count"] == 0
    assert data["running_count"] == 0
    assert data["pending_count"] == 0
    assert data["descriptor_processing_count"] == 0
    assert data["descriptor_dlq_count"] == 0
    assert data["queue_size"] == 0
    assert data["running_task_ids"] == []
    assert data["pending_task_ids"] == []
    assert data["patching_count"] == 0
    assert data["patching_task_ids"] == []


@pytest.mark.asyncio
async def test_queue_status_ignores_stale_snapshot():
    admin = _make_user("admin")
    app = _make_app(admin)

    from datetime import datetime, timezone, timedelta
    from task_worker.runtime_status import RUNTIME_STATUS_TTL_SECONDS

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=RUNTIME_STATUS_TTL_SECONDS + 5)
    stale_snapshot = {
        "is_running": True,
        "max_concurrent": 3,
        "task_timeout": 300,
        "running_count": 2,
        "pending_count": 1,
        "patching_count": 1,
        "queue_size": 2,
        "running_task_ids": ["run1", "run2"],
        "pending_task_ids": ["pend1"],
        "patching_task_ids": ["patch1"],
        "bad_gpu_ids": [1],
        "updated_at": stale_time.isoformat(),
    }

    with (
        patch(
            "gateway.routes.queue.get_runtime_status",
            new=AsyncMock(return_value=stale_snapshot),
        ),
        patch(
            "gateway.routes.queue.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/queue")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_running"] is True
    assert data["gpu_count"] == 0
    assert data["running_count"] == 0
    assert data["pending_count"] == 0
    assert data["queue_size"] == 0
    assert data["running_task_ids"] == []
    assert data["pending_task_ids"] == []
    assert data["patching_count"] == 0
    assert data["patching_task_ids"] == []


@pytest.mark.asyncio
async def test_cancel_queued_task_publishes_cancellation_without_local_queue():
    user = _make_user("user")
    fake_db = _FakeDB()
    app = _make_app(user)

    from gateway.routes import queue as queue_routes

    async def _override_db():
        yield fake_db

    app.dependency_overrides[queue_routes.get_db] = _override_db

    ai_task = SimpleNamespace(
        id="task-ai-123",
        status="running",
        user_id=str(user.id),
    )

    with (
        patch("gateway.routes.queue.get_analysis_state") as analysis_state_factory,
        patch("gateway.routes.queue.AITaskRepository.get_by_id", new=AsyncMock(return_value=ai_task)),
        patch(
            "gateway.routes.queue.AITaskRepository.update_status",
            new=AsyncMock(),
        ) as update_status,
        patch(
            "gateway.routes.queue.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gateway.routes.queue.publish_task_cancellation",
            new=AsyncMock(),
        ) as publish_cancel,
        patch(
            "gateway.routes.queue.cancel_ai_service_training",
            new=AsyncMock(),
        ) as notify_ai,
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        analysis_state = MagicMock()
        analysis_state.get = AsyncMock(return_value=None)
        analysis_state_factory.return_value = analysis_state

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/queue/task-ai-123")

    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True
    publish_cancel.assert_awaited_once_with("task-ai-123")
    update_status.assert_awaited_once()
    notify_ai.assert_awaited_once_with("task-ai-123")
    fake_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_unknown_task_does_not_publish_cancellation():
    user = _make_user("user")
    fake_db = _FakeDB()
    app = _make_app(user)

    from gateway.routes import queue as queue_routes

    async def _override_db():
        yield fake_db

    app.dependency_overrides[queue_routes.get_db] = _override_db

    with (
        patch("gateway.routes.queue.get_analysis_state") as analysis_state_factory,
        patch(
            "gateway.routes.queue.AITaskRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gateway.routes.queue.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gateway.routes.queue.publish_task_cancellation",
            new=AsyncMock(),
        ) as publish_cancel,
        patch(
            "gateway.routes.queue.cancel_ai_service_training",
            new=AsyncMock(),
        ) as notify_ai,
    ):
        analysis_state = MagicMock()
        analysis_state.get = AsyncMock(return_value=None)
        analysis_state_factory.return_value = analysis_state

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/queue/unknown-task")

    assert resp.status_code == 200
    assert resp.json()["cancelled"] is False
    publish_cancel.assert_not_awaited()
    notify_ai.assert_not_awaited()
    fake_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_task_in_queue_uses_persisted_state_without_local_queue():
    user = _make_user("user")
    fake_db = _FakeDB()
    app = _make_app(user)

    from gateway.routes import queue as queue_routes

    async def _override_db():
        yield fake_db

    app.dependency_overrides[queue_routes.get_db] = _override_db

    ai_task = SimpleNamespace(
        id="task-ai-queued",
        status="queued",
        user_id=str(user.id),
    )

    with (
        patch("gateway.routes.queue.get_analysis_state") as analysis_state_factory,
        patch(
            "gateway.routes.queue.AITaskRepository.get_by_id",
            new=AsyncMock(return_value=ai_task),
        ),
        patch(
            "gateway.routes.queue.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        analysis_state = MagicMock()
        analysis_state.get = AsyncMock(return_value=None)
        analysis_state_factory.return_value = analysis_state

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/queue/task-ai-queued")

    assert resp.status_code == 200
    assert resp.json() == {
        "task_id": "task-ai-queued",
        "in_queue": True,
        "status": "pending",
    }


@pytest.mark.asyncio
async def test_gpu_info_does_not_require_local_queue_for_bad_gpu_list():
    user = _make_user("admin")
    app = _make_app(user, include_gpu=True)

    fake_device = SimpleNamespace(index=0)

    with (
        patch("gateway.routes.gpu.torch.cuda.is_available", return_value=True),
        patch("gateway.routes.gpu.torch.cuda.device_count", return_value=1),
        patch("gateway.routes.gpu.torch.version.cuda", "12.1"),
        patch("gateway.routes.gpu.get_optimal_device", return_value=fake_device),
        patch("gateway.routes.gpu.torch.cuda.get_device_name", return_value="GPU0"),
        patch(
            "gateway.routes.gpu.get_gpu_memory_info",
            return_value=(128.0, 896.0, 1024.0),
        ),
        patch(
            "gateway.routes.gpu.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/gpu/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["bad_gpu_count"] == 0
    assert data["gpus"][0]["is_healthy"] is True


@pytest.mark.asyncio
async def test_gpu_info_reads_worker_bad_gpu_snapshot():
    user = _make_user("admin")
    app = _make_app(user, include_gpu=True)

    fake_device = SimpleNamespace(index=0)

    with (
        patch("gateway.routes.gpu.torch.cuda.is_available", return_value=True),
        patch("gateway.routes.gpu.torch.cuda.device_count", return_value=2),
        patch("gateway.routes.gpu.torch.version.cuda", "12.1"),
        patch("gateway.routes.gpu.get_optimal_device", return_value=fake_device),
        patch(
            "gateway.routes.gpu.torch.cuda.get_device_name",
            side_effect=["GPU0", "GPU1"],
        ),
        patch(
            "gateway.routes.gpu.get_gpu_memory_info",
            return_value=(128.0, 896.0, 1024.0),
        ),
        patch(
            "gateway.routes.gpu.get_runtime_status",
            new=AsyncMock(return_value={"bad_gpu_ids": [0]}),
        ),
        patch(
            "gateway.routes.gpu.get_task_queue",
            side_effect=AssertionError("local queue must not be used"),
            create=True,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/gpu/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["bad_gpu_count"] == 1
    assert data["gpus"][0]["is_healthy"] is False
    assert data["gpus"][1]["is_healthy"] is True
