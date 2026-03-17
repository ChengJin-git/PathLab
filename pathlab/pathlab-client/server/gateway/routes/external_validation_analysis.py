"""
External Validation Analysis Module

Handles running analysis for external validation tasks, including both
classification and survival analysis with bootstrap CI and chart generation.
"""

import asyncio
import functools
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, TypedDict

from fastapi import HTTPException

from backend.common.config import Config
from backend.database.repositories import (
    TrainedModelRepository,
    TrainingTaskRepository,
    WSIRepository,
)

from .analysis_helpers import _get_random_seed_from_task
from .analysis_metrics import (
    _calculate_all_metrics,
    _calculate_bootstrap_ci,
    _calculate_integrated_brier_score,
    _calculate_survival_bootstrap_ci,
    _generate_confusion_matrix_chart,
    _generate_roc_chart,
    _generate_km_analysis,
    _get_kfold_metrics,
    run_chart_in_process,
    _write_json_sync,
)

logger = logging.getLogger(__name__)


EXTRACTOR_EMBED_DIM: Dict[str, int] = {
    "resnet50": 2048,
    "vit_l_16": 1024,
    "conch": 512,
    "uni": 1024,
    "uni2": 1536,
    "virchow": 1280,
    "virchow2": 1280,
    "plip": 512,
    "phikon": 1024,
    "phikon2": 1024,
    "patho_clip": 512,
    "openmidnight": 1536,
    "conch15": 512,
    "H-Optimus-1": 1536,
    "H-Optimus-0": 1536,
    "mSTAR": 1024,
    "GPFM": 1024,
}


class ExtvalModelInfo(TypedDict):
    data_type: str
    task_type: str
    classes: List[str]
    feature_extractor: str
    wsi_ids: Set[str]
    source_dataset_id: Optional[str]
    seg_task_architecture: str
    seg_task_backbone: str
    seg_saved_architecture: str
    seg_saved_backbone: str
    segmentation_labels: List[str]
    training_dataset_ids: Set[str]


class ExtvalDatasetInfo(TypedDict):
    dataset_id: str
    data_type: str
    task_type: str
    aggregation_level: str
    labels: List[str]
    segmentation_labels: List[str]
    feature_extractors: List[str]
    wsi_ids: Set[str]


def _is_extval_segmentation_task(task_type: Optional[str]) -> bool:
    return task_type in ("segmentation", "patch_segmentation")


def _norm_labels(labels: List[str]) -> List[str]:
    return sorted({str(lbl).strip() for lbl in labels if str(lbl).strip()})


def check_extval_compatibility(
    model_info: ExtvalModelInfo,
    dataset_info: ExtvalDatasetInfo,
) -> Optional[str]:
    model_data_type = model_info["data_type"]
    model_task_type = model_info["task_type"]
    model_is_survival = model_task_type in ("wsi_survival", "survival")
    model_is_seg = _is_extval_segmentation_task(model_task_type)

    ds_data_type = dataset_info["data_type"]
    ds_task_type = dataset_info["task_type"]
    ds_is_survival = ds_task_type in ("wsi_survival", "survival")
    ds_is_seg = _is_extval_segmentation_task(ds_task_type)

    if ds_data_type != model_data_type:
        return (
            f"Data type mismatch: model uses '{model_data_type}' "
            f"but dataset uses '{ds_data_type}'."
        )

    if model_is_survival != ds_is_survival:
        return "Task type mismatch: survival model requires a survival dataset."

    if model_is_seg != ds_is_seg:
        return "Task type mismatch: segmentation model requires a segmentation dataset."

    if model_is_seg:
        if ds_data_type != "patch":
            return "Segmentation external validation requires a patch dataset."
        if dataset_info["aggregation_level"] != "file":
            return "Segmentation external validation requires a file-level dataset."

        seg_task_arch = model_info["seg_task_architecture"]
        seg_task_backbone = model_info["seg_task_backbone"]
        seg_saved_arch = model_info["seg_saved_architecture"]
        seg_saved_backbone = model_info["seg_saved_backbone"]

        if not all(
            [seg_task_arch, seg_task_backbone, seg_saved_arch, seg_saved_backbone]
        ):
            return (
                "Segmentation model architecture metadata is incomplete. "
                "Both architecture and backbone must be defined for external validation."
            )

        if seg_task_arch != seg_saved_arch or seg_task_backbone != seg_saved_backbone:
            return (
                f"Segmentation model metadata mismatch: task config expects "
                f"'{seg_task_arch}/{seg_task_backbone}' but stored model is "
                f"'{seg_saved_arch}/{seg_saved_backbone}'."
            )

        source_ds_id = model_info["source_dataset_id"]
        if not source_ds_id:
            return (
                "Cannot determine the source training dataset for this segmentation model. "
                "External validation requires a source model trained on a single dataset."
            )

        if dataset_info["dataset_id"] == source_ds_id:
            return "Target dataset must differ from the source training dataset."

        model_seg_labels = _norm_labels(model_info["segmentation_labels"])
        ds_seg_labels = _norm_labels(dataset_info["segmentation_labels"])

        if not model_seg_labels or not ds_seg_labels:
            return (
                "Segmentation label metadata is incomplete. "
                "Both the model and target dataset must define labels."
            )

        if model_seg_labels != ds_seg_labels:
            missing = sorted(set(model_seg_labels) - set(ds_seg_labels))
            extra = sorted(set(ds_seg_labels) - set(model_seg_labels))
            parts = ["Segmentation label mismatch."]
            if missing:
                parts.append(f"Model labels not in dataset: {missing}.")
            if extra:
                parts.append(f"Dataset labels not in model: {extra}.")
            return " ".join(parts)

        ds_wsi_ids = dataset_info["wsi_ids"]
        if (
            model_info["wsi_ids"]
            and ds_wsi_ids
            and (model_info["wsi_ids"] & ds_wsi_ids)
        ):
            return "Training data overlap: target dataset shares WSIs with the training set."

        return None

    if not model_is_survival:
        model_classes = set(_norm_labels(model_info["classes"]))
        ds_labels = set(_norm_labels(dataset_info["labels"]))
        if model_classes != ds_labels:
            missing = sorted(model_classes - ds_labels)
            extra = sorted(ds_labels - model_classes)
            parts = ["Label mismatch between model and dataset."]
            if missing:
                parts.append(f"Model classes not in dataset: {missing}.")
            if extra:
                parts.append(f"Dataset labels not in model: {extra}.")
            return " ".join(parts)

    if model_data_type == "wsi":
        model_extractor = model_info["feature_extractor"]
        model_embed_dim = EXTRACTOR_EMBED_DIM.get(model_extractor, 0)
        if model_extractor and model_embed_dim > 0:
            ds_extractors = dataset_info["feature_extractors"]
            if ds_extractors:
                has_same_dim = any(
                    EXTRACTOR_EMBED_DIM.get(e, 0) == model_embed_dim
                    for e in ds_extractors
                )
                if not has_same_dim:
                    return "Feature extractor embedding dimensions do not match."

    ds_wsi_ids = dataset_info["wsi_ids"]
    if model_info["wsi_ids"] and ds_wsi_ids and (model_info["wsi_ids"] & ds_wsi_ids):
        return (
            "Training data overlap: target dataset shares WSIs with the training set."
        )

    if dataset_info["dataset_id"] in model_info["training_dataset_ids"]:
        return "Target dataset was part of the model's training data."

    return None


def _normalize_segmentation_class_names(labels: List[Any]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for label in labels or []:
        value = str(label).strip()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _build_segmentation_class_summary(
    class_names: List[str],
    results_with_gt: List[Dict[str, Any]],
) -> Dict[str, Any]:
    import numpy as np

    metric_specs = {
        "iou_per_class": ("iou", "per_class_iou", "IoU"),
        "dice_per_class": ("dice", "per_class_dice", "Dice"),
        "precision_per_class": ("precision", None, "Precision"),
        "recall_per_class": ("recall", None, "Recall"),
        "f1_per_class": ("f1", None, "F1"),
    }

    class_metrics: Dict[str, Dict[str, float]] = {name: {} for name in class_names}
    chart_data: Dict[str, Dict[str, Any]] = {}
    per_class_data: Dict[str, List[Dict[str, float]]] = {}

    for raw_key, (metric_key, chart_key, metric_name) in metric_specs.items():
        rows = []
        for result in results_with_gt:
            values = (result.get("metrics") or {}).get(raw_key)
            if isinstance(values, list) and values:
                rows.append([float(v) for v in values])

        if not rows:
            continue

        arr = np.array(rows, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        means = arr.mean(axis=0)
        stds = arr.std(axis=0)

        if len(class_names) < len(means):
            class_names.extend(
                f"Class {index}" for index in range(len(class_names), len(means))
            )
            for name in class_names:
                class_metrics.setdefault(name, {})

        per_class_entries: List[Dict[str, float]] = []
        for index, class_name in enumerate(class_names[: len(means)]):
            mean_value = round(float(means[index]), 4)
            std_value = round(float(stds[index]), 4)
            class_metrics.setdefault(class_name, {})[metric_key] = mean_value
            per_class_entries.append(
                {
                    "class_index": index,
                    "class_name": class_name,
                    "mean": mean_value,
                    "std": std_value,
                }
            )

        per_class_data[raw_key] = per_class_entries
        if chart_key:
            chart_data[chart_key] = {
                "classes": class_names[: len(means)],
                "means": [round(float(v), 4) for v in means.tolist()],
                "stds": [round(float(v), 4) for v in stds.tolist()],
                "metric_name": metric_name,
            }

    return {
        "classes": class_names,
        "class_metrics": {
            name: metrics for name, metrics in class_metrics.items() if metrics
        },
        "chart_data": chart_data,
        "per_class_data": per_class_data,
    }


def _resolve_segmentation_primary_metric_key(
    class_names: List[str],
    results_with_gt: List[Dict[str, Any]],
) -> str:
    if len(class_names) > 1:
        return "miou"

    for result in results_with_gt:
        metrics = result.get("metrics") or {}
        if "miou" in metrics:
            return "miou"
        iou_per_class = metrics.get("iou_per_class")
        if isinstance(iou_per_class, list) and len(iou_per_class) > 1:
            return "miou"

    return "iou"


def _resolve_segmentation_metric_value(
    metrics: Dict[str, Any], metric_key: str
) -> Optional[float]:
    value = metrics.get(metric_key)
    if value is None and metric_key == "miou":
        value = metrics.get("iou")
    elif value is None and metric_key == "iou":
        value = metrics.get("miou")
    return float(value) if value is not None else None


async def _run_external_validation_analysis(
    task, request, db, progress_callback=None, progress_config=None, submitted_by=None
):
    """Run analysis for external validation task.

    Reads results from extval_{task_id}_result.json files.
    Supports both classification and survival tasks.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    task_id = task.task_id

    # Get model_config to find metadata
    model_config = task.model_config or {}

    # First pass: detect task type from result files
    # NOTE: Directory iteration + file I/O is synchronous — run in thread to avoid blocking event loop
    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    def _sync_detect_task_type():
        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    result_file = wsi_dir / f"extval_{task_id}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, "r") as f:
                                data = json.load(f)
                                return data.get("task_type", "classification")
                        except Exception:
                            continue
        return None

    detected_task_type = await asyncio.to_thread(_sync_detect_task_type)

    # Route to appropriate analysis based on task type
    if detected_task_type == "survival":
        return await _run_external_validation_survival_analysis(
            task,
            request,
            db,
            model_config,
            progress_callback,
            progress_config,
            submitted_by,
        )
    elif detected_task_type == "patch_segmentation":
        return await _run_external_validation_segmentation_analysis(
            task,
            request,
            db,
            model_config,
            progress_callback,
            progress_config,
            submitted_by,
        )
    else:
        return await _run_external_validation_classification_analysis(
            task,
            request,
            db,
            model_config,
            progress_callback,
            progress_config,
            submitted_by,
        )


async def _run_external_validation_survival_analysis(
    task,
    request,
    db,
    model_config,
    progress_callback=None,
    progress_config=None,
    submitted_by=None,
):
    """Run survival analysis for external validation task.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    # Default progress ranges if not provided
    if progress_config is None:
        progress_config = {"start": 20, "ci_start": 30, "ci_end": 95, "has_ci": True}
    p_start = progress_config.get("start", 20)
    p_ci_start = progress_config.get("ci_start", 30)
    p_ci_end = progress_config.get("ci_end", 95)

    task_id = task.task_id
    dataset_id = model_config.get("dataset_id")
    model_task_id = model_config.get("model_task_id")

    # Load results from ai_results directory
    # NOTE: This iterates through potentially thousands of directories and loads JSON files.
    # Run in thread to avoid blocking the event loop.
    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    def _sync_load_survival_results():
        _risks = []
        _times = []
        _events = []
        _surv_probs = []
        _wsi_results = []
        _bin_edges = None
        _is_kfold = False
        _num_folds = None
        _aggregation_level = "file"
        _metadata_read = False

        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    result_file = wsi_dir / f"extval_{task_id}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, "r") as f:
                                data = json.load(f)
                                if data.get("validation_task_id") == task_id:
                                    if not _metadata_read:
                                        _is_kfold = data.get("is_kfold", False)
                                        _num_folds = data.get("num_folds")
                                        _aggregation_level = data.get(
                                            "aggregation_level", "file"
                                        )
                                        _metadata_read = True

                                    risk_score = data.get("risk_score")
                                    event_time = data.get("event_time")
                                    event_status = data.get("event_status")

                                    if (
                                        risk_score is not None
                                        and event_time is not None
                                    ):
                                        _risks.append(risk_score)
                                        _times.append(event_time)
                                        _events.append(
                                            event_status
                                            if event_status is not None
                                            else 0
                                        )

                                        if data.get("surv_probs"):
                                            _surv_probs.append(data["surv_probs"])

                                        if _bin_edges is None and data.get("bin_edges"):
                                            _bin_edges = data["bin_edges"]

                                        _wsi_results.append(
                                            {
                                                "wsi_id": data.get("wsi_id"),
                                                "filename": None,
                                                "case_id": data.get(
                                                    "case_id", data.get("wsi_id")
                                                ),
                                                "risk_score": risk_score,
                                                "event_time": event_time,
                                                "event_status": event_status,
                                                "surv_probs": data.get("surv_probs"),
                                            }
                                        )
                        except Exception as e:
                            logger.warning(
                                f"Failed to load result from {result_file}: {e}"
                            )
                            continue

        return (
            _risks,
            _times,
            _events,
            _surv_probs,
            _wsi_results,
            _bin_edges,
            _is_kfold,
            _num_folds,
            _aggregation_level,
        )

    (
        risks,
        times,
        events,
        surv_probs,
        wsi_results,
        bin_edges,
        is_kfold,
        num_folds,
        aggregation_level,
    ) = await asyncio.to_thread(_sync_load_survival_results)

    if not risks:
        raise HTTPException(
            status_code=400,
            detail="No survival results found for this external validation task",
        )

    is_case_level = aggregation_level == "case"
    logger.info(
        f"External survival analysis for task {task_id}: aggregation_level={aggregation_level}, "
        f"is_case_level={is_case_level}, is_kfold={is_kfold}, num_folds={num_folds}"
    )

    # For case-level: aggregate results by case_id (one case = one sample)
    if is_case_level and wsi_results:
        case_results_map: Dict[str, Dict[str, Any]] = {}
        for res in wsi_results:
            case_id = res["case_id"]
            if case_id not in case_results_map:
                # Use first slide's result as the case result
                case_results_map[case_id] = res

        # Replace with case-level aggregated data
        wsi_results = list(case_results_map.values())
        risks = [r["risk_score"] for r in wsi_results]
        times = [r["event_time"] for r in wsi_results]
        events = [r["event_status"] for r in wsi_results]
        surv_probs = [r["surv_probs"] for r in wsi_results if r.get("surv_probs")]

        logger.info(
            f"Case-level external survival analysis: aggregated to {len(case_results_map)} cases"
        )

    # Compute C-Index using scikit-survival
    import numpy as np
    from sksurv.metrics import concordance_index_censored

    risks_arr = np.array(risks, dtype=float)
    times_arr = np.array(times, dtype=float)
    events_arr = np.array(events, dtype=bool)

    # Update progress - data loaded (use dynamic start + small offset)
    if progress_callback:
        await progress_callback(p_start + 3)

    try:
        c_index, _, _, _, _ = concordance_index_censored(
            events_arr, times_arr, risks_arr
        )
    except Exception as e:
        logger.warning(f"Failed to compute C-Index: {e}")
        c_index = None

    metrics = {"c_index": c_index}

    # Calculate Integrated Brier Score if requested
    if "integrated_brier_score" in request.metrics:
        ibs = _calculate_integrated_brier_score(times, events, surv_probs, bin_edges)
        if ibs is not None:
            metrics["integrated_brier_score"] = round(ibs, 4)

    # Update progress - metrics calculated (use ci_start)
    if progress_callback:
        await progress_callback(p_ci_start)

    # Calculate bootstrap confidence intervals if requested
    # Support both new bootstrap_ci_metrics list and legacy compute_bootstrap_ci flag
    # NOTE: Bootstrap CI is CPU-intensive, run in thread pool to avoid blocking event loop
    bootstrap_ci_result = None
    ci_metrics = (
        request.bootstrap_ci_metrics
        if request.bootstrap_ci_metrics
        else (request.metrics if request.compute_bootstrap_ci else [])
    )
    if ci_metrics:
        logger.info(
            f"Computing bootstrap 95% CI for external validation survival task {task_id}, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()

        # Create thread-safe progress callback for bootstrap CI (ci_start -> ci_end)
        ci_range = p_ci_end - p_ci_start

        def bootstrap_progress_sync(fraction: float):
            if progress_callback:
                # Map bootstrap progress (0.0-1.0) to overall progress (ci_start -> ci_end)
                overall_progress = int(p_ci_start + fraction * ci_range)
                loop.call_soon_threadsafe(
                    lambda p=overall_progress: asyncio.create_task(progress_callback(p))
                )

        bootstrap_ci_result = await loop.run_in_executor(
            None,  # Use default thread pool
            functools.partial(
                _calculate_survival_bootstrap_ci,
                risks,
                times,
                events,
                surv_probs,
                bin_edges,
                ci_metrics,
                progress_callback=bootstrap_progress_sync,
            ),
        )
        if bootstrap_ci_result:
            logger.info(f"Bootstrap CI calculated: {bootstrap_ci_result['metrics_ci']}")

    # Update progress - bootstrap CI done (or skipped)
    if progress_callback:
        await progress_callback(p_ci_end)

    # Create analysis output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Generate charts — run KM image generation and kfold metrics loading in parallel
    chart_paths = {}
    chart_data = {}

    km_coro = None
    km_path = None
    if "km_curve" in request.charts and len(risks) > 0:
        km_path = analysis_dir / "km_curve.png"
        include_km_ci = "c_index" in ci_metrics
        km_coro = run_chart_in_process(
            _generate_km_analysis, times, events, risks, km_path, include_km_ci
        )

    # Note: loss_curve is skipped for external validation (training-only)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Check for K-Fold training metrics from the original model — run in parallel with KM chart
    kfold_coro = _get_kfold_metrics(model_task_id) if model_task_id else None

    parallel_tasks = []
    task_names = []
    for name, coro in [("km", km_coro), ("kfold", kfold_coro)]:
        if coro is not None:
            parallel_tasks.append(coro)
            task_names.append(name)

    if parallel_tasks:
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        result_map = {}
        for name, result in zip(task_names, parallel_results):
            if isinstance(result, Exception):
                logger.error(f"Parallel task '{name}' failed: {result}")
                result_map[name] = None
            else:
                result_map[name] = result
    else:
        result_map = {}

    km_data = result_map.get("km")
    if km_data:
        chart_data["km_curve"] = km_data
        chart_paths["km_curve"] = str(km_path)

    kfold_metrics = result_map.get("kfold")

    # Save summary
    summary = {
        "task_id": task_id,
        "task_type": "external_validation_survival",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "description": request.description,
        "num_samples": len(risks),
        "metrics": metrics,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "dataset_id": dataset_id,
        "model_id": model_config.get("model_id"),
        "model_task_id": model_task_id,
        "aggregation_level": aggregation_level,
        "is_kfold": is_kfold,
        "num_folds": num_folds,
        "chart_paths": chart_paths,
        "chart_data": chart_data,
        "random_seed": random_seed,  # Invisible watermark for model provenance tracking
        "submitted_by": submitted_by,
    }

    # Add bootstrap CI if computed
    if bootstrap_ci_result:
        summary["bootstrap_ci"] = bootstrap_ci_result

    # Add K-Fold training info if available
    if kfold_metrics:
        summary["kfold_training"] = kfold_metrics

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    extval_surv_ids = [
        r["wsi_id"] for r in wsi_results if r.get("wsi_id") and not r.get("filename")
    ]
    if extval_surv_ids:
        extval_surv_map = await WSIRepository.get_by_ids(db, extval_surv_ids)
        for r in wsi_results:
            if not r.get("filename") and r.get("wsi_id"):
                wsi_obj = extval_surv_map.get(r["wsi_id"])
                r["filename"] = (wsi_obj.original_filename if wsi_obj else None) or r[
                    "wsi_id"
                ]

    await asyncio.to_thread(
        _write_json_sync,
        analysis_dir / "results.json",
        {"wsi_results": wsi_results, "metrics": metrics},
    )

    logger.info(
        f"External validation survival analysis completed for task {task_id}, saved to {analysis_dir}"
    )

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths,
    }


async def _run_external_validation_segmentation_analysis(
    task,
    request,
    db,
    model_config,
    progress_callback=None,
    progress_config=None,
    submitted_by=None,
):
    """Run segmentation analysis for external validation task.

    Reads per-image segmentation results from extval_{task_id}_result.json files,
    aggregates metrics (IoU, Dice, Accuracy, Precision, Recall), and generates
    per-class bar charts.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    import numpy as np
    from .analysis_helpers import _get_random_seed_from_task

    if progress_config is None:
        progress_config = {"start": 20, "ci_start": 50, "ci_end": 90, "has_ci": False}
    p_start = progress_config.get("start", 20)

    task_id = task.task_id
    dataset_id = model_config.get("dataset_id")
    model_task_id = model_config.get("model_task_id")

    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    def _sync_load_segmentation_results():
        _image_results = []
        _num_classes = None
        _class_names: List[str] = []

        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    result_file = wsi_dir / f"extval_{task_id}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, "r") as f:
                                data = json.load(f)
                            if (
                                data.get("validation_task_id") == task_id
                                and data.get("task_type") == "patch_segmentation"
                            ):
                                _image_results.append(data)
                                if _num_classes is None:
                                    _num_classes = data.get("num_classes", 1)
                                if not _class_names:
                                    _class_names = _normalize_segmentation_class_names(
                                        data.get("class_names", [])
                                    )
                        except Exception as e:
                            logger.warning(
                                f"Failed to load segmentation result from {result_file}: {e}"
                            )
                            continue

        return _image_results, _num_classes, _class_names

    image_results, num_classes, class_names = await asyncio.to_thread(
        _sync_load_segmentation_results
    )

    if not image_results:
        raise HTTPException(
            status_code=400,
            detail="No segmentation results found for this external validation task",
        )

    if not class_names:
        model_task = (
            await TrainingTaskRepository.get_by_id(db, model_task_id)
            if model_task_id
            else None
        )
        trained_model = (
            await TrainedModelRepository.get_by_id(db, model_config.get("model_id"))
            if model_config.get("model_id")
            else None
        )
        class_names = _normalize_segmentation_class_names(
            (model_task.classes if model_task else None)
            or (trained_model.classes if trained_model else None)
            or []
        )

    if progress_callback:
        await progress_callback(p_start + 5)

    # Aggregate metrics across all images
    has_metrics = any(
        r.get("has_ground_truth") and r.get("metrics") for r in image_results
    )

    metrics = {}
    per_class_summary = {
        "classes": class_names,
        "class_metrics": {},
        "chart_data": {},
        "per_class_data": {},
    }

    if has_metrics:
        results_with_gt = [
            r for r in image_results if r.get("has_ground_truth") and r.get("metrics")
        ]
        primary_metric_key = _resolve_segmentation_primary_metric_key(
            class_names, results_with_gt
        )
        metric_keys = [
            primary_metric_key,
            "dice",
            "accuracy",
            "precision",
            "recall",
            "f1",
        ]

        for key in metric_keys:
            values = [
                value
                for r in results_with_gt
                for value in [_resolve_segmentation_metric_value(r["metrics"], key)]
                if value is not None
            ]
            if values:
                metrics[key] = {
                    "mean": float(np.mean(values)),
                    "std": float(np.std(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "median": float(np.median(values)),
                    "count": len(values),
                }
        per_class_summary = _build_segmentation_class_summary(
            class_names, results_with_gt
        )
        class_names = per_class_summary["classes"]

    if progress_callback:
        await progress_callback(60)

    # Create analysis output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    random_seed = _get_random_seed_from_task(task)

    # Generate chart data for frontend
    chart_data = {}
    chart_paths = {}

    if "per_class_iou" in request.charts and per_class_summary["chart_data"].get(
        "per_class_iou"
    ):
        chart_data["per_class_iou"] = per_class_summary["chart_data"]["per_class_iou"]

    if "per_class_dice" in request.charts and per_class_summary["chart_data"].get(
        "per_class_dice"
    ):
        chart_data["per_class_dice"] = per_class_summary["chart_data"]["per_class_dice"]

    if progress_callback:
        await progress_callback(80)

    # Build summary
    # Flatten metrics for top-level display (mean values)
    flat_metrics = {}
    for key, stat in metrics.items():
        flat_metrics[key] = stat["mean"]

    num_with_ground_truth = sum(1 for r in image_results if r.get("has_ground_truth"))

    summary = {
        "task_id": task_id,
        "task_type": "segmentation",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "description": request.description,
        "num_samples": len(image_results),
        "num_with_ground_truth": num_with_ground_truth,
        "num_classes": num_classes,
        "classes": class_names,
        "metrics": flat_metrics,
        "class_metrics": per_class_summary["class_metrics"],
        "metrics_detailed": metrics,
        "per_class_data": per_class_summary["per_class_data"],
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "dataset_id": dataset_id,
        "model_id": model_config.get("model_id"),
        "model_task_id": model_task_id,
        "chart_paths": chart_paths,
        "chart_data": chart_data,
        "random_seed": random_seed,
        "submitted_by": submitted_by,
    }

    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    # Save detailed per-image results
    per_image_details = []
    for r in image_results:
        per_image_details.append(
            {
                "wsi_id": r.get("wsi_id"),
                "filename": None,
                "has_ground_truth": r.get("has_ground_truth", False),
                "metrics": r.get("metrics", {}),
                "num_classes": r.get("num_classes"),
                "class_names": r.get("class_names", []),
                "image_size": r.get("image_size"),
            }
        )

    extval_seg_ids = [
        r["wsi_id"]
        for r in per_image_details
        if r.get("wsi_id") and not r.get("filename")
    ]
    if extval_seg_ids:
        extval_seg_map = await WSIRepository.get_by_ids(db, extval_seg_ids)
        for r in per_image_details:
            if not r.get("filename") and r.get("wsi_id"):
                wsi_obj = extval_seg_map.get(r["wsi_id"])
                r["filename"] = (wsi_obj.original_filename if wsi_obj else None) or r[
                    "wsi_id"
                ]

    await asyncio.to_thread(
        _write_json_sync,
        analysis_dir / "results.json",
        {
            "task_id": task_id,
            "task_type": "segmentation",
            "num_samples": len(image_results),
            "num_with_ground_truth": num_with_ground_truth,
            "num_classes": num_classes,
            "classes": class_names,
            "metrics": flat_metrics,
            "class_metrics": per_class_summary["class_metrics"],
            "metrics_detailed": metrics,
            "per_class_data": per_class_summary["per_class_data"],
            "chart_data": chart_data,
            "wsi_results": per_image_details,
        },
    )

    if progress_callback:
        await progress_callback(97)

    logger.info(
        f"External validation segmentation analysis completed for task {task_id}, saved to {analysis_dir}"
    )

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths,
    }


async def _run_external_validation_classification_analysis(
    task,
    request,
    db,
    model_config,
    progress_callback=None,
    progress_config=None,
    submitted_by=None,
):
    """Run classification analysis for external validation task.

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    # Default progress ranges if not provided
    if progress_config is None:
        progress_config = {"start": 20, "ci_start": 30, "ci_end": 95, "has_ci": True}
    p_start = progress_config.get("start", 20)
    p_ci_start = progress_config.get("ci_start", 30)
    p_ci_end = progress_config.get("ci_end", 95)

    task_id = task.task_id
    dataset_id = model_config.get("dataset_id")
    model_task_id = model_config.get("model_task_id")

    # Load results from ai_results directory
    # NOTE: This iterates through potentially thousands of directories and loads JSON files.
    # Run in thread to avoid blocking the event loop.
    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    def _sync_load_classification_results():
        _predictions = []
        _labels = []
        _probs_list = []
        _wsi_results = []
        _is_kfold = False
        _num_folds = None
        _aggregation_level = "file"
        _metadata_read = False

        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    result_file = wsi_dir / f"extval_{task_id}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, "r") as f:
                                data = json.load(f)
                                if data.get(
                                    "validation_task_id"
                                ) == task_id and data.get("pred"):
                                    if not _metadata_read:
                                        _is_kfold = data.get("is_kfold", False)
                                        _num_folds = data.get("num_folds")
                                        _aggregation_level = data.get(
                                            "aggregation_level", "file"
                                        )
                                        _metadata_read = True

                                    _predictions.append(data["pred"])
                                    _labels.append(data.get("ground_truth", "unknown"))
                                    _probs_list.append(data.get("probs", {}))
                                    _wsi_results.append(
                                        {
                                            "wsi_id": data.get("wsi_id"),
                                            "filename": None,
                                            "case_id": data.get(
                                                "case_id", data.get("wsi_id")
                                            ),
                                            "label": data.get(
                                                "ground_truth", "unknown"
                                            ),
                                            "pred": data["pred"],
                                            "correct": data.get("correct"),
                                            "probs": data.get("probs"),
                                        }
                                    )
                        except Exception as e:
                            logger.warning(
                                f"Failed to load result from {result_file}: {e}"
                            )
                            continue

        return (
            _predictions,
            _labels,
            _probs_list,
            _wsi_results,
            _is_kfold,
            _num_folds,
            _aggregation_level,
        )

    (
        predictions,
        labels,
        probs_list,
        wsi_results,
        is_kfold,
        num_folds,
        aggregation_level,
    ) = await asyncio.to_thread(_sync_load_classification_results)

    if not predictions:
        raise HTTPException(
            status_code=400,
            detail="No classification results found for this external validation task",
        )

    is_case_level = aggregation_level == "case"
    logger.info(
        f"External classification analysis for task {task_id}: aggregation_level={aggregation_level}, "
        f"is_case_level={is_case_level}, is_kfold={is_kfold}, num_folds={num_folds}"
    )

    # For case-level: aggregate results by case_id (one case = one sample)
    if is_case_level and wsi_results:
        case_results: Dict[str, Dict[str, Any]] = {}
        for res in wsi_results:
            case_id = res["case_id"]
            if case_id not in case_results:
                # Use first slide's result as the case result
                case_results[case_id] = res

        # Replace predictions/labels with case-level aggregated data
        predictions = [r["pred"] for r in case_results.values()]
        labels = [r["label"] for r in case_results.values()]
        probs_list = [r["probs"] or {} for r in case_results.values()]

        logger.info(
            f"Case-level external classification analysis: aggregated {len(wsi_results)} slides to {len(case_results)} cases"
        )

    # Compute metrics
    all_classes = sorted(set(labels) | set(predictions))
    is_binary = len(all_classes) == 2

    # Build confusion matrix
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    for true_label, pred_label in zip(labels, predictions):
        confusion_matrix[true_label][pred_label] += 1

    # Update progress - data loaded (use dynamic start + small offset)
    if progress_callback:
        await progress_callback(p_start + 3)

    # Calculate metrics
    metrics_result = _calculate_all_metrics(
        labels, predictions, probs_list, all_classes, request.metrics
    )

    # Update progress - metrics calculated (use ci_start)
    if progress_callback:
        await progress_callback(p_ci_start)

    # Calculate bootstrap confidence intervals if requested
    # Support both new bootstrap_ci_metrics list and legacy compute_bootstrap_ci flag
    # NOTE: Bootstrap CI is CPU-intensive, run in thread pool to avoid blocking event loop
    bootstrap_ci_result = None
    ci_metrics = (
        request.bootstrap_ci_metrics
        if request.bootstrap_ci_metrics
        else (request.metrics if request.compute_bootstrap_ci else [])
    )
    if ci_metrics:
        logger.info(
            f"Computing bootstrap 95% CI for external validation task {task_id} with {len(predictions)} samples, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()

        # Create thread-safe progress callback for bootstrap CI (ci_start -> ci_end)
        ci_range = p_ci_end - p_ci_start

        def bootstrap_progress_sync(fraction: float):
            if progress_callback:
                # Map bootstrap progress (0.0-1.0) to overall progress (ci_start -> ci_end)
                overall_progress = int(p_ci_start + fraction * ci_range)
                loop.call_soon_threadsafe(
                    lambda p=overall_progress: asyncio.create_task(progress_callback(p))
                )

        bootstrap_ci_result = await loop.run_in_executor(
            None,  # Use default thread pool
            functools.partial(
                _calculate_bootstrap_ci,
                labels,
                predictions,
                probs_list,
                all_classes,
                ci_metrics,
                progress_callback=bootstrap_progress_sync,
            ),
        )
        logger.info(
            f"Bootstrap CI calculation completed for external validation task {task_id}"
        )

    # Update progress - bootstrap CI done (or skipped)
    if progress_callback:
        await progress_callback(p_ci_end)

    # Create analysis output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Check for K-Fold training metrics from the original model
    kfold_metrics = None
    if model_task_id:
        kfold_metrics = await _get_kfold_metrics(model_task_id)

    # Save summary
    summary = {
        "task_id": task_id,
        "task_type": "external_validation_classification",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "description": request.description,
        "num_samples": len(predictions),
        "classes": all_classes,
        "is_binary": is_binary,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "metrics": metrics_result["metrics"],
        "class_metrics": metrics_result["class_metrics"],
        "dataset_id": dataset_id,
        "model_id": model_config.get("model_id"),
        "model_task_id": model_task_id,
        "aggregation_level": aggregation_level,
        "is_kfold": is_kfold,
        "num_folds": num_folds,
        "random_seed": random_seed,  # Invisible watermark for model provenance tracking
        "submitted_by": submitted_by,
    }

    # Add bootstrap CI if computed
    if bootstrap_ci_result:
        summary["bootstrap_ci"] = bootstrap_ci_result

    # Add K-Fold training info if available
    if kfold_metrics:
        summary["kfold_training"] = kfold_metrics

    # Convert defaultdict → regular dict (defaultdict with lambda is not picklable
    # across processes, and we need to pass it to ProcessPoolExecutor)
    confusion_matrix_plain = {k: dict(v) for k, v in confusion_matrix.items()}

    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    # Save detailed results
    await asyncio.to_thread(
        _write_json_sync,
        analysis_dir / "results.json",
        {
            "wsi_results": wsi_results,
            "confusion_matrix": confusion_matrix_plain,
            "roc_data": metrics_result.get("roc_data", {}),
        },
    )

    # Generate charts and collect chart data for frontend ECharts rendering
    # Phase 1: Prepare ECharts data (fast) and build list of chart generation coroutines
    # Phase 2: Run all chart image generation in parallel via asyncio.gather()
    chart_paths = {}
    chart_data = {}
    chart_gen_tasks = []  # [(chart_name, coroutine), ...]

    if "confusion_matrix" in request.charts:
        # Prepare confusion matrix data for ECharts
        cm_data = []
        for i, true_cls in enumerate(all_classes):
            for j, pred_cls in enumerate(all_classes):
                value = confusion_matrix_plain.get(true_cls, {}).get(pred_cls, 0)
                cm_data.append([j, i, value])
        chart_data["confusion_matrix"] = {"classes": all_classes, "data": cm_data}
        chart_gen_tasks.append(
            (
                "confusion_matrix",
                run_chart_in_process(
                    _generate_confusion_matrix_chart,
                    confusion_matrix_plain,
                    all_classes,
                    analysis_dir / "confusion_matrix.png",
                ),
            )
        )

    if "roc_curve" in request.charts and metrics_result.get("roc_data"):
        # Prepare ROC curve data for ECharts
        roc_chart_data = {}
        roc_ci = bootstrap_ci_result.get("roc_ci", {}) if bootstrap_ci_result else {}
        for cls, data in metrics_result["roc_data"].items():
            roc_chart_data[cls] = {
                "fpr": [p["fpr"] for p in data["points"]],
                "tpr": [p["tpr"] for p in data["points"]],
                "auc": data["auc"],
            }
            if cls in roc_ci:
                roc_chart_data[cls]["fpr_grid"] = roc_ci[cls]["fpr_grid"]
                roc_chart_data[cls]["tpr_lower"] = roc_ci[cls]["tpr_lower"]
                roc_chart_data[cls]["tpr_upper"] = roc_ci[cls]["tpr_upper"]
        chart_data["roc_curve"] = {"classes": all_classes, "data": roc_chart_data}
        chart_gen_tasks.append(
            (
                "roc_curve",
                run_chart_in_process(
                    _generate_roc_chart,
                    metrics_result["roc_data"],
                    all_classes,
                    analysis_dir / "roc_curve.png",
                    roc_ci,
                ),
            )
        )

    # Note: loss_curve is skipped for external validation (training-only)

    # Phase 2: Generate all chart images in parallel (each runs in ProcessPoolExecutor)
    if chart_gen_tasks:
        results = await asyncio.gather(
            *[coro for _, coro in chart_gen_tasks], return_exceptions=True
        )
        for (name, _), result in zip(chart_gen_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Chart generation failed for {name}: {result}")
            elif result:
                chart_paths[name] = str(result)

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

    # Update summary with chart paths and chart data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    logger.info(
        f"External validation classification analysis completed for task {task_id}, saved to {analysis_dir}"
    )

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths,
    }
