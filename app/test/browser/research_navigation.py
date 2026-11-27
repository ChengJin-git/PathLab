"""Research navigation stays reachable while the real Chat follows a growing timeline."""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
CHAT = "research-navigation"
SESSION = "review-spatial"
session = {
    "session_id": SESSION, "chat_conversation_id": CHAT,
    "title": "Spatial proteomics · 跨队列证据审查",
    "question": "核查空间蛋白组基础模型的公开验证证据与研究方向。",
    "status": "running", "task_kind": "document", "sequence": 40,
    "created_at": time.time() - 38652, "updated_at": time.time(),
    "current_iteration": 0, "max_iterations": 0, "events": [], "jobs": [], "experiments": [],
    "state": {"research_phase": "planning", "plan": [
        {"id": "sources", "title": "核查原文与公开代码", "status": "completed", "phase": "ideation"},
        {"id": "evidence", "title": "建立跨 panel 与独立队列证据矩阵", "status": "running", "phase": "planning"},
        {"id": "report", "title": "整理研究路线和验证方案", "status": "pending", "phase": "writing"},
    ]},
    "activity": [
        {"kind": "message", "seq": index + 1, "message": {
            "id": f"finding-{index}", "type": "assistant",
            "text": f"### 第 {index + 1} 轮核查\n\n" + "结合原文核对输入模态、预训练队列和公开验证数据，区分作者主张与已验证证据。" * 4,
        }} for index in range(40)
    ],
}
chat = {
    "conversation_id": CHAT, "user_id": "owner", "workspace_id": None,
    "title": "SP foundation model review", "pinned": False, "folder_id": None,
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    "messages": [{"id": 1, "role": "user", "content": "请核查文献并完成研究报告。", "created_at": "2026-01-01T00:00:00Z"}],
}


def api(route):
    path = urlparse(route.request.url).path
    if path.endswith("/auth/me"):
        result = {"id": "owner", "username": "reviewer", "role": "admin", "is_active": True,
                  "is_verified": True, "agreement_accepted_at": "2026-01-01", "notice_acknowledged_at": "2026-01-01"}
    elif path.endswith("/events") or path.endswith("/stream"):
        route.fulfill(status=200, content_type="text/event-stream", body='data: {"kind":"heartbeat","items":[],"tasks":[]}\n\n')
        return
    elif path.endswith("/access-token"):
        result = {"token": "fixture"}
    elif path.endswith("/chat-navigation/chats"):
        result = {"items": [chat], "next_cursor": None}
    elif path.endswith("/research-statuses"):
        result = {"states": {CHAT: session["status"]}, "file_conversations": []}
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


def at_bottom(page):
    page.wait_for_function("""() => {
        const el = document.querySelector('[data-chat-messages-container]');
        return el && el.scrollHeight > el.clientHeight * 2 && el.scrollHeight - el.scrollTop - el.clientHeight < 5;
    }""")


def screenshot(page, name):
    if os.environ.get("VIEWER_SCREENSHOTS"):
        root = Path(os.environ["VIEWER_SCREENSHOTS"])
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / name), animations="disabled")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
        page.add_init_script("localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','zh-CN')")
        page.goto(BASE + f"/dashboard/{CHAT}")
        page.wait_for_load_state("networkidle")
        toolbar = page.get_by_test_id("chat-task-toolbar")
        details = toolbar.get_by_role("button", name="任务详情", exact=True)
        expand = toolbar.get_by_role("link", name="展开详情", exact=True)
        expect(details).to_be_visible()
        at_bottom(page)
        expect(details).to_be_in_viewport()
        expect(expand).to_be_in_viewport()
        screenshot(page, "research-chat-bottom.png")

        # A new API snapshot grows the real timeline; automatic following must survive.
        session["activity"].append({"kind": "message", "seq": 41, "message": {
            "id": "new-evidence", "type": "assistant", "text": "### 新的核查结果\n\n" + "\n\n".join([
                "**数据隔离。** 逐项核对研究、患者和切片级的训练测试边界，记录外部验证队列与预训练数据的重叠情况。",
                "**跨 panel 泛化。** 区分在同一数据集上随机遮蔽蛋白与在真实不同 panel 队列上的迁移，分别整理证据。",
                "**空间上下文。** 对比仅使用细胞表达的基线，核查空间位置打乱、邻域置换与组成控制后的增量价值。",
                "**公开验证资源。** 列出来源、矩阵和坐标的可用性，标记缺少患者标签或需要申请访问的数据。",
                "**下一步。** 汇总已核实的结论、证据限制和待验证方向，形成可用于选题的完整报告。",
            ]),
        }})
        session["sequence"] = 41
        expect(page.get_by_role("heading", name="新的核查结果")).to_be_visible(timeout=20000)
        at_bottom(page)
        details.click()
        panel = page.get_by_role("complementary", name="任务详情", exact=True)
        expect(panel).to_be_visible()
        expect(panel.get_by_text("建立跨 panel 与独立队列证据矩阵", exact=True)).to_be_visible()
        at_bottom(page)
        panel.get_by_role("button", name="结果", exact=True).click()
        expect(panel.get_by_role("button", name="结果", exact=True)).to_have_attribute("aria-pressed", "true")
        panel.get_by_role("button", name="任务计划", exact=True).click()
        screenshot(page, "research-inspector.png")
        page.keyboard.press("Escape")
        expect(panel).to_have_count(0)
        expect(details).to_be_focused()
        at_bottom(page)

        # The persistent link opens the full page directly, without scrolling the chat.
        expand.click()
        expect(page).to_have_url(BASE + f"/autoresearch/sessions/{SESSION}")
        expect(page.get_by_test_id("research-outline")).to_be_visible()
        expect(page.get_by_test_id("research-current-work")).to_contain_text("建立跨 panel 与独立队列证据矩阵")
        expect(page.get_by_role("navigation", name="总体进程", exact=True)).to_have_count(0)
        expect(page.get_by_text(re.compile(r"已用时 10小时 44分钟(?: 5[0-9]秒)?"))).to_be_visible()
        expect(page.get_by_role("tab", name="实验", exact=True)).to_have_count(0)
        expect(page.get_by_role("tab", name="原始日志", exact=True)).to_have_count(0)
        screenshot(page, "research-details.png")
        page.get_by_role("link", name="返回原对话", exact=True).click()
        at_bottom(page)
        details.click()
        toolbar.get_by_role("button", name="会话文件", exact=True).click()
        expect(panel).to_have_count(0)
        details.click()
        expect(panel).to_be_visible()
        expect(page.get_by_role("button", name="关闭文件预览", exact=True)).to_have_count(0)

        # Start a fresh mobile view to cover the sidebar's responsive default.
        mobile = browser.new_page(viewport={"width": 375, "height": 812})
        mobile.on("pageerror", lambda error: errors.append(str(error)))
        mobile.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
        mobile.add_init_script("localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','zh-CN');localStorage.setItem('pwa-install-dismissed', String(Date.now()))")
        mobile.goto(BASE + f"/dashboard/{CHAT}")
        mobile.wait_for_load_state("networkidle")
        at_bottom(mobile)
        mobile_toolbar = mobile.get_by_test_id("chat-task-toolbar")
        expect(mobile_toolbar.get_by_role("link", name="展开详情", exact=True)).to_be_in_viewport()
        screenshot(mobile, "research-chat-mobile.png")
        mobile_toolbar.get_by_role("button", name="任务详情", exact=True).click()
        mobile_panel = mobile.get_by_role("complementary", name="任务详情", exact=True)
        expect(mobile_panel).to_be_visible()
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
        screenshot(mobile, "research-inspector-mobile.png")
        mobile_panel.get_by_role("button", name="关闭", exact=True).click()
        at_bottom(mobile)
        mobile.get_by_role("button", name="Language", exact=True).click()
        mobile.get_by_role("button", name="English", exact=True).click()
        for width in (375, 768, 1024):
            mobile.set_viewport_size({"width": width, "height": 900})
            expect(mobile_toolbar.get_by_role("link", name="Expand details", exact=True)).to_be_in_viewport()
            mobile_toolbar.get_by_role("button", name="Task details", exact=True).click()
            english_panel = mobile.get_by_role("complementary", name="Task details", exact=True)
            expect(english_panel.get_by_role("button", name="Close", exact=True)).to_be_in_viewport()
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}px"
            english_panel.get_by_role("button", name="Close", exact=True).click()
        mobile.set_viewport_size({"width": 375, "height": 812})
        mobile_toolbar.get_by_role("link", name="Expand details", exact=True).click()
        expect(mobile.get_by_test_id("research-outline")).to_be_visible()
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Full-page mobile overflow"
        mobile.get_by_role("button", name="Language", exact=True).click()
        mobile.get_by_role("button", name="繁體中文", exact=True).click()
        expect(mobile.get_by_role("heading", name="任務計劃", exact=True)).to_be_visible()
        session["status"] = "completed"
        for step in session["state"]["plan"]:
            step["status"] = "completed"
        expect(mobile.get_by_role("button", name="繼續任務", exact=True)).to_be_visible()
        expect(mobile.get_by_role("spinbutton")).to_have_count(0)
        expect(mobile.get_by_role("combobox", name="Starting point", exact=True)).to_have_count(0)
        mobile.get_by_role("tab", name="詳情", exact=True).click()
        screenshot(mobile, "research-document-mobile.png")
        assert not errors, errors
        print("PASS persistent research navigation, auto-follow, inspector controls, page return and mobile layout")
    finally:
        browser.close()
