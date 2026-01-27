"""
LangGraph tools based on the Results Analysis API (Gateway /results).

- list_analysis_tasks: GET /results/tasks — list tasks available for analysis
- run_task_analysis: POST /results/tasks/{task_id}/analysis — run analysis on a task
- get_task_analysis: GET /results/tasks/{task_id}/analysis — get analysis history for a task
- get_analysis_stats: GET /results/analysis/stats — get quick analysis statistics
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import List, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.agent.tools.pathlab import get_gateway_base

# Application-level salt for secure login (must match server)
_APP_SALT = "PathLab2024SecureSalt"

# Cached JWT token to avoid repeated logins
_cached_token: Optional[str] = None
_token_expires_at: float = 0


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
                print(f"[DEBUG Analysis] Login failed: HTTP {resp.status_code} - {error_body}", flush=True)
                return None
            
            data = resp.json()
            token = data.get("access_token")
            if token:
                _cached_token = token
                # Assume token expires in 7 days (default JWT lifetime)
                _token_expires_at = current_time + (7 * 24 * 3600)
                return token
    except httpx.ConnectError as e:
        print(f"[DEBUG Analysis] Login connection error: Cannot connect to {login_url}. Gateway service may not be running. Error: {str(e) or repr(e)}", flush=True)
        return None
    except httpx.TimeoutException as e:
        print(f"[DEBUG Analysis] Login timeout: Request to {login_url} timed out. Error: {str(e) or repr(e)}", flush=True)
        return None
    except Exception as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        print(f"[DEBUG Analysis] Login error ({error_type}): {error_details}. URL: {login_url}", flush=True)
        import traceback
        print(f"[DEBUG Analysis] Traceback: {traceback.format_exc()}", flush=True)
        return None
    
    return None


def _get_auth_headers() -> dict:
    """Get Authorization headers for API requests. Returns empty dict if token unavailable."""
    # This is a sync wrapper - in async context, use await _get_jwt_token() instead
    return {}


async def _get_auth_headers_async() -> dict:
    """Get Authorization headers for API requests (async version)."""
    token = await _get_jwt_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# ---------------------------------------------------------------------------
# list_analysis_tasks
# ---------------------------------------------------------------------------

class ListAnalysisTasksInput(BaseModel):
    data_level: Optional[str] = Field(
        default=None,
        description="Optional filter: 'wsi' for WSI-level tasks, 'patch' for patch-level tasks. If None, returns all tasks."
    )


async def _list_analysis_tasks_impl(data_level: Optional[str] = None) -> str:
    """List tasks available for analysis (completed training tasks with features and models)."""
    url = f"{get_gateway_base()}/results/tasks"
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
                return f"List analysis tasks failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"List analysis tasks failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"List analysis tasks failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"List analysis tasks request failed ({error_type}): {error_details}"

    items = data.get("items") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not items:
        filter_text = f" (filter: {data_level})" if data_level else ""
        return f"No tasks available for analysis{filter_text}. Tasks must be completed and have both features and models."

    lines = [f"Tasks available for analysis ({len(items)}):"]
    for i, it in enumerate(items, 1):
        task_id = it.get("task_id", "?")
        name = (it.get("name") or task_id)[:40]
        status = it.get("status", "?")
        data_level_val = it.get("data_level", "wsi")
        has_ai_results = it.get("has_ai_results", False)
        ai_results_count = it.get("ai_results_count", 0)
        has_analysis = it.get("has_analysis", False)
        
        # Build status line
        status_parts = [f"status={status}", f"data_level={data_level_val}"]
        if has_ai_results:
            status_parts.append(f"ai_results={ai_results_count}")
        else:
            status_parts.append("no_ai_results (need to run inference first)")
        if has_analysis:
            status_parts.append("has_analysis")
        
        lines.append(f"  {i}. {task_id} — {name}")
        lines.append(f"      {' '.join(status_parts)}")
    
    return "\n".join(lines)


def _list_analysis_tasks_sync(data_level: Optional[str] = None) -> str:
    return asyncio.run(_list_analysis_tasks_impl(data_level=data_level))


list_analysis_tasks_tool = StructuredTool(
    name="list_analysis_tasks",
    description=(
        "List training tasks that are available for result analysis. "
        "Only completed tasks with both features and models are shown. "
        "Optionally filter by data_level (wsi or patch). "
        "Tasks without AI results need to run inference first before analysis."
    ),
    args_schema=ListAnalysisTasksInput,
    func=_list_analysis_tasks_sync,
    coroutine=_list_analysis_tasks_impl,
)


# ---------------------------------------------------------------------------
# run_task_analysis
# ---------------------------------------------------------------------------

class RunTaskAnalysisInput(BaseModel):
    task_id: str = Field(description="Training task ID to analyze.")
    metrics: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of metrics to calculate. "
            "Available: accuracy, precision, recall, specificity, f1, auc. "
            "If not provided, uses default metrics: [accuracy, precision, recall, specificity, f1, auc]."
        )
    )
    charts: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of charts to generate. "
            "For classification: roc_curve, confusion_matrix, loss_curve. "
            "For survival: km_curve, loss_curve. "
            "If not provided, generates default charts based on task type."
        )
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional description for this analysis run."
    )


async def _run_task_analysis_impl(
    task_id: str,
    metrics: Optional[List[str]] = None,
    charts: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> str:
    """Run analysis on a completed training task and generate metrics and charts."""
    url = f"{get_gateway_base()}/results/tasks/{task_id}/analysis"
    
    # Build payload - use defaults if not provided
    payload = {}
    if metrics is not None:
        payload["metrics"] = metrics
    if charts is not None:
        payload["charts"] = charts
    if description is not None:
        payload["description"] = description
    
    # Get auth headers
    headers = await _get_auth_headers_async()
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # Analysis may take time
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 401:
                # Retry with fresh token
                headers = await _get_auth_headers_async()
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:500] if resp.text else "No error message"
                return f"Run task analysis failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Run task analysis failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Run task analysis timeout: {str(e) or repr(e)}. Analysis may take a while, please try again later."
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Run task analysis request failed ({error_type}): {error_details}"

    # Extract key information from response
    analysis_id = data.get("analysis_id", "?")
    summary = data.get("summary", {})
    chart_paths = data.get("chart_paths", {})
    
    # Build response message
    lines = [f"Analysis completed: task_id={task_id}, analysis_id={analysis_id}"]
    
    # Add metrics if available
    metrics_data = summary.get("metrics", {})
    if metrics_data:
        lines.append("\nMetrics:")
        if "accuracy" in metrics_data:
            lines.append(f"  - Accuracy: {metrics_data['accuracy']}")
        if "macro_f1" in metrics_data:
            lines.append(f"  - Macro F1: {metrics_data['macro_f1']}")
        if "macro_auc" in metrics_data:
            lines.append(f"  - Macro AUC: {metrics_data['macro_auc']}")
        if "c_index" in metrics_data:
            lines.append(f"  - C-Index: {metrics_data['c_index']}")
    
    # Add class metrics summary if available
    class_metrics = summary.get("class_metrics", {})
    if class_metrics:
        lines.append("\nPer-class metrics:")
        for cls, metrics in list(class_metrics.items())[:5]:  # Show first 5 classes
            precision = metrics.get("precision", "?")
            recall = metrics.get("recall", "?")
            f1 = metrics.get("f1", "?")
            lines.append(f"  - {cls}: Precision={precision}, Recall={recall}, F1={f1}")
        if len(class_metrics) > 5:
            lines.append(f"  ... and {len(class_metrics) - 5} more classes")
    
    # Add charts info
    if chart_paths:
        lines.append("\nCharts generated:")
        for chart_name, chart_path in chart_paths.items():
            lines.append(f"  - {chart_name}: {chart_path.split('/')[-1]}")
    
    # Add analysis directory info
    analysis_dir = data.get("analysis_dir", "")
    if analysis_dir:
        lines.append(f"\nAnalysis results saved to: {analysis_dir}")
    
    num_samples = summary.get("num_samples", 0)
    if num_samples > 0:
        lines.append(f"Analyzed {num_samples} samples")
    
    return "\n".join(lines)


def _run_task_analysis_sync(
    task_id: str,
    metrics: Optional[List[str]] = None,
    charts: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> str:
    return asyncio.run(_run_task_analysis_impl(
        task_id=task_id,
        metrics=metrics,
        charts=charts,
        description=description
    ))


run_task_analysis_tool = StructuredTool(
    name="run_task_analysis",
    description=(
        "Run comprehensive analysis on a completed training task. "
        "Generates metrics (accuracy, precision, recall, F1, AUC for classification; C-Index for survival) "
        "and charts (ROC curve, confusion matrix, loss curve for classification; KM curve for survival). "
        "Results are saved to logs/analysis/{task_id}/{timestamp}/. "
        "The task must be completed and have AI results (run inference first if needed)."
    ),
    args_schema=RunTaskAnalysisInput,
    func=_run_task_analysis_sync,
    coroutine=_run_task_analysis_impl,
)


# ---------------------------------------------------------------------------
# get_task_analysis
# ---------------------------------------------------------------------------

class GetTaskAnalysisInput(BaseModel):
    task_id: str = Field(description="Training task ID to get analysis history for.")


async def _get_task_analysis_impl(task_id: str) -> str:
    """Get analysis history for a task."""
    url = f"{get_gateway_base()}/results/tasks/{task_id}/analysis"
    
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
                return f"Get task analysis failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get task analysis failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get task analysis failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get task analysis request failed ({error_type}): {error_details}"

    analyses = data.get("analyses", [])
    if not analyses:
        return f"No analysis history found for task {task_id}. Use run_task_analysis to create an analysis."

    lines = [f"Analysis history for task {task_id} ({len(analyses)} analyses):"]
    for i, analysis in enumerate(analyses, 1):
        analysis_id = analysis.get("analysis_id", "?")
        timestamp = analysis.get("timestamp", "?")
        desc = analysis.get("description", "")
        num_samples = analysis.get("num_samples", 0)
        
        # Extract key metrics for quick view
        metrics = analysis.get("metrics", {})
        metric_strs = []
        if "accuracy" in metrics:
            metric_strs.append(f"Accuracy={metrics['accuracy']}")
        if "macro_f1" in metrics:
            metric_strs.append(f"F1={metrics['macro_f1']}")
        if "c_index" in metrics:
            metric_strs.append(f"C-Index={metrics['c_index']}")
        
        lines.append(f"  {i}. {analysis_id} — {timestamp}")
        if desc:
            lines.append(f"      Description: {desc}")
        if num_samples > 0:
            lines.append(f"      Samples: {num_samples}")
        if metric_strs:
            lines.append(f"      Metrics: {', '.join(metric_strs)}")
    
    return "\n".join(lines)


def _get_task_analysis_sync(task_id: str) -> str:
    return asyncio.run(_get_task_analysis_impl(task_id=task_id))


get_task_analysis_tool = StructuredTool(
    name="get_task_analysis",
    description=(
        "Get analysis history for a training task. "
        "Returns all previous analysis runs with their metrics and timestamps. "
        "Use this to check if an analysis already exists before running a new one."
    ),
    args_schema=GetTaskAnalysisInput,
    func=_get_task_analysis_sync,
    coroutine=_get_task_analysis_impl,
)


# ---------------------------------------------------------------------------
# get_analysis_stats
# ---------------------------------------------------------------------------

class GetAnalysisStatsInput(BaseModel):
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task ID to filter stats. If not provided, returns stats for all tasks."
    )


async def _get_analysis_stats_impl(task_id: Optional[str] = None) -> str:
    """Get quick analysis statistics without running full analysis."""
    url = f"{get_gateway_base()}/results/analysis/stats"
    params = {}
    if task_id:
        params["task_id"] = task_id
    
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
                return f"Get analysis stats failed: HTTP {resp.status_code} - {error_body}"
            data = resp.json()
    except httpx.ConnectError as e:
        return f"Get analysis stats failed: Cannot connect to Gateway service at {url}. Please ensure the Gateway service is running. Error: {str(e) or repr(e)}"
    except httpx.TimeoutException as e:
        return f"Get analysis stats failed: Request timeout. Gateway service may be slow or unavailable. Error: {str(e) or repr(e)}"
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_details = str(e) or repr(e) or f"{error_type} occurred"
        return f"Get analysis stats request failed ({error_type}): {error_details}"

    total = data.get("total", 0)
    analyzed = data.get("analyzed", 0)
    
    if analyzed == 0:
        task_text = f" for task {task_id}" if task_id else ""
        return f"No analyzed results found{task_text}. Run inference first to generate AI results."

    lines = []
    if task_id:
        lines.append(f"Analysis statistics for task {task_id}:")
    else:
        lines.append("Overall analysis statistics:")
    
    lines.append(f"  Total samples: {total}")
    lines.append(f"  Analyzed samples: {analyzed}")
    
    # Overall metrics
    metrics = data.get("metrics", {})
    if metrics:
        lines.append("\nOverall metrics:")
        if "accuracy" in metrics:
            lines.append(f"  - Accuracy: {metrics['accuracy']}")
        if "macro_precision" in metrics:
            lines.append(f"  - Macro Precision: {metrics['macro_precision']}")
        if "macro_recall" in metrics:
            lines.append(f"  - Macro Recall: {metrics['macro_recall']}")
        if "macro_f1" in metrics:
            lines.append(f"  - Macro F1: {metrics['macro_f1']}")
        if "macro_auc" in metrics:
            lines.append(f"  - Macro AUC: {metrics['macro_auc']}")
    
    # Per-class metrics (show first 5)
    class_metrics = data.get("class_metrics", {})
    if class_metrics:
        lines.append("\nPer-class metrics:")
        for cls, cls_metrics in list(class_metrics.items())[:5]:
            precision = cls_metrics.get("precision", "?")
            recall = cls_metrics.get("recall", "?")
            f1 = cls_metrics.get("f1", "?")
            support = cls_metrics.get("support", "?")
            lines.append(f"  - {cls}: Precision={precision}, Recall={recall}, F1={f1}, Support={support}")
        if len(class_metrics) > 5:
            lines.append(f"  ... and {len(class_metrics) - 5} more classes")
    
    # Confusion matrix summary
    confusion_matrix = data.get("confusion_matrix", {})
    if confusion_matrix:
        lines.append("\nConfusion matrix available (use run_task_analysis to generate detailed charts)")
    
    return "\n".join(lines)


def _get_analysis_stats_sync(task_id: Optional[str] = None) -> str:
    return asyncio.run(_get_analysis_stats_impl(task_id=task_id))


get_analysis_stats_tool = StructuredTool(
    name="get_analysis_stats",
    description=(
        "Get quick analysis statistics for predictions without running full analysis. "
        "Returns overall metrics (accuracy, precision, recall, F1, AUC) and per-class metrics. "
        "Useful for quick checks. For detailed analysis with charts, use run_task_analysis instead."
    ),
    args_schema=GetAnalysisStatsInput,
    func=_get_analysis_stats_sync,
    coroutine=_get_analysis_stats_impl,
)
