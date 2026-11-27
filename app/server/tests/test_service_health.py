from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.common import service_health


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

    monkeypatch.setattr(service_health.httpx, "AsyncClient", lambda timeout=5.0: client_ctx)
    monkeypatch.setattr(service_health.Config, "AI_SERVICE_URL", "http://ai")
    monkeypatch.setattr(service_health.Config, "PREPROCESSING_SERVICE_URL", "http://pre")

    ready = await service_health.wait_for_services_ready(timeout=0.1, check_interval=0.01)

    assert ready is True
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_wait_for_services_ready_returns_false_after_timeout(monkeypatch):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=RuntimeError("boom"))
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(service_health.httpx, "AsyncClient", lambda timeout=5.0: client_ctx)
    monkeypatch.setattr(service_health.Config, "AI_SERVICE_URL", "http://ai")
    monkeypatch.setattr(service_health.Config, "PREPROCESSING_SERVICE_URL", "http://pre")

    ready = await service_health.wait_for_services_ready(timeout=0.02, check_interval=0.01)

    assert ready is False
