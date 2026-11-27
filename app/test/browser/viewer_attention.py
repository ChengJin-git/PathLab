"""Attention top/bottom thumbnails, task switching and click-to-focus in the real UI."""

import io
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")
image = Image.new("RGB", (1024, 768), "#efdee7")
draw = ImageDraw.Draw(image)
for x in range(35, 1000, 37):
    for y in range(24, 750, 41):
        draw.ellipse(
            (x, y, x + 12, y + 18), fill=("#93668e" if (x + y) % 3 else "#ab7e9d")
        )
buffer = io.BytesIO()
image.save(buffer, format="PNG")
requests = []
entries = [
    {
        "task_id": "task",
        "fold_key": fold,
        "task_name": name,
        "task_type": "wsi_classification",
        "data_type": "wsi",
        "has_heatmap": True,
        "prediction": "TME-associated",
        "probs": {"TME-associated": 0.602, "Tumor-intrinsic": 0.398},
        "classes": ["TME-associated", "Tumor-intrinsic"],
    }
    for fold, name in [("fold_0", "组织微环境分析"), ("fold_1", "第二组分析")]
]
patch_probs = {
    "Benign_eosinophil_granulocyte": 0,
    "Benign_lymphocyte": 0.000002,
    "Benign_mesothelial": 0.001,
    "Benign_neutrophil_granulocyte": 0,
    "Malignant_Determined": 0.673,
    "Malignant_Suspicious": 0.325998,
}
patch_entry = {
    "task_id": "patch-task",
    "fold_key": None,
    "task_name": "Ascites2020 腹水细胞分类_SmartCCS_人工参数",
    "task_type": "patch_classification",
    "data_type": "patch",
    "has_heatmap": True,
    "prediction": "Malignant_Determined",
    "probs": patch_probs,
    "classes": list(patch_probs),
}
seg_entry = {
    "task_id": "seg-task",
    "task_name": "CISD Cervical Cell Instance Segmentation-Smart-CCS-Agent-Expert",
    "task_type": "patch_segmentation",
    "data_type": "patch",
    "classes": ["SUPERFICIAL"],
    "class_colors": ["#e11d48"],
}
multi_seg_entry = {
    **seg_entry,
    "task_id": "multi-seg-task",
    "task_name": "细胞与细胞核分割",
    "classes": ["Cell", "Nucleus"],
    "class_colors": ["#e11d48", "#2563eb"],
}
det_entry = {
    "task_id": "det-task",
    "task_name": "细胞检测",
    "task_type": "patch_detection",
    "data_type": "patch",
    "classes": ["Cell", "Nucleus"],
    "class_colors": ["#e11d48", "#2563eb"],
}


def screenshot(page, name):
    if os.environ.get("VIEWER_SCREENSHOTS"):
        root = Path(os.environ["VIEWER_SCREENSHOTS"])
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / name))


def api(route):
    path = urlparse(route.request.url).path
    query = parse_qs(urlparse(route.request.url).query)
    requests.append((path, query))
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
        slide_id = path.split("/")[-2]
        result = {
            "wsi_id": slide_id,
            "name": "组织微环境切片.png",
            "dataset_id": "dataset",
            "dataset_name": "测试数据",
            "width": 1024,
            "height": 768,
            "data_type": "wsi" if slide_id == "attention" else "patch",
            "can_personal": True,
            "can_shared": True,
            "can_manage": True,
        }
    elif path.endswith("/available"):
        result = {
            "heatmaps": [
                patch_entry,
                {
                    **patch_entry,
                    "task_id": "patch-other",
                    "task_name": "第二组细胞分类",
                },
            ]
            if "/cytology/" in path
            else entries
        }
        if "/segmentation/" in path:
            result = {"heatmaps": [seg_entry, multi_seg_entry]}
        if "/detection/" in path:
            result = {"heatmaps": [det_entry]}
    elif path.endswith("/prediction"):
        item = (
            det_entry
            if "/detection/" in path
            else multi_seg_entry
            if query.get("task_id") == ["multi-seg-task"]
            else seg_entry
        )
        result = {**item, "class_names": item["classes"]}
        if "/detection/" in path:
            result["detection"] = {
                "prediction": {
                    "boxes": [[200, 200, 280, 280], [400, 400, 450, 450]],
                    "labels": [1, 2],
                    "scores": [0.95, 0.82],
                },
                "target": None,
            }
    elif path.endswith("/prediction_mask"):
        color = "#2563eb" if query.get("class_index") == ["1"] else "#e11d48"
        mask = Image.new("RGBA", (1024, 768))
        ImageDraw.Draw(mask).ellipse((200, 200, 350, 400), fill=color + "80")
        data = io.BytesIO()
        mask.save(data, format="PNG")
        route.fulfill(status=200, content_type="image/png", body=data.getvalue())
        return
    elif path.endswith("/info"):
        result = {"is_patch": True, "width": 1024, "height": 768}
    elif path.endswith("/data"):
        fold = query["fold_key"][0]
        shift = 0 if fold == "fold_0" else 12
        high = [
            {
                "index": index,
                "x": (index % 5) * 160 + shift,
                "y": (index // 5) * 160,
                "weight": 1,
                "raw_weight": 0.002641 - index * 0.000083,
            }
            for index in range(10)
        ]
        low = [
            {
                "index": 100 + index,
                "x": (index % 5) * 160 + shift,
                "y": 384 + (index // 5) * 128,
                "weight": 0,
                "raw_weight": 3.86e-8 + index * 0.142e-8,
            }
            for index in range(10)
        ]
        result = {
            "wsi_id": "attention",
            "task_id": "task",
            "fold_key": fold,
            "task_name": "Test",
            "patch_size": 128,
            "slide_width": 1024,
            "slide_height": 768,
            "num_patches": 400,
            "attention_min": low[0]["raw_weight"],
            "attention_max": high[0]["raw_weight"],
            "heatmap": high + low,
            "top_patches": high,
            "bottom_patches": low,
        }
    elif path.endswith("/patch_image"):
        x, y, size = (int(query[key][0]) for key in ["x", "y", "size"])
        assert size == 128 and query["thumbnail_size"] == ["160"]
        tile = image.crop((x, y, x + size, y + size))
        data = io.BytesIO()
        tile.save(data, format="PNG")
        route.fulfill(status=200, content_type="image/png", body=data.getvalue())
        return
    elif path.endswith(("/image", "/thumbnail", "/patch_cam")):
        route.fulfill(status=200, content_type="image/png", body=buffer.getvalue())
        return
    elif path.endswith("/regions"):
        result = {"items": [], "total": 0, "next_cursor": None}
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
    page.goto(BASE + "/wsi/attention")
    page.wait_for_load_state("networkidle")
    page.get_by_role("switch", name="注意力热图", exact=True).check()
    high = page.get_by_role("region", name="最高注意力", exact=True)
    low = page.get_by_role("region", name="最低注意力", exact=True)
    expect(high.get_by_role("button")).to_have_count(10)
    expect(low.get_by_role("button")).to_have_count(10)
    page.wait_for_function(
        'Array.from(document.querySelectorAll(".viewer-attention-patch img")).every(img=>img.complete&&img.naturalWidth>0)'
    )
    assert len(set(page.locator(".viewer-attention-score").all_text_contents())) == 20
    before = page.locator(".openseadragon-canvas canvas").first.evaluate(
        "(el)=>el.toDataURL()"
    )
    target = low.get_by_role("button", name="最低注意力 10", exact=True)
    target.click()
    expect(target).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        '(before)=>document.querySelector(".openseadragon-canvas canvas").toDataURL()!==before',
        arg=before,
    )
    # Changing folds clears the prior thumbnails; reopening uses the new result.
    page.get_by_role("button", name="选择分析结果", exact=True).click()
    page.get_by_role("option", name=re.compile("第二组分析.*第 1 折")).click()
    expect(page.locator(".viewer-attention-patch")).to_have_count(0)
    page.get_by_role("switch", name="注意力热图", exact=True).check()
    expect(high.get_by_role("button")).to_have_count(10)
    expect(high.get_by_role("button").first.locator("img")).to_have_attribute(
        "src", re.compile(r"x=12&")
    )
    assert any(
        path.endswith("/data") and query.get("fold_key") == ["fold_1"]
        for path, query in requests
    )
    high.get_by_role("button").first.focus()
    page.keyboard.press("Enter")
    expect(high.get_by_role("button").first).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".viewer-prediction-primary")).to_contain_text("60.2%")
    expect(page.get_by_text("TME-associated", exact=True)).to_have_count(1)
    opacity = page.get_by_role("slider", name="透明度", exact=True)
    opacity.focus()
    page.keyboard.press("ArrowRight")
    expect(opacity).to_have_attribute("aria-valuetext", "55%")
    screenshot(page, "results-wsi.png")
    for width, height in [(1440, 1000), (1024, 768), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        low.get_by_role("button").last.scroll_into_view_if_needed()
        expect(low.get_by_role("button").last).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        assert page.locator(".viewer-side").evaluate(
            "(el)=>el.scrollWidth<=el.clientWidth+1"
        )
        screenshot(page, f"attention-{width}.png")
    # Multi-class patch results use the same inspector, with progressive disclosure.
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(BASE + "/wsi/cytology")
    page.wait_for_load_state("networkidle")
    expect(
        page.get_by_role("heading", name="Malignant Determined", exact=True)
    ).to_be_visible()
    expect(
        page.get_by_role("list", name="其他类别概率").get_by_role("listitem")
    ).to_have_count(1)
    expect(page.get_by_role("list", name="其余类别")).to_have_count(0)
    screenshot(page, "results-patch-collapsed.png")
    page.get_by_role("button", name=re.compile("展开其余 4 类")).click()
    expect(
        page.get_by_role("list", name="其余类别").get_by_role("listitem")
    ).to_have_count(4)
    expect(page.get_by_text("<0.1%", exact=True)).to_be_visible()
    for width, height in [(1440, 1000), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.locator(".viewer-side").evaluate(
            "(el)=>el.scrollWidth<=el.clientWidth+1"
        )
        screenshot(page, f"results-patch-expanded-{width}.png")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("switch", name="注意力热图", exact=True).check()
    expect(page.locator("#viewer-result-image")).to_have_count(1)
    expect(page.get_by_role("slider", name="透明度", exact=True)).to_be_visible()
    assert not any(
        path.endswith("/prediction") and "/cytology/" in path for path, _ in requests
    )
    page.get_by_role("button", name="选择分析结果", exact=True).click()
    page.get_by_role("option", name=re.compile("第二组细胞分类")).click()
    expect(page.get_by_role("list", name="其余类别")).to_have_count(0)
    expect(
        page.get_by_role("switch", name="注意力热图", exact=True)
    ).not_to_be_checked()
    page.goto(BASE + "/wsi/segmentation")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("radio", name="SUPERFICIAL", exact=True)).to_be_checked()
    expect(page.get_by_text("SUPERFICIAL", exact=True)).to_be_visible()
    page.get_by_role("switch", name="分割图层", exact=True).check()
    expect(page.locator("#viewer-result-image")).to_have_attribute(
        "src", re.compile(r"class_index=0")
    )
    screenshot(page, "results-segmentation-single.png")
    page.get_by_role("button", name="选择分析结果", exact=True).click()
    page.get_by_role("option", name=re.compile("细胞与细胞核分割")).click()
    page.get_by_role("radio", name="Nucleus", exact=True).check()
    expect(page.locator("#viewer-result-image")).to_have_attribute(
        "src", re.compile(r"class_index=1")
    )
    expect(page.get_by_role("radio", name="Nucleus", exact=True)).to_be_checked()
    page.goto(BASE + "/wsi/detection")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("checkbox", name="Cell", exact=True)).to_be_checked()
    page.get_by_role("switch", name="检测框", exact=True).check()
    expect(page.locator('[data-result-class="0"]')).to_have_count(1)
    expect(page.locator('[data-result-class="1"]')).to_have_count(1)
    expect(page.get_by_role("button", name="Cell 0.95", exact=True)).to_be_visible()
    screenshot(page, "results-detection-classes.png")
    page.get_by_role("checkbox", name="Cell", exact=True).uncheck()
    expect(page.locator('[data-result-class="0"]')).to_have_count(0)
    expect(page.locator('[data-result-class="1"]')).to_have_count(1)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.locator(".viewer-side").evaluate(
        "(el)=>el.scrollWidth<=el.clientWidth+1"
    )
    screenshot(page, "results-detection-mobile.png")
    assert not errors, errors
    browser.close()
    print(
        "PASS result hierarchy, probability disclosure, layer controls, top/bottom thumbnails and responsive layout"
    )
