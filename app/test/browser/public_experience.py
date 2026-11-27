"""Public-page interaction checks. Run with VITE_API_BASE=/api and Playwright."""
import json
import os
import re
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("VIEWER_URL", "http://127.0.0.1:5189")


def api(route):
    path = route.request.url
    if "/auth/me" in path:
        data = {"is_logged_in": False}
    elif "/settings/public" in path:
        data = {"captcha_provider": "turnstile", "captcha_site_key": "fixture"}
    else:
        data = {"active": False, "items": [], "total": 0}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(re.compile("^" + re.escape(BASE) + "/api/"), api)
    page.add_init_script("""(() => {
      if (!localStorage.getItem('i18nextLng')) localStorage.setItem('i18nextLng', 'zh-CN');
      localStorage.setItem('pwa-install-dismissed', Date.now().toString());
      window.turnstile = {
        render(element) {
          const box = document.createElement('div');
          box.style.height = '65px';
          box.textContent = 'Verification';
          element.append(box);
          return 'fixture';
        }, remove() {}, reset() {}
      };
    })()""")
    page.goto(BASE + "/")
    page.wait_for_load_state("networkidle")

    flow = page.locator(".public-workflow__preview")
    flow.scroll_into_view_if_needed()
    expect(flow).to_have_attribute("data-playing", "true")
    expect(page.locator(".workflow-preview--research")).to_be_visible(timeout=10000)
    page.locator(".workflow-playback").click()
    expect(flow).to_have_attribute("data-playing", "false")

    agent = page.locator(".agent-research-demo")
    agent.scroll_into_view_if_needed()
    expect(agent).to_have_attribute("data-playing", "true")
    expect(agent.locator(".agent-execution-preview")).to_be_visible(timeout=10000)
    agent.get_by_role("button", name="暂停演示", exact=True).click()
    expect(agent).to_have_attribute("data-playing", "false")
    agent.get_by_role("button", name="生成报告", exact=True).click()
    expect(agent.locator(".research-report-preview")).to_be_visible()
    expect(agent.locator("img").first).to_have_attribute("src", re.compile("bot_avatar"))
    agent.get_by_role("button", name="播放流程", exact=True).click()
    page.evaluate("window.scrollTo(0,0)")
    expect(agent).to_have_attribute("data-playing", "false")

    source = page.get_by_role("button", name="查看引用原文", exact=True)
    source.click()
    expect(page.locator(".knowledge-preview__source")).to_contain_text("每位患者仅分配到一个分区")
    source.click()
    expect(page.locator(".knowledge-preview__source")).to_have_count(0)

    comparison = page.locator(".tissue-comparison")
    comparison.scroll_into_view_if_needed()
    before = comparison.locator("figure").last.locator(".tissue-image")
    expect(before).to_have_class(re.compile("is-annotated"))
    comparison.get_by_role("button", name="示例标注", exact=True).click()
    expect(before).not_to_have_class(re.compile("is-annotated"))

    page.emulate_media(reduced_motion="reduce")
    agent.scroll_into_view_if_needed()
    expect(agent).to_have_attribute("data-playing", "false")
    expect(agent.locator(".agent-research-demo__heading button")).to_have_count(0)
    agent.get_by_role("button", name="制定计划", exact=True).click()
    expect(agent.locator(".agent-plan-preview")).to_be_visible()

    for language in ["en-US", "zh-CN", "zh-HK"]:
        page.evaluate("language => localStorage.setItem('i18nextLng', language)", language)
        for width in [375, 1024, 1440]:
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(BASE + "/")
            page.wait_for_load_state("networkidle")
            agent.scroll_into_view_if_needed()
            heights = []
            for index in range(3):
                agent.locator(".agent-research-demo__steps button").nth(index).click()
                heights.append(agent.bounding_box()["height"])
                assert agent.locator(".agent-research-demo__body").evaluate("""el => {
                    const active = el.querySelector('.is-active').getBoundingClientRect();
                    const bounds = el.getBoundingClientRect();
                    return getComputedStyle(el).overflowY === 'clip'
                      && active.bottom <= bounds.bottom + 1
                      && el.scrollWidth <= el.clientWidth + 1;
                }"""), (language, width, index)
            assert max(heights) - min(heights) < 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        # Reload gets the explicit language from localStorage; no token is stored.
        for width, height in [(1366, 768), (1280, 720), (375, 667), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(BASE + "/login")
            page.wait_for_load_state("networkidle")
            assert page.locator(".public-login").evaluate(
                "el => el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1"
            ), (language, width, height)
            assert page.locator(".login-access__footer").evaluate(
                "el => el.getBoundingClientRect().bottom <= innerHeight + 1"
            )
    assert not errors, errors
    browser.close()
    print("PASS public autoplay, pause, reduced motion, citations, ROI toggle and single-screen login")
