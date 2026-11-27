"""Rendered preview routing, actual conversion, revision cache and authorization."""
# ruff: noqa: F811 -- shared pytest fixture.

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pymupdf
import pytest

from backend.services import document_preview as renderer
from backend.services.file_preview import preview
from test_chat_workbench import api as api


def make_pdf(path):
    with pymupdf.open() as document:
        for index in range(2):
            page = document.new_page(width=640, height=360)
            page.draw_rect(page.rect, color=None, fill=(0.1, 0.2, 0.5))
            page.insert_text((40, 80), f'Page {index + 1}', fontsize=24, color=(1, 1, 1))
        document.save(path)


def test_pdf_page_preview_is_bounded_cached_and_versioned(tmp_path):
    path = tmp_path / 'report.pdf'
    make_pdf(path)
    data = preview(path, path.name)
    assert data['kind'] == 'pdf' and data['page_count'] == 2
    assert data['first_page'].startswith('data:image/png;base64,')
    first = renderer.render_page(path, path.name, 1)
    assert first.read_bytes().startswith(b'\x89PNG')
    timestamp = first.stat().st_mtime_ns
    assert renderer.render_page(path, path.name, 1).stat().st_mtime_ns == timestamp
    assert renderer.render_page(path, path.name, 2).read_bytes() != first.read_bytes()
    for number in (0, 3, 10000):
        with pytest.raises(ValueError, match='previewPageNotFound'):
            renderer.render_page(path, path.name, number)
    with path.open('ab') as stream:
        stream.write(b'\n')
    assert renderer.render_page(path, path.name, 1) != first


def test_ready_preview_does_not_reopen_or_render_pdf(tmp_path, monkeypatch):
    path = tmp_path / 'report.pdf'
    make_pdf(path)
    expected = preview(path, path.name)
    monkeypatch.setattr(pymupdf, 'open', lambda *a, **kw: pytest.fail('ready preview reopened the PDF'))
    assert preview(path, path.name) == expected
    assert renderer.render_page(path, path.name, 1).is_file()


def test_warmup_returns_immediately_and_deduplicates(tmp_path, monkeypatch):
    path = tmp_path / 'report.pdf'
    make_pdf(path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def prepare(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(renderer, 'preview_document', prepare)
    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(renderer, '_warm_pool', executor)
        try:
            start = time.perf_counter()
            renderer.schedule_preview(path, path.name)
            assert time.perf_counter() - start < 0.5
            assert entered.wait(2)
            renderer.schedule_preview(path, path.name)
            assert len(calls) == 1
        finally:
            release.set()


def test_republishing_identical_bytes_keeps_preview_revision(tmp_path, monkeypatch):
    from backend.services import file_library
    monkeypatch.setattr(file_library.Config, 'get_uploads_dir', lambda: tmp_path)
    source = tmp_path / 'source.pdf'
    make_pdf(source)
    saved, digest = file_library.snapshot_file(source, 'owner', 'file')
    from pathlib import Path
    path = Path(saved)
    expected = preview(path, 'source.pdf')
    initial = path.stat().st_mtime_ns
    assert file_library.snapshot_file(source, 'owner', 'file') == (saved, digest)
    assert path.stat().st_mtime_ns == initial
    assert preview(path, 'source.pdf') == expected
    assert file_library.store_bytes('owner', 'file', 'source.pdf', source.read_bytes()) == (saved, digest)
    assert path.stat().st_mtime_ns == initial


def test_presentation_preserves_layout_and_reuses_conversion(tmp_path, monkeypatch):
    if not shutil.which('soffice'):
        pytest.skip('LibreOffice is required for actual presentation rendering')
    from pptx import Presentation
    from pptx.util import Inches
    from pptx.dml.color import RGBColor
    path = tmp_path / 'review.pptx'
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(12), Inches(6.75)
    for number in range(2):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(20, 50, 90)
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(10), Inches(2))
        box.text = f'Evidence review {number + 1}'
    presentation.save(path)
    result = preview(path, path.name)
    assert result['kind'] == 'slides' and result['page_count'] == 2
    assert result['page_width'] / result['page_height'] == pytest.approx(16 / 9, rel=0.01)
    image = renderer.render_page(path, path.name, 1)
    assert image.read_bytes().startswith(b'\x89PNG')
    monkeypatch.setattr(renderer.subprocess, 'Popen', lambda *a, **k: pytest.fail('cached preview reconverted'))
    assert preview(path, path.name)['page_count'] == 2
    assert renderer.render_page(path, path.name, 1) == image
    assert renderer.render_page(path, path.name, 2).is_file()


def test_page_limit_and_password_protection(tmp_path):
    path = tmp_path / 'locked.pdf'
    with pymupdf.open() as document:
        document.new_page()
        document.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='private')
    assert preview(path, path.name)['reason'] == 'previewUnavailable'
    huge = tmp_path / 'long.pdf'
    with pymupdf.open() as document:
        for _ in range(renderer.MAX_PAGES + 1):
            document.new_page()
        document.save(huge)
    assert preview(huge, huge.name)['reason'] == 'previewTooLarge'


async def test_each_rendered_page_rechecks_access_and_revision(api, tmp_path):
    path = tmp_path / 'report.pdf'
    make_pdf(path)
    response = await api.client.post('/workbench/uploads?workspace_id=ws', files={
        'file': ('report.pdf', path.read_bytes(), 'application/pdf'),
    })
    identity = response.json()['id']
    data = (await api.client.get(f'/workbench/files/{identity}?workspace_id=ws')).json()
    params = {'workspace_id': 'ws', 'revision': data['revision']}
    image = await api.client.get(f'/workbench/files/{identity}/pages/1', params=params)
    assert image.status_code == 200 and image.content.startswith(b'\x89PNG')
    assert image.headers['content-type'] == 'image/png'
    assert (await api.client.get(f'/workbench/files/{identity}/pages/1', params={**params, 'revision': 'stale'})).status_code == 409
    assert (await api.client.get(f'/workbench/files/{identity}/pages/3', params=params)).status_code == 404
    assert (await api.client.get('/workbench/files/secret/pages/1', params=params)).status_code == 404
    original = await api.client.get(f'/workbench/files/{identity}/content', params={'workspace_id': 'ws', 'download': 'true'})
    assert original.content == path.read_bytes()
