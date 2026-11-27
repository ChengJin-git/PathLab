import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import startup


@pytest.mark.asyncio
async def test_initialize_runtime_clients_attaches_http_clients(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    created_clients = []

    def _make_client(**kwargs):
        client = SimpleNamespace(kwargs=kwargs, aclose=AsyncMock())
        created_clients.append(client)
        return client

    monkeypatch.setattr(startup.httpx, "AsyncClient", _make_client)
    monkeypatch.setattr(startup, "AI_SERVICE_URL", "http://ai")
    monkeypatch.setattr(startup, "PREPROCESSING_SERVICE_URL", "http://pre")

    await startup.initialize_runtime_clients(app)

    assert app.state.ai_client is created_clients[0]
    assert app.state.preprocessing_client is created_clients[1]
    assert created_clients[0].kwargs["base_url"] == "http://ai"
    assert created_clients[1].kwargs["base_url"] == "http://pre"


@pytest.mark.asyncio
async def test_shutdown_runtime_clients_closes_attached_clients():
    ai_client = SimpleNamespace(aclose=AsyncMock())
    preprocessing_client = SimpleNamespace(aclose=AsyncMock())
    app = SimpleNamespace(
        state=SimpleNamespace(
            ai_client=ai_client,
            preprocessing_client=preprocessing_client,
        )
    )

    await startup.shutdown_runtime_clients(app)

    ai_client.aclose.assert_awaited_once()
    preprocessing_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_background_task_handles_pending_task():
    started = asyncio.Event()

    async def _pending() -> None:
        started.set()
        await asyncio.Event().wait()

    pending_task = asyncio.create_task(_pending())
    await started.wait()

    await startup.cancel_background_task(pending_task)

    assert pending_task.cancelled()


def test_start_background_prewarm_tasks_does_not_scan_all_users(monkeypatch):
    scheduled = []
    returned_tasks = [MagicMock(name="training-task"), MagicMock(name="chat-task")]
    iterator = iter(returned_tasks)

    def _create_task(coro):
        scheduled.append(coro)
        coro.close()
        return next(iterator)

    asr_prewarm = MagicMock()

    monkeypatch.setattr(startup.asyncio, "create_task", _create_task)
    monkeypatch.setattr(startup, "startup_prewarm_local_asr", asr_prewarm)

    training_task = startup.start_background_prewarm_tasks(has_cuda=True)

    assert training_task is returned_tasks[0]
    assert len(scheduled) == 1
    asr_prewarm.assert_called_once_with()


@pytest.mark.asyncio
async def test_initialize_gateway_runtime_runs_startup_sequence(monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    training_task = MagicMock(name="training-task")
    chat_task = MagicMock(name="chat-task")

    ensure_directories = MagicMock()
    init_db = AsyncMock()
    apply_schema_migration = AsyncMock()
    initialize_redis = AsyncMock()
    backfill_wsi_sources = AsyncMock()
    initialize_task_queue_runtime = AsyncMock(return_value={"has_cuda": True})
    resume_interrupted_tasks = AsyncMock()
    cleanup_progress_files = AsyncMock()
    cleanup_pdf_cache_runtime = AsyncMock()
    log_bundled_training_readiness = AsyncMock()
    cleanup_old_tasks = AsyncMock()
    start_background = MagicMock(return_value=training_task)
    initialize_runtime_clients = AsyncMock()

    monkeypatch.setattr(startup.Config, "ensure_directories", ensure_directories)
    monkeypatch.setattr(startup, "init_db", init_db, raising=False)
    monkeypatch.setattr(
        startup, "apply_gateway_schema_migration", apply_schema_migration, raising=False
    )
    monkeypatch.setattr(
        startup, "initialize_redis_connections", initialize_redis, raising=False
    )
    monkeypatch.setattr(
        startup, "backfill_wsi_sources", backfill_wsi_sources, raising=False
    )
    monkeypatch.setattr(
        startup,
        "initialize_task_queue_runtime",
        initialize_task_queue_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        startup, "cleanup_progress_files", cleanup_progress_files, raising=False
    )
    monkeypatch.setattr(
        startup, "cleanup_pdf_cache_runtime", cleanup_pdf_cache_runtime, raising=False
    )
    monkeypatch.setattr(
        startup,
        "log_bundled_training_readiness",
        log_bundled_training_readiness,
        raising=False,
    )
    monkeypatch.setattr("task_worker.recovery.resume_interrupted_tasks", resume_interrupted_tasks)
    monkeypatch.setattr(startup, "cleanup_old_tasks", cleanup_old_tasks)
    monkeypatch.setattr(
        startup, "start_background_prewarm_tasks", start_background, raising=False
    )
    monkeypatch.setattr(
        startup, "initialize_runtime_clients", initialize_runtime_clients
    )

    result = await startup.initialize_gateway_runtime(app)

    assert result == training_task
    ensure_directories.assert_called_once_with()
    init_db.assert_awaited_once()
    apply_schema_migration.assert_not_awaited()
    initialize_redis.assert_awaited_once()
    backfill_wsi_sources.assert_not_awaited()
    cleanup_progress_files.assert_not_awaited()
    initialize_task_queue_runtime.assert_not_awaited()
    resume_interrupted_tasks.assert_not_awaited()
    cleanup_old_tasks.assert_awaited_once()
    cleanup_pdf_cache_runtime.assert_awaited_once()
    log_bundled_training_readiness.assert_awaited_once()
    start_background.assert_called_once_with(has_cuda=False)
    initialize_runtime_clients.assert_awaited_once_with(app)


@pytest.mark.asyncio
async def test_shutdown_gateway_runtime_runs_shutdown_sequence():
    app = SimpleNamespace(state=SimpleNamespace())
    training_task = MagicMock(name="training-task")
    chat_task = MagicMock(name="chat-task")

    cancel_background_task = AsyncMock()
    shutdown_runtime_clients = AsyncMock()
    shutdown_task_queue = AsyncMock()
    close_db = AsyncMock()
    close_redis_connections = AsyncMock()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(startup, "cancel_background_task", cancel_background_task)
    monkeypatch.setattr(startup, "shutdown_runtime_clients", shutdown_runtime_clients)
    monkeypatch.setattr(startup, "shutdown_task_queue", shutdown_task_queue, raising=False)
    monkeypatch.setattr(startup, "close_db", close_db)
    monkeypatch.setattr(startup, "close_redis_connections", close_redis_connections)

    try:
        await startup.shutdown_gateway_runtime(app, training_task)
    finally:
        monkeypatch.undo()

    cancel_background_task.assert_any_await(training_task)
    shutdown_runtime_clients.assert_awaited_once_with(app)
    shutdown_task_queue.assert_not_awaited()
    close_db.assert_awaited_once()
    close_redis_connections.assert_awaited_once()
