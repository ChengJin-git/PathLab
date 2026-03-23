"""
Survival Analysis Module

Handles running survival analysis for AI training tasks, including
C-Index calculation, IBS, bootstrap CI, KM curves, and result persistence.
"""

import asyncio
import functools
import json
import logging
from typing import Dict, List, Optional, Any

from fastapi import HTTPException
from sqlalchemy import select

from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.database.models import TrainingTaskWSI
from backend.database.repositories import TrainingTaskRepository

from .analysis_base import (
    fill_wsi_filenames,
    make_analysis_dir,
    make_analysis_result,
    make_bootstrap_progress_sync,
    unpack_progress_config,
    utc_timestamp_z,
)
from .analysis_helpers import _get_random_seed_from_task
from .analysis_metrics import (
    _calculate_integrated_brier_score,
    _calculate_survival_bootstrap_ci,
    _generate_km_analysis,
    _get_loss_data,
    _get_kfold_metrics,
    run_chart_in_process,
    _write_json_sync,
)

logger = logging.getLogger(__name__)


async def _run_survival_analysis(
    task, request, db, progress_callback=None, progress_config=None, submitted_by=None
):
    """Run analysis for survival task.

    NOTE: Analysis is performed ONLY on the test set to provide unbiased metrics.
    Training and validation sets are excluded to avoid data leakage.
    For case-level datasets, metrics are calculated per case (one case = one sample).

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    p_start, p_ci_start, p_ci_end = unpack_progress_config(progress_config)
    task_id = task.task_id

    # Check if this is a case-level dataset
    aggregation_level = await TrainingTaskRepository.get_dataset_aggregation_level(
        db, task_id
    )
    is_case_level = aggregation_level == "case"
    logger.info(
        f"Survival analysis for task {task_id}: aggregation_level = {aggregation_level}, is_case_level = {is_case_level}"
    )

    # Get wsi_id to case_id mapping for case-level aggregation
    wsi_case_map: Dict[str, str] = {}
    if is_case_level:
        wsi_case_map = await TrainingTaskRepository.get_wsi_case_ids(db, task_id)

    # Check if this is a K-Fold training by looking at the splits
    kfold_query = (
        select(TrainingTaskWSI.split)
        .where(TrainingTaskWSI.task_id == task_id)
        .where(TrainingTaskWSI.split.like("fold_%"))
        .distinct()
    )
    kfold_result = await db.execute(kfold_query)
    kfold_splits = [row[0] for row in kfold_result.all()]
    is_kfold = len(kfold_splits) > 0

    # Get test set WSI IDs - analysis should only use test set for unbiased metrics
    test_wsi_query = (
        select(TrainingTaskWSI.wsi_id)
        .where(TrainingTaskWSI.task_id == task_id)
        .where(TrainingTaskWSI.split == "test")
    )
    test_wsi_result = await db.execute(test_wsi_query)
    test_wsi_ids = {row[0] for row in test_wsi_result.all()}

    if test_wsi_ids:
        logger.info(
            f"Survival analysis for task {task_id}: using {len(test_wsi_ids)} test set WSIs"
        )
    elif is_kfold:
        logger.info(
            f"Survival analysis for task {task_id}: K-Fold training detected ({len(kfold_splits)} folds), using all validation results"
        )
    else:
        logger.warning(
            f"Survival analysis for task {task_id}: no test set found, using all WSIs"
        )

    # We load result JSONs from ai_results dir since survival results structure is different
    # and might not be fully in DB (AIResult table is optimized for classification)

    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    risks = []
    times = []
    events = []
    wsi_results = []
    surv_probs = []  # list of lists
    bin_edges = None

    if ai_results_dir.exists():
        for wsi_dir in ai_results_dir.iterdir():
            if wsi_dir.is_dir():
                # Match both regular (train_{task_id}_result.json) and K-Fold (train_{task_id}_fold_*_result.json) files
                matched_files = list(wsi_dir.glob(f"train_{task_id}*_result.json"))
                if matched_files:
                    logger.debug(
                        f"Found {len(matched_files)} result files in {wsi_dir.name}: {[f.name for f in matched_files]}"
                    )
                for json_file in matched_files:
                    try:
                        with open(json_file, "r") as f:
                            data = json.load(f)
                            if data.get("task_id") == task_id:
                                wsi_id = data.get("wsi_id", wsi_dir.name)

                                # Only include if no test set defined OR wsi is in test set
                                if test_wsi_ids and wsi_id not in test_wsi_ids:
                                    continue  # Skip non-test set WSIs

                                # Required fields
                                if "risk_score" not in data or "event_time" not in data:
                                    continue

                                # Get case_id for this wsi
                                case_id = (
                                    wsi_case_map.get(wsi_id, wsi_id)
                                    if is_case_level
                                    else wsi_id
                                )

                                risks.append(data["risk_score"])
                                times.append(data["event_time"])
                                events.append(data.get("event_status", 0))

                                if "surv_probs" in data:
                                    surv_probs.append(data["surv_probs"])
                                else:
                                    logger.warning(f"No surv_probs in {json_file.name}")

                                if "bin_edges" in data and bin_edges is None:
                                    bin_edges = data["bin_edges"]

                                wsi_results.append(
                                    {
                                        "wsi_id": wsi_id,
                                        "filename": None,
                                        "case_id": case_id,
                                        "risk_score": data["risk_score"],
                                        "event_time": data["event_time"],
                                        "event_status": data.get("event_status", 0),
                                        "surv_probs": data.get("surv_probs"),
                                    }
                                )
                    except Exception as e:
                        logger.warning(
                            f"Failed to load survival result from {json_file}: {e}"
                        )
                        continue

    if not risks:
        # Check database if not found in files (fallback)
        pass
        if not risks:
            raise HTTPException(
                status_code=400,
                detail="No analyzed survival results found for this task",
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
            f"Case-level survival analysis: aggregated to {len(case_results_map)} cases"
        )

    logger.info(
        f"Survival analysis for task {task_id}: loaded {len(risks)} samples for C-Index calculation"
    )
    logger.info(
        f"  surv_probs count: {len(surv_probs)}, bin_edges available: {bin_edges is not None}"
    )

    # Update progress - data loaded (use dynamic start + small offset)
    if progress_callback:
        await progress_callback(p_start + 3)

    # Calculate C-Index using scikit-survival
    import numpy as np
    from sksurv.metrics import concordance_index_censored

    # concordance_index_censored expects:
    # - event_indicator: boolean array (True = event occurred)
    # - event_time: float array of times
    # - estimate: float array of risk scores (higher = higher risk)
    events_bool = np.array(events, dtype=bool)
    times_arr = np.array(times, dtype=float)
    risks_arr = np.array(risks, dtype=float)
    c_index, _, _, _, _ = concordance_index_censored(events_bool, times_arr, risks_arr)
    logger.info(f"  Calculated C-Index (scikit-survival): {c_index}")

    analysis_dir, timestamp = make_analysis_dir(task_id)

    metrics = {"c_index": round(c_index, 4)}

    # Calculate Integrated Brier Score if requested
    if "integrated_brier_score" in request.metrics:
        logger.info(
            f"IBS requested. surv_probs count: {len(surv_probs)}, bin_edges available: {bin_edges is not None}, "
            f"bin_edges length: {len(bin_edges) if bin_edges else 0}"
        )
        ibs = _calculate_integrated_brier_score(times, events, surv_probs, bin_edges)
        if ibs is not None:
            metrics["integrated_brier_score"] = round(ibs, 4)
            logger.info(f"IBS calculated successfully: {ibs:.4f}")
        else:
            logger.warning(f"IBS calculation returned None for task {task_id}")
    else:
        logger.info(f"IBS not requested. request.metrics: {request.metrics}")

    # Update progress - metrics calculated (use ci_start)
    if progress_callback:
        await progress_callback(p_ci_start)

    # Calculate bootstrap confidence intervals if requested
    # Support both new bootstrap_ci_metrics list and legacy compute_bootstrap_ci flag
    # NOTE: Bootstrap CI is only valid for manual/random split, not K-Fold
    #       K-Fold uses mean ± std across folds which provides its own variance estimate
    # NOTE: Bootstrap CI is CPU-intensive, run in thread pool to avoid blocking event loop
    bootstrap_ci_result = None
    ci_metrics = (
        request.bootstrap_ci_metrics
        if request.bootstrap_ci_metrics
        else (request.metrics if request.compute_bootstrap_ci else [])
    )

    # Skip Bootstrap CI for K-Fold tasks - they use mean ± std instead
    if is_kfold and ci_metrics:
        logger.info(
            f"Skipping bootstrap CI for K-Fold survival task {task_id} - using mean ± std instead"
        )
        ci_metrics = []

    if ci_metrics:
        logger.info(
            f"Computing bootstrap 95% CI for survival task {task_id}, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()
        bootstrap_progress_sync = make_bootstrap_progress_sync(
            progress_callback, p_ci_start, p_ci_end, loop
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

    # Generate Charts — run KM image generation, loss data loading, and kfold
    # metrics loading in parallel where possible
    chart_paths = {}
    chart_data = {}

    # Build parallel tasks: KM chart (CPU-intensive), loss data (file I/O), kfold metrics (file I/O)
    km_coro = None
    if "km_curve" in request.charts:
        km_path = analysis_dir / "km_curve.png"
        include_km_ci = "c_index" in ci_metrics
        km_coro = run_chart_in_process(
            _generate_km_analysis, times, events, risks, km_path, include_km_ci
        )

    loss_coro = _get_loss_data(task_id) if "loss_curve" in request.charts else None
    kfold_coro = _get_kfold_metrics(task_id)

    # Run all in parallel
    parallel_tasks = []
    task_names = []
    for name, coro in [("km", km_coro), ("loss", loss_coro), ("kfold", kfold_coro)]:
        if coro is not None:
            parallel_tasks.append(coro)
            task_names.append(name)

    parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
    result_map = {}
    for name, result in zip(task_names, parallel_results):
        if isinstance(result, Exception):
            logger.error(f"Parallel task '{name}' failed: {result}")
            result_map[name] = None
        else:
            result_map[name] = result

    # Unpack results
    km_data = result_map.get("km")
    if km_data:
        chart_paths["km_curve"] = str(km_path)
        chart_data["km_curve"] = km_data

    loss_data = result_map.get("loss")
    if loss_data:
        chart_data["loss_curve"] = loss_data

    kfold_metrics = result_map.get("kfold")

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Save Summary
    summary = {
        "task_id": task_id,
        "task_type": "survival",
        "timestamp": utc_timestamp_z(),
        "description": request.description,
        "num_samples": len(risks),
        "metrics": metrics,
        "chart_paths": chart_paths,
        "chart_data": chart_data,
        "random_seed": random_seed,  # Invisible watermark for model provenance tracking
        "submitted_by": submitted_by,
    }

    # Add K-Fold training info if available
    if kfold_metrics:
        summary["kfold_training"] = kfold_metrics

    # Add bootstrap CI if computed
    if bootstrap_ci_result:
        summary["bootstrap_ci"] = bootstrap_ci_result

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    await fill_wsi_filenames(db, wsi_results)

    await asyncio.to_thread(
        _write_json_sync,
        analysis_dir / "results.json",
        {"wsi_results": wsi_results, "metrics": metrics},
    )

    return make_analysis_result(task_id, timestamp, analysis_dir, summary, chart_paths)
