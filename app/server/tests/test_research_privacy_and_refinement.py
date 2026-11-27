"""Exercise real ownership queries and continuation transactions in an isolated DB."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Integer, MetaData, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.auth import dependencies as auth
from backend.auth.models import User
from backend.autoresearch.engine import scheduler, store, worker
from backend.autoresearch.engine import file_catalog
from backend.database.models import (
    AutoResearchEvent, AutoResearchExperiment, AutoResearchSession, ResearchJob, WorkbenchFile,
)
from gateway.routes import autoresearch as routes
from gateway.prompts.scoped import workflow_prompt


@pytest.fixture
async def research_api(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [User, AutoResearchSession, AutoResearchExperiment, AutoResearchEvent, ResearchJob, WorkbenchFile]:
        table = model.__table__.to_metadata(metadata)
        if model is AutoResearchEvent:
            # SQLite only auto-increments INTEGER PRIMARY KEY, not BIGINT.
            table.c.id.type = Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def safe_session():
        async with sessions() as db:
            yield db

    for module in [routes, store, scheduler, auth, file_catalog]:
        monkeypatch.setattr(module, "safe_session", safe_session)
    monkeypatch.setattr(routes.Config, "get_autoresearch_dir", lambda: tmp_path)
    monkeypatch.setattr(scheduler.Config, "get_max_autoresearch_concurrent", lambda: 2)
    users = {
        name: User(id=uuid.uuid4(), username=name, role=role, hashed_password="test", is_active=True)
        for name, role in [("alice", "pathologist"), ("bob", "pathologist"), ("admin", "admin"), ("guest", "guest")]
    }
    async with sessions() as db:
        db.add_all(users.values())
        for owner in ["alice", "bob"]:
            root = tmp_path / owner
            (root / "runs" / f"{owner}-run").mkdir(parents=True)
            (root / "report.md").write_text(f"{owner} private findings")
            (root / "runs" / f"{owner}-run" / "metrics.json").write_text('{"auc":0.81}')
            db.add(AutoResearchSession(
                session_id=owner, user_id=str(users[owner].id),
                conversation_id=f"native-{owner}", research_question=f"{owner} private question",
                status="completed", phase="completed",
                workspace_path=str(root), current_iteration=1, max_iterations=1,
                final_report=f"{owner} private findings",
                event_sequence=1, recovery_metadata={"title": f"{owner} research", "outcome": "completed", "finish_requested": True, "research_phase": "writing"},
            ))
            db.add(AutoResearchExperiment(
                session_id=owner, training_task_id=f"{owner}-run", experiment_name=f"{owner} baseline",
                status="completed", iteration=1, metrics={"val.auc": 0.81}, hyperparams={"seed": 42},
            ))
            db.add(AutoResearchEvent(session_id=owner, sequence=1, event_type="message", event_data={
                "kind": "message", "seq": 1, "message": {"type": "assistant", "text": f"{owner} private conversation"},
            }))
        await db.commit()
    actor = SimpleNamespace(user=users["alice"])
    app = FastAPI()
    app.include_router(routes.router)
    from gateway.routes import workbench
    app.include_router(workbench.router)
    app.dependency_overrides[routes.current_active_user] = lambda: actor.user
    app.dependency_overrides[auth.require_chat_access] = lambda: actor.user
    async def get_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[workbench.get_db] = get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, actor=actor, users=users, db=sessions, root=tmp_path)
    await engine.dispose()


async def test_list_and_detail_are_owner_scoped_admin_sees_all(research_api):
    api = research_api
    result = await api.client.get("/research/sessions")
    assert [row["session_id"] for row in result.json()["items"]] == ["alice"]
    assert "bob private" not in result.text
    own = await api.client.get("/research/sessions/alice")
    assert "alice private conversation" in own.text
    api.actor.user = api.users["admin"]
    result = await api.client.get("/research/sessions")
    assert {row["session_id"] for row in result.json()["items"]} == {"alice", "bob"}
    assert (await api.client.get("/research/sessions/bob")).status_code == 200
    assert (await api.client.get("/research/sessions/bob/files", params={"path": "report.md"})).status_code == 200


async def test_logical_activity_survives_snapshot_flood_and_command_delivery(research_api):
    api = research_api
    command = await store.command('alice', 'message', 'Compare the closest method')
    first = (await store.events('alice'))[-1]['seq']
    for i in range(8):
        await store.update('alice', event={'kind': 'message', 'message': {
            'id': f'tool-{i}', 'type': 'assistant', 'content': [
                {'type': 'tool', 'id': f't-{i}', 'name': 'read', 'state': {'status': 'running'}}]}})
    for i in range(130):
        await store.update('alice', event={'kind': 'message', 'message': {
            'id': 'tool-7', 'type': 'assistant', 'content': [
                {'type': 'tool', 'id': 't-7', 'name': 'read', 'state': {'status': 'completed', 'output': str(i)}}]}})
    await store.update('alice', event={'kind': 'message', 'message': {'id': 'secret', 'type': 'user', 'text': 'Internal supervisor'}})
    await store.update('alice', event={'kind': 'message', 'message': {'id': 'hidden', 'type': 'assistant', 'metadata': {'pathlabInternal': True}, 'text': 'Hidden internal'}})
    await store.update('alice', event={'kind': 'command', 'command_id': command, 'status': 'delivered'})
    items, before = [], 0
    while True:
        page = await store.activity('alice', before=before, limit=3)
        items = page['items'] + items
        if page['next_before'] is None:
            break
        before = page['next_before']
    assert len(items) == 10  # original prose, instruction, eight logical tool messages
    assert items[0]['message']['text'] == 'alice private conversation'
    assert items[1]['text'] == 'Compare the closest method'
    assert items[1]['status'] == 'delivered' and items[1]['activity_seq'] == first
    assert items[-1]['message']['content'][0]['state']['output'] == '129'
    assert len({item['activity_seq'] for item in items}) == len(items)
    response = await api.client.get('/workbench/research/alice/activity')
    assert response.status_code == 200, response.text
    assert 'Internal supervisor' not in response.text and 'Hidden internal' not in response.text
    from backend.autoresearch.engine.activity import project_event
    public_items = [project_event(item, 'en-US') for item in items]
    assert response.json()['items'] == public_items
    assert '"output"' not in response.text and '"input"' not in response.text
    assert (await api.client.get('/workbench/research/bob/activity')).status_code == 403
    detail = (await api.client.get('/research/sessions/alice?compact=true')).json()
    assert detail['activity'] == public_items and detail['activity_before'] is None
    for i in range(105):
        await store.update('alice', event={'kind': 'message', 'message': {
            'id': f'new-tool-{i}', 'type': 'assistant', 'content': [{'type': 'tool', 'name': 'read'}]}})
    detail = (await api.client.get('/research/sessions/alice?compact=true')).json()
    assert any(e.get('text') == 'Compare the closest method' for e in detail['activity'])
    assert any(e.get('message', {}).get('text') == 'alice private conversation' for e in detail['activity'])
    assert detail['activity_before'] > first


@pytest.mark.parametrize("role", ["alice", "guest"])
@pytest.mark.parametrize("method,path,body", [
    ("GET", "", None),
    ("GET", "/files?path=report.md", None),
    ("GET", "/source-files", None),
    ("POST", "/access-token", {"purpose": "events"}),
    ("POST", "/messages", {"text": "continue"}),
    ("POST", "/continue", {"text": "optimize", "baseline_run_id": "bob-run"}),
    ("POST", "/answers", {"form_id": "f", "answer": {}}),
    ("POST", "/resume", {}),
    ("POST", "/pause", {}),
    ("POST", "/stop", {}),
    ("PUT", "/source-files", {"path": "analysis.py", "content": "", "revision": "rev"}),
    ("DELETE", "", None),
])
async def test_private_session_endpoints_reject_other_users(research_api, role, method, path, body):
    api = research_api
    api.actor.user = api.users[role]
    response = await api.client.request(method, f"/research/sessions/bob{path}", json=body)
    assert response.status_code == 403
    assert "bob private" not in response.text


async def test_guest_cannot_submit_even_with_valid_payload(research_api):
    api = research_api
    api.actor.user = api.users["guest"]
    assert (await api.client.post("/research/sessions", json={"question": "CRC-MSI"})).status_code == 403


@pytest.mark.parametrize("purpose,path,run_id", [
    ("events", "/events", ""),
    ("session_download", "/download", ""),
    ("run_download", "/runs/bob-run/download", "bob-run"),
])
async def test_token_routes_recheck_owner_not_just_token_scope(research_api, purpose, path, run_id):
    api = research_api
    token, _ = auth.create_autoresearch_access_token(user=api.users["alice"], session_id="bob", purpose=purpose, run_id=run_id)
    response = await api.client.get(f"/research/sessions/bob{path}", params={"token": token})
    assert response.status_code == 403
    assert "bob private" not in response.text


async def test_owner_and_admin_can_download_but_guest_token_is_revoked(research_api):
    api = research_api
    for name, session_id in [("alice", "alice"), ("admin", "bob")]:
        token, _ = auth.create_autoresearch_access_token(user=api.users[name], session_id=session_id, purpose="session_download")
        response = await api.client.get(f"/research/sessions/{session_id}/download", params={"token": token})
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
    token, _ = auth.create_autoresearch_access_token(user=api.users["guest"], session_id="alice", purpose="session_download")
    assert (await api.client.get("/research/sessions/alice/download", params={"token": token})).status_code == 403


@pytest.mark.parametrize("lang,name", [("en", "AutoResearch"), ("zh_CN", "自主探索"), ("zh_HK", "自主探索")])
def test_chat_handoff_contract_uses_localized_product_name(lang, name):
    prompt = workflow_prompt(lang, ())
    assert name in prompt
    assert '"buttonText":"Open AutoResearch' not in prompt


async def test_completed_research_continues_from_selected_run_and_preserves_results(research_api):
    api = research_api
    response = await api.client.post("/research/sessions/alice/continue", json={
        "text": "Compare another aggregator without changing patient splits",
        "baseline_run_id": "alice-run", "additional_experiments": 2,
    })
    assert response.status_code == 200, response.text
    row = await store.get("alice")
    assert (row.status, row.phase, row.max_iterations, row.current_iteration) == ("queued", "planning", 3, 1)
    assert row.conversation_id == "native-alice"
    assert row.final_report == "alice private findings"
    meta = row.recovery_metadata
    assert meta["report_history"][0]["report"] == "alice private findings"
    assert not meta["finish_requested"]
    command = meta["commands"][0]
    assert command["continuation"]["previous_report"] == "alice private findings"
    assert command["continuation"]["baseline"]["metrics"] == {"val.auc": 0.81}
    assert command["continuation"]["baseline"]["config"] == {"seed": 42}
    assert len(await store.experiments("alice")) == 1
    events = await store.events("alice")
    assert events[-1]["baseline"]["run_id"] == "alice-run"
    assert (api.root / "alice/runs/alice-run/metrics.json").read_text() == '{"auc":0.81}'
    assert (await api.client.post("/research/sessions/alice/continue", json={"text": "duplicate"})).status_code == 409


@pytest.mark.parametrize("payload", [
    {"text": "   "},
    {"text": "optimize", "baseline_run_id": "bob-run"},
    {"text": "optimize", "baseline_run_id": "missing"},
])
async def test_invalid_refinement_does_not_mutate_original(research_api, payload):
    response = await research_api.client.post("/research/sessions/alice/continue", json=payload)
    assert response.status_code == 409
    row = await store.get("alice")
    assert row.status == "completed"
    assert "report_history" not in row.recovery_metadata


async def test_existing_stream_closes_when_owner_is_demoted(research_api):
    api = research_api
    token, _ = auth.create_autoresearch_access_token(user=api.users["alice"], session_id="alice", purpose="events")
    claims = await auth.get_autoresearch_access_token_claims(token)
    request = SimpleNamespace(headers={}, query_params={"token": token}, is_disconnected=AsyncMock(return_value=False))
    response = await routes.events("alice", request, claims=claims)
    async with api.db() as db:
        user = await db.get(User, api.users["alice"].id)
        user.role = "guest"
        await db.commit()
    assert [event async for event in response.body_iterator] == []


async def test_refinement_reaches_original_native_conversation(research_api, monkeypatch):
    api = research_api
    await api.client.post("/research/sessions/alice/continue", json={
        "text": "Improve validation AUROC", "baseline_run_id": "alice-run", "additional_experiments": 2,
    })

    async def finish_after_prompt(*args, **kwargs):
        await store.update("alice", meta={"finish_requested": True}, final_report="Updated findings")

    client = SimpleNamespace(
        ensure_research_tools=AsyncMock(return_value=False),
        prompt=AsyncMock(side_effect=finish_after_prompt),
        messages=AsyncMock(return_value=[]), active=AsyncMock(return_value=False),
        work_state=AsyncMock(return_value={'root_active': False, 'children': [], 'shells': [], 'inbox': 0}),
        interrupted_children=AsyncMock(return_value=[]),
        forms=AsyncMock(return_value=[]), create=AsyncMock(),
    )
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), start=AsyncMock(return_value=client), stop=AsyncMock())
    monkeypatch.setattr(worker, "AgentRuntime", lambda sid: runtime)
    monkeypatch.setattr(worker, "resolve_model_config", AsyncMock(return_value=SimpleNamespace(public=lambda: {}, model="test")))
    monkeypatch.setattr("backend.autoresearch.engine.datasets.validate_access", AsyncMock())
    monkeypatch.setattr(worker, "watch_events", AsyncMock())
    await worker.run_session("alice")
    client.create.assert_not_awaited()
    prompt = client.prompt.call_args.args
    assert prompt[0] == "native-alice"
    assert "alice-run" in prompt[1]
    assert "alice private findings" in prompt[1]
    assert "Improve validation AUROC" in prompt[1]
    assert "Remaining experiment attempts: 2" in prompt[1]
    assert client.prompt.call_args.kwargs['delivery'] == 'steer'
    row = await store.get("alice")
    assert row.status == "completed"
    assert row.final_report == "Updated findings"
    assert row.recovery_metadata["report_history"][0]["report"] == "alice private findings"
    runtime.stop.assert_awaited_once()


async def test_restart_recovers_original_native_session_to_completion_in_global_fifo(research_api, monkeypatch):
    import asyncio
    from datetime import datetime
    api = research_api
    async with api.db() as db:
        alice = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'alice'))
        bob = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == 'bob'))
        alice.status, alice.created_at = 'running', datetime(2026, 1, 1)
        alice.event_sequence = bob.event_sequence = 1
        alice.recovery_metadata = {'started_at': 100, 'last_active_at': 200, 'time_budget_seconds': 300,
                                   'datasets_prepared': True, 'research_phase': 'writing'}
        bob.status, bob.created_at = 'queued', datetime(2026, 1, 2)
        bob.recovery_metadata = {}
        await db.commit()
    monkeypatch.setattr(scheduler.time, 'time', lambda: 1000.0)
    async def finish(*args, **kwargs):
        await store.update('alice', meta={'finish_requested': True}, final_report='Recovered report')
    client = SimpleNamespace(ensure_research_tools=AsyncMock(return_value=False), prompt=AsyncMock(side_effect=finish), messages=AsyncMock(return_value=[]),
                             active=AsyncMock(return_value=False), forms=AsyncMock(return_value=[]), create=AsyncMock(),
                             work_state=AsyncMock(return_value={'root_active': False, 'children': [], 'shells': [], 'inbox': 0}),
                             interrupted_children=AsyncMock(return_value=[]))
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), start=AsyncMock(return_value=client), stop=AsyncMock())
    monkeypatch.setattr(worker, 'AgentRuntime', lambda sid: runtime)
    monkeypatch.setattr(worker, 'resolve_model_config', AsyncMock(return_value=SimpleNamespace(public=lambda: {}, model='test')))
    monkeypatch.setattr('backend.autoresearch.engine.datasets.validate_access', AsyncMock())
    monkeypatch.setattr(worker, 'watch_events', AsyncMock())
    supervisor = scheduler.ResearchScheduler(worker.run_session, AsyncMock(), AsyncMock())
    rows = [await store.get('bob'), await store.get('alice')]
    try:
        await supervisor.recover(rows)
        assert (await scheduler.queue_snapshot())['positions'] == {'alice': 1, 'bob': 2}
        await supervisor.tick(rows, 1)
        await asyncio.wait_for(supervisor.tasks['alice'], 10)
        client.create.assert_not_awaited()
        assert client.prompt.call_args.args[0] == 'native-alice'
        assert 'alice private question' in client.prompt.call_args.args[1]
        restored = await store.get('alice')
        assert restored.status == 'completed' and restored.final_report == 'Recovered report'
        assert restored.current_iteration == 1
        assert restored.recovery_metadata['started_at'] == 900
        assert (await store.get('bob')).status == 'queued'
    finally:
        await supervisor.shutdown()


async def test_live_child_wait_does_not_idle_out_and_user_steers_during_pending_mount(research_api, monkeypatch):
    import asyncio
    await store.update('alice', status='running', max_iterations=4, meta={
        'finish_requested': False, 'datasets_prepared': True,
        'pending_references': [{'type': 'file', 'id': 'pending'}],
    })
    # Start with a normal mount snapshot, then receive references while native work is live.
    session = await store.get('alice')
    pending = session.recovery_metadata['pending_references']
    await store.update('alice', meta={'pending_references': []})
    await store.command('alice', 'message', 'Switch the next training objective')
    idle = {'root_active': False, 'children': [], 'shells': [], 'inbox': 0}
    calls = 0
    async def state(*args):
        nonlocal calls
        calls += 1
        if calls < 9:
            return {**idle, 'children': [{'id': 'child', 'title': 'Audit loss'}]}
        await store.update('alice', meta={'finish_requested': True, 'pending_references': []})
        return idle
    async def start(*args, **kwargs):
        await store.update('alice', meta={'pending_references': pending})
        return client
    client = SimpleNamespace(ensure_research_tools=AsyncMock(return_value=False), prompt=AsyncMock(), messages=AsyncMock(return_value=[]),
        active=AsyncMock(return_value=True), work_state=AsyncMock(side_effect=state),
        forms=AsyncMock(return_value=[]), create=AsyncMock(), interrupted_children=AsyncMock(return_value=[]))
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), start=AsyncMock(side_effect=start), stop=AsyncMock())
    monkeypatch.setattr(worker, 'AgentRuntime', lambda sid: runtime)
    monkeypatch.setattr(worker, 'resolve_model_config', AsyncMock(return_value=SimpleNamespace(public=dict, model='test')))
    monkeypatch.setattr('backend.autoresearch.engine.datasets.validate_access', AsyncMock())
    async def events(client, sid, changed):
        while True:
            changed.set()
            await asyncio.sleep(.02)
    monkeypatch.setattr(worker, 'watch_events', events)
    await asyncio.wait_for(worker.run_session('alice'), 12)
    assert calls == 9
    client.prompt.assert_awaited_once()
    assert client.prompt.call_args.kwargs['delivery'] == 'steer'
    assert 'mounts are pending' in client.prompt.call_args.args[1]
    assert (await store.get('alice')).status == 'completed'


async def test_completed_job_wakes_scientific_agent_with_strategy_not_artifact_dump(research_api, monkeypatch):
    import asyncio
    import itertools
    import time

    await store.update('alice', status='running', meta={
        'finish_requested': False, 'datasets_prepared': True,
        'task_kind': 'experiment', 'research_standard': 'scientific',
    })
    notifications = []
    async def prompt(cid, text, *args, **kwargs):
        if text.startswith('Background jobs finished.'):
            notifications.append(text)
            await store.update('alice', meta={'finish_requested': True})
    client = SimpleNamespace(
        ensure_research_tools=AsyncMock(return_value=False), prompt=AsyncMock(side_effect=prompt),
        messages=AsyncMock(return_value=[]), forms=AsyncMock(return_value=[]),
        active=AsyncMock(return_value=False), interrupted_children=AsyncMock(return_value=[]),
        work_state=AsyncMock(return_value={'root_active': False, 'children': [], 'shells': [], 'inbox': 0}),
    )
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), start=AsyncMock(return_value=client), stop=AsyncMock())
    monkeypatch.setattr(worker, 'AgentRuntime', lambda sid: runtime)
    monkeypatch.setattr(worker, 'resolve_model_config', AsyncMock(return_value=SimpleNamespace(public=dict, model='test')))
    monkeypatch.setattr('backend.autoresearch.engine.datasets.validate_access', AsyncMock())
    monkeypatch.setattr(store, 'jobs', AsyncMock(return_value=[{
        'job_id': 'done', 'kind': 'experiment', 'status': 'completed', 'payload': {'name': 'Comparison'},
        'result': {'metrics': {'delta': -.1}, 'artifact_directory': 'runs/done/output',
                   'artifacts': [{'path': 'do-not-repeat-full-artifact-list'}] * 100},
    }]))
    ticks = itertools.count(step=10)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=time.time, monotonic=lambda: next(ticks)))
    async def events(client, sid, changed):
        while True:
            changed.set()
            await asyncio.sleep(.01)
    monkeypatch.setattr(worker, 'watch_events', events)
    await asyncio.wait_for(worker.run_session('alice'), 10)
    assert len(notifications) == 1
    assert 'Research strategy checkpoint' in notifications[0]
    assert 'runs/done/output' in notifications[0] and '"delta": -0.1' in notifications[0]
    assert 'do-not-repeat-full-artifact-list' not in notifications[0]
    assert (await store.get('alice')).recovery_metadata['delivered_jobs'] == ['done']


@pytest.mark.parametrize('failure', ['native_turn', 'writer', 'persistent_native'])
async def test_worker_returns_repairable_failures_to_agent_before_escalation(research_api, monkeypatch, failure):
    import asyncio
    import itertools
    import time

    await store.update('alice', status='running', meta={
        'finish_requested': False, 'datasets_prepared': True,
    })
    repaired = False
    async def prompt(cid, text, *args, **kwargs):
        nonlocal repaired
        if 'previous native turn failed' in text or 'Article writing was interrupted' in text:
            repaired = True
            if failure != 'persistent_native':
                await store.update('alice', meta={'finish_requested': True, 'report_generation_id': None})
        elif failure == 'writer':
            await store.update('alice', meta={'report_generation_id': 'writer'})

    client = SimpleNamespace(
        ensure_research_tools=AsyncMock(return_value=False),
        prompt=AsyncMock(side_effect=prompt),
        messages=AsyncMock(return_value=[{'id': 'failed-turn', 'type': 'idle', 'outcome': 'failed', 'error': {'message': 'temporary failure'}}] if failure != 'writer' else []),
        active=AsyncMock(return_value=False),
        work_state=AsyncMock(return_value={'root_active': False, 'children': [], 'shells': [], 'inbox': 0}),
        interrupted_children=AsyncMock(return_value=[]), forms=AsyncMock(return_value=[]), interrupt=AsyncMock(),
    )
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), start=AsyncMock(return_value=client), stop=AsyncMock())
    monkeypatch.setattr(worker, 'AgentRuntime', lambda sid: runtime)
    monkeypatch.setattr(worker, 'resolve_model_config', AsyncMock(return_value=SimpleNamespace(public=dict, model='test')))
    monkeypatch.setattr('backend.autoresearch.engine.datasets.validate_access', AsyncMock())
    monkeypatch.setattr('backend.services.manuscript_writer.read_job', AsyncMock(return_value=(None, SimpleNamespace(status='failed', error_code='generation_failed'))))
    ticks = itertools.count(step=10)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=time.time, monotonic=lambda: next(ticks)))
    async def events(client, sid, changed):
        while True:
            changed.set()
            await asyncio.sleep(.01)
    monkeypatch.setattr(worker, 'watch_events', events)
    await asyncio.wait_for(worker.run_session('alice'), 10)
    assert repaired
    row = await store.get('alice')
    assert row.status == ('blocked' if failure == 'persistent_native' else 'completed')
    if failure == 'persistent_native':
        assert client.prompt.await_count == 7  # initial recovery plus six bounded continuations
    runtime.stop.assert_awaited_once()
