"""Browser regression for the viewer. Run against Vite with VITE_API_BASE=/api.

Dependencies: playwright, Pillow. Example:
  VIEWER_URL=http://127.0.0.1:5189 python test/browser/viewer_workspace.py
"""

import io
import json
import os
import re
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
image = Image.new("RGB", (1024, 768), "#ecd6e3")
draw = ImageDraw.Draw(image)
for x in range(50, 1000, 80):
    for y in range(40, 740, 70):
        draw.ellipse((x, y, x + 28, y + 40), fill="#93668e")
buffer = io.BytesIO()
image.save(buffer, format="PNG")
regions = {"personal": {}, "shared": {}}


def api(route):
    request = route.request
    path = urlparse(request.url).path
    query = parse_qs(urlparse(request.url).query)
    body = request.post_data_json if request.method == "POST" else {}
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
    elif path.endswith("/context"):
        result = {
            "wsi_id": "slide",
            "name": "测试切片.png",
            "dataset_id": "dataset",
            "dataset_name": "测试数据集",
            "width": 1024,
            "height": 768,
            "data_type": "patch",
            "can_personal": True,
            "can_shared": True,
            "can_manage": True,
        }
    elif path.endswith("/capabilities"):
        result = {"features": [], "prompt_models": []}
    elif path.endswith("/regions/selection"):
        items = [
            regions[body["layer"]][id]
            for id in body["ids"]
            if id in regions[body["layer"]]
        ]
        result = {
            "items": [r for r in items if not r.get("deleted")],
            "revisions": {r["id"]: r["revision"] for r in items},
        }
    elif path.endswith("/regions"):
        layer = body.get("layer", query.get("layer", ["personal"])[0])
        if request.method == "POST":
            changes = []
            for change in body["changes"]:
                old = regions[layer].get(change["id"])
                revision = (old or {}).get("revision", 0) + 1
                value = (
                    {
                        **change["value"],
                        "id": change["id"],
                        "revision": revision,
                        "layer": layer,
                    }
                    if change["value"]
                    else None
                )
                regions[layer][change["id"]] = value or {
                    "id": change["id"],
                    "deleted": True,
                    "revision": revision,
                }
                changes.append(
                    {"id": change["id"], "revision": revision, "value": value}
                )
            result = {"operation_id": body["operation_id"], "changes": changes}
        else:
            items = sorted(
                [r for r in regions[layer].values() if not r.get("deleted")],
                key=lambda r: r["id"],
            )
            after = query.get("after", [""])[0]
            limit = int(query.get("limit", ["50"])[0])
            remaining = [r for r in items if r["id"] > after]
            result = {
                "items": remaining[:limit],
                "total": len(items),
                "next_cursor": remaining[limit - 1]["id"]
                if len(remaining) > limit
                else None,
            }
    elif path.endswith("/events"):
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body='data: {"type":"keepalive"}\n\n',
        )
        return
    elif path.endswith("/assistant"):
        result = {
            "action": "handoff",
            "reason": "complex_request",
            "message": "这个需求适合回到主页面继续分析，我会带上当前切片和你的问题。",
            "regions": [],
        }
    elif path.endswith("/available"):
        result = {"heatmaps": []}
    elif path.endswith("/info"):
        result = {"is_patch": True, "width": 1024, "height": 768}
    elif path.endswith(("/image", "/thumbnail", "/patch_file")):
        route.fulfill(status=200, content_type="image/png", body=buffer.getvalue())
        return
    elif path.endswith("/labels"):
        result = {"annotations": {}, "record_count": 0}
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


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
    page.add_init_script(
        "localStorage.setItem('pathlab_auth_token','fixture');localStorage.setItem('i18nextLng','zh-CN')"
    )
    page.goto(BASE + "/wsi/slide")
    page.wait_for_load_state("networkidle")
    for width, height in [(1440, 1000), (1024, 768), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert (
            abs(page.locator(".viewer-workspace").bounding_box()["height"] - height) < 2
        )
        assert page.evaluate("document.documentElement.scrollHeight<=innerHeight+1")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("tab", name="标注", exact=True).click()
    expect(page.get_by_role("toolbar", name="切片工具")).to_have_count(1)
    expect(page.get_by_role("button", name="放大", exact=True)).to_have_count(1)
    # The larger controls wrap within the canvas when the inspector narrows it.
    for width, height in [(1024, 768), (768, 900), (390, 844), (320, 740)]:
        page.set_viewport_size({"width": width, "height": height})
        if width <= 640:
            page.get_by_role("button", name="收起阅片面板", exact=True).click()
        toolbar = page.get_by_role("toolbar", name="切片工具")
        assert toolbar.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        box = toolbar.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        page.get_by_role("button", name="放大", exact=True).click()
        if width <= 640:
            page.locator('.viewer-topbar button[aria-controls="slide-inspector"]').click()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="适合窗口", exact=True).click()
    page.get_by_role("button", name="框选一个区域", exact=True).click()
    box = page.locator(".viewer-slide > canvas").bounding_box()
    page.mouse.move(box["x"] + 300, box["y"] + 250)
    page.mouse.down()
    page.mouse.move(box["x"] + 500, box["y"] + 400, steps=8)
    page.mouse.up()
    expect(
        page.get_by_role("button", name="删除标注 未分类", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="撤销", exact=True).click()
    expect(page.get_by_text("从一处感兴趣的区域开始", exact=True)).to_be_visible()
    page.get_by_role("button", name="重做", exact=True).click()
    page.get_by_role("button", name="操作", exact=True).click()
    page.get_by_role("menuitem", name="将所选发布到团队", exact=True).click()
    expect(page.get_by_role("button", name="标注", exact=True)).to_contain_text(
        "团队标注"
    )
    page.get_by_role("button", name="删除标注 未分类", exact=True).click()
    expect(
        page.get_by_role("button", name="删除标注 未分类", exact=True)
    ).to_have_count(0)
    before = page.locator(".openseadragon-canvas canvas").evaluate(
        "(element)=>element.toDataURL()"
    )
    page.mouse.move(box["x"] + 550, box["y"] + 400)
    page.mouse.wheel(0, -180)
    page.wait_for_function(
        '(before)=>document.querySelector(".openseadragon-canvas canvas").toDataURL()!==before',
        arg=before,
    )
    for index in range(120):
        regions["shared"][f"page-{index:04}"] = {
            "id": f"page-{index:04}",
            "revision": 1,
            "type": "rect",
            "x": 10 + index,
            "y": 20,
            "width": 10,
            "height": 10,
            "label": f"标注 {index:03}",
            "color": "#6366f1",
        }
    page.get_by_role("button", name="标注", exact=True).click()
    page.get_by_role("option", name="我的标注", exact=True).click()
    page.get_by_role("button", name="标注", exact=True).click()
    page.get_by_role("option", name="团队标注", exact=True).click()
    expect(page.get_by_role("button", name=re.compile("^删除标注 标注"))).to_have_count(
        50
    )
    page.get_by_role("button", name="下一页", exact=True).click()
    expect(
        page.get_by_role("button", name="删除标注 标注 050", exact=True)
    ).to_be_visible()
    page.get_by_role("tab", name="阅片助手", exact=True).click()
    page.get_by_role("textbox", name="想找哪里，或分析什么？").fill(
        "比较整个数据集并生成报告"
    )
    page.get_by_role("button", name="发送", exact=True).click()
    expect(
        page.get_by_text(
            "这个需求适合回到主页面继续分析，我会带上当前切片和你的问题。", exact=True
        )
    ).to_be_visible()
    page.evaluate(
        "() => { const push=history.pushState.bind(history);history.pushState=(state,...rest)=>{window.__handoff=state;return push(state,...rest)} }"
    )
    page.get_by_role("button", name="返回主页面继续", exact=True).click()
    page.wait_for_url("**/dashboard")
    state = page.evaluate("window.__handoff.usr")
    assert "比较整个数据集并生成报告" in state["toolDraft"]
    assert {"kind": "slide", "id": "slide"} in state["references"]
    assert not errors, errors
    browser.close()
    print("PASS viewer browser interaction and contextual handoff")
