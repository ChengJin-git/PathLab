"""
PathLab 平台级 tools：Gateway 相关、可被 research / training / chat 等复用。

- list_wsi: GET /wsi，列出 WSI slides，供选择 wsi_ids。
- list_datasets: GET /wsi/datasets，列出所有数据集及其统计信息。
- get_gateway_base: 供 training 等模块拼 Gateway URL 使用。
- get_pathlab_tools: 返回 [list_wsi_tool, list_datasets_tool]，便于在研究等流程中按需组合。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from typing import Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_DEFAULT_GATEWAY_URL = "http://127.0.0.1:5100"

# Application-level salt for secure login (must match server)
_APP_SALT = "PathLab2024SecureSalt"

# Cached JWT token to avoid repeated logins
_cached_token: Optional[str] = None
_token_expires_at: float = 0

# 按后缀区分 slide（整张切片）与 patch（裁切块）
_SLIDE_SUFFIXES = {".svs", ".ndpi", ".tif", ".tiff", ".scn", ".vms", ".vmu", ".bif", ".mrxs", ".czi", ".svslide", ".isyntax", ".npi", ".nfksz", ".sdpc", ".kfb"}
_PATCH_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def get_gateway_base(base: str | None = None) -> str:
    """Gateway 根 URL，供 list_wsi、training 等调用。"""
    return (base or os.environ.get("GATEWAY_SERVICE_URL") or _DEFAULT_GATEWAY_URL).rstrip("/")


async def _get_jwt_token() -> Optional[str]:
    """
    Get JWT token for admin user (admin/Smartlab2022).
    Uses cached token if still valid, otherwise logs in to get a new token.
    """
    global _cached_token, _token_expires_at
    
    # Check if cached token is still valid (refresh 1 hour before expiration)
    current_time = time.time()
    if _cached_token and current_time < _token_expires_at - 3600:
        return _cached_token
    
    # Login to get new token
    gateway_base = get_gateway_base()
    login_url = f"{gateway_base}/auth/secure-login"
    
    username = "admin"
    password = "Smartlab2022"
    
    # Compute secure login hash: SHA256(SHA256(password) + timestamp + APP_SALT)
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    timestamp = int(time.time() * 1000)
    hashed_password = hashlib.sha256(f"{password_hash}{timestamp}{_APP_SALT}".encode()).hexdigest()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                login_url,
                json={
                    "username": username,
                    "hashed_password": hashed_password,
                    "timestamp": timestamp,
                }
            )
            if resp.status_code != 200:
                error_body = resp.text[:200] if resp.text else "No error message"
                print(f"[DEBUG PathLab] Login failed: HTTP {resp.status_code} - {error_body}", flush=True)
                return None
            
            data = resp.json()
            token = data.get("access_token")
            if token:
                _cached_token = token
                # Assume token expires in 7 days (default JWT lifetime)
                _token_expires_at = current_time + (7 * 24 * 3600)
                return token
    except httpx.ConnectError as e:
        print(f"[DEBUG PathLab] Login connection error: Cannot connect to {login_url}. Gateway service may not be running. Error: {str(e) or repr(e)}", flush=True)
        return None
    except httpx.TimeoutException as e:
        print(f"[DEBUG PathLab] Login timeout: Request to {login_url} timed out. Error: {str(e) or repr(e)}", flush=True)
        return None
    except Exception as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        print(f"[DEBUG PathLab] Login error ({error_type}): {error_details}. URL: {login_url}", flush=True)
        import traceback
        print(f"[DEBUG PathLab] Traceback: {traceback.format_exc()}", flush=True)
        return None
    
    return None


async def _get_auth_headers_async() -> dict:
    """Get Authorization headers for API requests (async version)."""
    token = await _get_jwt_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _file_type_by_suffix(filename_or_path: str) -> str:
    """根据文件后缀判断 slide / patch，无后缀或未知则 unknown。"""
    if not (filename_or_path or "").strip():
        return "unknown"
    s = filename_or_path.strip()
    if "/" in s or "\\" in s:
        s = s.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in s:
        return "unknown"
    ext = "." + s.rsplit(".", 1)[-1].lower()
    if ext in _SLIDE_SUFFIXES:
        return "slide"
    if ext in _PATCH_SUFFIXES:
        return "patch"
    return "unknown"


# ---------------------------------------------------------------------------
# list_wsi
# ---------------------------------------------------------------------------

class ListWsiInput(BaseModel):
    skip: int = Field(default=0, ge=0, description="Pagination offset.")
    limit: int = Field(
        default=100,
        ge=0,
        le=500,
        description="Max items to return. Use 0 to return all files (no limit). Default is 100."
    )
    dataset_name: Optional[str] = Field(
        default=None,
        description="Optional dataset name to filter WSI slides. Use 'Uncategorized' for WSI without a dataset."
    )


async def _list_wsi_impl(skip: int = 0, limit: int = 100, dataset_name: Optional[str] = None) -> str:
    url = f"{get_gateway_base()}/wsi"
    # Gateway API supports limit=0 to return all records
    params = {"skip": skip, "limit": limit if limit > 0 else 0}
    if dataset_name:
        params["dataset_name"] = dataset_name
    
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
                return f"List WSI failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"List WSI failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"List WSI failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"List WSI request failed ({error_type}): {error_details}"

    items = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
    
    if not items:
        filter_text = f" in dataset '{dataset_name}'" if dataset_name else ""
        return f"No WSI found{filter_text}. Register slides first (e.g. POST /wsi/upload/path)."

    filter_text = f" (dataset: {dataset_name})" if dataset_name else ""
    # Only show pagination info if limit > 0 and we got fewer items than total
    if limit > 0 and total > len(items):
        total_text = f" (showing {len(items)} of {total})"
    else:
        total_text = ""
    lines = [f"WSI ({len(items)}{total_text}){filter_text}，type 由文件后缀区分 (slide=整张切片 / patch=裁切块)："]
    
    for i, it in enumerate(items, 1):
        wsi_id = it.get("wsi_id", "?")
        label = it.get("label") or ""
        dataset = it.get("dataset_name") or "Uncategorized"
        fn = (it.get("original_filename") or "")[:40]
        ftype = _file_type_by_suffix(it.get("original_filename") or it.get("wsi_path") or "")
        extra = [f"label={label}"] if label else []
        if fn:
            extra.append(f"file={fn}")
        # Only show dataset if not filtering by dataset (to avoid redundancy)
        if not dataset_name:
            extra.append(f"dataset={dataset}")
        lines.append(f"  {i}. {wsi_id}, type={ftype}" + (f" — {', '.join(extra)}" if extra else ""))
    return "\n".join(lines)


def _list_wsi_sync(skip: int = 0, limit: int = 100, dataset_name: Optional[str] = None) -> str:
    return asyncio.run(_list_wsi_impl(skip=skip, limit=limit, dataset_name=dataset_name))


list_wsi_tool = StructuredTool(
    name="list_wsi",
    description=(
        "List WSI slides in the database. Use wsi_id in create_training_task as wsi_ids. "
        "Set limit=0 to return all files (no pagination). "
        "Optionally filter by dataset_name to list WSI from a specific dataset. "
        "Use 'Uncategorized' for WSI without a dataset."
    ),
    args_schema=ListWsiInput,
    func=_list_wsi_sync,
    coroutine=_list_wsi_impl,
)


# ---------------------------------------------------------------------------
# list_datasets
# ---------------------------------------------------------------------------

class ListDatasetsInput(BaseModel):
    data_level: Optional[str] = Field(
        default=None,
        description="Optional filter: 'wsi' for WSI files, 'patch' for image files. If None, returns all datasets."
    )


async def _list_datasets_impl(data_level: Optional[str] = None) -> str:
    url = f"{get_gateway_base()}/wsi/datasets"
    params = {}
    if data_level:
        params["data_level"] = data_level
    
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
                return f"List datasets failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"List datasets failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"List datasets failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"List datasets request failed ({error_type}): {error_details}"

    datasets = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not datasets:
        filter_text = f" (filter: {data_level})" if data_level else ""
        return f"No datasets found{filter_text}."

    lines = [f"Datasets ({len(datasets)}):"]
    for i, ds in enumerate(datasets, 1):
        name = ds.get("dataset_name") or ds.get("name", "Uncategorized")
        count = ds.get("file_count", 0)
        size = ds.get("total_size", 0)
        ds_type = ds.get("dataset_type", "classification")
        
        # Format size
        if size >= 1024 ** 3:
            size_str = f"{size / (1024**3):.2f} GB"
        elif size >= 1024 ** 2:
            size_str = f"{size / (1024**2):.2f} MB"
        elif size >= 1024:
            size_str = f"{size / 1024:.2f} KB"
        else:
            size_str = f"{size} B"
        
        lines.append(f"  {i}. {name} — {count} files, {size_str}, type={ds_type}")
    
    return "\n".join(lines)


def _list_datasets_sync(data_level: Optional[str] = None) -> str:
    return asyncio.run(_list_datasets_impl(data_level=data_level))


list_datasets_tool = StructuredTool(
    name="list_datasets",
    description="List all datasets in the database with file count and total size. Optionally filter by data_level (wsi or patch).",
    args_schema=ListDatasetsInput,
    func=_list_datasets_sync,
    coroutine=_list_datasets_impl,
)


def get_pathlab_tools() -> list:
    """返回平台级 tools 列表，便于 research 等按需组合。例如：tools.extend(get_pathlab_tools())。"""
    return [list_wsi_tool, list_datasets_tool]
