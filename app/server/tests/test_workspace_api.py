"""Route-level policy tests: no real GPU, filesystem scans or external requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Depends
from httpx import AsyncClient, ASGITransport

from backend.services.workspaces import WorkspaceScope
from gateway.routes import workspaces
from gateway import workspace_access


def fake_user(role="pathologist"):
    return SimpleNamespace(
        id="owner",
        role=role,
        is_admin=lambda: role == "admin",
        can_use_gpu=lambda: role != "guest",
    )


@pytest.fixture
def app(monkeypatch):
    app = FastAPI()
    app.include_router(workspaces.router)
    app.dependency_overrides[workspaces.current_active_user] = lambda: fake_user()
    db = AsyncMock()

    async def get_db():
        yield db

    app.dependency_overrides[workspaces.get_db] = get_db
    return app, db


async def test_cannot_create_workspace_with_unreadable_dataset(app):
    application, db = app
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workspaces", json={"name": "Private", "dataset_ids": ["other-user"]}
        )
    assert response.status_code == 403
    db.commit.assert_not_awaited()


async def test_non_admin_cannot_configure_server_root(app):
    application, db = app
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workspaces", json={"name": "Project", "root_paths": ["/data"]}
        )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled_skills", ["shell"]),
        ("enabled_connectors", ["unknown"]),
        ("execution_mode", "full_access"),
    ],
)
async def test_unknown_capabilities_rejected(app, field, value):
    application, _ = app
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workspaces", json={"name": "Project", field: value}
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "mode,skills,path,expected",
    [
        ("read_only", ("training",), "/tasks/training", 403),
        ("standard", (), "/tasks/training", 403),
        ("standard", ("training",), "/tasks/training", 200),
    ],
)
async def test_workspace_policy_is_enforced_on_execution(
    monkeypatch, mode, skills, path, expected
):
    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(workspace_access, "safe_session", session)
    monkeypatch.setattr(
        "backend.auth.dependencies._get_user_from_jwt",
        AsyncMock(return_value=fake_user()),
    )
    monkeypatch.setattr(
        workspace_access,
        "resolve_scope",
        AsyncMock(
            return_value=WorkspaceScope(
                workspace_id="ws", execution_mode=mode, enabled_skills=skills
            )
        ),
    )
    app = FastAPI()

    @app.post(path, dependencies=[Depends(workspace_access.enforce_workspace_request)])
    async def execute():
        return {"executed": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            path,
            json={},
            headers={"Authorization": "Bearer test", "X-Workspace-ID": "ws"},
        )
    assert response.status_code == expected


async def test_missing_connector_configuration_is_reported_without_secrets(
    app, monkeypatch
):
    application, _ = app
    monkeypatch.setattr(
        workspaces.Config,
        "get_global_settings",
        lambda: {"exa_api_key": "", "openrouter_api_key": "never-return"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/workspaces/capabilities")
    assert "never-return" not in response.text
    assert (
        next(
            item for item in response.json()["connectors"] if item["id"] == "web_search"
        )["available"]
        is False
    )
