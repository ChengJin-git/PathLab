from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import startup


@pytest.mark.asyncio
async def test_wait_for_services_ready_returns_true_when_all_health_checks_pass(
    monkeypatch,
):
    response = MagicMock(status_code=200)
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(startup.httpx, "AsyncClient", lambda timeout=5.0: client_ctx)
    monkeypatch.setattr(startup, "AI_SERVICE_URL", "http://ai")
    monkeypatch.setattr(startup, "PREPROCESSING_SERVICE_URL", "http://pre")

    ready = await startup.wait_for_services_ready(timeout=0.1, check_interval=0.01)

    assert ready is True
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_wait_for_services_ready_returns_false_after_timeout(monkeypatch):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=RuntimeError("boom"))
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(startup.httpx, "AsyncClient", lambda timeout=5.0: client_ctx)
    monkeypatch.setattr(startup, "AI_SERVICE_URL", "http://ai")
    monkeypatch.setattr(startup, "PREPROCESSING_SERVICE_URL", "http://pre")

    ready = await startup.wait_for_services_ready(timeout=0.02, check_interval=0.01)

    assert ready is False
