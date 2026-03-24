"""
Analysis Utilities
==================

Shared helpers used across all analysis route modules
(classification, segmentation, survival, external validation).

Consolidates the former analysis_base.py and analysis_helpers.py into a single
module so consumers only need one import target.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from backend.auth.dependencies import (
    check_dataset_gpu_permission,
    check_task_access_permission,
)
from backend.common.config import Config
from backend.database.repositories import (
    TrainingTaskRepository,
    WSIRepository,
)

from .analysis_metrics import _write_json_sync, run_chart_in_process  # noqa: F401 – re-exported

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress config helpers
# ---------------------------------------------------------------------------


def unpack_progress_config(
    progress_config: Optional[Dict[str, Any]],
    default: Optional[Dict[str, Any]] = None,
) -> tuple[int, int, int]:
    """Unpack the standard progress_config dict into (p_start, p_ci_start, p_ci_end).

    Returns the three integer progress percentages used throughout analysis functions.
    """
    if progress_config is None:
        progress_config = default or {
            "start": 20,
            "ci_start": 30,
            "ci_end": 95,
            "has_ci": True,
        }
    p_start = progress_config.get("start", 20)
    p_ci_start = progress_config.get("ci_start", 30)
    p_ci_end = progress_config.get("ci_end", 95)
    return p_start, p_ci_start, p_ci_end


# ---------------------------------------------------------------------------
# Bootstrap CI progress callback
# ---------------------------------------------------------------------------


def make_bootstrap_progress_sync(
    progress_callback: Optional[Callable],
    p_ci_start: int,
    p_ci_end: int,
    loop: asyncio.AbstractEventLoop,
) -> Callable[[float], None]:
    """Return a thread-safe sync callback that maps bootstrap fraction (0.0-1.0)
    to overall progress (p_ci_start -> p_ci_end) and schedules the async callback.
    """
    ci_range = p_ci_end - p_ci_start

    def bootstrap_progress_sync(fraction: float) -> None:
        if progress_callback:
            overall_progress = int(p_ci_start + fraction * ci_range)
            loop.call_soon_threadsafe(
                lambda p=overall_progress: asyncio.create_task(progress_callback(p))
            )

    return bootstrap_progress_sync


# ---------------------------------------------------------------------------
# Analysis output directory
# ---------------------------------------------------------------------------


def make_analysis_dir(task_id: str) -> tuple[Any, str]:
    """Create the timestamped analysis output directory.

    Returns (analysis_dir: Path, timestamp: str).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir, timestamp


# ---------------------------------------------------------------------------
# Filename resolution (WSI lookup)
# ---------------------------------------------------------------------------


async def fill_wsi_filenames(
    db: Any, results: List[Dict[str, Any]], wsi_id_key: str = "wsi_id"
) -> None:
    """Resolve missing filenames in *results* by batch-querying WSIRepository.

    Modifies *results* in-place — sets ``filename`` on each entry that lacks one.
    """
    missing_ids = [
        r[wsi_id_key] for r in results if r.get(wsi_id_key) and not r.get("filename")
    ]
    if not missing_ids:
        return
    wsi_map = await WSIRepository.get_by_ids(db, missing_ids)
    for r in results:
        if not r.get("filename") and r.get(wsi_id_key):
            wsi_obj = wsi_map.get(r[wsi_id_key])
            r["filename"] = (wsi_obj.original_filename if wsi_obj else None) or r[
                wsi_id_key
            ]


# ---------------------------------------------------------------------------
# Chart generation (parallel gather)
# ---------------------------------------------------------------------------


async def run_chart_tasks(
    chart_gen_tasks: List[tuple],
) -> Dict[str, str]:
    """Run all pending chart generation coroutines in parallel and collect paths.

    *chart_gen_tasks* is a list of ``(name, coroutine)`` tuples as built in each
    analysis module.

    Returns a dict mapping chart name → file path string.
    """
    if not chart_gen_tasks:
        return {}

    results = await asyncio.gather(
        *[coro for _, coro in chart_gen_tasks], return_exceptions=True
    )
    chart_paths: Dict[str, str] = {}
    for (name, _), result in zip(chart_gen_tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Chart generation failed for {name}: {result}")
        elif result is not None:
            chart_paths[name] = str(result)
    return chart_paths


# ---------------------------------------------------------------------------
# Standard analysis return value
# ---------------------------------------------------------------------------


def make_analysis_result(
    task_id: str,
    timestamp: str,
    analysis_dir: Any,
    summary: Dict[str, Any],
    chart_paths: Dict[str, str],
) -> Dict[str, Any]:
    """Build the standard dict returned by every ``_run_*_analysis`` function."""
    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths,
    }


# ---------------------------------------------------------------------------
# UTC timestamp string (ISO-8601 with Z suffix)
# ---------------------------------------------------------------------------


def utc_timestamp_z() -> str:
    """Return current UTC time as ISO-8601 string with 'Z' suffix (no tzinfo offset)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


# ---------------------------------------------------------------------------
# Task seed / dataset resolution
# ---------------------------------------------------------------------------


def _get_random_seed_from_task(task) -> Optional[int]:
    """Extract random seed from task's preprocessing_config.

    The seed is stored in preprocessing_config.split_config.seed and serves
    as both a reproducibility parameter and an invisible watermark for model provenance.
    """
    if not task or not task.preprocessing_config:
        return None
    split_config = task.preprocessing_config.get("split_config", {})
    return split_config.get("seed")


async def _resolve_task_dataset_id(task, db) -> Optional[str]:
    """Resolve dataset_id for a training task.

    For external validation tasks, dataset_id is stored in model_config.
    For regular training tasks, dataset_id must be derived from the task's WSIs
    through the TrainingTaskWSI junction table.

    Args:
        task: TrainingTask object
        db: Database session

    Returns:
        dataset_id string or None
    """
    mc = task.model_config or {}
    # External validation tasks have dataset_id in model_config
    dataset_id = mc.get("dataset_id")
    if dataset_id:
        return dataset_id

    # For regular training tasks, derive from WSIs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
    if wsi_ids:
        first_wsi = await WSIRepository.get_by_id(db, wsi_ids[0])
        if first_wsi and first_wsi.dataset_id:
            return first_wsi.dataset_id

    return None


async def _require_task_access(
    user,
    task,
    db,
    *,
    owner_user_id: Optional[str] = None,
    forbidden_detail: str = "You don't have permission to access this task",
) -> Optional[str]:
    """Require read access to a training task and return its resolved dataset_id."""
    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if not await check_task_access_permission(
        user,
        owner_user_id or task.user_id,
        task_dataset_id,
        db,
    ):
        raise HTTPException(status_code=403, detail=forbidden_detail)
    return task_dataset_id


async def _get_task_with_access(
    task_id: str,
    user,
    db,
    *,
    not_found_detail: Optional[str] = None,
    forbidden_detail: str = "You don't have permission to access this task",
) -> tuple[Any, Optional[str]]:
    """Load a task, require access, and return ``(task, dataset_id)``."""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(
            status_code=404, detail=not_found_detail or f"Task not found: {task_id}"
        )

    task_dataset_id = await _require_task_access(
        user,
        task,
        db,
        forbidden_detail=forbidden_detail,
    )
    return task, task_dataset_id


async def _require_task_gpu_permission(
    user,
    task,
    db,
    *,
    forbidden_detail: str,
    fallback_role_detail: Optional[str] = None,
) -> Optional[str]:
    """Require GPU permission for a task's dataset, with role fallback when no dataset exists."""
    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if task_dataset_id:
        has_permission = await check_dataset_gpu_permission(user, task_dataset_id, db)
        if not has_permission:
            raise HTTPException(status_code=403, detail=forbidden_detail)
        return task_dataset_id

    if not user.can_use_gpu():
        raise HTTPException(
            status_code=403, detail=fallback_role_detail or forbidden_detail
        )

    return None


# ---------------------------------------------------------------------------
# Label / string coercion helpers
# ---------------------------------------------------------------------------


def _normalize_label_names(labels: List[str]) -> List[str]:
    return sorted({str(label).strip() for label in labels if str(label).strip()})


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _coerce_str_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if isinstance(v, (str, int, float)) or v is not None]


# ---------------------------------------------------------------------------
# Attention weight splitting (case → slide level)
# ---------------------------------------------------------------------------


def _split_case_attention_to_slides_static(
    attention: Optional[Any],
    case_id: str,
    case_wsi_patch_counts: Dict[str, List[int]],
    case_to_wsi: Dict[str, List[str]],
) -> Dict[str, Optional[Any]]:
    """
    Split case-level attention weights back to individual slides.
    Static version for use in results.py inference.
    """
    import numpy as np

    if attention is None:
        wsi_ids = case_to_wsi.get(case_id, [])
        return {wsi_id: None for wsi_id in wsi_ids}

    wsi_ids = case_to_wsi.get(case_id, [])
    patch_counts = case_wsi_patch_counts.get(case_id, [])

    if len(wsi_ids) != len(patch_counts):
        return {wsi_id: None for wsi_id in wsi_ids}

    slide_attentions: Dict[str, Optional["np.ndarray[Any, Any]"]] = {}
    start_idx = 0

    for wsi_id, count in zip(wsi_ids, patch_counts):
        end_idx = start_idx + count
        if attention.ndim == 1:
            slide_attentions[wsi_id] = attention[start_idx:end_idx]
        elif attention.ndim == 2:
            slide_attentions[wsi_id] = attention[:, start_idx:end_idx]
        else:
            slide_attentions[wsi_id] = None
        start_idx = end_idx

    return slide_attentions


# ---------------------------------------------------------------------------
# Segmentation analysis helpers
# ---------------------------------------------------------------------------


def _normalize_segmentation_class_names(labels: Optional[List[Any]]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for label in labels or []:
        value = str(label).strip()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _resolve_segmentation_metric_value(
    metrics: Optional[Dict[str, Any]], metric_key: str
) -> Optional[float]:
    if not isinstance(metrics, dict):
        return None

    value = metrics.get(metric_key)
    if value is None and metric_key == "miou":
        value = metrics.get("iou")
    elif value is None and metric_key == "iou":
        value = metrics.get("miou")

    return float(value) if value is not None else None
