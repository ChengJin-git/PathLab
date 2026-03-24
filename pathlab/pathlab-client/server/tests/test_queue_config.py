import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from helpers import _make_user


def _make_queue_stub(
    max_concurrent: int = 4,
    gpu_count: int = 2,
    running_ids: list[str] | None = None,
    pending_ids: list[str] | None = None,
) -> MagicMock:
    queue = MagicMock()
    queue.max_concurrent = max_concurrent
    queue.gpu_count = gpu_count
    queue.set_max_concurrent = AsyncMock()
    queue.cancel_task = AsyncMock(return_value=True)
    queue.get_status = MagicMock(
        return_value={
            "max_concurrent": max_concurrent,
            "running_count": len(running_ids or []),
            "pending_count": len(pending_ids or []),
            "queue_size": len(running_ids or []) + len(pending_ids or []),
            "running_task_ids": running_ids or [],
            "pending_task_ids": pending_ids or [],
            "is_running": True,
        }
    )
    return queue


def _make_queue_app_with_stub(user_stub, queue_stub) -> "FastAPI":
    from fastapi import FastAPI
    from gateway.routes.queue import router as queue_router
    from backend.auth import current_active_user
    from backend.auth.dependencies import require_admin

    app = FastAPI()
    app.dependency_overrides[current_active_user] = lambda: user_stub
    app.dependency_overrides[require_admin] = lambda: user_stub
    app.include_router(queue_router)
    return app


@pytest.fixture
def admin():
    return _make_user("admin")


@pytest.fixture
def queue_stub():
    return _make_queue_stub()


@pytest_asyncio.fixture
async def client(admin, queue_stub, tmp_path):
    app = _make_queue_app_with_stub(admin, queue_stub)
    with (
        patch("gateway.routes.queue.get_task_queue", return_value=queue_stub),
        patch(
            "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
        ),
    ):
        from backend.common.config import Config

        Config._task_timeout = None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


@pytest.mark.asyncio
class TestGetQueueConfig:
    async def test_returns_max_concurrent_and_task_timeout(self, client):
        resp = await client.get("/queue/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "max_concurrent" in data
        assert "task_timeout" in data

    async def test_max_concurrent_matches_queue(self, client, queue_stub):
        resp = await client.get("/queue/config")
        assert resp.json()["max_concurrent"] == queue_stub.max_concurrent

    async def test_task_timeout_is_positive_integer(self, client):
        resp = await client.get("/queue/config")
        assert resp.json()["task_timeout"] > 0


@pytest.mark.asyncio
class TestGetQueueStatus:
    async def test_returns_200(self, client):
        resp = await client.get("/queue")
        assert resp.status_code == 200

    async def test_status_includes_required_fields(self, client):
        resp = await client.get("/queue")
        data = resp.json()
        assert "max_concurrent" in data
        assert "running_count" in data
        assert "pending_count" in data
        assert "queue_size" in data
        assert "running_task_ids" in data
        assert "pending_task_ids" in data
        assert "is_running" in data

    async def test_is_running_true(self, client):
        resp = await client.get("/queue")
        assert resp.json()["is_running"] is True

    async def test_queue_not_initialized_returns_503(self, admin, tmp_path):
        app = _make_queue_app_with_stub(admin, MagicMock())
        with patch("gateway.routes.queue.get_task_queue", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.get("/queue")
        assert resp.status_code == 503


@pytest.mark.asyncio
class TestUpdateQueueConfig:
    async def test_update_task_timeout(self, client, tmp_path):
        with patch(
            "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
        ):
            resp = await client.post("/queue/config", json={"task_timeout": 7200})
        assert resp.status_code == 200
        assert "7200" in resp.json()["message"]

    async def test_update_max_concurrent_multi_gpu(self, admin, tmp_path):
        multi_gpu_queue = _make_queue_stub(max_concurrent=1, gpu_count=4)
        app = _make_queue_app_with_stub(admin, multi_gpu_queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=multi_gpu_queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.post("/queue/config", json={"max_concurrent": 3})
        assert resp.status_code == 200
        multi_gpu_queue.set_max_concurrent.assert_awaited_once_with(3)

    async def test_single_gpu_rejects_max_concurrent_change(self, admin, tmp_path):
        single_gpu_queue = _make_queue_stub(max_concurrent=1, gpu_count=1)
        app = _make_queue_app_with_stub(admin, single_gpu_queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=single_gpu_queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.post("/queue/config", json={"max_concurrent": 2})
        assert resp.status_code == 400

    async def test_empty_body_returns_400(self, client):
        resp = await client.post("/queue/config", json={})
        assert resp.status_code == 400

    async def test_update_both_fields_simultaneously(self, admin, tmp_path):
        multi_gpu_queue = _make_queue_stub(max_concurrent=1, gpu_count=2)
        app = _make_queue_app_with_stub(admin, multi_gpu_queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=multi_gpu_queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.post(
                    "/queue/config", json={"max_concurrent": 2, "task_timeout": 3600}
                )
        assert resp.status_code == 200
        msg = resp.json()["message"]
        assert "max_concurrent" in msg
        assert "task_timeout" in msg


@pytest.mark.asyncio
class TestCheckTaskInQueue:
    async def test_task_is_running(self, admin, tmp_path):
        task_id = "task-running-001"
        queue = _make_queue_stub(running_ids=[task_id])
        app = _make_queue_app_with_stub(admin, queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.get(f"/queue/{task_id}")
        data = resp.json()
        assert data["in_queue"] is True
        assert data["status"] == "running"

    async def test_task_is_pending(self, admin, tmp_path):
        task_id = "task-pending-002"
        queue = _make_queue_stub(pending_ids=[task_id])
        app = _make_queue_app_with_stub(admin, queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.get(f"/queue/{task_id}")
        data = resp.json()
        assert data["in_queue"] is True
        assert data["status"] == "pending"

    async def test_task_not_found(self, admin, tmp_path):
        queue = _make_queue_stub()
        app = _make_queue_app_with_stub(admin, queue)
        with (
            patch("gateway.routes.queue.get_task_queue", return_value=queue),
            patch(
                "backend.common.config.Config.STORAGE_CONFIG_FILE",
                str(tmp_path / "s.json"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.get("/queue/nonexistent-task")
        data = resp.json()
        assert data["in_queue"] is False
        assert data["status"] == "not_found"
