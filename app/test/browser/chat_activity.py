"""Public-only Chat activity, disclosure latency and bounded projection cost."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
CHAT = "activity-review"
activity = [
    {"id": str(index), "operation": operation, "status": "completed", "subject": subject,
     "detail": "INTERNAL_SENTINEL /srv/private/context.json token=secret"}
    for index, (operation, subject) in enumerate([
        ("context", "Internal context"), ("tool", "LOAD_CAPABILITY"),
        ("search", "spatial proteomics foundation model cross panel"),
        ("search", "Spatium 公开验证数据"),
        ("read", "Spatium: A Protein Language Foundation Model for Spatial Proteomics"),
        ("respond", ""),
    ])
]
chat = {
    "conversation_id": CHAT, "user_id": "owner", "workspace_id": None,
    "title": "空间蛋白组研究方向", "pinned": False, "folder_id": None,
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    "messages": [
        {"id": 1, "role": "user", "content": "帮我核查空间蛋白组基础模型的研究方向。", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 2, "role": "assistant", "content": "建议优先核查独立队列验证、真实跨 panel 迁移和空间负对照，再判断大规模预训练的增量价值。", "created_at": "2026-01-01T00:00:01Z", "metadata": {"artifacts": {"activity": activity}}},
    ],
}
requests = []


def api(route):
    path = urlparse(route.request.url).path
    requests.append(path)
    if path.endswith("/auth/me"):
        result = {"id": "owner", "username": "reviewer", "role": "admin", "is_active": True,
                  "is_verified": True, "agreement_accepted_at": "2026-01-01", "notice_acknowledged_at": "2026-01-01"}
    elif path.endswith("/stream"):
        route.fulfill(status=200, content_type="text/event-stream", body='data: {"items":[],"tasks":[]}\n\n')
        return
    elif path.endswith("/chat-navigation/chats"):
        result = {"items": [chat], "next_cursor": None}
    elif path.endswith("/research-statuses"):
        result = {"states": {}, "file_conversations": []}
    elif path.endswith(f"/conversations/{CHAT}"):
        result = chat
    elif path.endswith("/conversations"):
        result = {"conversations": [chat], "total": 1}
    elif "maintenance" in path:
        result = {"active": False, "needs_acknowledgment": False}
    else:
        result = {"items": [], "total": 0, "next_cursor": None, "tasks": [], "skills": [], "connectors": [],
                  "elevated_dataset_ids": [], "gpu_dataset_ids": []}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(result))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
        page.add_init_script("localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','zh-CN');localStorage.setItem('pwa-install-dismissed',String(Date.now()))")
        page.goto(BASE + f"/dashboard/{CHAT}")
        page.wait_for_load_state("networkidle")
        strip = page.locator("[data-chat-activity]")
        toggle = strip.get_by_role("button", name="处理过程", exact=True)
        expect(toggle).to_contain_text("已阅读《Spatium")
        expect(strip.get_by_role("list")).to_have_count(0)
        before = len(requests)
        # Measure actual DOM disclosure to the next frame, without Playwright's actionability wait.
        elapsed = toggle.evaluate("""async button => {
            const start = performance.now();
            button.click();
            await new Promise(requestAnimationFrame);
            if (!button.parentElement.querySelector('ol')) throw new Error('Disclosure delayed');
            return performance.now() - start;
        }""")
        expect(strip.get_by_role("listitem")).to_have_count(4)
        expect(strip.get_by_role("list")).to_contain_text("已搜索“Spatium 公开验证数据”相关资料")
        assert "INTERNAL_SENTINEL" not in strip.inner_html() and "LOAD_CAPABILITY" not in strip.inner_html()
        assert " · " not in strip.inner_text()
        assert len(requests) == before, "Disclosure issued a network request"
        assert elapsed < 150, f"Disclosure stalled: {elapsed:.1f} ms"
        if os.environ.get("VIEWER_SCREENSHOTS"):
            root = Path(os.environ["VIEWER_SCREENSHOTS"])
            root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(root / "chat-activity.png"), animations="disabled")
        page.set_viewport_size({"width": 375, "height": 812})
        expect(toggle).to_be_visible()
        assert strip.evaluate("el => el.scrollWidth <= el.clientWidth"), "Activity overflow on mobile"
        toggle.click()
        expect(strip.get_by_role("list")).to_have_count(0)
        page.get_by_role("button", name="Language", exact=True).click()
        page.get_by_role("button", name="English", exact=True).click()
        expect(strip.get_by_role("button", name="Activity", exact=True)).to_contain_text("Read “Spatium")
        timings = page.evaluate("""async () => {
            const { summarizeChatActivity } = await import('/src/components/chat/chatActivity.ts');
            const items = Array.from({length: 12}, (_, i) => ({id: String(i), operation: ['context','search','read','respond'][i % 4], status: 'completed', subject: 'Public article title ' + i}));
            for (let i = 0; i < 1000; i++) summarizeChatActivity(items, false);
            const samples = [];
            for (let batch = 0; batch < 10; batch++) {
                const start = performance.now();
                for (let i = 0; i < 1000; i++) summarizeChatActivity(items, false);
                samples.push((performance.now() - start) / 1000);
            }
            return {mean_ms: samples.reduce((a,b) => a+b, 0) / samples.length, max_batch_ms: Math.max(...samples)};
        }""")
        assert timings["mean_ms"] < 1, timings
        assert not errors, errors
        print(f"PASS public-only activity, desktop/mobile and zero-request disclosure ({elapsed:.1f}ms); projection {timings}")
    finally:
        browser.close()
