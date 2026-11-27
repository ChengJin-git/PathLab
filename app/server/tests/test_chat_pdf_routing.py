import asyncio
import json
import time
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from backend.services.articles import reader as chat_pdf
from backend.services.articles.document import select_article_context
from backend.services.articles.identity import get_url_hash
from gateway.routes.chat_pdf import serve_pdf_image


def test_extracted_control_glyphs_preserve_offsets_and_unicode_evidence():
    from backend.services.articles.document import clean_extracted_content, _build_document_graph_from_pymupdf_chunks

    first = '公式 x\x00y\x13z，AUC=0.934\tα≤β\n\n'
    second = '|模型|指标|\n|---|---|\n|中文|0.812|'
    chunk = {'metadata': {'page': 6, 'title': 'Title\x00'}, 'text': first + second,
             'page_boxes': [{'pos': [0, len(first)], 'class': 'formula'},
                            {'pos': [len(first), len(first + second)], 'class': 'table', 'bbox': [1, 2, 3, 4]}]}
    cleaned = clean_extracted_content(chunk)
    assert len(cleaned['text']) == len(chunk['text'])
    assert cleaned['text'] == first.replace('\x00', '\ufffd').replace('\x13', '\ufffd') + second
    assert cleaned['metadata']['title'] == 'Title\ufffd'
    graph = _build_document_graph_from_pymupdf_chunks([cleaned], 'pymupdf')
    assert graph['blocks'][0]['latex'] == cleaned['text'][:len(first)].strip()
    assert graph['blocks'][1]['cells'][-1] == ['中文', '0.812']
    assert graph['blocks'][1]['page'] == 6
    assert '\x00' in chunk['text']  # normalization does not rewrite the input receipt


async def test_reader_serves_clean_cached_text_and_structured_evidence_without_redownload(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_pdf, '_pdf_cache_dir', tmp_path)
    monkeypatch.setattr(chat_pdf, 'validate_external_url', lambda url: url)
    url = 'https://example.test/paper.pdf'
    identity = get_url_hash(url)
    (tmp_path / f'{identity}.json').write_text(json.dumps({
        'schema_version': chat_pdf.CACHE_SCHEMA, 'cached_at': time.time(), 'parse_method': 'pymupdf',
        'page_count': 28, 'title': 'Title\x00', 'content_scope': 'pdf',
    }))
    (tmp_path / f'{identity}.md').write_text('--- Page 6 ---\nFormula x\x00y\x13z; AUC 0.934.')
    (tmp_path / f'{identity}.structured.json').write_text(json.dumps({'blocks': [{'text': 'x\x00y', 'page': 6}]}))
    download = AsyncMock()
    parse = AsyncMock()
    monkeypatch.setattr(chat_pdf, 'download_pdf', download)
    monkeypatch.setattr(chat_pdf, 'parse_pdf', parse)
    result = await chat_pdf.process_pdf_url(url, 'Title')
    assert result['success'] and result['from_cache'] and result['page_count'] == 28
    assert result['pdf_content'] == '--- Page 6 ---\nFormula x\ufffdy\ufffdz; AUC 0.934.'
    assert result['title'] == 'Title\ufffd'
    assert chat_pdf.get_cached_structured_content(url)['blocks'][0] == {'text': 'x\ufffdy', 'page': 6}
    download.assert_not_awaited()
    parse.assert_not_awaited()


async def test_first_pdf_read_and_cache_store_clean_text_but_preserve_original_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_pdf, '_pdf_cache_dir', tmp_path)
    monkeypatch.setattr(chat_pdf, 'validate_external_url', lambda url: url)
    original = b'%PDF-1.4 original\x00binary'
    monkeypatch.setattr(chat_pdf, 'download_pdf', AsyncMock(return_value=original))
    parsed = chat_pdf.ParsedPdfResult('--- Page 6 ---\nx\x00y', 'pymupdf', 1,
                                     {'blocks': [{'latex': 'x\x00y', 'page': 6}]})
    monkeypatch.setattr(chat_pdf, 'parse_pdf', AsyncMock(return_value=parsed))
    url = 'https://example.test/first.pdf'
    result = await chat_pdf.process_pdf_url(url, 'Title', action='read_download')
    identity = get_url_hash(url)
    assert result['success'] and result['pdf_content'] == '--- Page 6 ---\nx\ufffdy'
    assert (tmp_path / f'{identity}.pdf').read_bytes() == original
    assert '\x00' not in (tmp_path / f'{identity}.md').read_text()
    assert '\\u0000' not in (tmp_path / f'{identity}.structured.json').read_text()


def test_canonical_arxiv_variants_share_cache_and_version_is_distinct():
    assert get_url_hash("https://arxiv.org/pdf/1706.03762.pdf") == get_url_hash(
        "https://arxiv.org/abs/1706.03762#section"
    )
    assert get_url_hash("https://arxiv.org/abs/1706.03762v1") != get_url_hash(
        "https://arxiv.org/abs/1706.03762v2"
    )


def test_long_paper_selection_keeps_requested_middle_page():
    document = "\n".join(
        f"--- Page {index} ---\n"
        + (
            "irrelevant text " * 1000
            if index != 6
            else "calibration ablation 0.934 " * 1000
        )
        for index in range(1, 12)
    )
    selected = select_article_context(document, "page 6 calibration ablation", 16000)
    assert "--- Page 6 ---" in selected and "0.934" in selected
    assert len(selected) <= 16000


def test_long_html_selection_keeps_relevant_sections_without_inventing_pages():
    document = "# Abstract\n" + "Background description. " * 1500
    document += "\n## Methods\nUnified knowledge distillation temperature was 0.04.\n"
    document += "\n## References\n" + "Bibliography entries. " * 1500
    selected = select_article_context(
        document, "Methods distillation temperature", 8000
    )
    assert "temperature was 0.04" in selected
    assert "## Methods" in selected and "--- Page" not in selected
    assert len(selected) <= 8000


@pytest.mark.asyncio
async def test_download_only_does_not_parse_and_repeat_read_uses_cache(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", tmp_path)
    monkeypatch.setattr(chat_pdf, "validate_external_url", lambda url: url)
    download = AsyncMock(return_value=b"%PDF-1.4 actual downloaded fixture")
    parsed = chat_pdf.ParsedPdfResult(
        "--- Page 1 ---\nMeasured result.", "pymupdf", 1, {"blocks": []}
    )
    parse = AsyncMock(return_value=parsed)
    monkeypatch.setattr(chat_pdf, "download_pdf", download)
    monkeypatch.setattr(chat_pdf, "parse_pdf", parse)
    url = "https://arxiv.org/abs/1706.03762"
    result = await chat_pdf.process_pdf_url(url, "Attention", action="download")
    assert result["success"] and result["download_path"]
    parse.assert_not_awaited()
    first = await chat_pdf.process_pdf_url(url, "Attention")
    second = await chat_pdf.process_pdf_url(
        "https://arxiv.org/pdf/1706.03762.pdf", "Attention"
    )
    assert first["pdf_content"] == second["pdf_content"] and second["from_cache"]
    assert download.await_count == 1 and parse.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_reads_share_one_download_and_parse(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", tmp_path)
    monkeypatch.setattr(chat_pdf, "validate_external_url", lambda url: url)
    download = AsyncMock(return_value=b"%PDF-1.4 content")
    parse = AsyncMock(
        return_value=chat_pdf.ParsedPdfResult(
            "--- Page 1 ---\nResult.", "pymupdf", 1, {"blocks": []}
        )
    )
    monkeypatch.setattr(chat_pdf, "download_pdf", download)
    monkeypatch.setattr(chat_pdf, "parse_pdf", parse)
    results = await asyncio.gather(
        *(
            chat_pdf.process_pdf_url("https://arxiv.org/abs/1706.03762", "Title")
            for _ in range(3)
        )
    )
    assert all(result["success"] for result in results)
    assert download.await_count == 1 and parse.await_count == 1


@pytest.mark.asyncio
async def test_image_endpoint_rejects_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", tmp_path / "cache")
    identity = "a" * 64
    directory = chat_pdf.get_pdf_cache_dir() / "images" / identity
    directory.mkdir(parents=True)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"private")
    (directory / "link.png").symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        await serve_pdf_image(identity, "link.png", user=object())
    assert error.value.status_code == 400


async def test_parse_timeout_is_not_reported_as_a_network_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", tmp_path)
    monkeypatch.setattr(chat_pdf, "validate_external_url", lambda url: url)
    monkeypatch.setattr(
        chat_pdf, "download_pdf", AsyncMock(return_value=b"%PDF-1.4 fixture")
    )
    monkeypatch.setattr(
        chat_pdf, "parse_pdf", AsyncMock(side_effect=chat_pdf.PdfParseTimeoutError())
    )
    result = await chat_pdf.process_pdf_url("https://arxiv.org/abs/2407.18449", "GPFM")
    assert not result["success"]
    assert result["error"] == "parse_failed"
    assert result["error_code"] == "parse_timeout"
    assert 'error_detail' not in result
    assert len(list(tmp_path.glob("*.pdf"))) == 1


async def test_combined_read_keeps_successful_download_when_parsing_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_pdf, '_pdf_cache_dir', tmp_path)
    monkeypatch.setattr(chat_pdf, 'validate_external_url', lambda url: url)
    monkeypatch.setattr(chat_pdf, 'download_pdf', AsyncMock(return_value=b'%PDF-1.4 original bytes'))
    monkeypatch.setattr(chat_pdf, 'parse_pdf', AsyncMock(side_effect=chat_pdf.PdfParseTimeoutError()))
    result = await chat_pdf.process_pdf_url('https://example.test/original.pdf', 'Original', action='read_download')
    assert not result['success'] and result['error_code'] == 'parse_timeout'
    from pathlib import Path
    assert Path(result['download_path']).read_bytes() == b'%PDF-1.4 original bytes'


async def test_parser_queue_is_bounded_and_reports_waiting(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setitem(chat_pdf._parse_slots, loop, asyncio.Semaphore(0))
    monkeypatch.setattr(chat_pdf, "PDF_PARSE_QUEUE_TIMEOUT", 0.01)
    progress = []
    with pytest.raises(chat_pdf.PdfParseBusyError):
        await chat_pdf.parse_pdf(b"%PDF-1.4 fixture", on_progress=progress.append)
    assert progress == [{"status": "waiting"}]
    assert chat_pdf._parse_waiting[loop] == 0


async def test_publisher_fulltext_html_skips_pdf_and_preserves_scope(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(chat_pdf, "_pdf_cache_dir", tmp_path)
    monkeypatch.setattr(chat_pdf, "validate_external_url", lambda url: url)
    web = {
        "success": True,
        "title": "GPFM",
        "markdown": "Published methods and results",
        "content_scope": "fulltext_html",
    }
    monkeypatch.setattr(
        chat_pdf, "_fetch_lightweight_web_markdown", AsyncMock(return_value=web)
    )
    download = AsyncMock()
    monkeypatch.setattr(chat_pdf, "download_pdf", download)
    result = await chat_pdf.process_pdf_url(
        "https://www.nature.com/articles/example", "GPFM"
    )
    assert result["success"] and result["content_scope"] == "fulltext_html"
    assert result["page_count"] == 0 and result["parse_method"] == "web"
    download.assert_not_awaited()


def test_html_fulltext_detection_does_not_promote_abstracts():
    body = "Measured GPFM results. " * 20
    abstract = f'<title>GPFM</title><article class="c-article-body"><h2>Abstract</h2><p>{body}</p></article>'
    assert (
        chat_pdf._extract_html(
            abstract, "https://www.nature.com/articles/example", "GPFM"
        )["content_scope"]
        == "webpage"
    )
    full = abstract.replace(
        "</article>",
        "<h2>Results</h2><p>0.934</p><h2>Methods</h2><p>Distillation</p></article>",
    )
    assert (
        chat_pdf._extract_html(full, "https://www.nature.com/articles/example", "GPFM")[
            "content_scope"
        ]
        == "fulltext_html"
    )
    assert (
        chat_pdf._extract_html(abstract, "https://arxiv.org/abs/2407.18449", "GPFM")[
            "content_scope"
        ]
        == "abstract"
    )
