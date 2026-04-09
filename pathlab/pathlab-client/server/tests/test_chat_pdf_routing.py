import json
import sys
import types
from datetime import datetime

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
