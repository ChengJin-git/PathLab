"""Client disconnects release pooled connections without cancelling termination."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import database


async def test_get_db_cancellation_rolls_back_and_closes_once(monkeypatch):
    session = SimpleNamespace(
        rollback=AsyncMock(), close=AsyncMock(), commit=AsyncMock()
    )
    monkeypatch.setattr(database, "async_session", lambda: session)
    dependency = database.get_db()
    assert await anext(dependency) is session
    with pytest.raises(asyncio.CancelledError):
        await dependency.athrow(asyncio.CancelledError())
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


async def test_connection_invalidation_is_shielded_from_anyio_cancellation():
    closed = []

    async def invalidate():
        await anyio.lowlevel.checkpoint()
        closed.append(True)

    with anyio.CancelScope() as scope:
        scope.cancel()
        await database._invalidate_session_connection(
            SimpleNamespace(invalidate=invalidate)
        )
    assert closed == [True]


async def test_get_db_success_commits_and_closes_only_once(monkeypatch):
    session = SimpleNamespace(
        rollback=AsyncMock(), close=AsyncMock(), commit=AsyncMock()
    )
    monkeypatch.setattr(database, "async_session", lambda: session)
    dependency = database.get_db()
    assert await anext(dependency) is session
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)
    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.fixture
async def postgres(monkeypatch):
    url = os.getenv("PATHLAB_TEST_POSTGRES_URL")
    if not url:
        pytest.skip(
            "Set PATHLAB_TEST_POSTGRES_URL for actual asyncpg cancellation checks"
        )
    engine = create_async_engine(url, pool_size=2, max_overflow=0, pool_timeout=1)
    monkeypatch.setattr(
        database, "async_session", async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_sse_read_finishes_before_disconnect_and_returns_connection(
    postgres, caplog
):
    started = asyncio.Event()
    invalidations = []

    @event.listens_for(postgres.sync_engine, "before_cursor_execute")
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "pg_sleep" in statement:
            started.set()

    @event.listens_for(postgres.sync_engine, "invalidate")
    def invalidated(connection, record, exception):
        invalidations.append(exception)

    caplog.set_level(logging.WARNING, logger="sqlalchemy.pool")
    completed, propagated = [], []

    async def read():
        try:
            async with database.read_session() as session:
                assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                assert await session.scalar(text("SHOW statement_timeout")) == "5s"
                await session.execute(text("SELECT pg_sleep(0.05)"))
                completed.append(True)
        except asyncio.CancelledError:
            propagated.append(True)
            raise

    for _ in range(5):
        started.clear()
        async with anyio.create_task_group() as group:
            group.start_soon(read)
            await started.wait()
            group.cancel_scope.cancel()
        assert postgres.pool.checkedout() == 0
    assert len(completed) == len(propagated) == 5
    assert not invalidations
    assert not any(
        "terminating connection" in record.message for record in caplog.records
    )
    async with database.read_session() as session:
        assert await session.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("kind", ["training", "storage"])
async def test_task_sse_releases_session_before_network_and_yield(monkeypatch, kind):
    from gateway.routes import training, storage_tasks

    active = []

    @asynccontextmanager
    async def read_session():
        active.append(True)
        try:
            yield SimpleNamespace()
        finally:
            active.clear()

    monkeypatch.setattr(database, "read_session", read_session)
    user = SimpleNamespace(id="owner", is_admin=lambda: False)
    if kind == "training":
        monkeypatch.setattr(
            training.TrainingTaskRepository, "get_all", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            training.TrainingTaskRepository,
            "get_wsi_counts_batch",
            AsyncMock(return_value={}),
        )

        async def network(*args):
            assert not active, "Redis awaited while holding a database connection"
            return {}

        monkeypatch.setattr("backend.common.progress_store.get_progress_batch", network)
        monkeypatch.setattr(training, "get_worker_runtime_snapshot", network)
        response = await training.stream_training_tasks(user)
    else:
        monkeypatch.setattr(
            storage_tasks.StorageTaskRepository,
            "get_user_tasks",
            AsyncMock(return_value=[]),
        )
        response = await storage_tasks.stream_storage_tasks(user)
    assert "items" in await anext(response.body_iterator)
    assert not active, "Streaming response retained a database connection"
    await response.body_iterator.aclose()


@pytest.mark.parametrize("kind", ["training", "storage"])
@pytest.mark.parametrize("when", ["query", "send"])
async def test_real_asgi_disconnect_leaves_pool_healthy(
    postgres, monkeypatch, caplog, kind, when
):
    from gateway.routes import training, storage_tasks

    query_started, disconnect = asyncio.Event(), asyncio.Event()

    @event.listens_for(postgres.sync_engine, "before_cursor_execute")
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "pg_sleep" in statement:
            query_started.set()

    async def slow_query(db, *args, **kwargs):
        await db.execute(text("SELECT pg_sleep(0.03)"))
        return []

    monkeypatch.setattr(training.TrainingTaskRepository, "get_all", slow_query)
    monkeypatch.setattr(
        training.TrainingTaskRepository,
        "get_wsi_counts_batch",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "backend.common.progress_store.get_progress_batch", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        training, "get_worker_runtime_snapshot", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        storage_tasks.StorageTaskRepository, "get_user_tasks", slow_query
    )
    user = SimpleNamespace(id="owner", is_admin=lambda: False)
    caplog.set_level(logging.WARNING, logger="sqlalchemy.pool")
    body_chunks = []

    async def send(message):
        if message["type"] == "http.response.body":
            assert postgres.pool.checkedout() == 0
            if message["body"]:
                body_chunks.append(message["body"])
            if when == "send" and message["body"]:
                disconnect.set()

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"}}
    for _ in range(3):
        query_started.clear()
        disconnect.clear()
        response = await (
            training.stream_training_tasks(user)
            if kind == "training"
            else storage_tasks.stream_storage_tasks(user)
        )
        serving = asyncio.create_task(response(scope, receive, send))
        try:
            await asyncio.wait_for(query_started.wait(), 2)
            if when == "query":
                disconnect.set()
            await asyncio.wait_for(serving, 2)
        finally:
            if not serving.done():
                serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)
        assert postgres.pool.checkedout() == 0
    assert len(body_chunks) == (3 if when == "send" else 0)
    assert not any(
        "terminating connection" in record.message for record in caplog.records
    )
    async with database.read_session() as db:
        assert await db.scalar(text("SELECT 1")) == 1
