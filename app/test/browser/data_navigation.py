"""Data navigation, task ordering and real loading-state layout in a browser."""

import json, os, re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
pending = []
hold = True
dataset = {
    "dataset_id": "data",
    "dataset_name": "细胞研究数据",
    "user_id": "owner",
    "can_delete": True,
    "data_type": "patch",
    "task_types": ["patch_classification"],
    "aggregation_level": "file",
    "source_organ": "Lung",
    "metadata": {},
    "revision": 1,
    "tasks": [],
    "is_public": False,
    "file_count": 100,
    "total_size": 1000,
    "has_predefined_splits": False,
}


def api(route):
    path = urlparse(route.request.url).path
    if path.endswith("/auth/me"):
        result = {
            "id": "owner",
            "username": "reviewer",
            "role": "pathologist",
            "is_active": True,
            "is_verified": True,
            "agreement_accepted_at": "2026-01-01",
            "notice_acknowledged_at": "2026-01-01",
        }
    elif path.endswith("/wsi/datasets"):
        if hold:
            pending.append(route)
            return
        result = {"items": [dataset], "total": 1}
    elif path.endswith("/dataset-source-options"):
        result = {"items": ["Lung"]}
    elif "maintenance" in path:
        result = {"active": False, "needs_acknowledgment": False}
    else:
        result = {
            "items": [],
            "total": 0,
            "tasks": [],
            "skills": [],
            "connectors": [],
            "elevated_dataset_ids": [],
            "gpu_dataset_ids": [],
        }
    route.fulfill(status=200, content_type="application/json", body=json.dumps(result))


def screenshot(page, name):
    if os.environ.get("VIEWER_SCREENSHOTS"):
        root = Path(os.environ["VIEWER_SCREENSHOTS"])
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / name))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
    page.add_init_script(
        "localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','zh-CN')"
    )
    page.goto(BASE + "/datasets", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="数据仓库", exact=True)).to_be_visible()
    expect(page.locator('[data-loading-layout="datasets"]')).to_be_visible()
    assert pending
    screenshot(page, "datasets-loading.png")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
    screenshot(page, "datasets-loading-mobile.png")
    page.emulate_media(reduced_motion="reduce")
    assert (
        page.locator(".loading-shape").first.evaluate(
            '(el)=>getComputedStyle(el,"::after").animationName'
        )
        == "none"
    )
    hold = False
    for route in pending:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"items": [dataset], "total": 1}),
        )
    expect(page.get_by_test_id("dataset-card-title")).to_have_text("细胞研究数据")
    expect(page.locator('[data-loading-layout="datasets"]')).to_have_count(0)
    page.set_viewport_size({"width": 1440, "height": 1000})
    task_filter = page.get_by_text("任务类型", exact=True).locator("..")
    assert task_filter.get_by_role("button").all_text_contents() == [
        "全部",
        "分类",
        "生存分析",
        "检测",
        "分割",
    ]
    assert "目标检测" not in page.locator("body").inner_text()
    if not page.get_by_role('navigation', name='Workbench').is_visible():
        page.get_by_role('button', name='打开侧边栏', exact=True).last.click()
    page.get_by_role("navigation", name="Workbench").get_by_role(
        "button", name="上传数据", exact=True
    ).click()
    page.wait_for_url("**/upload")
    expect(page.locator(".upload-task-options")).to_be_visible()
    assert page.locator(".upload-task-option strong").all_text_contents() == [
        "分类",
        "检测",
        "分割",
    ]
    screenshot(page, "upload-task-order.png")
    page.get_by_role("navigation", name="Workbench").get_by_role(
        "button", name="数据仓库", exact=True
    ).click()
    page.wait_for_url("**/datasets")
    expect(page.get_by_test_id("dataset-card-title")).to_be_visible()
    assert not errors, errors
    browser.close()
    print(
        "PASS /datasets and /upload, delayed-data skeleton, reduced motion, task order and navigation"
    )
