"""
AI Results API Routes

Handles retrieval of AI analysis results, task-level analysis execution,
and saving analysis results to logs/analysis/{task_id}/.
"""
import logging
import json
import base64
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.database.models import AIResult, WSISlide, TrainingTask, TrainedModel
from backend.database.repositories import AIResultRepository, WSIRepository, TrainingTaskRepository
from backend.common.config import Config

router = APIRouter(prefix="/results", tags=["AI Results"])
logger = logging.getLogger(__name__)


class AnalysisRequest(BaseModel):
    """Request body for running analysis on a task."""
    metrics: List[str] = ["accuracy", "precision", "recall", "specificity", "f1", "auc"]
    charts: List[str] = ["roc_curve", "confusion_matrix", "loss_curve"]
    description: Optional[str] = None


@router.get("")
async def get_all_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all AI results with associated WSI labels for analysis.

    Returns:
        List of results with predictions and ground truth labels
    """
    # Query results with WSI info
    query = (
        select(AIResult, WSISlide)
        .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
        .order_by(AIResult.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    items = []
    for ai_result, wsi in rows:
        item = ai_result.to_dict()
        item["label"] = wsi.label  # Ground truth
        item["case_id"] = wsi.case_id
        item["original_filename"] = wsi.original_filename
        items.append(item)

    return {"items": items, "total": len(items)}


@router.get("/analysis/stats")
async def get_analysis_stats(
    task_id: Optional[str] = Query(None, description="Filter by task_id"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive analysis statistics for all predictions.

    Computes:
    - Overall accuracy, precision, recall/sensitivity, specificity, F1
    - Per-class metrics
    - Confusion matrix
    - Class distributions
    - ROC curve data (per class, with AUC)

    Note: Handles both binary and multi-class classification.
    """
    # Query results with WSI labels
    query = (
        select(AIResult, WSISlide)
        .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
        .where(AIResult.pred.isnot(None))  # Only analyzed results
    )
    if task_id:
        query = query.where(AIResult.task_id == task_id)

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        return {
            "total": 0,
            "analyzed": 0,
            "metrics": {},
            "confusion_matrix": {},
            "class_metrics": {},
            "roc_data": {},
            "classes": []
        }

    # Collect predictions and labels
    predictions = []
    labels = []
    probs_list = []  # For ROC/AUC

    for ai_result, wsi in rows:
        if ai_result.pred and wsi.label:
            predictions.append(ai_result.pred)
            labels.append(wsi.label)
            probs_list.append(ai_result.probs or {})

    if not predictions:
        return {
            "total": len(rows),
            "analyzed": 0,
            "metrics": {},
            "confusion_matrix": {},
            "class_metrics": {},
            "roc_data": {},
            "classes": []
        }

    # Get unique classes (sorted)
    all_classes = sorted(set(labels) | set(predictions))
    n_classes = len(all_classes)
    is_binary = n_classes == 2

    # Build confusion matrix
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    for true_label, pred_label in zip(labels, predictions):
        confusion_matrix[true_label][pred_label] += 1

    # Convert to serializable format
    cm_dict = {
        "matrix": {
            true_cls: dict(confusion_matrix[true_cls])
            for true_cls in all_classes
        },
        "classes": all_classes
    }

    # Calculate per-class metrics
    class_metrics = {}
    for cls in all_classes:
        # True Positive: predicted as cls and actually cls
        tp = confusion_matrix[cls].get(cls, 0)
        # False Positive: predicted as cls but not actually cls
        fp = sum(confusion_matrix[other][cls] for other in all_classes if other != cls)
        # False Negative: actually cls but not predicted as cls
        fn = sum(confusion_matrix[cls].get(other, 0) for other in all_classes if other != cls)
        # True Negative: not cls and not predicted as cls
        tn = sum(
            confusion_matrix[true_cls].get(pred_cls, 0)
            for true_cls in all_classes if true_cls != cls
            for pred_cls in all_classes if pred_cls != cls
        )

        # Metrics
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0  # sensitivity
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        class_metrics[cls] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "sensitivity": round(recall, 4),  # Same as recall
            "specificity": round(specificity, 4),
            "f1": round(f1, 4),
            "support": tp + fn  # Number of true instances
        }

    # Calculate overall metrics (macro average)
    n_correct = sum(confusion_matrix[cls].get(cls, 0) for cls in all_classes)
    n_total = len(predictions)
    accuracy = n_correct / n_total if n_total > 0 else 0

    macro_precision = sum(m["precision"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_recall = sum(m["recall"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_f1 = sum(m["f1"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_specificity = sum(m["specificity"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0

    # Weighted average (by support)
    total_support = sum(m["support"] for m in class_metrics.values())
    weighted_precision = sum(m["precision"] * m["support"] for m in class_metrics.values()) / total_support if total_support > 0 else 0
    weighted_recall = sum(m["recall"] * m["support"] for m in class_metrics.values()) / total_support if total_support > 0 else 0
    weighted_f1 = sum(m["f1"] * m["support"] for m in class_metrics.values()) / total_support if total_support > 0 else 0

    overall_metrics = {
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_sensitivity": round(macro_recall, 4),
        "macro_specificity": round(macro_specificity, 4),
        "macro_f1": round(macro_f1, 4),
        "weighted_precision": round(weighted_precision, 4),
        "weighted_recall": round(weighted_recall, 4),
        "weighted_f1": round(weighted_f1, 4),
    }

    # Calculate ROC curve data and AUC for each class
    roc_data = {}
    for cls in all_classes:
        # Get probability scores for this class
        scores = []
        binary_labels = []
        for i, probs in enumerate(probs_list):
            if cls in probs:
                scores.append(probs[cls])
                binary_labels.append(1 if labels[i] == cls else 0)

        if len(scores) > 0 and sum(binary_labels) > 0 and sum(binary_labels) < len(binary_labels):
            # Calculate ROC points
            roc_points = _compute_roc_curve(binary_labels, scores)
            auc = _compute_auc(roc_points)
            roc_data[cls] = {
                "points": roc_points,
                "auc": round(auc, 4)
            }

    # Overall AUC (macro average)
    if roc_data:
        overall_metrics["macro_auc"] = round(
            sum(r["auc"] for r in roc_data.values()) / len(roc_data), 4
        )

    # Label and prediction distributions
    label_dist = defaultdict(int)
    pred_dist = defaultdict(int)
    for l in labels:
        label_dist[l] += 1
    for p in predictions:
        pred_dist[p] += 1

    return {
        "total": len(rows),
        "analyzed": len(predictions),
        "is_binary": is_binary,
        "classes": all_classes,
        "metrics": overall_metrics,
        "class_metrics": class_metrics,
        "confusion_matrix": cm_dict,
        "roc_data": roc_data,
        "label_distribution": dict(label_dist),
        "prediction_distribution": dict(pred_dist)
    }


def _compute_roc_curve(y_true: List[int], y_scores: List[float], num_thresholds: int = 100) -> List[Dict[str, float]]:
    """
    Compute ROC curve points.

    Returns list of {fpr, tpr, threshold} points.
    """
    # Sort by scores descending
    sorted_indices = sorted(range(len(y_scores)), key=lambda i: y_scores[i], reverse=True)
    y_true_sorted = [y_true[i] for i in sorted_indices]
    y_scores_sorted = [y_scores[i] for i in sorted_indices]

    # Count positives and negatives
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos

    if n_pos == 0 or n_neg == 0:
        return [{"fpr": 0, "tpr": 0, "threshold": 1}, {"fpr": 1, "tpr": 1, "threshold": 0}]

    # Generate thresholds
    unique_scores = sorted(set(y_scores_sorted), reverse=True)
    if len(unique_scores) > num_thresholds:
        step = len(unique_scores) // num_thresholds
        thresholds = unique_scores[::step] + [unique_scores[-1]]
    else:
        thresholds = unique_scores

    points = [{"fpr": 0, "tpr": 0, "threshold": 1.0}]

    for threshold in thresholds:
        tp = sum(1 for i in range(len(y_scores)) if y_scores[i] >= threshold and y_true[i] == 1)
        fp = sum(1 for i in range(len(y_scores)) if y_scores[i] >= threshold and y_true[i] == 0)

        tpr = tp / n_pos
        fpr = fp / n_neg

        points.append({
            "fpr": round(fpr, 4),
            "tpr": round(tpr, 4),
            "threshold": round(threshold, 4)
        })

    points.append({"fpr": 1, "tpr": 1, "threshold": 0.0})

    # Remove duplicates while preserving order
    seen = set()
    unique_points = []
    for p in points:
        key = (p["fpr"], p["tpr"])
        if key not in seen:
            seen.add(key)
            unique_points.append(p)

    return unique_points


def _compute_auc(roc_points: List[Dict[str, float]]) -> float:
    """
    Compute Area Under ROC Curve using trapezoidal rule.
    """
    # Sort by FPR
    sorted_points = sorted(roc_points, key=lambda p: p["fpr"])

    auc = 0.0
    for i in range(1, len(sorted_points)):
        x1, y1 = sorted_points[i-1]["fpr"], sorted_points[i-1]["tpr"]
        x2, y2 = sorted_points[i]["fpr"], sorted_points[i]["tpr"]
        auc += (x2 - x1) * (y1 + y2) / 2

    return auc


@router.get("/tasks")
async def get_analysis_tasks(db: AsyncSession = Depends(get_db)):
    """
    Get list of tasks available for analysis.

    Combines:
    1. Completed training tasks from database
    2. Tasks found in ai_results directory (for backward compatibility)
    """
    task_map = {}

    # 1. Get completed tasks from database
    query = select(TrainingTask).where(TrainingTask.status == "completed").order_by(TrainingTask.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    for task in tasks:
        analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task.task_id
        has_analysis = analysis_dir.exists() and any(analysis_dir.iterdir()) if analysis_dir.exists() else False

        task_map[task.task_id] = {
            "task_id": task.task_id,
            "name": task.task_name or task.task_id,
            "model_type": task.task_type,
            "status": task.status,
            "created_at": task.created_at.isoformat() + 'Z' if task.created_at else None,
            "has_analysis": has_analysis,
            "source": "database"
        }

    # 2. Scan ai_results directory for task_ids not in database
    ai_results_dir = Config.get_uploads_dir() / "ai_results"
    if ai_results_dir.exists():
        task_ids_from_results = set()

        # Scan all WSI result directories
        for wsi_dir in ai_results_dir.iterdir():
            if wsi_dir.is_dir():
                for json_file in wsi_dir.glob("*.json"):
                    try:
                        with open(json_file, 'r') as f:
                            data = json.load(f)
                            if "task_id" in data:
                                task_ids_from_results.add(data["task_id"])
                    except Exception:
                        continue

        # Add tasks from ai_results that are not in database
        for task_id in task_ids_from_results:
            if task_id not in task_map:
                analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id
                has_analysis = analysis_dir.exists() and any(analysis_dir.iterdir()) if analysis_dir.exists() else False

                task_map[task_id] = {
                    "task_id": task_id,
                    "name": task_id,
                    "model_type": "unknown",
                    "status": "completed",
                    "created_at": None,
                    "has_analysis": has_analysis,
                    "source": "ai_results"
                }

    # Sort by created_at (None values last)
    task_list = sorted(
        task_map.values(),
        key=lambda x: (x["created_at"] is None, x["created_at"] or ""),
        reverse=True
    )

    return {"tasks": task_list}


@router.get("/tasks/{task_id}/analysis")
async def get_task_analysis(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get existing analysis results for a task.
    """
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id

    if not analysis_dir.exists():
        return {"task_id": task_id, "analyses": []}

    analyses = []
    for item in sorted(analysis_dir.iterdir(), reverse=True):
        if item.is_dir():
            # Each analysis run is in a timestamped directory
            summary_file = item / "summary.json"
            if summary_file.exists():
                with open(summary_file, 'r') as f:
                    summary = json.load(f)
                    summary["analysis_id"] = item.name
                    analyses.append(summary)

    return {"task_id": task_id, "analyses": analyses}


@router.post("/tasks/{task_id}/analysis")
async def run_task_analysis(
    task_id: str,
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Run analysis on a completed training task and save results to logs/analysis/{task_id}/.

    Args:
        task_id: Training task ID to analyze
        request: Analysis configuration (metrics, charts to generate)

    Returns:
        Analysis results summary with paths to generated files
    """
    predictions = []
    labels = []
    probs_list = []
    wsi_results = []

    # Try to get results from database first
    task = await TrainingTaskRepository.get_by_id(db, task_id)

    if task and task.status == "completed":
        # Query results for this task from database
        query = (
            select(AIResult, WSISlide)
            .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
            .where(AIResult.task_id == task_id)
            .where(AIResult.pred.isnot(None))
        )
        result = await db.execute(query)
        rows = result.all()

        for ai_result, wsi in rows:
            predictions.append(ai_result.pred)
            labels.append(wsi.label)
            probs_list.append(ai_result.probs or {})
            wsi_results.append({
                "wsi_id": ai_result.wsi_id,
                "case_id": wsi.case_id,
                "label": wsi.label,
                "pred": ai_result.pred,
                "correct": ai_result.pred == wsi.label,
                "probs": ai_result.probs
            })

    # If no results from database, try to load from ai_results directory
    if not predictions:
        ai_results_dir = Config.get_uploads_dir() / "ai_results"
        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    for json_file in wsi_dir.glob("*.json"):
                        try:
                            with open(json_file, 'r') as f:
                                data = json.load(f)
                                if data.get("task_id") == task_id and data.get("pred"):
                                    predictions.append(data["pred"])
                                    labels.append(data.get("ground_truth", "unknown"))
                                    probs_list.append(data.get("probs", {}))
                                    wsi_results.append({
                                        "wsi_id": data.get("wsi_id", wsi_dir.name),
                                        "case_id": wsi_dir.name,
                                        "label": data.get("ground_truth", "unknown"),
                                        "pred": data["pred"],
                                        "correct": data.get("correct", data["pred"] == data.get("ground_truth")),
                                        "probs": data.get("probs")
                                    })
                        except Exception as e:
                            logger.warning(f"Failed to load result from {json_file}: {e}")
                            continue

    if not predictions:
        raise HTTPException(status_code=400, detail="No analyzed results found for this task")

    # Compute metrics
    all_classes = sorted(set(labels) | set(predictions))
    is_binary = len(all_classes) == 2

    # Build confusion matrix
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    for true_label, pred_label in zip(labels, predictions):
        confusion_matrix[true_label][pred_label] += 1

    # Calculate metrics
    metrics_result = _calculate_all_metrics(
        labels, predictions, probs_list, all_classes, request.metrics
    )

    # Create analysis output directory
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Save summary
    summary = {
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "description": request.description,
        "num_samples": len(predictions),
        "classes": all_classes,
        "is_binary": is_binary,
        "requested_metrics": request.metrics,
        "requested_charts": request.charts,
        "metrics": metrics_result["metrics"],
        "class_metrics": metrics_result["class_metrics"]
    }

    with open(analysis_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    # Save detailed results
    with open(analysis_dir / "results.json", 'w') as f:
        json.dump({
            "wsi_results": wsi_results,
            "confusion_matrix": {k: dict(v) for k, v in confusion_matrix.items()},
            "roc_data": metrics_result.get("roc_data", {})
        }, f, indent=2)

    # Generate charts and collect chart data for frontend ECharts rendering
    chart_paths = {}
    chart_data = {}

    if "confusion_matrix" in request.charts:
        # Prepare confusion matrix data for ECharts
        cm_data = []
        for i, true_cls in enumerate(all_classes):
            for j, pred_cls in enumerate(all_classes):
                value = confusion_matrix.get(true_cls, {}).get(pred_cls, 0)
                cm_data.append([j, i, value])
        chart_data["confusion_matrix"] = {
            "classes": all_classes,
            "data": cm_data
        }

        cm_path = _generate_confusion_matrix_chart(
            confusion_matrix, all_classes, analysis_dir / "confusion_matrix.png"
        )
        if cm_path:
            chart_paths["confusion_matrix"] = str(cm_path)

    if "roc_curve" in request.charts and metrics_result.get("roc_data"):
        # Prepare ROC curve data for ECharts
        roc_chart_data = {}
        for cls, data in metrics_result["roc_data"].items():
            roc_chart_data[cls] = {
                "fpr": [p["fpr"] for p in data["points"]],
                "tpr": [p["tpr"] for p in data["points"]],
                "auc": data["auc"]
            }
        chart_data["roc_curve"] = {
            "classes": all_classes,
            "data": roc_chart_data
        }

        roc_path = _generate_roc_chart(
            metrics_result["roc_data"], all_classes, analysis_dir / "roc_curve.png"
        )
        if roc_path:
            chart_paths["roc_curve"] = str(roc_path)

    if "loss_curve" in request.charts:
        # Load loss history from model metrics
        loss_data = await _get_loss_data(task_id)
        if loss_data:
            chart_data["loss_curve"] = loss_data

        loss_path = await _generate_loss_chart(task_id, analysis_dir / "loss_curve.png")
        if loss_path:
            chart_paths["loss_curve"] = str(loss_path)

    # Update summary with chart paths and chart data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    with open(analysis_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Analysis completed for task {task_id}, saved to {analysis_dir}")

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths
    }


@router.get("/tasks/{task_id}/analysis/{analysis_id}/file/{filename}")
async def get_analysis_file(task_id: str, analysis_id: str, filename: str):
    """
    Get a specific file from an analysis run.
    """
    file_path = Config.get_uploads_dir() / "logs" / "analysis" / task_id / analysis_id / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(file_path)


@router.delete("/tasks/{task_id}/analysis/{analysis_id}")
async def delete_task_analysis(task_id: str, analysis_id: str):
    """
    Delete a specific analysis run for a task.

    Args:
        task_id: Training task ID
        analysis_id: Analysis run ID (timestamp directory name)

    Returns:
        Success message
    """
    import shutil

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / analysis_id

    if not analysis_dir.exists():
        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    if not analysis_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid analysis ID: {analysis_id}")

    try:
        shutil.rmtree(analysis_dir)
        logger.info(f"Deleted analysis {analysis_id} for task {task_id}")
        return {"message": f"Analysis {analysis_id} deleted successfully", "task_id": task_id, "analysis_id": analysis_id}
    except Exception as e:
        logger.error(f"Failed to delete analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete analysis: {str(e)}")


def _calculate_all_metrics(
    labels: List[str],
    predictions: List[str],
    probs_list: List[Dict],
    all_classes: List[str],
    requested_metrics: List[str]
) -> Dict[str, Any]:
    """Calculate all requested metrics."""
    n_classes = len(all_classes)

    # Build confusion matrix
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    for true_label, pred_label in zip(labels, predictions):
        confusion_matrix[true_label][pred_label] += 1

    # Calculate per-class metrics
    class_metrics = {}
    for cls in all_classes:
        tp = confusion_matrix[cls].get(cls, 0)
        fp = sum(confusion_matrix[other][cls] for other in all_classes if other != cls)
        fn = sum(confusion_matrix[cls].get(other, 0) for other in all_classes if other != cls)
        tn = sum(
            confusion_matrix[true_cls].get(pred_cls, 0)
            for true_cls in all_classes if true_cls != cls
            for pred_cls in all_classes if pred_cls != cls
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        class_metrics[cls] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "sensitivity": round(recall, 4),
            "specificity": round(specificity, 4),
            "f1": round(f1, 4),
            "support": tp + fn
        }

    # Overall metrics
    n_correct = sum(confusion_matrix[cls].get(cls, 0) for cls in all_classes)
    n_total = len(predictions)
    accuracy = n_correct / n_total if n_total > 0 else 0

    macro_precision = sum(m["precision"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_recall = sum(m["recall"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_f1 = sum(m["f1"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0
    macro_specificity = sum(m["specificity"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0

    metrics = {
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_sensitivity": round(macro_recall, 4),
        "macro_specificity": round(macro_specificity, 4),
        "macro_f1": round(macro_f1, 4)
    }

    # ROC/AUC if requested
    roc_data = {}
    if "auc" in requested_metrics:
        for cls in all_classes:
            scores = []
            binary_labels = []
            for i, probs in enumerate(probs_list):
                if cls in probs:
                    scores.append(probs[cls])
                    binary_labels.append(1 if labels[i] == cls else 0)

            if scores and sum(binary_labels) > 0 and sum(binary_labels) < len(binary_labels):
                roc_points = _compute_roc_curve(binary_labels, scores)
                auc = _compute_auc(roc_points)
                roc_data[cls] = {"points": roc_points, "auc": round(auc, 4)}

        if roc_data:
            metrics["macro_auc"] = round(sum(r["auc"] for r in roc_data.values()) / len(roc_data), 4)

    return {
        "metrics": metrics,
        "class_metrics": class_metrics,
        "roc_data": roc_data
    }


def _setup_matplotlib_font():
    """Setup matplotlib to use Liberation Sans (open-source Arial alternative)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Liberation Sans is the open-source font closest to Arial
    # Fallback chain: Liberation Sans -> DejaVu Sans -> sans-serif
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Liberation Sans', 'DejaVu Sans', 'Arial', 'Helvetica', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False

    return plt


def _generate_confusion_matrix_chart(confusion_matrix, classes, output_path) -> Optional[Path]:
    """Generate confusion matrix heatmap chart with high DPI for export."""
    try:
        plt = _setup_matplotlib_font()
        import numpy as np

        n_classes = len(classes)
        cm = np.zeros((n_classes, n_classes), dtype=int)
        for i, true_cls in enumerate(classes):
            for j, pred_cls in enumerate(classes):
                cm[i, j] = confusion_matrix.get(true_cls, {}).get(pred_cls, 0)

        # Larger figure size for better text visibility
        fig, ax = plt.subplots(figsize=(12, 10))
        im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
        cbar = ax.figure.colorbar(im, ax=ax)
        cbar.ax.tick_params(labelsize=18)

        ax.set(xticks=np.arange(n_classes),
               yticks=np.arange(n_classes),
               xticklabels=classes,
               yticklabels=classes)

        # Large font sizes for publication quality
        ax.set_xlabel('Predicted Label', fontsize=24, fontweight='bold')
        ax.set_ylabel('True Label', fontsize=24, fontweight='bold')
        ax.set_title('Confusion Matrix', fontsize=28, fontweight='bold', pad=20)
        ax.tick_params(axis='both', labelsize=20)

        # Add text annotations with larger font
        thresh = cm.max() / 2.
        for i in range(n_classes):
            for j in range(n_classes):
                ax.text(j, i, format(cm[i, j], 'd'),
                       ha="center", va="center", fontsize=24, fontweight='bold',
                       color="white" if cm[i, j] > thresh else "black")

        plt.tight_layout()
        plt.savefig(output_path, dpi=600, bbox_inches='tight')
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to generate confusion matrix chart: {e}")
        return None


def _generate_roc_chart(roc_data, classes, output_path) -> Optional[Path]:
    """Generate ROC curve chart with high DPI for export."""
    try:
        plt = _setup_matplotlib_font()

        # Larger figure size for better text visibility
        fig, ax = plt.subplots(figsize=(12, 10))

        colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

        for i, cls in enumerate(classes):
            if cls in roc_data:
                points = roc_data[cls]["points"]
                auc = roc_data[cls]["auc"]
                fpr = [p["fpr"] for p in points]
                tpr = [p["tpr"] for p in points]
                ax.plot(fpr, tpr, color=colors[i % len(colors)], lw=3,
                       label=f'{cls} (AUC = {auc:.3f})')

        ax.plot([0, 1], [0, 1], 'k--', lw=2, label='Random (AUC = 0.5)')
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.set_xlabel('False Positive Rate', fontsize=24, fontweight='bold')
        ax.set_ylabel('True Positive Rate', fontsize=24, fontweight='bold')
        ax.set_title('ROC Curve', fontsize=28, fontweight='bold', pad=20)
        ax.legend(loc="lower right", fontsize=18)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis='both', labelsize=18)

        plt.tight_layout()
        plt.savefig(output_path, dpi=600, bbox_inches='tight')
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to generate ROC chart: {e}")
        return None


async def _get_loss_data(task_id: str) -> Optional[Dict[str, Any]]:
    """Get loss data for ECharts rendering."""
    try:
        # Find model metrics file
        models_dir = Config.get_uploads_dir() / "models"
        metrics_file = None

        for model_dir in models_dir.iterdir():
            if model_dir.is_dir() and task_id in model_dir.name:
                mf = model_dir / "metrics.json"
                if mf.exists():
                    metrics_file = mf
                    break

        if not metrics_file:
            return None

        with open(metrics_file, 'r') as f:
            metrics = json.load(f)

        history = metrics.get("history", {})
        loss = history.get("loss", [])

        if not loss:
            return None

        return {
            "epochs": list(range(1, len(loss) + 1)),
            "loss": loss,
            "val_loss": history.get("val_loss", []),
            "accuracy": history.get("accuracy", []),
            "val_accuracy": history.get("val_accuracy", [])
        }
    except Exception as e:
        logger.error(f"Failed to get loss data: {e}")
        return None


async def _generate_loss_chart(task_id: str, output_path: Path) -> Optional[Path]:
    """Generate loss curve chart from training metrics."""
    try:
        plt = _setup_matplotlib_font()

        loss_data = await _get_loss_data(task_id)
        if not loss_data or not loss_data.get("loss"):
            return None

        loss = loss_data["loss"]

        # Larger figure size for better text visibility
        fig, ax = plt.subplots(figsize=(12, 10))
        ax.plot(range(1, len(loss) + 1), loss, 'b-', lw=3, label='Training Loss')

        # Plot validation loss if available
        val_loss = loss_data.get("val_loss", [])
        if val_loss:
            ax.plot(range(1, len(val_loss) + 1), val_loss, 'r--', lw=3, label='Validation Loss')

        ax.set_xlabel('Epoch', fontsize=24, fontweight='bold')
        ax.set_ylabel('Loss', fontsize=24, fontweight='bold')
        ax.set_title('Training Loss Curve', fontsize=28, fontweight='bold', pad=20)
        ax.legend(fontsize=18)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis='both', labelsize=18)

        plt.tight_layout()
        plt.savefig(output_path, dpi=600, bbox_inches='tight')
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to generate loss chart: {e}")
        return None


@router.get("/wsi/{wsi_id}")
async def get_results(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get AI analysis results for a WSI from database.

    Args:
        wsi_id: The WSI ID to get results for

    Returns:
        AI result data including predictions and probabilities
    """
    # Get from database
    result = await AIResultRepository.get_by_wsi_id(db, wsi_id)
    if result:
        return result.to_dict()

    # No result found
    return {"wsi_id": wsi_id, "pred": None, "probs": None}
