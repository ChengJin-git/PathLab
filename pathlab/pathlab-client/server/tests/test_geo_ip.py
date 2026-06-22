import pytest
from backend.common.geo_ip import get_client_ip, is_mainland_china_ip


class MockClient:
    def __init__(self, host):
        self.host = host


class MockRequest:
    def __init__(self, host="", headers=None):
        self.client = MockClient(host) if host else None
        self.headers = headers or {}


class TestGetClientIP:
    def test_direct_connection(self):
        req = MockRequest(host="1.2.3.4")
        assert get_client_ip(req) == "1.2.3.4"

    def test_x_forwarded_for(self):
        req = MockRequest(host="10.0.0.1", headers={"x-forwarded-for": "5.6.7.8, 10.0.0.2"})
        assert get_client_ip(req) == "5.6.7.8"

    def test_cf_connecting_ip(self):
        req = MockRequest(host="10.0.0.1", headers={"cf-connecting-ip": "9.10.11.12"})
        assert get_client_ip(req) == "9.10.11.12"

    def test_private_ip_fallback(self):
        req = MockRequest(host="192.168.1.1")
        assert get_client_ip(req) == "192.168.1.1"


class TestIsMainlandChinaIP:
    @pytest.mark.asyncio
    async def test_china_ip(self, monkeypatch):
        async def mock_fetch(ip):
            return {"countryCode": "CN"}
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        monkeypatch.setattr("backend.common.geo_ip._ip_cache", {})
        assert await is_mainland_china_ip("1.1.1.1") is True

    @pytest.mark.asyncio
    async def test_us_ip(self, monkeypatch):
        async def mock_fetch(ip):
            return {"countryCode": "US"}
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        monkeypatch.setattr("backend.common.geo_ip._ip_cache", {})
        assert await is_mainland_china_ip("1.1.1.1") is False

    @pytest.mark.asyncio
    async def test_service_failure_fallback(self, monkeypatch):
        async def mock_fetch(ip):
            raise Exception("Service down")
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        monkeypatch.setattr("backend.common.geo_ip._ip_cache", {})
        monkeypatch.setattr("backend.common.geo_ip._circuit_failures", 0)
        assert await is_mainland_china_ip("1.1.1.1") is False

    @pytest.mark.asyncio
    async def test_private_ip(self):
        assert await is_mainland_china_ip("192.168.1.1") is False
        assert await is_mainland_china_ip("10.0.0.1") is False
        assert await is_mainland_china_ip("127.0.0.1") is False
