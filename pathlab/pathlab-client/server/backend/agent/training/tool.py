"""
LangGraph tools based on the Training API (Gateway).

- list_wsi: 从 backend.agent.tools.pathlab 导入，统一使用平台级 tool。
- create_training_task: POST /tasks/training — creates task and runs pipeline
  (preprocess -> feature extraction -> MIL). Returns task_id.
- list_training_tasks: GET /tasks/training
- get_training_task: GET /tasks/training/{task_id}
- get_training_task_models: GET /tasks/training/{task_id}/models
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.agent.tools.pathlab import get_gateway_base, list_wsi_tool


# ---------------------------------------------------------------------------
# create_training_task
# ---------------------------------------------------------------------------

# Pipeline defaults for preprocessing (tile/seg/filter) and model.
_PREPROCESSING_DEFAULTS = {
    "sthresh": 5, "mthresh": 7, "close": 4, "use_otsu": False,
    "contour_fn": "four_pt", "use_padding": True, "a_t": 1, "a_h": 256, "max_n_holes": 100,
}


class CreateTrainingTaskInput(BaseModel):
    task_name: str = Field(description="Task name.")
    task_type: str = Field(description="Task type: classification or segmentation.")
    data_level: str = Field(description="Data level: wsi or patch.")
    wsi_ids: List[str] = Field(description="List of WSI IDs. Use list_wsi to see available IDs.")
    task_description: Optional[str] = Field(default=None, description="Optional task description.")
    huggingface_token: Optional[str] = Field(default=None, description="HuggingFace token for gated extractors (e.g. UNI).")
    # Preprocessing (pipeline uses these + seg/filter defaults)
    tile_size: int = Field(default=512, ge=1, le=2048, description="Patch size (tile_size).")
    stride: int = Field(default=512, ge=0, le=2048, description="Stride; 0 means no overlap.")
    level: int = Field(default=0, ge=0, description="Pyramid level for patching.")
    feature_extractor: str = Field(default="resnet50", description="Feature extractor (resnet50, uni, etc.).")
    feature_batch_size: int = Field(default=256, ge=1, le=512, description="Feature extraction batch size.")
    # Model
    epochs: int = Field(default=10, ge=1, le=1000, description="Training epochs.")
    learning_rate: float = Field(default=1e-4, gt=0, le=1.0, description="Learning rate.")
    aggregator: str = Field(default="abmil", description="MIL aggregator: abmil, etc.")


async def _create_training_task_impl(
    task_name: str,
    task_type: str,
    data_level: str,
    wsi_ids: List[str],
    task_description: Optional[str] = None,
    huggingface_token: Optional[str] = None,
    tile_size: int = 512,
    stride: int = 512,
    level: int = 0,
    feature_extractor: str = "resnet50",
    feature_batch_size: int = 256,
    epochs: int = 10,
    learning_rate: float = 1e-4,
    aggregator: str = "abmil",
) -> str:
    url = f"{get_gateway_base()}/tasks/training"
    preprocessing = {
        "tile_size": tile_size,
        "stride": stride,
        "level": level,
        "feature_extractor": feature_extractor,
        "feature_batch_size": feature_batch_size,
        **_PREPROCESSING_DEFAULTS,
    }
    model = {"epochs": epochs, "learning_rate": learning_rate, "aggregator": aggregator}
    payload = {
        "task_name": task_name,
        "task_type": task_type,
        "data_level": data_level,
        "wsi_ids": wsi_ids,
        "preprocessing": preprocessing,
        "model": model,
    }
    if task_description is not None:
        payload["task_description"] = task_description
    if huggingface_token:
        payload["huggingface_token"] = huggingface_token

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                return f"Create training task failed: HTTP {resp.status_code} - {resp.text[:500]}"
            data = resp.json()
    except httpx.RequestError as e:
        return f"Create training task request failed: {e!s}"

    task_id = data.get("task_id") or data.get("task", {}).get("task_id")
    wsi_count = data.get("wsi_count", len(wsi_ids))
    # Different pipeline descriptions for different data levels
    data_level = kwargs.get('data_level', 'wsi')
    if data_level == 'patch':
        pipeline_desc = "Feature Extractor + Linear Probe training"
    else:
        pipeline_desc = "preprocess -> feature extraction -> MIL training"
    return f"Training task created: task_id={task_id}, wsi_count={wsi_count}. Pipeline ({pipeline_desc}) is running in the background. Use get_training_task to check status."


def _create_training_task_sync(**kwargs) -> str:
    return asyncio.run(_create_training_task_impl(**kwargs))


create_training_task_tool = StructuredTool(
    name="create_training_task",
    description=(
        "Create a training task and run the pipeline. "
        "For WSI-level (data_level='wsi'): preprocess (compute_patches) -> feature extraction -> MIL training. "
        "For patch-level (data_level='patch'): Feature Extractor + Linear Probe training (skips patch extraction and feature extraction). "
        "Use list_wsi to get wsi_ids. Returns task_id; check status with get_training_task."
    ),
    args_schema=CreateTrainingTaskInput,
    func=_create_training_task_sync,
    coroutine=_create_training_task_impl,
)


# ---------------------------------------------------------------------------
# list_training_tasks
# ---------------------------------------------------------------------------

class ListTrainingTasksInput(BaseModel):
    skip: int = Field(default=0, ge=0, description="Pagination offset.")
    limit: int = Field(default=100, ge=1, le=500, description="Max items to return.")


async def _list_training_tasks_impl(skip: int = 0, limit: int = 100) -> str:
    url = f"{get_gateway_base()}/tasks/training"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"skip": skip, "limit": limit})
            if resp.status_code != 200:
                return f"List training tasks failed: HTTP {resp.status_code} - {resp.text[:300]}"
            data = resp.json()
    except httpx.RequestError as e:
        return f"List training tasks request failed: {e!s}"

    items = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not items:
        return "No training tasks."

    lines = [f"Training tasks ({len(items)}):"]
    for i, it in enumerate(items, 1):
        tid = it.get("task_id", "?")
        status = it.get("status", "?")
        name = (it.get("task_name") or "")[:30]
        wsi = it.get("wsi_count", "?")
        lines.append(f"  {i}. {tid} — status={status}, name={name}, wsi_count={wsi}")
    return "\n".join(lines)


def _list_training_tasks_sync(skip: int = 0, limit: int = 100) -> str:
    return asyncio.run(_list_training_tasks_impl(skip=skip, limit=limit))


list_training_tasks_tool = StructuredTool(
    name="list_training_tasks",
    description="List training tasks with status and wsi_count.",
    args_schema=ListTrainingTasksInput,
    func=_list_training_tasks_sync,
    coroutine=_list_training_tasks_impl,
)


# ---------------------------------------------------------------------------
# get_training_task
# ---------------------------------------------------------------------------

class GetTrainingTaskInput(BaseModel):
    task_id: str = Field(description="Training task ID.")


async def _get_training_task_impl(task_id: str) -> str:
    url = f"{get_gateway_base()}/tasks/training/{task_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return f"Get training task failed: HTTP {resp.status_code} - {resp.text[:300]}"
            data = resp.json()
    except httpx.RequestError as e:
        return f"Get training task request failed: {e!s}"

    status = data.get("status", "?")
    progress = data.get("progress", 0)
    wsi_count = data.get("wsi_count", 0)
    wsi_ids = data.get("wsi_ids", [])
    err = data.get("error_message", "")
    lines = [f"Task {task_id}: status={status}, progress={progress}%, wsi_count={wsi_count}"]
    if err:
        lines.append(f"  error: {err}")
    if wsi_ids:
        lines.append(f"  wsi_ids: {wsi_ids[:10]}{'...' if len(wsi_ids) > 10 else ''}")
    return "\n".join(lines)


def _get_training_task_sync(task_id: str) -> str:
    return asyncio.run(_get_training_task_impl(task_id=task_id))


get_training_task_tool = StructuredTool(
    name="get_training_task",
    description="Get training task status, progress, and wsi_ids.",
    args_schema=GetTrainingTaskInput,
    func=_get_training_task_sync,
    coroutine=_get_training_task_impl,
)


# ---------------------------------------------------------------------------
# get_training_task_models
# ---------------------------------------------------------------------------

async def _get_training_task_models_impl(task_id: str) -> str:
    url = f"{_gateway()}/tasks/training/{task_id}/models"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return f"Get training task models failed: HTTP {resp.status_code} - {resp.text[:300]}"
            data = resp.json()
    except httpx.RequestError as e:
        return f"Get training task models request failed: {e!s}"

    items = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not items:
        return f"No trained models for task {task_id} yet (training may still be running or failed)."

    lines = [f"Models for task {task_id} ({len(items)}):"]
    for i, it in enumerate(items, 1):
        mid = it.get("model_id", "?")
        path = (it.get("model_path") or "")[:60]
        lines.append(f"  {i}. model_id={mid}, path={path}")
    return "\n".join(lines)


def _get_training_task_models_sync(task_id: str) -> str:
    return asyncio.run(_get_training_task_models_impl(task_id=task_id))


get_training_task_models_tool = StructuredTool(
    name="get_training_task_models",
    description="List trained models for a training task. Only available after training completes.",
    args_schema=GetTrainingTaskInput,
    func=_get_training_task_models_sync,
    coroutine=_get_training_task_models_impl,
)
