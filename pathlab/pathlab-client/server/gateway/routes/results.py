"""
AI Results API Routes

Handles retrieval of AI analysis results and comprehensive statistics.
"""
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.database.models import AIResult, WSISlide
from backend.database.repositories import AIResultRepository, WSIRepository

router = APIRouter(prefix="/results", tags=["AI Results"])
logger = logging.getLogger(__name__)


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


@router.get("/{wsi_id}")
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

