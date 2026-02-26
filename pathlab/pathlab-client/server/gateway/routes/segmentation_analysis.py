"""
Segmentation Analysis Module

Handles running analysis for segmentation training tasks.
Since segmentation tasks don't produce per-WSI inference results (AIResult),
analysis is based on training metrics (IoU, Dice, loss curves) stored in
metrics.json alongside the model checkpoint.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.common.config import Config
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


async def _run_segmentation_analysis(
    task, request, db, progress_callback=None, progress_config=None, submitted_by=None
):
    """Run analysis for segmentation task.

    Unlike classification/survival analysis which uses per-WSI inference results,
    segmentation analysis is based on training metrics (IoU, Dice, loss curves)
    stored in metrics.json alongside the model checkpoint.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with progress range configuration.
    """
    if progress_config is None:
        progress_config = {"start": 20, "ci_start": 30, "ci_end": 95, "has_ci": False}
    p_start = progress_config.get("start", 20)

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
    }

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
                "train_iou": train_iou,
                "val_iou": val_iou,
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
                "train_dice": train_dice,
                "val_dice": val_dice,
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

