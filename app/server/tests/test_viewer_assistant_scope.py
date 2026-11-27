from unittest.mock import AsyncMock
from backend.services.viewer_assistant import Decision
from gateway.routes import viewer
from test_viewer_workspace import workspace  # noqa: F401


async def test_complex_request_only_hands_off_original_goal(workspace, monkeypatch):
    goal = "对整个数据集比较三种模型，做生存分析并生成报告"
    message = "这个需求需要结合整个数据集进一步分析。我们回到主页面继续，我会带上当前切片和你的问题。"
    decide = AsyncMock(
        return_value=Decision(scope="main_workspace", action="measure", message=message)
    )
    monkeypatch.setattr("backend.services.viewer_assistant.decide", decide)
    search = AsyncMock(
        side_effect=AssertionError("complex requests must not execute local tools")
    )
    monkeypatch.setattr(viewer, "feature_search", search)
    response = await workspace.client.post(
        "/viewer/slides/slide/assistant", json={"message": goal}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["action"] == "handoff"
        and body["goal"] == goal
        and body["message"] == message
        and body["regions"] == []
    )
    search.assert_not_called()


async def test_simple_measurement_stays_on_current_slide(workspace, monkeypatch):
    from test_viewer_workspace import mutate, change

    await mutate(workspace, [change()])
    monkeypatch.setattr(
        "backend.services.viewer_assistant.decide",
        AsyncMock(return_value=Decision(action="measure", message="已测量所选区域。")),
    )
    response = await workspace.client.post(
        "/viewer/slides/slide/assistant",
        json={"message": "测量所选区域", "selected_ids": ["region"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["measurement"]["area_px"] == 1200
