import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from tests.conftest import make_settings_app, _make_user


@pytest.fixture(autouse=True)
def reset_config_cache(monkeypatch):
    monkeypatch.delenv("TURNSTILE_ENABLED", raising=False)
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    from backend.common.config import Config

    Config._global_settings_cache = None
    Config._global_settings_dirty = True
    yield
    Config._global_settings_cache = None
    Config._global_settings_dirty = True


@pytest.fixture
def admin():
    return _make_user("admin")


@pytest.fixture
def non_admin():
    return _make_user("guest")


@pytest_asyncio.fixture
async def admin_client(admin, tmp_path):
    with patch(
        "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
    ):
        app = make_settings_app(admin)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


@pytest_asyncio.fixture
async def guest_client(non_admin, tmp_path):
    with patch(
        "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
    ):
        app = make_settings_app(non_admin)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


@pytest.mark.asyncio
class TestPublicSettings:
    async def test_public_endpoint_returns_200(self, admin_client):
        resp = await admin_client.get("/settings/public")
        assert resp.status_code == 200

    async def test_public_endpoint_returns_turnstile_fields(self, admin_client):
        resp = await admin_client.get("/settings/public")
        data = resp.json()
        assert "turnstile_enabled" in data
        assert "turnstile_site_key" in data

    async def test_public_settings_default_turnstile_disabled(self, admin_client):
        resp = await admin_client.get("/settings/public")
        assert resp.json()["turnstile_enabled"] is False

    async def test_public_settings_reflect_updated_turnstile(self, tmp_path):
        with patch(
            "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
        ):
            from backend.common.config import Config

            Config._global_settings_dirty = True
            Config.update_global_settings(
                {"turnstile_enabled": True, "turnstile_site_key": "my-site-key"}
            )
            app = make_settings_app(_make_user("admin"))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                resp = await c.get("/settings/public")
            data = resp.json()
        assert data["turnstile_enabled"] is True
        assert data["turnstile_site_key"] == "my-site-key"


@pytest.mark.asyncio
class TestGetGlobalSettings:
    async def test_returns_all_setting_fields(self, admin_client):
        resp = await admin_client.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "openrouter_api_key",
            "openrouter_base_url",
            "openrouter_model",
            "huggingface_token",
            "dashscope_api_key",
            "exa_api_key",
            "local_vllm_enabled",
            "local_vllm_base_url",
            "local_vllm_model",
            "local_vllm_api_key",
            "local_asr_enabled",
            "local_asr_base_url",
            "local_asr_model",
            "local_asr_api_key",
            "turnstile_enabled",
            "turnstile_site_key",
            "turnstile_secret_key",
            "resend_enabled",
            "resend_api_key",
            "resend_from_email",
            "site_url",
        }
        assert expected_keys.issubset(data.keys())

    async def test_default_openrouter_model(self, admin_client):
        resp = await admin_client.get("/settings")
        assert resp.json()["openrouter_model"] == "qwen/qwen3.5-plus-02-15"

    async def test_default_vllm_base_url(self, admin_client):
        resp = await admin_client.get("/settings")
        assert resp.json()["local_vllm_base_url"] == "http://127.0.0.1:8000/v1"

    async def test_default_asr_base_url(self, admin_client):
        resp = await admin_client.get("/settings")
        assert "ws://" in resp.json()["local_asr_base_url"]


@pytest.mark.asyncio
class TestUpdateGlobalSettings:
    async def test_update_openrouter_key(self, admin_client):
        resp = await admin_client.post(
            "/settings", json={"openrouter_api_key": "sk-or-test"}
        )
        assert resp.status_code == 200
        assert resp.json()["openrouter_api_key"] == "sk-or-test"

    async def test_update_model_name(self, admin_client):
        resp = await admin_client.post(
            "/settings", json={"openrouter_model": "anthropic/claude-3.5-sonnet"}
        )
        assert resp.json()["openrouter_model"] == "anthropic/claude-3.5-sonnet"

    async def test_update_multiple_fields_at_once(self, admin_client):
        resp = await admin_client.post(
            "/settings",
            json={
                "openrouter_api_key": "key-abc",
                "huggingface_token": "hf-xyz",
                "dashscope_api_key": "ds-123",
            },
        )
        data = resp.json()
        assert data["openrouter_api_key"] == "key-abc"
        assert data["huggingface_token"] == "hf-xyz"
        assert data["dashscope_api_key"] == "ds-123"

    async def test_update_vllm_enable(self, admin_client):
        resp = await admin_client.post(
            "/settings",
            json={"local_vllm_enabled": True, "local_vllm_model": "llama-3"},
        )
        data = resp.json()
        assert data["local_vllm_enabled"] is True
        assert data["local_vllm_model"] == "llama-3"

    async def test_update_asr_enable(self, admin_client):
        resp = await admin_client.post(
            "/settings",
            json={"local_asr_enabled": True, "local_asr_model": "whisper"},
        )
        data = resp.json()
        assert data["local_asr_enabled"] is True
        assert data["local_asr_model"] == "whisper"

    async def test_empty_update_body_returns_400(self, admin_client):
        resp = await admin_client.post("/settings", json={})
        assert resp.status_code == 400

    async def test_update_persists_across_requests(self, tmp_path):
        with patch(
            "backend.common.config.Config.STORAGE_CONFIG_FILE", str(tmp_path / "s.json")
        ):
            from backend.common.config import Config

            Config._global_settings_dirty = True
            app = make_settings_app(_make_user("admin"))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                await c.post("/settings", json={"exa_api_key": "exa-persist"})
                resp = await c.get("/settings")
        assert resp.json()["exa_api_key"] == "exa-persist"


@pytest.mark.asyncio
class TestCheckVllm:
    async def test_vllm_online(self, admin_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "llama-3"}]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_aclient = MagicMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_client)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "gateway.routes.settings.httpx.AsyncClient", return_value=mock_aclient
        ):
            resp = await admin_client.post(
                "/settings/check-vllm",
                json={"base_url": "http://localhost:8000/v1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["online"] is True
        assert data["model"] == "llama-3"

    async def test_vllm_offline_connection_refused(self, admin_client):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_aclient = MagicMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_client)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "gateway.routes.settings.httpx.AsyncClient", return_value=mock_aclient
        ):
            resp = await admin_client.post(
                "/settings/check-vllm",
                json={"base_url": "http://no-such-host:8000/v1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["online"] is False
        assert data["error"] == "Connection refused"

    async def test_vllm_offline_timeout(self, admin_client):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_aclient = MagicMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_client)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "gateway.routes.settings.httpx.AsyncClient", return_value=mock_aclient
        ):
            resp = await admin_client.post(
                "/settings/check-vllm",
                json={"base_url": "http://slow-host:8000/v1", "api_key": "key"},
            )
        assert resp.json()["online"] is False
        assert "timeout" in resp.json()["error"].lower()

    async def test_vllm_no_models_listed(self, admin_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_aclient = MagicMock()
        mock_aclient.__aenter__ = AsyncMock(return_value=mock_client)
        mock_aclient.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "gateway.routes.settings.httpx.AsyncClient", return_value=mock_aclient
        ):
            resp = await admin_client.post(
                "/settings/check-vllm",
                json={"base_url": "http://localhost:8000/v1"},
            )
        data = resp.json()
        assert data["online"] is True
        assert data["model"] is None
