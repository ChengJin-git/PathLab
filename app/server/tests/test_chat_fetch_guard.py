import socket
import httpx
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from backend.services.articles import sources as chat_pdf_sources, reader as chat_pdf
from backend.common import net_guard


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            chat_pdf_sources.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


async def test_private_download_and_web_urls_rejected():
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match='blocked_url'):
        await chat_pdf_sources.download_pdf("http://169.254.169.254/latest/meta-data/")
    assert (
        await chat_pdf._fetch_lightweight_web_markdown(
            "http://127.0.0.1/private", "Private"
        )
    )["error_code"] == "blocked_url"


async def test_download_redirect_rechecks_network_target(client):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client(handler)
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match='blocked_url'):
        await chat_pdf_sources.download_pdf("https://example.org/file.pdf")
    assert seen == ["https://example.org/file.pdf"]


@pytest.mark.parametrize("provider", ["unpaywall", "semantic_scholar"])
async def test_oa_provider_cannot_redirect_to_private_network(client, provider, monkeypatch):
    monkeypatch.setenv("PATHLAB_CONTACT_EMAIL", "ops@example.org")
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "best_oa_location": {"url_for_pdf": "http://127.0.0.1/private"},
                "openAccessPdf": {"url": "http://127.0.0.1/private"},
            },
        )

    client(handler)
    function = getattr(chat_pdf_sources, "_try_" + provider + "_download")
    assert await function("https://doi.org/10.1234/test") is None
    assert all("127.0.0.1" not in url for url in seen)


async def test_landing_page_pdf_metadata_is_followed_once(client):
    def handler(request):
        if request.url.path == "/article":
            return httpx.Response(
                200, text='<meta name="citation_pdf_url" content="/paper.pdf">'
            )
        return httpx.Response(
            200,
            content=b"%PDF-1.4 actual pdf",
            headers={"content-type": "application/pdf"},
        )

    client(handler)
    assert (
        await chat_pdf_sources.download_pdf("https://example.org/article")
        == b"%PDF-1.4 actual pdf"
    )


async def test_pdf_mime_does_not_turn_html_into_pdf(client):
    client(
        lambda request: httpx.Response(
            200,
            text="<html>Access denied</html>",
            headers={"content-type": "application/pdf"},
        )
    )
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match='no_pdf'):
        await chat_pdf_sources.download_pdf("https://example.org/paper.pdf")


async def test_streamed_download_rejects_size_before_full_body(client):
    client(
        lambda request: httpx.Response(
            200, headers={"content-length": "999999"}, content=b"body"
        )
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="size limit"):
            await net_guard.guarded_get(http, "https://example.org/huge", max_bytes=100)


async def test_download_reports_received_bytes_without_changing_pdf(client):
    payload = b"%PDF-1.4 actual downloaded body"
    client(lambda request: httpx.Response(200, content=payload))
    progress = []
    result = await chat_pdf_sources.download_pdf(
        "https://example.org/paper.pdf",
        on_progress=lambda *values: progress.append(values),
    )
    assert result == payload
    assert progress[0] == (0, len(payload))
    assert progress[-1] == (len(payload), len(payload))


@pytest.mark.parametrize('status, code', [(403,'access_denied'),(404,'not_found'),(429,'rate_limited'),(503,'source_unavailable')])
async def test_download_preserves_verified_http_cause(client, status, code):
    client(lambda request: httpx.Response(status))
    with pytest.raises(chat_pdf_sources.ArticleDownloadError) as error:
        await chat_pdf_sources.download_pdf('https://example.org/original.pdf')
    assert error.value.code == code


@pytest.mark.parametrize("suffix", ["", ".full", ".full.pdf", ".abstract"])
def test_biorxiv_version_is_not_part_of_registry_doi(suffix):
    url = "https://www.biorxiv.org/content/10.64898/2026.07.23.740264v1" + suffix
    assert chat_pdf_sources._extract_doi(url) == "10.64898/2026.07.23.740264"
    assert chat_pdf_sources.get_biorxiv_pdf_url(url + "?download=1#page=2") == (
        "https://www.biorxiv.org/content/10.64898/2026.07.23.740264v1.full.pdf?download=1"
    )


async def test_publisher_cooldown_recovers_original_pdf(client, monkeypatch):
    seen = []
    sleep = AsyncMock()
    monkeypatch.setattr(chat_pdf_sources.asyncio, "sleep", sleep)

    def handler(request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "9"})
        return httpx.Response(200, content=b"%PDF-1.4 original")

    client(handler)
    assert await chat_pdf_sources.download_pdf("https://example.org/paper.pdf") == b"%PDF-1.4 original"
    sleep.assert_awaited_once_with(9)
    assert seen == ["https://example.org/paper.pdf"] * 2


async def test_persistent_cooldown_retries_only_once(client, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(chat_pdf_sources.asyncio, "sleep", sleep)
    client(lambda request: httpx.Response(429, headers={"retry-after": "1"}))
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match="rate_limited"):
        await chat_pdf_sources.download_pdf("https://example.org/paper.pdf")
    sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize("value", ["", "invalid", "120", "-1"])
def test_unbounded_or_invalid_retry_after_is_not_retried(value):
    assert chat_pdf_sources._retry_after_seconds(value) is None


def test_retry_after_accepts_http_date():
    value = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=8), usegmt=True)
    assert 6 <= chat_pdf_sources._retry_after_seconds(value) <= 8


async def test_retry_wait_obeys_total_download_deadline(client):
    client(lambda request: httpx.Response(429, headers={"retry-after": "9"}))
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match="request_timeout"):
        await chat_pdf_sources.download_pdf("https://example.org/paper.pdf", timeout=0.05)


async def test_read_does_not_hit_landing_page_after_publisher_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_pdf, "get_pdf_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(chat_pdf, "download_pdf", AsyncMock(
        side_effect=chat_pdf_sources.ArticleDownloadError("rate_limited")
    ))
    web = AsyncMock()
    monkeypatch.setattr(chat_pdf, "_fetch_lightweight_web_markdown", web)
    with pytest.raises(chat_pdf_sources.ArticleDownloadError, match="rate_limited"):
        await chat_pdf._read_article(
            "https://www.biorxiv.org/content/10.64898/2026.07.23.740264v1",
            "Spatium", False, "read", lambda status: None,
        )
    web.assert_not_awaited()
