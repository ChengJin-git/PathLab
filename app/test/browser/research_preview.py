"""Actual PDF/PPTX/DOCX page rendering through Chat and research detail previews."""

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server'))
from backend.services.file_preview import preview
from backend.services.document_preview import render_page

BASE = os.environ.get('VIEWER_URL', 'http://127.0.0.1:5189')
CHAT, SESSION = 'preview-chat', 'preview-study'


def fixtures(root):
    import pymupdf
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from docx import Document
    from openpyxl import Workbook

    with pymupdf.open() as document:
        for index in range(2):
            page = document.new_page(width=640, height=360)
            page.draw_rect(page.rect, color=None, fill=(0.96, 0.97, 0.99))
            page.insert_text((40, 70), f'Research evidence / {index + 1}', fontsize=28, color=(0.1, 0.2, 0.4))
            page.insert_text((40, 130), 'Patient-level splits and independent validation', fontsize=18)
        document.save(root / 'report.pdf')
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(12), Inches(6.75)
    for index in range(2):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(20, 36, 64)
        box = slide.shapes.add_textbox(Inches(0.8), Inches(1.3), Inches(10.4), Inches(1.5))
        p = box.text_frame.paragraphs[0]
        p.text = f'Spatial proteomics / {index + 1}'
        p.font.size, p.font.color.rgb = Pt(36), RGBColor(245, 248, 255)
        box = slide.shapes.add_textbox(Inches(0.8), Inches(3), Inches(10.4), Inches(1.5))
        p = box.text_frame.paragraphs[0]
        p.text = 'Public cohorts, cross-panel transfer and evidence quality'
        p.font.size, p.font.color.rgb = Pt(23), RGBColor(175, 210, 245)
    presentation.save(root / 'review.pptx')
    document = Document()
    document.add_heading('Evidence review', 0)
    document.add_paragraph('Independent validation and public data access.')
    document.add_page_break()
    document.add_heading('Study design', 1)
    document.save(root / 'review.docx')
    workbook = Workbook()
    workbook.active.title = 'Summary'
    workbook.active.append(['Metric', 'Value'])
    workbook.active.append(['AUC', 0.81])
    workbook.create_sheet('Validation').append(['External cohort', 42])
    workbook.save(root / 'metrics.xlsx')
    (root / 'metrics.csv').write_text('Metric,Value\nAUC,0.81')
    (root / 'report.md').write_text('# Evidence review\n\nMeasured evidence.')
    (root / 'report.html').write_text('<h1>HTML report</h1><p>Visual summary</p>')
    (root / 'analysis.py').write_text('print("measured results")')
    (root / 'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"><rect width="600" height="300" fill="#eaf2fb"/><text x="40" y="100" font-size="30">Evidence figure</text></svg>')


with tempfile.TemporaryDirectory(prefix='pathlab-preview-') as directory:
    root = Path(directory)
    fixtures(root)
    names = [path.name for path in root.iterdir() if path.is_file()]
    descriptors = {}
    for name in names:
        descriptors[name] = {'file_id': name, **preview(root / name, name)}
    assert descriptors['review.pptx']['kind'] == 'slides'
    assert descriptors['review.docx']['kind'] == 'document'
    files = [{'kind': 'file', 'id': name, 'name': name, 'path': name, 'session_id': SESSION, 'revision': 'v1'} for name in names]
    prose = '\n\n'.join(f'[Open {name}]({name})' for name in names)
    session = {'session_id': SESSION, 'chat_conversation_id': CHAT, 'title': 'Preview deliverables',
               'question': 'Review generated files', 'status': 'completed', 'task_kind': 'document', 'created_at': 1,
               'events': [], 'activity': [{'kind': 'message', 'seq': 1, 'message': {'id': 'deliver', 'type': 'assistant', 'text': prose}}],
               'jobs': [], 'experiments': [], 'state': {'plan': [], 'artifacts': [{'path': name, 'name': name} for name in names]}}
    chat = {'conversation_id': CHAT, 'user_id': 'owner', 'workspace_id': None, 'title': 'Generated reports',
            'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z', 'messages': [], 'pinned': False}
    requests = []

    def api(route):
        url = urlparse(route.request.url)
        path = url.path
        requests.append(path)
        if path.endswith('/auth/me'):
            result = {'id': 'owner', 'username': 'reviewer', 'role': 'admin', 'is_active': True, 'is_verified': True,
                      'agreement_accepted_at': '2026-01-01', 'notice_acknowledged_at': '2026-01-01'}
        elif path.endswith('/stream'):
            route.fulfill(status=200, content_type='text/event-stream', body='data: {"items":[],"tasks":[]}\n\n')
            return
        elif path.endswith('/chat-navigation/chats'):
            result = {'items': [chat], 'next_cursor': None}
        elif path.endswith('/research-statuses'):
            result = {'states': {}, 'file_conversations': [CHAT]}
        elif path.endswith(f'/conversations/{CHAT}/research'):
            result = {'items': [session]}
        elif path.endswith(f'/conversations/{CHAT}/files'):
            result = {'items': files, 'next_cursor': None}
        elif path.endswith(f'/conversations/{CHAT}'):
            result = chat
        elif path.endswith('/conversations'):
            result = {'conversations': [chat], 'total': 1}
        elif path.endswith(f'/sessions/{SESSION}'):
            result = session
        elif path.endswith('/file-reference'):
            name = route.request.post_data_json['path']
            result = next(file for file in files if file['name'] == name)
            if route.request.post_data_json.get('include_preview'):
                result = {**result, 'preview': descriptors[name]}
        elif '/workbench/files/' in path:
            part = path.split('/workbench/files/', 1)[1].split('/')
            name = part[0]
            if len(part) > 1 and part[1] == 'pages':
                page = render_page(root / name, name, int(part[2]))
                route.fulfill(status=200, content_type='image/png', body=page.read_bytes())
                return
            if len(part) > 1 and part[1] == 'content':
                route.fulfill(status=200, content_type='image/svg+xml', body=(root / name).read_bytes())
                return
            result = {'file_id': name, **preview(root / name, name, parse_qs(url.query).get('sheet', [''])[0])}
        elif 'maintenance' in path:
            result = {'active': False, 'needs_acknowledgment': False}
        else:
            result = {'items': [], 'total': 0, 'next_cursor': None, 'tasks': [], 'skills': [], 'connectors': [], 'elevated_dataset_ids': [], 'gpu_dataset_ids': []}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route(re.compile('^' + re.escape(BASE) + '/api/'), api)
            page.add_init_script("if (window === window.top) { localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','en-US');localStorage.setItem('pwa-install-dismissed',String(Date.now())); }")
            page.goto(BASE + f'/autoresearch/sessions/{SESSION}', wait_until='domcontentloaded', timeout=60000)
            page.wait_for_load_state('networkidle', timeout=60000)
            timings = {}
            for name in ('review.pptx', 'report.pdf', 'review.docx'):
                start = time.perf_counter()
                page.get_by_role('button', name=f'Open {name}', exact=True).click()
                dialog = page.get_by_role('dialog')
                image = dialog.get_by_role('img')
                expect(image).to_be_visible()
                expect(image).to_have_attribute('alt', re.compile('1 of 2'))
                image.evaluate('img => img.decode()')
                timings[name] = round((time.perf_counter() - start) * 1000, 1)
                assert f'/api/workbench/files/{name}/pages/1' not in requests
                assert f'/api/workbench/files/{name}' not in requests
                assert image.evaluate('img => img.naturalWidth > 500')
                dialog.get_by_role('button', name='Next page', exact=True).click()
                expect(image).to_have_attribute('alt', re.compile('2 of 2'))
                image.evaluate('img => img.decode()')
                calls = len(requests)
                dialog.get_by_role('button', name='Previous page', exact=True).click()
                expect(image).to_have_attribute('alt', re.compile('1 of 2'))
                image.evaluate('img => img.decode()')
                assert len(requests) == calls, 'Previous page fetched again'
                dialog.get_by_role('button', name='Next page', exact=True).click()
                dialog.get_by_role('button', name='Preview zoom', exact=True).click()
                page.get_by_role('option', name='150%', exact=True).click()
                expect(image).to_be_visible()
                if os.environ.get('VIEWER_SCREENSHOTS'):
                    output = Path(os.environ['VIEWER_SCREENSHOTS'])
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / (name + '.png')), animations='disabled')
                dialog.get_by_role('button', name='Close', exact=True).click()
            for name, kind in [('metrics.xlsx','table'), ('metrics.csv','table'), ('report.md','markdown'), ('report.html','html'), ('analysis.py','code'), ('figure.svg','image')]:
                page.get_by_role('button', name=f'Open {name}', exact=True).click()
                dialog = page.get_by_role('dialog')
                expect(dialog.locator(f'[data-preview-kind="{kind}"]')).to_be_visible()
                if name == 'metrics.xlsx':
                    dialog.get_by_role('button', name='Worksheet', exact=True).click()
                    page.get_by_role('option', name='Validation', exact=True).click()
                    expect(dialog.get_by_text('External cohort', exact=True)).to_be_visible()
                dialog.get_by_role('button', name='Close', exact=True).click()
            # The artifact button uses the same viewer, and switching to Chat preserves format.
            page.get_by_role('tab', name='Artifacts', exact=True).click()
            page.get_by_role('button', name='Preview review.pptx', exact=True).click()
            expect(page.get_by_role('dialog').locator('[data-preview-kind="slides"]')).to_be_visible()
            page.get_by_role('dialog').get_by_role('button', name='Close', exact=True).click()
            page.get_by_role('link', name='Back to conversation', exact=True).click()
            page.get_by_role('button', name='Open review.pptx', exact=True).click()
            expect(page.locator('[data-preview-kind="slides"]')).to_be_visible()
            image = page.locator('[data-preview-kind="slides"]').get_by_role('img')
            expect(image).to_be_visible()
            before = len([value for value in requests if '/pages/' in value])
            page.get_by_role('button', name='Expand to full screen', exact=True).click()
            expect(page.get_by_role('dialog').locator('[data-preview-kind="slides"]')).to_be_visible()
            assert len([value for value in requests if '/pages/' in value]) == before
            page.get_by_role('button', name='Exit full screen', exact=True).click()
            page.set_viewport_size({'width': 375, 'height': 812})
            expect(page.locator('[data-preview-kind="slides"]').get_by_role('button', name='Next page', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            print('PASS actual PDF/PPTX/DOCX pages, cached navigation, typed formats, shared links, fullscreen and mobile; ready-preview click-to-paint ms:', timings)
        finally:
            browser.close()
