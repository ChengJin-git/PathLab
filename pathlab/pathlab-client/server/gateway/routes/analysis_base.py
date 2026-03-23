"""
Analysis Base Helpers

Shared utilities extracted from classification_analysis.py, segmentation_analysis.py,
survival_analysis.py, and external_validation_analysis.py to eliminate structural
redundancy. Pure functions / helpers only — no behavior changes.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.common.config import Config
from backend.database.repositories import WSIRepository

from .analysis_metrics import _write_json_sync, run_chart_in_process

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
