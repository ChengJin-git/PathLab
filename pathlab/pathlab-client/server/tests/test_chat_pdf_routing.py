import json
import sys
import types
from datetime import datetime
from typing import Any

import pytest
from fastapi import HTTPException

from gateway.routes import chat_pdf


class _FakeDoc:
    def __init__(self, total_pages: int):
        self._total_pages = total_pages

    def __len__(self) -> int:
        return self._total_pages

    def close(self) -> None:
        return None


def _install_fake_pymupdf(monkeypatch, page_texts: list[str]) -> None:
    fake_doc = _FakeDoc(len(page_texts))

    def _fake_open(_path: str) -> _FakeDoc:
        return fake_doc

    def _fake_to_markdown(doc, **kwargs):
        pages = kwargs.get("pages")
        expected_pages = list(range(len(page_texts)))
        assert doc is fake_doc
        assert pages == expected_pages
        return [
            {
                "metadata": {"page": index + 1},
                "text": text,
            }
            for index, text in enumerate(page_texts)
        ]

    monkeypatch.setitem(sys.modules, "pymupdf", types.SimpleNamespace(open=_fake_open))
    monkeypatch.setitem(
        sys.modules,
        "pymupdf4llm",
        types.SimpleNamespace(to_markdown=_fake_to_markdown),
    )


def test_pymupdf_keeps_sparse_but_meaningful_fast_parse(monkeypatch):
    page_texts = [
        "Useful quick-read findings stay visible here.",
        "Readable notes still survive this fast pass.",
        "Sparse pages can still carry clear meaning.",
        "Users should not wait for Marker on this.",
        "Upgrade later can improve structure safely.",
    ]
    _install_fake_pymupdf(monkeypatch, page_texts)

    result = chat_pdf._parse_pdf_with_pymupdf_result(b"%PDF-1.4", max_pages=0)

    assert result is not None
    assert result.parse_method == chat_pdf.PDF_PARSE_METHOD_PYMUPDF
    assert result.page_count == 5
    assert "--- Page 1 ---" in result.markdown
    assert "--- Page 5 ---" in result.markdown


def test_pymupdf_rejects_nearly_empty_fast_parse(monkeypatch):
    _install_fake_pymupdf(monkeypatch, ["header", "page", "only", "tiny", "bits"])

    result = chat_pdf._parse_pdf_with_pymupdf_result(b"%PDF-1.4", max_pages=0)

    assert result is None


def test_get_cached_pdf_prefers_high_quality_marker_markdown(tmp_path, monkeypatch):
    url = "https://example.com/paper.pdf"
    url_hash = chat_pdf.get_url_hash(url)

    monkeypatch.setattr(
        chat_pdf.Config, "get_uploads_dir", staticmethod(lambda: tmp_path)
    )
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", None)

    cache_dir = chat_pdf.get_pdf_cache_dir()
    (cache_dir / f"{url_hash}.pdf").write_bytes(b"%PDF-1.4")
    (cache_dir / f"{url_hash}.json").write_text(
        json.dumps(
            {
                "url": url,
                "title": "Example",
                "cached_at": datetime.now().isoformat(),
            }
        ),
        encoding="utf-8",
    )
    (cache_dir / f"{url_hash}.md").write_text("fast markdown", encoding="utf-8")
    (cache_dir / f"{url_hash}.marker.md").write_text(
        "high quality markdown", encoding="utf-8"
    )

    cached = chat_pdf._get_cached_pdf(url)

    assert cached is not None
    _, _, cached_markdown, parse_method = cached
    assert cached_markdown == "high quality markdown"
    assert parse_method == chat_pdf.PDF_PARSE_METHOD_MARKER


@pytest.mark.asyncio
async def test_best_effort_foreground_skips_all_local_marker_paths(monkeypatch):
    calls = {
        "via_gpu_queue": False,
        "direct_gpu": False,
        "cpu": False,
    }

    async def _fake_via_gpu_queue(*args, **kwargs):
        calls["via_gpu_queue"] = True
        return None

    async def _fake_direct_gpu(*args, **kwargs):
        calls["direct_gpu"] = True
        return None

    async def _fake_cpu(*args, **kwargs):
        calls["cpu"] = True
        return chat_pdf.ParsedPdfResult(
            markdown="cpu fallback",
            parse_method=chat_pdf.PDF_PARSE_METHOD_MARKER,
            page_count=1,
            structured_content={},
        )

    monkeypatch.setattr(
        chat_pdf, "_parse_pdf_with_marker_via_gpu_queue", _fake_via_gpu_queue
    )
    monkeypatch.setattr(
        chat_pdf, "_parse_pdf_with_marker_direct_gpu_if_available", _fake_direct_gpu
    )
    monkeypatch.setattr(chat_pdf, "_parse_pdf_with_marker_on_cpu", _fake_cpu)

    result = await chat_pdf._parse_pdf_with_marker_best_effort(
        pdf_bytes=b"%PDF-1.4",
        max_pages=0,
        images_output_dir=None,
        images_url_prefix=None,
        upgrade_url=None,
    )

    assert not calls["via_gpu_queue"]
    assert not calls["direct_gpu"]
    assert not calls["cpu"]
    assert result is None


@pytest.mark.asyncio
async def test_best_effort_background_skips_all_local_paths_and_returns_none(monkeypatch):
    calls = {
        "via_gpu_queue": False,
        "direct_gpu": False,
        "cpu": False,
    }
    recorded_states: list[dict[str, Any]] = []

    async def _fake_via_gpu_queue(*args, **kwargs):
        calls["via_gpu_queue"] = True
        return None

    async def _fake_direct_gpu(*args, **kwargs):
        calls["direct_gpu"] = True
        return None

    async def _fake_cpu(*args, **kwargs):
        calls["cpu"] = True
        return None

    def _fake_record_state(url, status, detail, **extra):
        recorded_states.append({"url": url, "status": status, "detail": detail, **extra})

    monkeypatch.setattr(
        chat_pdf, "_parse_pdf_with_marker_via_gpu_queue", _fake_via_gpu_queue
    )
    monkeypatch.setattr(
        chat_pdf, "_parse_pdf_with_marker_direct_gpu_if_available", _fake_direct_gpu
    )
    monkeypatch.setattr(chat_pdf, "_parse_pdf_with_marker_on_cpu", _fake_cpu)
    monkeypatch.setattr(chat_pdf, "_record_high_quality_upgrade_state", _fake_record_state)

    result = await chat_pdf._parse_pdf_with_marker_best_effort(
        pdf_bytes=b"%PDF-1.4",
        max_pages=0,
        images_output_dir=None,
        images_url_prefix=None,
        upgrade_url="https://example.com/paper.pdf",
    )

    assert not calls["via_gpu_queue"]
    assert not calls["direct_gpu"]
    assert not calls["cpu"]
    assert result is None
    assert any(
        s["status"] == chat_pdf.PDF_UPGRADE_STATUS_SKIPPED
        and "Gateway" in s["detail"]
        for s in recorded_states
    )


@pytest.mark.asyncio
async def test_serve_pdf_image_rejects_symlink_escape(tmp_path, monkeypatch):
    url_hash = "abc123"
    uploads_dir = tmp_path / "uploads"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.png"
    outside_file.write_bytes(b"secret")

    monkeypatch.setattr(
        chat_pdf.Config, "get_uploads_dir", staticmethod(lambda: uploads_dir)
    )
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", None)

    image_dir = chat_pdf.get_pdf_cache_dir() / "images" / url_hash
    image_dir.mkdir(parents=True)
    (image_dir / "escape.png").symlink_to(outside_file)

    with pytest.raises(HTTPException) as exc_info:
        await chat_pdf.serve_pdf_image(url_hash, "escape.png", user=object())

    assert exc_info.value.status_code == 400
