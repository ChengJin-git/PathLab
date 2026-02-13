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
from typing import Dict

from fastapi import HTTPException

from backend.common.config import Config

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


async def _run_external_validation_analysis(task, request, db, progress_callback=None, progress_config=None, submitted_by=None):
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
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                return data.get("task_type", "classification")
                        except Exception:
                            continue
        return None

    detected_task_type = await asyncio.to_thread(_sync_detect_task_type)

    # Route to appropriate analysis based on task type
    if detected_task_type == "survival":
        return await _run_external_validation_survival_analysis(task, request, db, model_config, progress_callback, progress_config, submitted_by)
    else:
        return await _run_external_validation_classification_analysis(task, request, db, model_config, progress_callback, progress_config, submitted_by)


async def _run_external_validation_survival_analysis(task, request, db, model_config, progress_callback=None, progress_config=None, submitted_by=None):
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
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                if data.get("validation_task_id") == task_id:
                                    if not _metadata_read:
                                        _is_kfold = data.get("is_kfold", False)
                                        _num_folds = data.get("num_folds")
                                        _aggregation_level = data.get("aggregation_level", "file")
                                        _metadata_read = True

                                    risk_score = data.get("risk_score")
                                    event_time = data.get("event_time")
                                    event_status = data.get("event_status")

                                    if risk_score is not None and event_time is not None:
                                        _risks.append(risk_score)
                                        _times.append(event_time)
                                        _events.append(event_status if event_status is not None else 0)

                                        if data.get("surv_probs"):
                                            _surv_probs.append(data["surv_probs"])

                                        if _bin_edges is None and data.get("bin_edges"):
                                            _bin_edges = data["bin_edges"]

                                        _wsi_results.append({
                                            "wsi_id": data.get("wsi_id"),
                                            "case_id": data.get("case_id", data.get("wsi_id")),
                                            "risk_score": risk_score,
                                            "event_time": event_time,
                                            "event_status": event_status,
                                            "surv_probs": data.get("surv_probs")
                                        })
                        except Exception as e:
                            logger.warning(f"Failed to load result from {result_file}: {e}")
                            continue

        return _risks, _times, _events, _surv_probs, _wsi_results, _bin_edges, _is_kfold, _num_folds, _aggregation_level

    risks, times, events, surv_probs, wsi_results, bin_edges, is_kfold, num_folds, aggregation_level = await asyncio.to_thread(_sync_load_survival_results)

    if not risks:
        raise HTTPException(status_code=400, detail="No survival results found for this external validation task")

    is_case_level = aggregation_level == "case"
    logger.info(f"External survival analysis for task {task_id}: aggregation_level={aggregation_level}, "
                f"is_case_level={is_case_level}, is_kfold={is_kfold}, num_folds={num_folds}")

    # For case-level: aggregate results by case_id (one case = one sample)
    if is_case_level and wsi_results:
        case_results_map: Dict[str, Dict] = {}
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

        logger.info(f"Case-level external survival analysis: aggregated to {len(case_results_map)} cases")

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
    ci_metrics = request.bootstrap_ci_metrics if request.bootstrap_ci_metrics else (request.metrics if request.compute_bootstrap_ci else [])
    if ci_metrics:
        logger.info(f"Computing bootstrap 95% CI for external validation survival task {task_id}, metrics: {ci_metrics}...")
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
                risks, times, events, surv_probs, bin_edges, ci_metrics,
                progress_callback=bootstrap_progress_sync
            )
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
        km_coro = run_chart_in_process(_generate_km_analysis, times, events, risks, km_path, include_km_ci)

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
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
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

    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "summary.json", summary
    )

    # Save detailed results
    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "results.json", {
            "wsi_results": wsi_results,
            "metrics": metrics
        }
    )

    logger.info(f"External validation survival analysis completed for task {task_id}, saved to {analysis_dir}")

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths
    }



async def _run_external_validation_classification_analysis(task, request, db, model_config, progress_callback=None, progress_config=None, submitted_by=None):
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
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                if data.get("validation_task_id") == task_id and data.get("pred"):
                                    if not _metadata_read:
                                        _is_kfold = data.get("is_kfold", False)
                                        _num_folds = data.get("num_folds")
                                        _aggregation_level = data.get("aggregation_level", "file")
                                        _metadata_read = True

                                    _predictions.append(data["pred"])
                                    _labels.append(data.get("ground_truth", "unknown"))
                                    _probs_list.append(data.get("probs", {}))
                                    _wsi_results.append({
                                        "wsi_id": data.get("wsi_id"),
                                        "case_id": data.get("case_id", data.get("wsi_id")),
                                        "label": data.get("ground_truth", "unknown"),
                                        "pred": data["pred"],
                                        "correct": data.get("correct"),
                                        "probs": data.get("probs")
                                    })
                        except Exception as e:
                            logger.warning(f"Failed to load result from {result_file}: {e}")
                            continue

        return _predictions, _labels, _probs_list, _wsi_results, _is_kfold, _num_folds, _aggregation_level

    predictions, labels, probs_list, wsi_results, is_kfold, num_folds, aggregation_level = await asyncio.to_thread(_sync_load_classification_results)

    if not predictions:
        raise HTTPException(status_code=400, detail="No classification results found for this external validation task")

    is_case_level = aggregation_level == "case"
    logger.info(f"External classification analysis for task {task_id}: aggregation_level={aggregation_level}, "
                f"is_case_level={is_case_level}, is_kfold={is_kfold}, num_folds={num_folds}")

    # For case-level: aggregate results by case_id (one case = one sample)
    if is_case_level and wsi_results:
        case_results: Dict[str, Dict] = {}
        for res in wsi_results:
            case_id = res["case_id"]
            if case_id not in case_results:
                # Use first slide's result as the case result
                case_results[case_id] = res

        # Replace predictions/labels with case-level aggregated data
        predictions = [r["pred"] for r in case_results.values()]
        labels = [r["label"] for r in case_results.values()]
        probs_list = [r["probs"] or {} for r in case_results.values()]

        logger.info(f"Case-level external classification analysis: aggregated {len(wsi_results)} slides to {len(case_results)} cases")

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
    ci_metrics = request.bootstrap_ci_metrics if request.bootstrap_ci_metrics else (request.metrics if request.compute_bootstrap_ci else [])
    if ci_metrics:
        logger.info(f"Computing bootstrap 95% CI for external validation task {task_id} with {len(predictions)} samples, metrics: {ci_metrics}...")
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
                labels, predictions, probs_list, all_classes, ci_metrics,
                progress_callback=bootstrap_progress_sync
            )
        )
        logger.info(f"Bootstrap CI calculation completed for external validation task {task_id}")

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
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
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

    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "summary.json", summary
    )

    # Save detailed results
    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "results.json", {
            "wsi_results": wsi_results,
            "confusion_matrix": confusion_matrix_plain,
            "roc_data": metrics_result.get("roc_data", {})
        }
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
        chart_data["confusion_matrix"] = {
            "classes": all_classes,
            "data": cm_data
        }
        chart_gen_tasks.append(("confusion_matrix", run_chart_in_process(
            _generate_confusion_matrix_chart,
            confusion_matrix_plain, all_classes, analysis_dir / "confusion_matrix.png"
        )))

    if "roc_curve" in request.charts and metrics_result.get("roc_data"):
        # Prepare ROC curve data for ECharts
        roc_chart_data = {}
        roc_ci = bootstrap_ci_result.get("roc_ci", {}) if bootstrap_ci_result else {}
        for cls, data in metrics_result["roc_data"].items():
            roc_chart_data[cls] = {
                "fpr": [p["fpr"] for p in data["points"]],
                "tpr": [p["tpr"] for p in data["points"]],
                "auc": data["auc"]
            }
            if cls in roc_ci:
                roc_chart_data[cls]["fpr_grid"] = roc_ci[cls]["fpr_grid"]
                roc_chart_data[cls]["tpr_lower"] = roc_ci[cls]["tpr_lower"]
                roc_chart_data[cls]["tpr_upper"] = roc_ci[cls]["tpr_upper"]
        chart_data["roc_curve"] = {
            "classes": all_classes,
            "data": roc_chart_data
        }
        chart_gen_tasks.append(("roc_curve", run_chart_in_process(
            _generate_roc_chart,
            metrics_result["roc_data"], all_classes, analysis_dir / "roc_curve.png",
            roc_ci
        )))

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
    await asyncio.to_thread(
        _write_json_sync, analysis_dir / "summary.json", summary
    )

    logger.info(f"External validation classification analysis completed for task {task_id}, saved to {analysis_dir}")

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths
    }