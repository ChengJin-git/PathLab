"""Tests for training tools (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.training import (
    list_wsi_tool,
    create_training_task_tool,
    list_training_tasks_tool,
    get_training_task_tool,
    get_training_task_models_tool,
)


def _mock_async_client(get_json=None, post_json=None, get_status=200, post_status=200):
    mock_resp = MagicMock()
    mock_resp.status_code = get_status if get_json is not None else post_status
    mock_resp.json.return_value = get_json if get_json is not None else post_json
    mock_resp.text = "error"

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_client


@pytest.mark.asyncio
async def test_list_wsi_tool_success():
    mock_cm, mock_client = _mock_async_client(get_json={"items": [{"wsi_id": "s1", "label": "A"}]})
    with patch("backend.agent.tools.pathlab.httpx.AsyncClient", return_value=mock_cm):
        out = await list_wsi_tool.ainvoke({"skip": 0, "limit": 10})
    assert "s1" in out and "A" in out
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_create_training_task_tool_success():
    mock_cm, mock_client = _mock_async_client(
        post_json={"task_id": "train_abc123", "wsi_count": 2}
    )
    with patch("backend.agent.training.src.training.tool.httpx.AsyncClient", return_value=mock_cm):
        out = await create_training_task_tool.ainvoke({
            "task_name": "t1",
            "task_type": "classification",
            "data_level": "wsi",
            "wsi_ids": ["s1", "s2"],
        })
    assert "train_abc123" in out
    mock_client.post.assert_called_once()
    body = mock_client.post.call_args[1]["json"]
    assert body["task_name"] == "t1" and body["wsi_ids"] == ["s1", "s2"]
    assert "preprocessing" in body and "tile_size" in body["preprocessing"]
    assert "model" in body and "epochs" in body["model"]


@pytest.mark.asyncio
async def test_list_training_tasks_tool_success():
    mock_cm, mock_client = _mock_async_client(
        get_json={"items": [{"task_id": "t1", "status": "running", "wsi_count": 3}]}
    )
    with patch("backend.agent.training.src.training.tool.httpx.AsyncClient", return_value=mock_cm):
        out = await list_training_tasks_tool.ainvoke({})
    assert "t1" in out and "running" in out
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_training_task_tool_success():
    mock_cm, mock_client = _mock_async_client(
        get_json={"task_id": "t1", "status": "completed", "progress": 100, "wsi_count": 2, "wsi_ids": ["a", "b"]}
    )
    with patch("backend.agent.training.src.training.tool.httpx.AsyncClient", return_value=mock_cm):
        out = await get_training_task_tool.ainvoke({"task_id": "t1"})
    assert "t1" in out and "completed" in out
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_training_task_models_tool_success():
    mock_cm, mock_client = _mock_async_client(
        get_json={"items": [{"model_id": "m1", "model_path": "/path/to/m1.pt"}]}
    )
    with patch("backend.agent.training.src.training.tool.httpx.AsyncClient", return_value=mock_cm):
        out = await get_training_task_models_tool.ainvoke({"task_id": "t1"})
    assert "m1" in out
    mock_client.get.assert_called_once()
