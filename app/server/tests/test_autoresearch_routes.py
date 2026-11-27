"""HTTP contract for the unified OpenCode research API."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.routes import autoresearch as routes


@pytest.fixture
def api(monkeypatch):
    user = SimpleNamespace(id="owner", role="pathologist", is_admin=lambda: False, can_use_gpu=lambda: True)
    row = SimpleNamespace(
        session_id="s", user_id="owner", status="running", recovery_metadata={}
    )
    monkeypatch.setattr(routes.store, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(
        routes.store,
        "summary",
        lambda row: {"session_id": row.session_id, "status": row.status},
    )
    monkeypatch.setattr(routes.store, "command", AsyncMock(return_value="command"))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: user
    return TestClient(app)


def test_message_acceptance_has_command_identity(api):
    response = api.post(
        "/research/sessions/s/messages", json={"text": "Use patient-level splits"}
    )
    assert response.status_code == 200
    assert response.json() == {"command_id": "command", "status": "queued"}
    routes.store.command.assert_awaited_once_with(
        "s", "message", "Use patient-level splits"
    )


def test_pause_and_stop_are_distinct_commands(api):
    assert api.post("/research/sessions/s/pause").status_code == 200
    assert api.post("/research/sessions/s/stop").status_code == 200
    assert [call.args[1] for call in routes.store.command.await_args_list] == [
        "pause",
        "stop",
    ]


def test_unknown_old_request_fields_are_rejected(api):
    response = api.post(
        "/research/sessions", json={"question": "Research", "max_iter": 3}
    )
    assert response.status_code == 422


def test_other_owner_cannot_send_instructions(api, monkeypatch):
    monkeypatch.setattr(
        routes.store,
        "get",
        AsyncMock(return_value=SimpleNamespace(user_id="different")),
    )
    assert api.post("/research/sessions/s/messages", json={"text": "Continue"}).status_code == 403


@pytest.mark.parametrize("effort,advanced,attempts,seconds", [("low", {}, 3, 3600), ("medium", {}, 8, 14400), ("high", {}, 20, 43200), ("medium", {"max_experiments": 4, "time_budget_seconds": 7200, "skills": [{"name": "CRC", "content": "# Use patient splits"}]}, 4, 7200)])
async def test_effort_resolves_server_owned_execution_budget(monkeypatch, tmp_path, effort, advanced, attempts, seconds):
    db = SimpleNamespace(bind=None, scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])), add=Mock(), commit=AsyncMock())

    @asynccontextmanager
    async def database():
        yield db

    monkeypatch.setattr(routes, "safe_session", database)
    scope = SimpleNamespace(execution_mode="default", enabled_skills=["training"], enabled_connectors=['web_search','articles'], datasets=lambda user: None)
    monkeypatch.setattr("backend.services.workspaces.resolve_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(routes, "resolve_model_config", AsyncMock(return_value=SimpleNamespace(public=lambda: {})))
    monkeypatch.setattr(routes, "workspace", lambda sid: tmp_path / sid)
    monkeypatch.setattr(routes.store, "update", AsyncMock())
    monkeypatch.setattr(routes.store, "get", AsyncMock(return_value=SimpleNamespace(status="queued")))
    monkeypatch.setattr(routes.store, "summary", lambda row: {})
    monkeypatch.setattr(routes, "queue_snapshot", AsyncMock(return_value={"positions": {}, "limit": 2, "running": 0}))
    await routes.create_session(routes.StartResearch(question="CRC-MSI", effort=effort, advanced=advanced), SimpleNamespace(id="owner", role="pathologist", can_use_gpu=lambda: True), None)
    row = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], routes.AutoResearchSession))
    assert row.max_iterations == attempts
    assert row.recovery_metadata["time_budget_seconds"] == seconds
    assert row.recovery_metadata["effort"] == effort
    assert row.recovery_metadata['enabled_connectors'] == ['articles', 'web_search']
    assert row.recovery_metadata['title'] == 'Autonomous research'
    assert row.recovery_metadata['title_pending'] is True
    assert row.research_question == 'CRC-MSI'
    if advanced:
        assert row.recovery_metadata['custom_skills'][0]['id'] == 'user-skill-1'
        assert 'patient splits' in row.recovery_metadata['custom_skills'][0]['content']


def test_start_rejects_raw_budget_overrides(api):
    assert routes.StartResearch(question="CRC-MSI").effort == "medium"
    for payload in [{"max_experiments": 50}, {"time_budget_seconds": 600}, {"effort": "extreme"}]:
        assert api.post("/research/sessions", json={"question": "CRC-MSI", **payload}).status_code == 422
