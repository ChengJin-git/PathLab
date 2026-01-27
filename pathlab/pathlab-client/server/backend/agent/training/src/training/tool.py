"""
LangGraph tools based on the Training API (Gateway).

- list_datasets: 在 backend.agent.tools.pathlab，此处从 pathlab 引入以便与 training 工具一起使用。
- list_wsi: 在 backend.agent.tools.pathlab，此处从 pathlab 引入以便与 training 工具一起使用。
- create_training_task: POST /tasks/training — creates task and runs pipeline.
  For WSI-level: preprocess -> feature extraction -> MIL training.
  For patch-level: Feature Extractor + Linear Probe training (skips patch extraction and feature extraction).
- list_training_tasks: GET /tasks/training
- get_training_task: GET /tasks/training/{task_id}
- get_training_task_models: GET /tasks/training/{task_id}/models
- delete_training_task: DELETE /tasks/training/{task_id} — delete task and files
- get_training_logs: GET /tasks/training/{task_id}/logs — get logs with filtering and pagination
- get_recent_training_logs: GET /tasks/training/{task_id}/logs/recent — get recent N logs
"""
from __future__ import annotations

import asyncio
import json
from typing import List, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.agent.tools.pathlab import (
    ListWsiInput,
    ListDatasetsInput,
    get_gateway_base,
    list_wsi_tool,
    list_datasets_tool,
    _get_auth_headers_async,
)


# ---------------------------------------------------------------------------
# create_training_task / propose_create_training_task
# ---------------------------------------------------------------------------

# Pipeline defaults for preprocessing (tile/seg/filter) and model.
_PREPROCESSING_DEFAULTS = {
    "sthresh": 5, "mthresh": 7, "close": 4, "use_otsu": False,
    "contour_fn": "four_pt", "use_padding": True, "a_t": 1, "a_h": 256, "max_n_holes": 100,
}


def _format_training_params_for_confirm(**kwargs) -> str:
    """把 create_training_task 参数格式化成易读的确认文案。"""
    data_level = kwargs.get('data_level', '')
    data_level_desc = {
        'patch': 'patch-level（裁切块，跳过 patch extraction 和 feature extraction）',
        'wsi': 'WSI-level（整张切片，需要 patch extraction 和 feature extraction）'
    }.get(data_level, data_level)
    
    lines = [
        "我将使用以下参数创建训练任务：",
        f"- task_name: {kwargs.get('task_name', '')}",
        f"- task_type: {kwargs.get('task_type', '')}",
        f"- data_level: {data_level_desc}",
        f"- wsi_ids: {kwargs.get('wsi_ids', [])}",
        f"- task_description: {kwargs.get('task_description') or '(无)'}",
    ]
    
    # 根据 data_level 显示不同的参数说明
    if data_level == 'patch':
        lines.extend([
            "Patch-level 训练参数 (Feature Extractor + Linear Probe):",
            f"  - feature_extractor: {kwargs.get('feature_extractor', 'resnet50')}",
            f"  - epochs: {kwargs.get('epochs', 10)}, learning_rate: {kwargs.get('learning_rate', 1e-4)}",
            "  (patch-level 使用 Feature Extractor + Linear Probe，跳过 patch extraction 和 feature extraction，不使用 MIL/aggregator)",
        ])
    else:
        lines.extend([
            "WSI-level 训练参数 (preprocess -> feature -> MIL):",
            "Preprocessing:",
            f"  - tile_size: {kwargs.get('tile_size', 512)}, stride: {kwargs.get('stride', 512)}, level: {kwargs.get('level', 0)}",
            f"  - feature_extractor: {kwargs.get('feature_extractor', 'resnet50')}, feature_batch_size: {kwargs.get('feature_batch_size', 256)}",
            "Model (MIL):",
            f"  - epochs: {kwargs.get('epochs', 10)}, learning_rate: {kwargs.get('learning_rate', 1e-4)}, aggregator: {kwargs.get('aggregator', 'abmil')}",
        ])
    
    lines.extend([
        "",
        "如需修改请直接说明（例如：epochs 20、tile_size 256、data_level patch/wsi）；确认请回复 确认/运行/OK；取消请回复 取消。",
    ])
    return "\n".join(lines)


def _propose_create_training_task_impl(**kwargs) -> str:
    return _format_training_params_for_confirm(**kwargs)


async def _propose_create_training_task_async(**kwargs) -> str:
    return _propose_create_training_task_impl(**kwargs)


class CreateTrainingTaskInput(BaseModel):
    task_name: str = Field(description="Task name.")
    task_type: str = Field(description="Task type: classification or segmentation.")
    data_level: str = Field(
        description=(
            "Data level: 'wsi' or 'patch'. "
            "Determine based on: (1) User's explicit mention (patch/patch-level/裁切块 vs wsi/wsi-level/整张切片), "
            "(2) WSI type from list_wsi output (type=patch → data_level='patch', type=slide → data_level='wsi'), "
            "(3) Default to 'wsi' if unclear. "
            "Patch-level: images are already cropped patches, skip patch extraction and feature extraction. "
            "WSI-level: full slides, need patch extraction and feature extraction."
        )
    )
    wsi_ids: List[str] = Field(description="List of WSI IDs. Use list_wsi to see available IDs and their types (type=patch or type=slide).")
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
    aggregator: str = Field(
        default="abmil",
        description="MIL aggregator: abmil, etc. (Only used for WSI-level tasks. Ignored for patch-level tasks which use Linear Probe.)"
    )


propose_create_training_task_tool = StructuredTool(
    name="propose_create_training_task",
    description=(
        "Propose training task parameters for user confirmation. "
        "Use when the user wants to create a training task; do NOT call create_training_task directly. "
        "Always call list_wsi first to see available WSI IDs and their types. "
        "Determine data_level based on: (1) user's explicit mention, (2) WSI type from list_wsi (type=patch → 'patch', type=slide → 'wsi'), (3) default 'wsi' if unclear. "
        "After calling, the user will be asked to confirm or modify."
    ),
    args_schema=CreateTrainingTaskInput,
    func=_propose_create_training_task_impl,
    coroutine=_propose_create_training_task_async,
)


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

    print(
        f"[DEBUG Training] create_training_task 被调用 url={url} task_name={task_name!r} task_type={task_type!r} "
        f"data_level={data_level!r} wsi_ids={wsi_ids[:3]}{'...' if len(wsi_ids) > 3 else ''}",
        flush=True,
    )
    print(
        f"[DEBUG Training] payload keys: {list(payload.keys())}, preprocessing keys: {list(preprocessing.keys())}, model keys: {list(model.keys())}",
        flush=True,
    )

    # Validate payload can be JSON serialized
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        error_msg = f"Payload JSON serialization failed: {str(e)}"
        print(f"[DEBUG Training] {error_msg}", flush=True)
        return f"Create training task failed: {error_msg}"

    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:500] if resp.text else "No error message"
                print(
                    f"[DEBUG Training] POST /tasks/training 失败 status={resp.status_code} body={error_body!r}",
                    flush=True,
                )
                return f"Create training task failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
            _tid = data.get("task_id") or (data.get("task") or {}).get("task_id")
            print(f"[DEBUG Training] POST /tasks/training 成功 status=200 task_id={_tid}", flush=True)
    except httpx.TimeoutException as e:
        error_msg = f"Request timeout: {str(e) or repr(e)}. Gateway service may be slow or unavailable."
        print(f"[DEBUG Training] POST /tasks/training 超时 {error_msg}", flush=True)
        import traceback
        print(f"[DEBUG Training] Traceback: {traceback.format_exc()}", flush=True)
        return f"Create training task failed: {error_msg}"
    except httpx.ConnectError as e:
        error_msg = f"Cannot connect to gateway service at {url}. Please ensure the gateway service is running. Error: {str(e) or repr(e)}"
        print(f"[DEBUG Training] POST /tasks/training 连接错误 {error_msg}", flush=True)
        import traceback
        print(f"[DEBUG Training] Traceback: {traceback.format_exc()}", flush=True)
        return f"Create training task failed: {error_msg}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        error_msg = f"Request failed: {error_type} - {error_details}"
        print(f"[DEBUG Training] POST /tasks/training 请求异常 {error_msg}", flush=True)
        import traceback
        print(f"[DEBUG Training] Traceback: {traceback.format_exc()}", flush=True)
        # Try to get more details from exception attributes
        if hasattr(e, 'request'):
            print(f"[DEBUG Training] Request URL: {getattr(e.request, 'url', 'N/A')}", flush=True)
        return f"Create training task failed: {error_msg}"
    except Exception as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        error_msg = f"Unexpected error: {error_type} - {error_details}"
        print(f"[DEBUG Training] POST /tasks/training 未知异常 {error_msg}", flush=True)
        import traceback
        print(f"[DEBUG Training] Traceback: {traceback.format_exc()}", flush=True)
        return f"Create training task failed: {error_msg}"

    task_id = data.get("task_id") or data.get("task", {}).get("task_id")
    wsi_count = data.get("wsi_count", len(wsi_ids))
    # Different pipeline descriptions for different data levels
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
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"skip": skip, "limit": limit}, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.get(url, params={"skip": skip, "limit": limit}, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"List training tasks failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"List training tasks failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"List training tasks failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"List training tasks request failed ({error_type}): {error_details}"

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
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"Get training task failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get training task failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get training task failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get training task request failed ({error_type}): {error_details}"

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
    url = f"{get_gateway_base()}/tasks/training/{task_id}/models"
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"Get training task models failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get training task models failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get training task models failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get training task models request failed ({error_type}): {error_details}"

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


# ---------------------------------------------------------------------------
# delete_training_task
# ---------------------------------------------------------------------------

class DeleteTrainingTaskInput(BaseModel):
    task_id: str = Field(description="Training task ID to delete.")
    mode: str = Field(
        default="standard",
        description='Deletion mode: "standard" (delete training dir and logs, keep models) or "complete" (delete all including models).'
    )


async def _delete_training_task_impl(task_id: str, mode: str = "standard") -> str:
    url = f"{get_gateway_base()}/tasks/training/{task_id}"
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(url, params={"mode": mode}, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.delete(url, params={"mode": mode}, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"Delete training task failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Delete training task failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Delete training task failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Delete training task request failed ({error_type}): {error_details}"

    message = data.get("message", "Training task deleted")
    storage_cleanup = data.get("storage_cleanup", {})
    summary = storage_cleanup.get("summary", "") if storage_cleanup else ""
    
    lines = [f"Task {task_id} deleted: {message}"]
    if summary:
        lines.append(f"  Storage cleanup: {summary}")
    return "\n".join(lines)


def _delete_training_task_sync(task_id: str, mode: str = "standard") -> str:
    return asyncio.run(_delete_training_task_impl(task_id=task_id, mode=mode))


delete_training_task_tool = StructuredTool(
    name="delete_training_task",
    description="Delete a training task and its associated files. Use mode='standard' to keep models, or 'complete' to delete everything.",
    args_schema=DeleteTrainingTaskInput,
    func=_delete_training_task_sync,
    coroutine=_delete_training_task_impl,
)


# ---------------------------------------------------------------------------
# get_training_logs
# ---------------------------------------------------------------------------

class GetTrainingLogsInput(BaseModel):
    task_id: str = Field(description="Training task ID.")
    level: Optional[str] = Field(default=None, description="Filter by log level: INFO, WARNING, ERROR.")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum number of logs to return.")
    offset: int = Field(default=0, ge=0, description="Offset for pagination.")


async def _get_training_logs_impl(
    task_id: str,
    level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    url = f"{get_gateway_base()}/tasks/training/{task_id}/logs"
    params = {"limit": limit, "offset": offset}
    if level:
        params["level"] = level
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"Get training logs failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get training logs failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get training logs failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get training logs request failed ({error_type}): {error_details}"

    logs = data.get("logs", [])
    count = data.get("count", len(logs))
    
    if not logs:
        return f"No logs found for task {task_id}" + (f" (filter: level={level})" if level else "")
    
    lines = [f"Training logs for task {task_id} ({count} total, showing {len(logs)}):"]
    for i, log in enumerate(logs[:20], 1):  # Show first 20 logs
        log_level = log.get("level", "?")
        timestamp = log.get("timestamp", "?")
        message = (log.get("message") or "")[:100]
        lines.append(f"  {i}. [{log_level}] {timestamp}: {message}")
    
    if len(logs) > 20:
        lines.append(f"  ... and {len(logs) - 20} more logs (use offset to see more)")
    
    return "\n".join(lines)


def _get_training_logs_sync(
    task_id: str,
    level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    return asyncio.run(_get_training_logs_impl(task_id=task_id, level=level, limit=limit, offset=offset))


get_training_logs_tool = StructuredTool(
    name="get_training_logs",
    description="Get training logs for a task with optional level filtering and pagination. Use to check training progress or debug issues.",
    args_schema=GetTrainingLogsInput,
    func=_get_training_logs_sync,
    coroutine=_get_training_logs_impl,
)


# ---------------------------------------------------------------------------
# get_recent_training_logs
# ---------------------------------------------------------------------------

class GetRecentTrainingLogsInput(BaseModel):
    task_id: str = Field(description="Training task ID.")
    count: int = Field(default=100, ge=1, le=500, description="Number of recent logs to return.")


async def _get_recent_training_logs_impl(task_id: str, count: int = 100) -> str:
    url = f"{get_gateway_base()}/tasks/training/{task_id}/logs/recent"
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"count": count}, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.get(url, params={"count": count}, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:300] if resp.text else "No error message"
                return f"Get recent training logs failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get recent training logs failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get recent training logs failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get recent training logs request failed ({error_type}): {error_details}"

    logs = data.get("logs", [])
    count_actual = data.get("count", len(logs))
    
    if not logs:
        return f"No recent logs found for task {task_id}"
    
    lines = [f"Recent logs for task {task_id} ({count_actual} logs):"]
    for i, log in enumerate(logs[:30], 1):  # Show first 30 logs
        log_level = log.get("level", "?")
        timestamp = log.get("timestamp", "?")
        message = (log.get("message") or "")[:120]
        lines.append(f"  {i}. [{log_level}] {timestamp}: {message}")
    
    if len(logs) > 30:
        lines.append(f"  ... and {len(logs) - 30} more logs")
    
    return "\n".join(lines)


def _get_recent_training_logs_sync(task_id: str, count: int = 100) -> str:
    return asyncio.run(_get_recent_training_logs_impl(task_id=task_id, count=count))


get_recent_training_logs_tool = StructuredTool(
    name="get_recent_training_logs",
    description="Get the most recent N logs for a training task. Quick way to see latest training progress without pagination.",
    args_schema=GetRecentTrainingLogsInput,
    func=_get_recent_training_logs_sync,
    coroutine=_get_recent_training_logs_impl,
)
