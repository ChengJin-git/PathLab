import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import current_active_user
from backend.autoresearch.engine import scheduler as module
from backend.autoresearch.engine.scheduler import ResearchScheduler, session_queue
from backend.common.config import Config
from gateway.routes.queue import router as queue_router


@pytest.fixture
def fake_store(monkeypatch):
    rows = {
        str(i): SimpleNamespace(id=i, session_id=str(i), user_id=f"owner-{i}", status="queued", recovery_metadata={}, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1)) for i in range(5)
    }

    async def update(sid, **kwargs):
        if kwargs.get('expected_statuses') and rows[sid].status not in kwargs['expected_statuses']:
            return {}
        if "status" in kwargs:
            rows[sid].status = kwargs["status"]
        rows[sid].recovery_metadata.update(kwargs.get('meta', {}))
        return kwargs.get("event", {})

    monkeypatch.setattr(module.store, "update", AsyncMock(side_effect=update))
    monkeypatch.setattr(
        module.store, "get", AsyncMock(side_effect=lambda sid: rows[sid])
    )
    monkeypatch.setattr(module.store, "take_commands", AsyncMock(return_value=[]))
    return rows


@pytest.mark.asyncio
async def test_cap_counts_waiting_agents_and_admits_fifo_after_completion(fake_store):
    gates = {sid: asyncio.Event() for sid in fake_store}
    entered = []

    async def run(sid):
        entered.append(sid)
        fake_store[sid].status = "waiting"
        await gates[sid].wait()
        fake_store[sid].status = "completed"

    scheduler = ResearchScheduler(run, AsyncMock(), AsyncMock())
    try:
        await scheduler.tick(list(fake_store.values()), 2)
        await asyncio.sleep(0)
        await scheduler.tick(list(fake_store.values()), 2)
        assert entered == ["0", "1"]
        assert fake_store["2"].status == "queued"
        gates["0"].set()
        await scheduler.tasks["0"]
        await scheduler.tick(
            [r for r in fake_store.values() if r.status != "completed"], 2
        )
        await asyncio.sleep(0)
        assert entered == ["0", "1", "2"]
        assert len(scheduler.tasks) == 2
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_lowering_limit_stops_excess_runtime_before_new_admission(fake_store):
    cleaned = []

    async def run(sid):
        fake_store[sid].status = "running"
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.append(sid)

    stop_jobs = AsyncMock()
    scheduler = ResearchScheduler(run, stop_jobs, AsyncMock())
    try:
        await scheduler.tick(list(fake_store.values()), 3)
        await asyncio.sleep(0)
        await scheduler.tick(list(fake_store.values()), 1)
        assert len(scheduler.tasks) == 1
        assert cleaned == ["1", "2"]
        assert fake_store["1"].status == "queued"
        stop_jobs.assert_not_awaited()
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_stop_queued_session_does_not_wait_for_capacity(fake_store):
    scheduler = ResearchScheduler(AsyncMock(), AsyncMock(), AsyncMock())
    fake_store["0"].status = "stopping"
    await scheduler.tick([fake_store["0"]], 0)
    assert fake_store["0"].status == "interrupted"
    scheduler.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_reaps_all_orphans_before_admitting_with_lower_cap(fake_store):
    for row in fake_store.values():
        row.status = "running"
    cleanup = AsyncMock()

    async def run(sid):
        assert cleanup.await_count == 5
        await asyncio.Event().wait()

    scheduler = ResearchScheduler(run, AsyncMock(), cleanup)
    try:
        await scheduler.recover(list(fake_store.values()))
        await scheduler.tick(list(fake_store.values()), 1)
        await asyncio.sleep(0)
        assert len(scheduler.tasks) == 1
        assert sum(row.status == "queued" for row in fake_store.values()) == 4
    finally:
        await scheduler.shutdown()


def test_queue_notice_counts_only_available_slots():
    snapshot = {"limit": 2, "running": 1, "positions": {"a": 1, "b": 2}}
    assert not session_queue(snapshot, "a", "queued")["busy"]
    assert session_queue(snapshot, "b", "queued")["busy"]


async def test_failed_runner_recovers_without_charging_database_downtime(fake_store, monkeypatch):
    row = fake_store['0']
    row.status = 'waiting'
    row.recovery_metadata = {'started_at': 100, 'last_active_at': 200}
    monkeypatch.setattr(module.time, 'time', lambda: 1000)
    async def failed():
        raise RuntimeError('database unavailable')
    task = asyncio.create_task(failed())
    await asyncio.gather(task, return_exceptions=True)
    gate = asyncio.Event()
    scheduler = ResearchScheduler(lambda _: gate.wait(), AsyncMock(), AsyncMock())
    scheduler.tasks['0'] = task
    try:
        await scheduler.tick([row], 1)
        assert row.status == 'preparing'
        assert row.recovery_metadata['started_at'] == 900
        assert scheduler.tasks['0'] is not task
    finally:
        gate.set()
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_global_fifo_never_skips_an_earlier_submission_from_the_same_owner(fake_store):
    fake_store["0"].user_id = fake_store["1"].user_id = "owner-a"
    fake_store["2"].user_id = "owner-b"
    entered = []

    async def run(sid):
        entered.append(sid)
        await asyncio.Event().wait()

    scheduler = ResearchScheduler(run, AsyncMock(), AsyncMock())
    try:
        await scheduler.tick(list(reversed(fake_store.values())), 2)
        await asyncio.sleep(0)
        assert entered == ["0", "1"]
        assert fake_store["2"].status == "queued"
        fake_store["2"].status = "stopping"
        await scheduler.tick(list(fake_store.values()), 2)
        assert fake_store["2"].status == "interrupted"
    finally:
        await scheduler.shutdown()


async def test_restart_preserves_order_native_state_and_remaining_budget(fake_store, monkeypatch):
    monkeypatch.setattr(module.time, 'time', lambda: 1000.0)
    first = fake_store['0']
    first.status = 'waiting'
    first.conversation_id = 'native-session'
    first.current_iteration = 2
    first.recovery_metadata = {'started_at': 100, 'last_active_at': 200, 'gpu_wait_started_at': 180, 'datasets_prepared': True, 'delivered_jobs': ['done-job']}
    fake_store['1'].status = 'paused'
    fake_store['2'].status = 'blocked'
    fake_store['3'].status = 'completed'
    # An explicit continuation joins the tail instead of jumping ahead by age.
    fake_store['4'].recovery_metadata = {'queue_submitted_at': 2000}
    first.created_at = datetime.fromtimestamp(1, timezone.utc)
    gate = asyncio.Event()
    entered = []
    async def run(sid):
        entered.append(sid)
        await gate.wait()
    scheduler = ResearchScheduler(run, AsyncMock(), AsyncMock())
    try:
        await scheduler.recover(list(reversed(fake_store.values())))
        assert first.status == 'queued'
        assert first.recovery_metadata['queue_entered_at'] == 200
        await scheduler.tick(list(fake_store.values()), 1)
        await asyncio.sleep(0)
        assert entered == ['0']
        assert first.recovery_metadata['started_at'] == 920  # 80 active seconds, no double credit
        assert first.conversation_id == 'native-session' and first.current_iteration == 2
        assert first.recovery_metadata['delivered_jobs'] == ['done-job']
        assert [fake_store[str(i)].status for i in [1,2,3]] == ['paused', 'blocked', 'completed']
    finally:
        await scheduler.shutdown()
    assert first.status == 'queued' and not scheduler.tasks


async def test_graceful_shutdown_and_second_restart_keep_fifo_identity(fake_store, monkeypatch):
    monkeypatch.setattr(module.time, 'time', lambda: 300.0)
    row = fake_store['0']
    row.recovery_metadata = {'started_at': 200, 'queue_submitted_at': 50}
    async def run(sid):
        fake_store[sid].status = 'running'
        await asyncio.Event().wait()
    scheduler = ResearchScheduler(run, AsyncMock(), AsyncMock())
    await scheduler.tick([row], 1)
    await asyncio.sleep(0)
    await scheduler.shutdown()
    assert row.status == 'queued'
    assert row.recovery_metadata['queue_entered_at'] == 300
    monkeypatch.setattr(module.time, 'time', lambda: 500.0)
    restarted = ResearchScheduler(run, AsyncMock(), AsyncMock())
    try:
        await restarted.recover([row])
        await restarted.tick([row], 1)
        assert row.recovery_metadata['started_at'] == 400
        assert row.recovery_metadata['queue_submitted_at'] == 50
    finally:
        await restarted.shutdown()


@pytest.mark.parametrize(
    "role,expected", [("guest", 403), ("pathologist", 403), ("admin", 200)]
)
def test_only_admin_can_change_research_limit(role, expected, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", tmp_path / "settings.json")
    user = SimpleNamespace(role=role, is_admin=lambda: role == "admin")
    app = FastAPI()
    app.include_router(queue_router)
    app.dependency_overrides[current_active_user] = lambda: user
    with TestClient(app) as client:
        response = client.post("/queue/config", json={"max_autoresearch_concurrent": 3})
        assert response.status_code == expected
    assert Config.get_max_autoresearch_concurrent() == (3 if role == "admin" else 2)
    assert Config.get_max_concurrent(default=7) == 7
