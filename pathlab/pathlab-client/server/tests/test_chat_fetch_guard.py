import importlib.util
import socket
import sys
import types
from pathlib import Path

import httpx
import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]

class _Logger:
    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass


def install_gateway_dependency_stub(monkeypatch):
    deps = types.ModuleType("gateway.dependencies")
    deps.logger = _Logger()
    monkeypatch.setitem(sys.modules, "gateway.dependencies", deps)


def _load_module(module_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(module_name, SERVER_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def allow_example_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )


@pytest.mark.asyncio
async def test_download_pdf_blocks_metadata_service_url(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    module = _load_module("gateway.routes.chat_pdf_sources", "gateway/routes/chat_pdf_sources.py")

    assert await module.download_pdf("http://169.254.169.254/latest/meta-data/") is None


@pytest.mark.asyncio
async def test_download_pdf_blocks_redirect_to_internal_url(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    allow_example_dns(monkeypatch)
    module = _load_module("gateway.routes.chat_pdf_sources", "gateway/routes/chat_pdf_sources.py")
    requested: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            requested.append(str(url))
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data/"},
                request=httpx.Request("GET", str(url)),
            )

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)

    assert await module.download_pdf("https://example.com/paper.pdf") is None
    assert requested == ["https://example.com/paper.pdf"]


@pytest.mark.asyncio
async def test_unpaywall_download_blocks_internal_pdf_location(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    module = _load_module("gateway.routes.chat_pdf_sources", "gateway/routes/chat_pdf_sources.py")
    requested: list[str] = []
    internal_url = "http://169.254.169.254/latest/meta-data/"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            requested.append(str(url))
            if str(url).startswith("https://api.unpaywall.org/"):
                return httpx.Response(
                    200,
                    json={"best_oa_location": {"url_for_pdf": internal_url}},
                    request=httpx.Request("GET", str(url)),
                )
            return httpx.Response(500, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)

    assert await module._try_unpaywall_download("https://doi.org/10.1234/example") is None
    assert internal_url not in requested


@pytest.mark.asyncio
async def test_semantic_scholar_download_blocks_internal_pdf_location(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    module = _load_module("gateway.routes.chat_pdf_sources", "gateway/routes/chat_pdf_sources.py")
    requested: list[str] = []
    internal_url = "http://169.254.169.254/latest/meta-data/"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            requested.append(str(url))
            if str(url).startswith("https://api.semanticscholar.org/"):
                return httpx.Response(
                    200,
                    json={"openAccessPdf": {"url": internal_url}},
                    request=httpx.Request("GET", str(url)),
                )
            return httpx.Response(500, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)

    assert await module._try_semantic_scholar_download("https://doi.org/10.1234/example") is None
    assert internal_url not in requested


@pytest.mark.asyncio
async def test_doi_redirect_does_not_auto_follow_internal_location(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    module = _load_module("gateway.routes.chat_pdf_sources", "gateway/routes/chat_pdf_sources.py")
    requested: list[str] = []
    internal_url = "http://169.254.169.254/latest/meta-data/"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.follow_redirects = kwargs.get("follow_redirects", False)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, **kwargs):
            requested.append(str(url))
            if self.follow_redirects:
                requested.append(internal_url)
                return httpx.Response(
                    200,
                    request=httpx.Request("HEAD", str(url)),
                    extensions={"network_stream": None},
                )
            return httpx.Response(
                302,
                headers={"location": internal_url},
                request=httpx.Request("HEAD", str(url)),
            )

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)

    assert await module._follow_doi_redirect("10.1234/example") == "https://doi.org/10.1234/example"
    assert internal_url not in requested


@pytest.mark.asyncio
async def test_lightweight_web_fetch_blocks_localhost(monkeypatch):
    install_gateway_dependency_stub(monkeypatch)
    deps = types.ModuleType("gateway.routes.transformers_runtime")
    deps.ensure_transformers_runtime_ready = lambda: None
    monkeypatch.setitem(sys.modules, "gateway.routes.transformers_runtime", deps)

    vectorstore = types.ModuleType("gateway.routes.chat_pdf_vectorstore")
    vectorstore.search_pdf_chunks = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "gateway.routes.chat_pdf_vectorstore", vectorstore)

    document = types.ModuleType("gateway.routes.chat_pdf_document")

    class ParsedPdfResult(dict):
        pass

    document.ParsedPdfResult = ParsedPdfResult
    for name in (
        "tokenize_for_search",
        "split_md_into_pages",
        "_parse_markdown_table_rows",
        "_coerce_text",
        "_safe_int",
        "_normalize_bbox",
        "_build_markdown_table_from_rows",
        "_extract_markdown_image",
        "_make_page_node",
        "_append_blocks_from_markdown_text",
        "_build_document_graph_from_markdown",
        "_marker_image_block_id_from_name",
        "_normalize_marker_markdown",
        "_extract_marker_text_from_html",
        "_extract_marker_table_rows",
        "_collect_marker_section_titles",
        "_resolve_marker_section_path",
        "_find_marker_image_url",
        "_collect_marker_caption_text",
        "_build_document_graph_from_marker_document",
        "_build_document_graph_from_pymupdf_chunks",
        "_to_parsed_pdf_result",
        "search_pdf_pages",
    ):
        setattr(document, name, lambda *args, **kwargs: "")
    monkeypatch.setitem(sys.modules, "gateway.routes.chat_pdf_document", document)

    module = _load_module("gateway.routes.chat_pdf", "gateway/routes/chat_pdf.py")
    result = await module._fetch_lightweight_web_markdown(
        "http://localhost/private",
        "Local",
        "web",
    )

    assert result["success"] is False
    assert result["error_code"] == "blocked_url"
