import pytest

from gateway.net_guard import EgressDeniedError, resolve_redirect_url, validate_external_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://0.0.0.0/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[fd00::1]/",
    ],
)
def test_validate_external_url_rejects_internal_targets(url):
    with pytest.raises(EgressDeniedError):
        validate_external_url(url)


def test_validate_external_url_allows_public_https(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )

    assert validate_external_url("https://example.com/article") == "https://example.com/article"


def test_resolve_redirect_url_rejects_internal_location(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("127.0.0.1", 80))],
    )

    with pytest.raises(EgressDeniedError):
        resolve_redirect_url("https://example.com/start", "http://localhost/private")
