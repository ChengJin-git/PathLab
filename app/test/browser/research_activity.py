"""Long autonomous progress stays bounded and localized in Chat and task details."""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
CHAT, SESSION = "progress-chat", "progress-study"
descriptions = ["核查疗效队列的患者数量与临床终点", "核查邻域状态证据的空间负对照", "核查公开数据是否包含可复用的细胞表"]
activity = [{"kind": "message", "seq": 1, "message": {"id": "intro", "type": "assistant", "text": "我会核查原文证据和公开数据的实际可用性。"}}]
activity += [{"kind": "message", "seq": index + 2, "message": {
    "id": f"step-{index}", "type": "assistant", "content": [{"type": "activity", "id": f"a-{index}",
        "action": "search_literature" if index % 2 else "read_source", "description": descriptions[index % 3],
        "status": "completed" if index < 59 else "running", "language": "zh-CN"}],
}} for index in range(60)]
activity.append({"kind": "native_work", "seq": 63, "status": "running", "action": "work",
                 "description": "核查公开数据资源", "language": "zh-CN"})
session = {"session_id": SESSION, "chat_conversation_id": CHAT, "title": "空间蛋白组证据核查", "question": "核查公开证据", "status": "running",
           "task_kind": "document", "created_at": time.time() - 600, "updated_at": time.time(), "sequence": 63,
           "activity": activity, "events": [], "jobs": [], "experiments": [], "state": {"plan": []}}
chat = {"conversation_id": CHAT, "user_id": "owner", "workspace_id": None, "title": "公开证据核查", "pinned": False,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "messages": [{"id": 1, "role": "user", "content": "核查疗效与邻域证据，确认公开数据可用。", "created_at": "2026-01-01T00:00:00Z"}]}
requests = []


def api(route):
    path = urlparse(route.request.url).path
    requests.append(path)
    if path.endswith("/auth/me"):
        result = {"id": "owner", "username": "reviewer", "role": "admin", "is_active": True,
                  "is_verified": True, "agreement_accepted_at": "2026-01-01", "notice_acknowledged_at": "2026-01-01"}
    elif path.endswith("/stream") or path.endswith("/events"):
        route.fulfill(status=200, content_type="text/event-stream", body='data: {"kind":"heartbeat","items":[],"tasks":[]}\n\n')
        return
    elif path.endswith("/access-token"):
        result = {"token": "fixture"}
    elif path.endswith("/chat-navigation/chats"):
        result = {"items": [chat], "next_cursor": None}
    elif path.endswith("/research-statuses"):
        result = {"states": {CHAT: "running"}, "file_conversations": []}
    elif path.endswith(f"/conversations/{CHAT}/research"):
        result = {"items": [session]}
    elif path.endswith(f"/conversations/{CHAT}"):
        result = chat
    elif path.endswith("/conversations"):
        result = {"conversations": [chat], "total": 1}
    elif path.endswith(f"/sessions/{SESSION}"):
        result = session
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
        process = page.locator("[data-research-process]")
        toggle = process.get_by_role("button", name="执行过程", exact=True)
        expect(toggle).to_contain_text(descriptions[2])
        expect(toggle).not_to_contain_text(descriptions[0])
        assert toggle.bounding_box()["height"] == 44
        before = len(requests)
        elapsed = toggle.evaluate("""async button => {
            const start = performance.now(); button.click();
            await new Promise(requestAnimationFrame);
            if (!button.parentElement.querySelector('ol')) throw new Error('Disclosure delayed');
            return performance.now() - start;
        }""")
        expect(process.get_by_role("listitem")).to_have_count(20)
        assert len(requests) == before
        assert elapsed < 150, elapsed
        process.get_by_role("button", name="查看更早的 40 项进展", exact=True).click()
        expect(process.get_by_role("listitem")).to_have_count(60)
        assert " · " not in process.inner_text()
        assert "步骤详情" not in process.inner_text()
        if os.environ.get("VIEWER_SCREENSHOTS"):
            root = Path(os.environ["VIEWER_SCREENSHOTS"])
            root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(root / "research-progress.png"), animations="disabled")
        # A running action becomes longer; neither its count nor topic accumulates.
        activity[-2]["message"]["content"][0]["description"] = "核查患者级划分及外部验证队列是否存在预训练数据重叠，整理临床终点与公开资源的可访问性"
        expect(toggle).to_contain_text("核查患者级划分", timeout=20000)
        assert toggle.bounding_box()["height"] == 44
        assert toggle.evaluate("el => el.scrollWidth <= el.clientWidth")
        page.get_by_role("button", name="Language", exact=True).click()
        page.get_by_role("button", name="English", exact=True).click()
        expect(process.get_by_role("button", name="Execution process", exact=True)).to_contain_text("Find published evidence")
        assert "核查" not in process.inner_text()
        page.get_by_role("button", name="Language", exact=True).click()
        page.get_by_role("button", name="繁體中文", exact=True).click()
        expect(process.get_by_role("button", name="執行過程", exact=True)).to_contain_text("查找文獻證據")
        for width in (375, 768):
            page.set_viewport_size({"width": width, "height": 900})
            assert process.evaluate("el => el.scrollWidth <= el.clientWidth"), f"Overflow at {width}"
            assert process.get_by_role("button", name="執行過程", exact=True).bounding_box()["height"] == 44
        page.get_by_test_id("chat-task-toolbar").get_by_role("link", name="展開詳情", exact=True).click()
        expect(page.get_by_test_id("research-details").get_by_role("button", name="執行過程", exact=True)).to_contain_text("查找文獻證據")
        timings = page.evaluate("""async () => {
            const {researchProgress} = await import('/src/components/autoresearch/researchProgress.ts');
            const events = Array.from({length: 500}, (_, i) => ({kind: 'message', message: {id: String(i), content: [{type: 'activity', action: 'read_source', status: 'completed', description: '核查公开数据'}]}}));
            for (let i=0; i<100; i++) researchProgress(events, true);
            const start = performance.now();
            for (let i=0; i<1000; i++) researchProgress(events, true);
            return (performance.now()-start)/1000;
        }""")
        assert timings < 5, timings
        assert not errors, errors
        print(f"PASS long research progress, three locales, shared details and bounded mobile header; disclosure {elapsed:.1f}ms, 500-action projection {timings:.3f}ms")
    finally:
        browser.close()
