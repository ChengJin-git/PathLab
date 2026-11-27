from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import startup


@pytest.mark.asyncio
async def test_initialize_gateway_runtime_does_not_start_local_worker_execution(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    training_task = MagicMock(name="training-task")
    chat_task = MagicMock(name="chat-task")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Gateway must not start worker-owned queue execution")

    monkeypatch.setattr(startup.Config, "ensure_directories", MagicMock())
    monkeypatch.setattr(startup, "init_db", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "apply_gateway_schema_migration", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "initialize_redis_connections", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "backfill_wsi_sources", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "cleanup_progress_files", forbidden, raising=False)
    monkeypatch.setattr("backend.common.progress_store.cleanup_all_progress", forbidden)
    monkeypatch.setattr(startup, "cleanup_old_tasks", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "cleanup_pdf_cache_runtime", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "log_bundled_training_readiness", AsyncMock(), raising=False)
    monkeypatch.setattr(startup, "initialize_runtime_clients", AsyncMock())
    monkeypatch.setattr(
        startup,
        "start_background_prewarm_tasks",
        MagicMock(return_value=training_task),
        raising=False,
    )
    monkeypatch.setattr(startup, "initialize_task_queue_runtime", forbidden, raising=False)
    monkeypatch.setattr("task_worker.recovery.resume_interrupted_tasks", forbidden)

    result = await startup.initialize_gateway_runtime(app)

    assert result == training_task


@pytest.mark.asyncio
async def test_shutdown_gateway_runtime_does_not_stop_local_worker_queue(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Gateway must not stop worker-owned queue execution")

    monkeypatch.setattr(startup, "cancel_background_task", AsyncMock())
    monkeypatch.setattr(startup, "shutdown_runtime_clients", AsyncMock())
    monkeypatch.setattr(startup, "close_db", AsyncMock())
    monkeypatch.setattr(startup, "close_redis_connections", AsyncMock())
    monkeypatch.setattr(startup, "shutdown_task_queue", forbidden, raising=False)

    await startup.shutdown_gateway_runtime(
        app,
        MagicMock(name="training-task"),
    )
