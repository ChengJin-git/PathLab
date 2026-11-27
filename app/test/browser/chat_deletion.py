"""Optimistic chat deletion, concurrent rollback and quiet cleanup in a browser."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
pending = {}
chats = [
    {
        "conversation_id": identity,
        "user_id": "owner",
        "workspace_id": None,
        "title": title,
        "folder_id": None,
        "folder_name": None,
        "pinned": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    for identity, title in [("first", "第一段对话"), ("second", "第二段对话")]
]


def api(route):
    url = urlparse(route.request.url)
    path = url.path
    if path.endswith("/auth/me"):
        result = {
            "id": "owner", "username": "reviewer", "role": "pathologist",
            "is_active": True, "is_verified": True,
            "agreement_accepted_at": "2026-01-01",
            "notice_acknowledged_at": "2026-01-01",
        }
    elif path.endswith("/stream"):
        items = []
        if path.endswith("/storage/tasks/stream"):
            items = [
                {
                    "task_id": "internal", "task_type": "chat_delete",
                    "status": "processing", "progress": 0,
                },
                {
                    "task_id": "visible", "task_type": "batch_update_metadata",
                    "status": "processing", "progress": 20,
                },
            ]
        route.fulfill(
            status=200, content_type="text/event-stream",
            body="data: " + json.dumps({"items": items, "tasks": []}) + "\n\n",
        )
        return
    elif path.endswith("/chat-navigation/chats"):
        query = parse_qs(url.query).get("q", [""])[0]
        result = {"items": [chat for chat in chats if query in chat["title"]], "next_cursor": None}
    elif path.endswith("/research-statuses"):
        result = {"states": {}, "file_conversations": []}
    elif "/conversations/" in path and route.request.method == "DELETE":
        pending[path.rsplit("/", 1)[-1]] = route
        return
    elif "maintenance" in path:
        result = {"active": False, "needs_acknowledgment": False}
    else:
        result = {
            "items": [], "total": 0, "next_cursor": None,
            "tasks": [], "skills": [], "connectors": [],
            "elevated_dataset_ids": [], "gpu_dataset_ids": [],
        }
    route.fulfill(status=200, content_type="application/json", body=json.dumps(result))


def remove(page, title):
    page.get_by_role("button", name="聊天选项: " + title, exact=True).click()
    page.get_by_role("menuitem", name="删除聊天", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="删除聊天", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name=title, exact=True)).to_have_count(0)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
        page.add_init_script(
            "localStorage.setItem('pathlab_auth_token','fixture');"
            "localStorage.setItem('i18nextLng','zh-CN')"
        )
        page.goto(BASE + "/datasets")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("button", name="第一段对话", exact=True)).to_be_visible()

        # The pending DELETE stays unresolved while the UI immediately removes each row.
        remove(page, "第一段对话")
        remove(page, "第二段对话")
        assert set(pending) == {"first", "second"}
        expect(page).to_have_url(BASE + "/datasets")
        search = page.get_by_role("textbox", name="搜索聊天…", exact=True)
        with page.expect_response(lambda response: "/chat-navigation/chats?" in response.url and "q=" in response.url):
            search.fill("对话")
        expect(page.get_by_role("button", name="第一段对话", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="第二段对话", exact=True)).to_have_count(0)

        # One failure must restore only that chat, including after list refetches.
        pending.pop("second").fulfill(status=503, json={"detail": "Temporary failure"})
        expect(page.get_by_role("button", name="第二段对话", exact=True)).to_be_visible()
        expect(page.get_by_role("alert")).to_have_text("未能删除此对话，已恢复到列表，请重试。")
        expect(page.get_by_role("button", name="第一段对话", exact=True)).to_have_count(0)
        chats[:] = [chat for chat in chats if chat["conversation_id"] != "first"]
        pending.pop("first").fulfill(status=200, json={"conversation_id": "first", "status": "deleted"})

        progress = page.get_by_role("button", name="后台进度", exact=True)
        expect(progress).to_have_text("后台进度1")
        progress.click()
        expect(page.get_by_text("元数据更新", exact=True).first).to_be_visible()
        assert "Conversation cleanup" not in page.locator("body").inner_text()
        assert "清理对话" not in page.locator("body").inner_text()

        # Locale changes update the live storage task, not just its type badge.
        page.get_by_role("button", name="Language", exact=True).click()
        page.get_by_role("button", name="English", exact=True).click()
        page.get_by_role("button", name="Background progress", exact=True).click()
        expect(page.get_by_text("Metadata Update", exact=True).first).to_be_visible()
        assert "Conversation cleanup" not in page.locator("body").inner_text()
        assert "Conversation & experiment cleanup" not in page.locator("body").inner_text()

        if os.environ.get("VIEWER_SCREENSHOTS"):
            root = Path(os.environ["VIEWER_SCREENSHOTS"])
            root.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(root / "chat-deletion-progress.png"))
        assert not errors, errors
        print("PASS immediate deletion, concurrent rollback, stale lists, quiet cleanup and live i18n")
    finally:
        browser.close()
