"""
Classification Analysis Module

Handles running classification analysis for AI training tasks, including
metric calculation, bootstrap CI, chart generation, and result persistence.
"""

import asyncio
import functools
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Any

from fastapi import HTTPException
from sqlalchemy import select

from backend.ai.schemas.base import TaskStatus
from backend.ai.task_taxonomy import normalize_task_type
from backend.database.models import AIResult, WSISlide, TrainingTaskWSI
from backend.database.repositories import TrainingTaskRepository, WSIRepository

from .analysis_utils import (
    fill_wsi_filenames,
    make_analysis_dir,
    make_analysis_result,
    make_bootstrap_progress_sync,
    run_chart_tasks,
    unpack_progress_config,
    utc_timestamp_z,
    _get_random_seed_from_task,
)
from .analysis_metrics import (
    _calculate_all_metrics,
    _calculate_bootstrap_ci,
    _generate_confusion_matrix_chart,
    _generate_roc_chart,
    _get_loss_data,
    _get_kfold_metrics,
    _render_loss_chart_sync,
    run_chart_in_process,
    _write_json_sync,
)

logger = logging.getLogger(__name__)


def _canonical_analysis_task_type(task) -> str:
    return normalize_task_type(
        task_type=getattr(task, "task_type", "wsi_classification"),
        data_type=getattr(task, "data_type", "wsi"),
    )


async def _run_classification_analysis(
    task, request, db, progress_callback=None, progress_config=None, submitted_by=None
):
    """Run analysis for classification task.

    NOTE: Analysis is performed ONLY on the test set to provide unbiased metrics.
    Training and validation sets are excluded to avoid data leakage.
    For case-level datasets, metrics are calculated per case (one case = one sample).

    Args:
        progress_callback: Optional async function to report progress (0-100).
        progress_config: Optional dict with 'start', 'ci_start', 'ci_end', 'has_ci' for dynamic progress ranges.
    """
    p_start, p_ci_start, p_ci_end = unpack_progress_config(progress_config)
    task_id = task.task_id
    predictions = []
    labels = []
    probs_list = []
    wsi_results = []

    # Check if this is a case-level dataset
    aggregation_level = await TrainingTaskRepository.get_dataset_aggregation_level(
        db, task_id
    )
    is_case_level = aggregation_level == "case"
    logger.info(
        f"Classification analysis for task {task_id}: aggregation_level = {aggregation_level}, is_case_level = {is_case_level}"
    )

    is_kfold = False

    if task and task.status == TaskStatus.COMPLETED:
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

        # Query results for this task from database, filtered by test set
        query = (
            select(AIResult, WSISlide)
            .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
            .where(AIResult.task_id == task_id)
            .where(AIResult.pred.isnot(None))
        )

        # Only filter by test set if we have test WSIs defined
        if test_wsi_ids:
            query = query.where(AIResult.wsi_id.in_(test_wsi_ids))
            logger.info(
                f"Analysis for task {task_id}: using {len(test_wsi_ids)} test set WSIs"
            )
        elif is_kfold:
            logger.info(
                f"Analysis for task {task_id}: K-Fold training detected ({len(kfold_splits)} folds), using all validation results"
            )
        else:
            logger.warning(
                f"Analysis for task {task_id}: no test set found, using all WSIs"
            )

        result = await db.execute(query)
        rows = result.all()

        for ai_result, wsi in rows:
            predictions.append(ai_result.pred)
            labels.append(wsi.label)
            probs_list.append(ai_result.probs or {})
            wsi_results.append(
                {
                    "wsi_id": ai_result.wsi_id,
                    "filename": wsi.original_filename or ai_result.wsi_id,
                    "case_id": wsi.case_id or ai_result.wsi_id,
                    "label": wsi.label,
                    "pred": ai_result.pred,
                    "correct": ai_result.pred == wsi.label,
                    "probs": ai_result.probs,
                }
            )

    if not predictions:
        raise HTTPException(
            status_code=400, detail="No analyzed results found for this task"
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
            f"Case-level classification analysis: aggregated {len(wsi_results)} slides to {len(case_results)} cases"
        )

    # Compute metrics
    all_classes = sorted(set(labels) | set(predictions))
    is_binary = len(all_classes) == 2

    # Update progress - data loaded (use dynamic start + small offset)
    if progress_callback:
        await progress_callback(p_start + 3)

    # Build confusion matrix
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    for true_label, pred_label in zip(labels, predictions):
        confusion_matrix[true_label][pred_label] += 1

    # Calculate metrics
    # Run CPU-intensive metrics calculation in executor to avoid blocking event loop
    loop = asyncio.get_event_loop()
    metrics_result = await loop.run_in_executor(
        None,
        functools.partial(
            _calculate_all_metrics,
            labels=labels,
            predictions=predictions,
            probs_list=probs_list,
            all_classes=all_classes,
            requested_metrics=request.metrics,
        ),
    )

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
            f"Skipping bootstrap CI for K-Fold task {task_id} - using mean ± std instead"
        )
        ci_metrics = []

    if ci_metrics:
        logger.info(
            f"Computing bootstrap 95% CI for task {task_id} with {len(predictions)} samples, metrics: {ci_metrics}..."
        )
        loop = asyncio.get_event_loop()
        bootstrap_progress_sync = make_bootstrap_progress_sync(
            progress_callback, p_ci_start, p_ci_end, loop
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
        logger.info(f"Bootstrap CI calculation completed for task {task_id}")

    # Update progress - bootstrap CI done (or skipped)
    if progress_callback:
        await progress_callback(p_ci_end)

    analysis_dir, timestamp = make_analysis_dir(task_id)

    # Check for K-Fold training metrics
    kfold_metrics = await _get_kfold_metrics(task_id)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Save summary
    summary = {
        "task_id": task_id,
        "task_type": _canonical_analysis_task_type(task),
        "timestamp": utc_timestamp_z(),
        "description": request.description,
        "num_samples": len(predictions),
        "classes": all_classes,
        "is_binary": is_binary,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "metrics": metrics_result["metrics"],
        "class_metrics": metrics_result["class_metrics"],
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

    await fill_wsi_filenames(db, wsi_results)

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

    if "loss_curve" in request.charts:
        # Load loss history for ECharts (async file I/O — must finish before parallel phase)
        loss_data = await _get_loss_data(task_id)
        if loss_data:
            chart_data["loss_curve"] = loss_data
            chart_gen_tasks.append(
                (
                    "loss_curve",
                    run_chart_in_process(
                        _render_loss_chart_sync,
                        loss_data,
                        analysis_dir / "loss_curve.png",
                    ),
                )
            )

    chart_paths.update(await run_chart_tasks(chart_gen_tasks))

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

    # Update summary with chart paths and chart data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    await asyncio.to_thread(_write_json_sync, analysis_dir / "summary.json", summary)

    logger.info(f"Analysis completed for task {task_id}, saved to {analysis_dir}")

    return await make_analysis_result(task_id, timestamp, analysis_dir, summary, chart_paths)
