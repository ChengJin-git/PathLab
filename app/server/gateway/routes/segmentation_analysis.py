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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from sqlalchemy import select

from backend.ai.task_taxonomy import normalize_task_type
from backend.common.config import Config
from backend.database.models import AIResult, TrainingTaskWSI
from backend.database.repositories import TrainedModelRepository

from .analysis_utils import (
    fill_wsi_filenames,
    make_analysis_dir,
    make_analysis_result,
    make_bootstrap_progress_sync,
    run_chart_tasks,
    unpack_progress_config,
    utc_timestamp_z,
    _get_random_seed_from_task,
    _normalize_segmentation_class_names,
    _resolve_segmentation_metric_value,
)
from .analysis_metrics import (
    _render_loss_chart_sync,
    run_chart_in_process,
    _write_json_sync,
)

logger = logging.getLogger(__name__)


def _canonical_analysis_task_type(task) -> str:
    return normalize_task_type(
        task_type=getattr(task, "task_type", "patch_segmentation"),
        data_type=getattr(task, "data_type", "patch"),
    )


def _resolve_segmentation_class_names(
    task,
    seg_metrics: Dict[str, Any],
    final_metrics: Dict[str, Any],
    ai_rows: List[AIResult],
    fallback_model_classes: Optional[List[Any]] = None,
) -> List[str]:
    class_names = _normalize_segmentation_class_names(getattr(task, "classes", None))
    if not class_names:
        config = seg_metrics.get("config", {}) if isinstance(seg_metrics, dict) else {}
        class_names = _normalize_segmentation_class_names(
            config.get("classes") or config.get("class_names")
        )
    if not class_names:
        for row in ai_rows:
            extra_metadata = row.extra_metadata or {}
            class_names = _normalize_segmentation_class_names(
                extra_metadata.get("class_names")
            )
            if class_names:
                break
    if not class_names:
        class_names = _normalize_segmentation_class_names(fallback_model_classes)

    num_classes = len(class_names)
    for key in ("iou_per_class", "dice_per_class"):
        values = final_metrics.get(key)
        if isinstance(values, list):
            num_classes = max(num_classes, len(values))

    if not class_names and num_classes > 0:
        class_names = [f"Class {index}" for index in range(num_classes)]
    elif len(class_names) < num_classes:
        class_names.extend(
            f"Class {index}" for index in range(len(class_names), num_classes)
        )

    return class_names


def _build_segmentation_class_metrics(
    class_names: List[str],
    per_image_metrics: List[Dict[str, Any]],
    final_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    class_metrics: Dict[str, Dict[str, float]] = {name: {} for name in class_names}
    chart_payloads: Dict[str, Dict[str, Any]] = {}

    metric_specs = {
        "iou_per_class": ("iou", "per_class_iou", "IoU"),
        "dice_per_class": ("dice", "per_class_dice", "Dice"),
        "precision_per_class": ("precision", None, "Precision"),
        "recall_per_class": ("recall", None, "Recall"),
        "f1_per_class": ("f1", None, "F1"),
    }

    for raw_key, (metric_key, chart_key, metric_name) in metric_specs.items():
        per_image_rows: List[List[float]] = []
        for metrics in per_image_metrics:
            values = metrics.get(raw_key)
            if isinstance(values, list) and values:
                per_image_rows.append([float(v) for v in values])

        means: Optional[np.ndarray[Any, Any]] = None
        stds: Optional[np.ndarray[Any, Any]] = None

        if per_image_rows:
            arr = np.array(per_image_rows, dtype=np.float64)
            if arr.ndim == 1:
                arr = arr.reshape(-1, 1)
            means = arr.mean(axis=0)
            stds = arr.std(axis=0)
        else:
            values = final_metrics.get(raw_key)
            if isinstance(values, list) and values:
                means = np.array([float(v) for v in values], dtype=np.float64)

        if means is None:
            continue

        if len(class_names) < len(means):
            class_names.extend(
                f"Class {index}" for index in range(len(class_names), len(means))
            )
            for name in class_names:
                class_metrics.setdefault(name, {})

        for index, class_name in enumerate(class_names[: len(means)]):
            class_metrics.setdefault(class_name, {})[metric_key] = round(
                float(means[index]), 4
            )

        if chart_key:
            chart_payload: Dict[str, Any] = {
                "classes": class_names[: len(means)],
                "means": [round(float(v), 4) for v in means.tolist()],
                "metric_name": metric_name,
            }
            if stds is not None:
                chart_payload["stds"] = [round(float(v), 4) for v in stds.tolist()]
            chart_payloads[chart_key] = chart_payload

    return {
        "classes": class_names,
        "class_metrics": {
            name: metrics for name, metrics in class_metrics.items() if metrics
        },
        "chart_data": chart_payloads,
    }


def _load_segmentation_metrics_sync(
    task_id: str, model_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    uploads_dir = Config.get_uploads_dir()

    candidates: list[Path] = []

    if model_dir is not None:
        candidates.append(model_dir / "metrics.json")

    candidates.append(uploads_dir / task_id / "checkpoints" / "metrics.json")

    models_dir = uploads_dir / "models"
    if models_dir.exists():
        for md in models_dir.iterdir():
            if md.is_dir() and task_id in md.name:
                candidates.append(md / "metrics.json")

    for candidate in candidates:
        if candidate.exists():
            with open(candidate, "r") as f:
                return json.load(f)

    return None


def _render_metric_curve_sync(
    metric_name: str,
    train_values: list[Any],
    val_values: list[Any],
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
        ax.set_title(
            title or f"{metric_name} Curve", fontsize=28, fontweight="bold", pad=20
        )
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


def _extract_metric_series(metrics_list: list[Any], metric_name: str) -> list[Any]:
    """Extract a specific metric's values across epochs from a list of per-epoch metric dicts."""
    return [m.get(metric_name, 0.0) for m in metrics_list if isinstance(m, dict)]


def _is_multiclass_segmentation(
    class_names: Optional[List[str]],
    metrics_payloads: List[Optional[Dict[str, Any]]],
) -> bool:
    if class_names and len(class_names) > 1:
        return True

    for metrics in metrics_payloads:
        if not isinstance(metrics, dict):
            continue
        if "miou" in metrics:
            return True
        iou_per_class = metrics.get("iou_per_class")
        if isinstance(iou_per_class, list) and len(iou_per_class) > 1:
            return True

    return False


def _calculate_segmentation_bootstrap_ci(
    per_image_metrics: List[Dict[str, Any]],
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
        return {
            "metrics_ci": {},
            "n_bootstrap": n_bootstrap,
            "confidence_level": confidence_level,
        }

    primary_metric_key = (
        "miou" if _is_multiclass_segmentation(None, per_image_metrics) else "iou"
    )
    supported_metric_keys = [
        primary_metric_key,
        "dice",
        "accuracy",
        "precision",
        "recall",
        "f1",
    ]
    requested_metric_keys = set(requested_metrics)
    if primary_metric_key == "miou" and "iou" in requested_metric_keys:
        requested_metric_keys.add("miou")
    if primary_metric_key == "iou" and "miou" in requested_metric_keys:
        requested_metric_keys.add("iou")

    target_keys = [
        key
        for key in supported_metric_keys
        if key in requested_metric_keys
        and any(
            _resolve_segmentation_metric_value(m, key) is not None
            for m in per_image_metrics
        )
    ]

    if not target_keys:
        return {
            "metrics_ci": {},
            "n_bootstrap": n_bootstrap,
            "confidence_level": confidence_level,
        }

    # Build arrays for fast vectorised bootstrap
    arrays: Dict[str, np.ndarray[Any, Any]] = {}
    for key in target_keys:
        arrays[key] = np.array(
            [
                _resolve_segmentation_metric_value(m, key) or 0.0
                for m in per_image_metrics
            ],
            dtype=np.float64,
        )

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
    p_start, p_ci_start, p_ci_end = unpack_progress_config(progress_config)
    task_id = task.task_id
    fallback_model_classes: List[Any] = []

    trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
    trained_model = trained_models[0] if trained_models else None

    model_dir: Optional[Path] = None
    if trained_model is not None and trained_model.model_path is not None:
        model_dir = Path(str(trained_model.model_path)).parent

    # Load training metrics from metrics.json
    seg_metrics = await asyncio.to_thread(
        _load_segmentation_metrics_sync, task_id, model_dir
    )

    if not seg_metrics:
        if trained_model:
            fallback_model_classes = trained_model.classes or []
            seg_metrics = {
                "best_val_metrics": trained_model.val_metrics or {},
                "history": {
                    "train_loss": (trained_model.train_metrics or {}).get("loss", []),
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
                "Ensure the training has completed successfully.",
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
    # ----------------------------------------------------------------
    # Query per-image metrics from AIResult records for bootstrap CI
    # These are populated by _run_inference_patch_segmentation
    # ----------------------------------------------------------------
    per_image_metrics: List[Dict[str, Any]] = []

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
        logger.info(
            f"Segmentation analysis for task {task_id}: using {len(test_wsi_ids)} test set images"
        )
    else:
        logger.info(
            f"Segmentation analysis for task {task_id}: no test set found, using all images"
        )

    ai_result = await db.execute(query)
    ai_rows = ai_result.scalars().all()

    for row in ai_rows:
        # Per-image metrics are stored in probs (primary) or extra_metadata.metrics
        metrics_dict = row.probs or {}
        if not metrics_dict and row.extra_metadata:
            metrics_dict = row.extra_metadata.get("metrics", {})
        if metrics_dict and any(k in metrics_dict for k in ("iou", "dice", "accuracy")):
            per_image_metrics.append(metrics_dict)

    logger.info(
        f"Segmentation analysis: loaded {len(per_image_metrics)} per-image metric records from AIResult"
    )

    class_names = _resolve_segmentation_class_names(
        task, seg_metrics, final_metrics, ai_rows, fallback_model_classes
    )
    primary_metric_key = (
        "miou"
        if _is_multiclass_segmentation(class_names, [final_metrics, *per_image_metrics])
        else "iou"
    )
    primary_metric_label = "mIoU" if primary_metric_key == "miou" else "IoU"

    summary_metrics = {}
    primary_metric_value = _resolve_segmentation_metric_value(
        final_metrics, primary_metric_key
    )
    if primary_metric_value is not None:
        summary_metrics[primary_metric_key] = round(primary_metric_value, 4)
    for key in ("dice", "accuracy", "precision", "recall", "f1"):
        if key in final_metrics:
            summary_metrics[key] = final_metrics[key]

    if progress_callback:
        await progress_callback(p_start + 10)

    class_analysis = _build_segmentation_class_metrics(
        class_names,
        per_image_metrics,
        final_metrics,
    )

    # Override summary_metrics with mean of per-image metrics if available
    if per_image_metrics:
        for key in (
            primary_metric_key,
            "dice",
            "accuracy",
            "precision",
            "recall",
            "f1",
        ):
            values = [
                _resolve_segmentation_metric_value(m, key) for m in per_image_metrics
            ]
            values = [value for value in values if value is not None]
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
        else (
            request.metrics if getattr(request, "compute_bootstrap_ci", False) else []
        )
    )

    if ci_metrics and per_image_metrics:
        logger.info(
            f"Computing segmentation bootstrap 95% CI for task {task_id} "
            f"with {len(per_image_metrics)} images, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()
        bootstrap_progress_sync = make_bootstrap_progress_sync(
            progress_callback, p_ci_start, p_ci_end, loop
        )
        bootstrap_ci_result = await loop.run_in_executor(
            None,
            functools.partial(
                _calculate_segmentation_bootstrap_ci,
                per_image_metrics,
                ci_metrics,
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

    analysis_dir, timestamp = make_analysis_dir(task_id)

    # Extract random seed
    random_seed = _get_random_seed_from_task(task)

    # Save summary
    summary = {
        "task_id": task_id,
        "task_type": _canonical_analysis_task_type(task),
        "timestamp": utc_timestamp_z(),
        "description": request.description,
        "num_samples": len(ai_rows),
        "num_with_ground_truth": len(per_image_metrics),
        "metrics_source": metrics_source,
        "best_epoch": best_epoch,
        "metrics": summary_metrics,
        "classes": class_analysis["classes"],
        "class_metrics": class_analysis["class_metrics"],
        "best_val_metrics": best_val_metrics,
        "test_metrics": test_metrics,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "random_seed": random_seed,
        "submitted_by": submitted_by,
        "num_images": len(ai_rows),
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
        chart_gen_tasks.append(
            (
                "loss_curve",
                run_chart_in_process(
                    _render_loss_chart_sync, loss_data, analysis_dir / "loss_curve.png"
                ),
            )
        )

    # IoU curve
    if "iou_curve" in request.charts and val_metrics_list:
        train_iou = _extract_metric_series(train_metrics_list, primary_metric_key)
        val_iou = _extract_metric_series(val_metrics_list, primary_metric_key)
        if not train_iou and primary_metric_key == "miou":
            train_iou = _extract_metric_series(train_metrics_list, "iou")
        if not val_iou and primary_metric_key == "miou":
            val_iou = _extract_metric_series(val_metrics_list, "iou")
        if train_iou or val_iou:
            chart_data["iou_curve"] = {
                "epochs": list(range(1, max(len(train_iou), len(val_iou)) + 1)),
                "train_values": train_iou,
                "val_values": val_iou,
                "metric_name": primary_metric_label,
            }
            chart_gen_tasks.append(
                (
                    "iou_curve",
                    run_chart_in_process(
                        _render_metric_curve_sync,
                        primary_metric_label,
                        train_iou,
                        val_iou,
                        analysis_dir / "iou_curve.png",
                        f"{primary_metric_label} (Intersection over Union) Curve",
                        primary_metric_label,
                    ),
                )
            )

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
            chart_gen_tasks.append(
                (
                    "dice_curve",
                    run_chart_in_process(
                        _render_metric_curve_sync,
                        "Dice",
                        train_dice,
                        val_dice,
                        analysis_dir / "dice_curve.png",
                        "Dice Coefficient Curve",
                        "Dice",
                    ),
                )
            )

    if "per_class_iou" in request.charts and class_analysis["chart_data"].get(
        "per_class_iou"
    ):
        chart_data["per_class_iou"] = class_analysis["chart_data"]["per_class_iou"]

    if "per_class_dice" in request.charts and class_analysis["chart_data"].get(
        "per_class_dice"
    ):
        chart_data["per_class_dice"] = class_analysis["chart_data"]["per_class_dice"]

    chart_paths.update(await run_chart_tasks(chart_gen_tasks))

    if progress_callback:
        await progress_callback(90)

    # Save detailed per-image results for download/export parity with other task types.
    per_image_details = []
    for row in ai_rows:
        extra_metadata = row.extra_metadata or {}
        metrics_dict = row.probs or {}
        if not metrics_dict and extra_metadata:
            metrics_dict = extra_metadata.get("metrics", {})

        row_class_names = _normalize_segmentation_class_names(
            extra_metadata.get("class_names")
        )
        per_image_details.append(
            {
                "wsi_id": row.wsi_id,
                "filename": None,
                "has_ground_truth": bool(extra_metadata.get("has_ground_truth", False)),
                "metrics": metrics_dict,
                "num_classes": extra_metadata.get("num_classes"),
                "class_names": row_class_names or class_names,
                "image_size": extra_metadata.get("image_size"),
            }
        )

    # Save summary with chart paths and data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    await fill_wsi_filenames(db, per_image_details)

    await asyncio.to_thread(
        _write_json_sync,
        analysis_dir / "results.json",
        {
            "task_id": task_id,
            "task_type": _canonical_analysis_task_type(task),
            "num_samples": len(ai_rows),
            "num_with_ground_truth": len(per_image_metrics),
            "classes": class_names,
            "metrics": summary_metrics,
            "class_metrics": class_analysis["class_metrics"],
            "best_val_metrics": best_val_metrics,
            "test_metrics": test_metrics,
            "metrics_source": metrics_source,
            "chart_data": chart_data,
            "wsi_results": per_image_details,
        },
    )

    logger.info(
        f"Segmentation analysis completed for task {task_id}, saved to {analysis_dir}"
    )

    return await make_analysis_result(task_id, timestamp, analysis_dir, summary, chart_paths)
