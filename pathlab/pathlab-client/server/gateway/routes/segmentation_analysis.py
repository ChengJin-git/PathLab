"""
Segmentation Analysis Module

Handles running analysis for segmentation training tasks.
Computes per-image segmentation metrics from AIResult records and
provides bootstrap 95% CI at the image level, consistent with
classification and survival analysis modules.
Training curves (IoU, Dice, loss) are loaded from metrics.json.
"""
import asyncio
import functools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from sqlalchemy import select

from backend.common.config import Config
from backend.database.models import AIResult, TrainingTaskWSI
from backend.database.repositories import TrainedModelRepository

from .analysis_helpers import _get_random_seed_from_task
from .analysis_metrics import (
    _render_loss_chart_sync,
    run_chart_in_process,
    _write_json_sync,
)

logger = logging.getLogger(__name__)


def _load_segmentation_metrics_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """Load segmentation training metrics from metrics.json.

    Searches for metrics.json in the model's checkpoint directory.
    The segmentation trainer saves checkpoints to {UPLOADS_DIR}/{task_id}/checkpoints/.
    """
    uploads_dir = Config.get_uploads_dir()

    # Primary location: {UPLOADS_DIR}/{task_id}/checkpoints/metrics.json
    metrics_file = uploads_dir / task_id / "checkpoints" / "metrics.json"
    if metrics_file.exists():
        with open(metrics_file, "r") as f:
            return json.load(f)

    # Fallback: search in models/ directory (in case model was moved)
    models_dir = uploads_dir / "models"
    if models_dir.exists():
        for model_dir in models_dir.iterdir():
            if model_dir.is_dir() and task_id in model_dir.name:
                mf = model_dir / "metrics.json"
                if mf.exists():
                    with open(mf, "r") as f:
                        return json.load(f)

    return None


def _render_metric_curve_sync(
    metric_name: str,
    train_values: list,
    val_values: list,
    output_path: Path,
    title: str = "",
    y_label: str = "",
) -> Optional[Path]:
    """Render a metric curve chart (IoU, Dice, etc.) using matplotlib."""
    try:
        from .analysis_metrics import _setup_matplotlib_font
        plt = _setup_matplotlib_font()

        fig, ax = plt.subplots(figsize=(12, 10))
        epochs = list(range(1, len(train_values) + 1))

        ax.plot(epochs, train_values, "b-", lw=3, label=f"Train {metric_name}")
        if val_values:
            val_epochs = list(range(1, len(val_values) + 1))
            ax.plot(val_epochs, val_values, "r--", lw=3, label=f"Val {metric_name}")

        ax.set_xlabel("Epoch", fontsize=24, fontweight="bold")
        ax.set_ylabel(y_label or metric_name, fontsize=24, fontweight="bold")
        ax.set_title(title or f"{metric_name} Curve", fontsize=28, fontweight="bold", pad=20)
        ax.legend(fontsize=18)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="both", labelsize=18)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to render {metric_name} chart: {e}")
        return None


def _extract_metric_series(metrics_list: list, metric_name: str) -> list:
    """Extract a specific metric's values across epochs from a list of per-epoch metric dicts."""
    return [m.get(metric_name, 0.0) for m in metrics_list if isinstance(m, dict)]


def _calculate_segmentation_bootstrap_ci(
    per_image_metrics: List[Dict[str, float]],
    requested_metrics: List[str],
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """Calculate 95% CI for segmentation metrics using bootstrap resampling at image level.

    Each element of *per_image_metrics* is a dict like
    ``{"iou": 0.82, "dice": 0.90, "accuracy": 0.95, ...}``
    produced by ``_run_inference_patch_segmentation``.

    Returns a dict with ``metrics_ci`` keyed by metric name.
    """
    n_samples = len(per_image_metrics)
    if n_samples < 2:
        logger.warning("Bootstrap CI requires at least 2 images")
        return {"metrics_ci": {}, "n_bootstrap": n_bootstrap, "confidence_level": confidence_level}

    # Supported segmentation metrics
    seg_metric_keys = ["iou", "dice", "accuracy", "precision", "recall"]
    # Only compute CI for metrics that exist in the data AND were requested
    available_keys = set()
    for m in per_image_metrics:
        available_keys.update(m.keys())
    target_keys = [k for k in seg_metric_keys if k in available_keys and k in requested_metrics]

    if not target_keys:
        return {"metrics_ci": {}, "n_bootstrap": n_bootstrap, "confidence_level": confidence_level}

    # Build arrays for fast vectorised bootstrap
    arrays: Dict[str, np.ndarray] = {}
    for key in target_keys:
        arrays[key] = np.array([m.get(key, 0.0) for m in per_image_metrics], dtype=np.float64)

    boot_results: Dict[str, List[float]] = {k: [] for k in target_keys}

    rng = np.random.default_rng()
    for i in range(n_bootstrap):
        if progress_callback and i % 50 == 0:
            progress_callback(i / n_bootstrap)

        indices = rng.integers(0, n_samples, size=n_samples)
        for key in target_keys:
            boot_results[key].append(float(np.mean(arrays[key][indices])))

    alpha = 1 - confidence_level
    lo = alpha / 2 * 100
    hi = (1 - alpha / 2) * 100

    metrics_ci: Dict[str, Any] = {}
    for key in target_keys:
        arr = np.array(boot_results[key])
        metrics_ci[key] = {
            "lower": round(float(np.percentile(arr, lo)), 4),
            "upper": round(float(np.percentile(arr, hi)), 4),
            "mean": round(float(np.mean(arr)), 4),
            "n_samples": n_samples,
        }

    if progress_callback:
        progress_callback(1.0)

    logger.info(
        f"Segmentation bootstrap CI computed: {len(boot_results[target_keys[0]])} valid samples, "
        f"metrics: {target_keys}"
    )
    return {
        "metrics_ci": metrics_ci,
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level,
    }


async def _run_segmentation_analysis(
    task, request, db, progress_callback=None, progress_config=None, submitted_by=None
):
    """Run analysis for segmentation task.

    Combines training curves from metrics.json with per-image metrics from
    AIResult records (populated by ``_run_inference_patch_segmentation``).
    Bootstrap 95% CI is computed by resampling at the *image* level.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with progress range configuration.
    """
    if progress_config is None:
        progress_config = {"start": 20, "ci_start": 30, "ci_end": 95, "has_ci": True}
    p_start = progress_config.get("start", 20)
    p_ci_start = progress_config.get("ci_start", 30)
    p_ci_end = progress_config.get("ci_end", 95)

    task_id = task.task_id

    # Load training metrics from metrics.json
    seg_metrics = await asyncio.to_thread(_load_segmentation_metrics_sync, task_id)

    if not seg_metrics:
        # Fallback: try to get metrics from TrainedModel DB record
        models = await TrainedModelRepository.get_by_task_id(db, task_id)
        if models:
            model = models[0]
            seg_metrics = {
                "best_val_metrics": model.val_metrics or {},
                "history": {
                    "train_loss": (model.train_metrics or {}).get("loss", []),
                    "val_loss": [],
                    "train_metrics": [],
                    "val_metrics": [],
                },
            }
        else:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="No segmentation training metrics found for this task. "
                       "Ensure the training has completed successfully."
            )

    if progress_callback:
        await progress_callback(p_start + 5)

    # Extract metrics
    history = seg_metrics.get("history", {})
    best_val_metrics = seg_metrics.get("best_val_metrics", {})
    test_metrics = seg_metrics.get("test_metrics")
    best_epoch = seg_metrics.get("best_epoch")

    train_loss = history.get("train_loss", [])
    val_loss = history.get("val_loss", [])
    train_metrics_list = history.get("train_metrics", [])
    val_metrics_list = history.get("val_metrics", [])

    # Use test_metrics if available, otherwise use best_val_metrics
    final_metrics = test_metrics if test_metrics else best_val_metrics
    metrics_source = "test" if test_metrics else "validation"

    # Build summary metrics
    summary_metrics = {}
    for key in ("iou", "dice", "accuracy", "precision", "recall", "f1"):
        if key in final_metrics:
            summary_metrics[key] = final_metrics[key]

    if progress_callback:
        await progress_callback(p_start + 10)

    # ----------------------------------------------------------------
    # Query per-image metrics from AIResult records for bootstrap CI
    # These are populated by _run_inference_patch_segmentation
    # ----------------------------------------------------------------
    per_image_metrics: List[Dict[str, float]] = []

    # Determine test set WSI IDs (same pattern as classification)
    test_wsi_query = (
        select(TrainingTaskWSI.wsi_id)
        .where(TrainingTaskWSI.task_id == task_id)
        .where(TrainingTaskWSI.split == "test")
    )
    test_wsi_result = await db.execute(test_wsi_query)
    test_wsi_ids = {row[0] for row in test_wsi_result.all()}

    # Query AIResult records
    query = (
        select(AIResult)
        .where(AIResult.task_id == task_id)
        .where(AIResult.pred.isnot(None))
    )
    if test_wsi_ids:
        query = query.where(AIResult.wsi_id.in_(test_wsi_ids))
        logger.info(f"Segmentation analysis for task {task_id}: using {len(test_wsi_ids)} test set images")
    else:
        logger.info(f"Segmentation analysis for task {task_id}: no test set found, using all images")

    ai_result = await db.execute(query)
    ai_rows = ai_result.scalars().all()

    for row in ai_rows:
        # Per-image metrics are stored in probs (primary) or extra_metadata.metrics
        metrics_dict = row.probs or {}
        if not metrics_dict and row.extra_metadata:
            metrics_dict = row.extra_metadata.get("metrics", {})
        if metrics_dict and any(k in metrics_dict for k in ("iou", "dice", "accuracy")):
            per_image_metrics.append(metrics_dict)

    logger.info(f"Segmentation analysis: loaded {len(per_image_metrics)} per-image metric records from AIResult")

    # Override summary_metrics with mean of per-image metrics if available
    if per_image_metrics:
        for key in ("iou", "dice", "accuracy", "precision", "recall"):
            values = [m.get(key) for m in per_image_metrics if m.get(key) is not None]
            if values:
                summary_metrics[key] = round(float(np.mean(values)), 4)
        metrics_source = "per_image"

    # ----------------------------------------------------------------
    # Bootstrap 95% CI (image-level resampling)
    # ----------------------------------------------------------------
    bootstrap_ci_result = None
    ci_metrics = (
        request.bootstrap_ci_metrics
        if request.bootstrap_ci_metrics
        else (request.metrics if getattr(request, "compute_bootstrap_ci", False) else [])
    )

    if ci_metrics and per_image_metrics:
        logger.info(
            f"Computing segmentation bootstrap 95% CI for task {task_id} "
            f"with {len(per_image_metrics)} images, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()

        ci_range = p_ci_end - p_ci_start
        def bootstrap_progress_sync(fraction: float):
            if progress_callback:
                overall_progress = int(p_ci_start + fraction * ci_range)
                loop.call_soon_threadsafe(
                    lambda p=overall_progress: asyncio.create_task(progress_callback(p))
                )

        bootstrap_ci_result = await loop.run_in_executor(
            None,
            functools.partial(
                _calculate_segmentation_bootstrap_ci,
                per_image_metrics, ci_metrics,
                progress_callback=bootstrap_progress_sync,
            ),
        )
        logger.info(f"Segmentation bootstrap CI completed for task {task_id}")
    elif ci_metrics and not per_image_metrics:
        logger.warning(
            f"Bootstrap CI requested but no per-image AIResult records found for task {task_id}. "
            "Skipping CI calculation."
        )

    if progress_callback:
        await progress_callback(p_ci_end)

    # Create analysis output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Extract random seed
    random_seed = _get_random_seed_from_task(task)

    # Save summary
    summary = {
        "task_id": task_id,
        "task_type": "segmentation",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "description": request.description,
        "metrics_source": metrics_source,
        "best_epoch": best_epoch,
        "metrics": summary_metrics,
        "best_val_metrics": best_val_metrics,
        "test_metrics": test_metrics,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "random_seed": random_seed,
        "submitted_by": submitted_by,
        "num_images": len(per_image_metrics),
    }

    # Add bootstrap CI if computed
    if bootstrap_ci_result:
        summary["bootstrap_ci"] = bootstrap_ci_result

    if progress_callback:
        await progress_callback(p_start + 20)

    # Generate charts
    chart_paths = {}
    chart_data = {}
    chart_gen_tasks = []

    # Loss curve
    if "loss_curve" in request.charts and train_loss:
        loss_data = {
            "loss": train_loss,
            "val_loss": val_loss,
            "epochs": list(range(1, len(train_loss) + 1)),
        }
        chart_data["loss_curve"] = loss_data
        chart_gen_tasks.append(("loss_curve", run_chart_in_process(
            _render_loss_chart_sync, loss_data, analysis_dir / "loss_curve.png"
        )))

    # IoU curve
    if "iou_curve" in request.charts and val_metrics_list:
        train_iou = _extract_metric_series(train_metrics_list, "iou")
        val_iou = _extract_metric_series(val_metrics_list, "iou")
        if train_iou or val_iou:
            chart_data["iou_curve"] = {
                "epochs": list(range(1, max(len(train_iou), len(val_iou)) + 1)),
                "train_values": train_iou,
                "val_values": val_iou,
                "metric_name": "IoU",
            }
            chart_gen_tasks.append(("iou_curve", run_chart_in_process(
                _render_metric_curve_sync,
                "IoU", train_iou, val_iou,
                analysis_dir / "iou_curve.png",
                "IoU (Intersection over Union) Curve", "IoU"
            )))

    # Dice curve
    if "dice_curve" in request.charts and val_metrics_list:
        train_dice = _extract_metric_series(train_metrics_list, "dice")
        val_dice = _extract_metric_series(val_metrics_list, "dice")
        if train_dice or val_dice:
            chart_data["dice_curve"] = {
                "epochs": list(range(1, max(len(train_dice), len(val_dice)) + 1)),
                "train_values": train_dice,
                "val_values": val_dice,
                "metric_name": "Dice",
            }
            chart_gen_tasks.append(("dice_curve", run_chart_in_process(
                _render_metric_curve_sync,
                "Dice", train_dice, val_dice,
                analysis_dir / "dice_curve.png",
                "Dice Coefficient Curve", "Dice"
            )))

    # Generate all charts in parallel
    if chart_gen_tasks:
        results = await asyncio.gather(
            *[coro for _, coro in chart_gen_tasks], return_exceptions=True
        )
        for (name, _), result in zip(chart_gen_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Chart generation failed for {name}: {result}")
            elif result is not None:
                chart_paths[name] = str(result)

    if progress_callback:
        await progress_callback(90)

    # Save summary with chart paths and data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "summary.json", summary
    )

    logger.info(f"Segmentation analysis completed for task {task_id}, saved to {analysis_dir}")

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths,
    }

