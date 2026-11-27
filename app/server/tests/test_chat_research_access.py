import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import current_active_user
from backend.auth import dependencies as auth
from backend.auth.dependencies import get_user_from_header_or_param
from gateway.routes import autoresearch, chat


async def test_guest_can_enter_chat_but_has_no_gpu_capability():
    guest = SimpleNamespace(role="guest", can_use_gpu=lambda: False)
    assert await auth.require_chat_access(guest) is guest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await auth.require_can_use_gpu(guest)


@pytest.mark.parametrize(
    "path",
    [
        "/research/configuration",
        "/research/datasets",
        "/research/sessions",
        "/research/sessions/s1",
    ],
)
def test_guest_cannot_read_research(path, monkeypatch):
    app = FastAPI()
    app.include_router(autoresearch.router)
    app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(
        role="guest"
    )
    read = AsyncMock()
    monkeypatch.setattr(autoresearch.store, "get", read)
    response = TestClient(app).get(path)
    assert response.status_code == 403
    read.assert_not_awaited()


def test_guest_pdf_read_still_validates_path():
    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[get_user_from_header_or_param] = lambda: SimpleNamespace(
        role="guest"
    )
    response = TestClient(app).get("/pdf-images/hash/page.png?token=test")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_scoped_token_rechecks_current_role_after_demotion(monkeypatch):
    owner = SimpleNamespace(id=uuid.uuid4(), role="pathologist", is_admin=lambda: False)
    token, _ = auth.create_autoresearch_access_token(
        user=owner, session_id="s", purpose="events"
    )

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(id=owner.id, role="guest", is_active=True)
            )
        )

    monkeypatch.setattr(auth, "safe_session", session)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await auth.get_autoresearch_access_token_claims(token)
    assert error.value.status_code == 403
