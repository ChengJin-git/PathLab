import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from gateway.routes import auth as auth_routes


class _FakeRequest:
    def __init__(self, client_host="8.8.8.8"):
        self.client = MagicMock()
        self.client.host = client_host


@pytest.mark.asyncio
async def test_verify_turnstile_success():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: {"success": True}
        result = await auth_routes.verify_turnstile("token", "secret")
        assert result is True


@pytest.mark.asyncio
async def test_verify_turnstile_failure():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: {"success": False, "error-codes": ["timeout-or-duplicate"]}
        result = await auth_routes.verify_turnstile("token", "secret")
        assert result is False


@pytest.mark.asyncio
async def test_verify_tencent_captcha_success():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: {"Response": {"CaptchaCode": 1}}
        result = await auth_routes.verify_tencent_captcha("ticket", "randstr", "1.1.1.1", "189949311", "secret")
        assert result is True


@pytest.mark.asyncio
async def test_verify_tencent_captcha_failure():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json = lambda: {"Response": {"Error": {"Code": "AuthFailure"}}}
        result = await auth_routes.verify_tencent_captcha("ticket", "randstr", "1.1.1.1", "appid", "secret")
        assert result is False


@pytest.mark.asyncio
async def test_verify_captcha_turnstile_for_non_china_ip():
    with patch.object(auth_routes.Config, "get_global_settings", return_value={"turnstile_enabled": True, "turnstile_secret_key": "secret"}):
        with patch.object(auth_routes, "is_mainland_china_ip", new_callable=AsyncMock, return_value=False):
            with patch.object(auth_routes, "verify_turnstile", new_callable=AsyncMock, return_value=True):
                req = _FakeRequest("8.8.8.8")
                valid, error = await auth_routes.verify_captcha(req, "token", None, None)
                assert valid is True
                assert error is None


@pytest.mark.asyncio
async def test_verify_captcha_tencent_for_china_ip():
    with patch.object(auth_routes.Config, "get_global_settings", return_value={
        "tencent_captcha_enabled": True,
        "tencent_captcha_secret_key": "secret",
        "tencent_captcha_app_id": "appid",
        "turnstile_enabled": True,
    }):
        with patch.object(auth_routes, "is_mainland_china_ip", new_callable=AsyncMock, return_value=True):
            with patch.object(auth_routes, "verify_tencent_captcha", new_callable=AsyncMock, return_value=True):
                req = _FakeRequest("1.1.1.1")
                valid, error = await auth_routes.verify_captcha(req, None, "ticket", "randstr")
                assert valid is True
                assert error is None


@pytest.mark.asyncio
async def test_verify_captcha_missing_token():
    with patch.object(auth_routes.Config, "get_global_settings", return_value={"turnstile_enabled": True, "turnstile_secret_key": "secret"}):
        with patch.object(auth_routes, "is_mainland_china_ip", new_callable=AsyncMock, return_value=False):
            req = _FakeRequest("8.8.8.8")
            valid, error = await auth_routes.verify_captcha(req, None, None, None)
            assert valid is False
            assert error == "TURNSTILE_TOKEN_REQUIRED"


@pytest.mark.asyncio
async def test_verify_captcha_no_provider_enabled():
    with patch.object(auth_routes.Config, "get_global_settings", return_value={"turnstile_enabled": False, "tencent_captcha_enabled": False}):
        with patch.object(auth_routes, "is_mainland_china_ip", new_callable=AsyncMock, return_value=False):
            req = _FakeRequest("8.8.8.8")
            valid, error = await auth_routes.verify_captcha(req, None, None, None)
            assert valid is True
            assert error is None
