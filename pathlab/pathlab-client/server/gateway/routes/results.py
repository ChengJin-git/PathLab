"""
AI Results API Routes

Handles retrieval of AI analysis results, task-level analysis execution,
and saving analysis results to logs/analysis/{task_id}/.
"""
import asyncio
import functools
import logging
import json
import base64
import shutil
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Callable
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.orm import selectinload

from backend.ai.schemas.base import TaskStatus
from backend.database import get_db, safe_session
from backend.database.models import AIResult, WSISlide, TrainingTask, TrainedModel, TrainingTaskWSI, DataGroup, Dataset
from backend.database.repositories import AIResultRepository, WSIRepository, TrainingTaskRepository, TrainedModelRepository, DataGroupRepository, DatasetRepository, DatasetPermissionRepository
from backend.common.config import Config
from backend.storage import StorageManager
from backend.auth import current_active_user, User, get_user_from_header_or_param, get_user_from_token_param
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership, check_dataset_gpu_permission, check_wsi_access_permission, check_task_access_permission

# Initialize storage manager
storage_manager = StorageManager(str(Config.get_uploads_dir()))

router = APIRouter(prefix="/results", tags=["AI Results"])
logger = logging.getLogger(__name__)


async def _get_elevated_dataset_ids(user: User, db: AsyncSession) -> Optional[List[str]]:
    """
    Get dataset IDs for which the user has temporary elevated permissions.
    Returns None for admin users (no filtering needed).
    Returns empty list if no elevated permissions.
    """
    if user.is_admin():
        return None
    permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
    return [p.dataset_id for p in permissions if p.is_valid()]


# =============================================================================
# Analysis Task State Management (in-memory)
# =============================================================================

class AnalysisTaskState:
    """In-memory state for tracking analysis tasks."""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}  # Track running asyncio.Task for cancellation
        self._lock = asyncio.Lock()

    async def create(
        self,
        analysis_id: str,
        task_id: str,
        user_id: str,
        title: str = "",
        analysis_type: str = "internal"  # "internal" or "external"
    ) -> Dict[str, Any]:
        """Create a new analysis task entry."""
        async with self._lock:
            state = {
                "analysis_id": analysis_id,
                "task_id": task_id,
                "user_id": user_id,
                "title": title or f"Analyzing task {task_id}",
                "analysis_type": analysis_type,
                "status": TaskStatus.PENDING,  # pending, queued, running, completed, failed
                "progress": 0,
                "error_message": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "started_at": None,
                "finished_at": None,
            }
            self._tasks[analysis_id] = state
            logger.info(f"AnalysisTaskState.create: Created task analysis_id={analysis_id}, task_id={task_id}, title={title}, user_id={user_id}, total_tasks={len(self._tasks)}")
            return state.copy()

    async def get(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis task state."""
        async with self._lock:
            state = self._tasks.get(analysis_id)
            return state.copy() if state else None

    async def update(self, analysis_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update analysis task state."""
        async with self._lock:
            if analysis_id not in self._tasks:
                return None
            self._tasks[analysis_id].update(kwargs)
            return self._tasks[analysis_id].copy()

    async def set_queued(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as queued (waiting in GPU queue)."""
        return await self.update(
            analysis_id,
            status=TaskStatus.QUEUED,
            progress=0
        )

    async def set_running(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as running."""
        return await self.update(
            analysis_id,
            status=TaskStatus.RUNNING,
            progress=10,
            started_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_completed(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as completed."""
        return await self.update(
            analysis_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_failed(self, analysis_id: str, error: str) -> Optional[Dict[str, Any]]:
        """Mark task as failed."""
        return await self.update(
            analysis_id,
            status=TaskStatus.FAILED,
            error_message=error,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_cancelled(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as cancelled."""
        return await self.update(
            analysis_id,
            status=TaskStatus.CANCELLED,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    def register_task(self, analysis_id: str, task: asyncio.Task) -> None:
        """Register an asyncio.Task for potential cancellation."""
        self._running_tasks[analysis_id] = task

    def unregister_task(self, analysis_id: str) -> None:
        """Unregister an asyncio.Task after completion."""
        self._running_tasks.pop(analysis_id, None)

    async def cancel_running_task(self, analysis_id: str) -> bool:
        """Cancel a running asyncio.Task if it exists.

        Returns:
            True if task was found and cancel was called, False otherwise.
        """
        task = self._running_tasks.get(analysis_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled running analysis task: {analysis_id}")
            return True
        return False

    async def get_by_task_id(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all analysis tasks for a training task."""
        async with self._lock:
            return [
                state.copy() for state in self._tasks.values()
                if state["task_id"] == task_id
            ]

    async def get_all(self, user_id: Optional[str] = None, max_age_minutes: int = 10) -> List[Dict[str, Any]]:
        """Get all analysis tasks, optionally filtered by user.

        Args:
            user_id: If provided, filter to this user's tasks. If None (admin), return all.
            max_age_minutes: Only return completed/failed tasks within this age.

        Returns:
            List of analysis task states.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(minutes=max_age_minutes)
            results = []
            # Debug: log total tasks in memory
            if self._tasks:
                logger.debug(f"AnalysisTaskState.get_all: {len(self._tasks)} tasks in memory, user_id_filter={user_id}")
            for state in self._tasks.values():
                # Filter by user if specified
                if user_id and state.get("user_id") != user_id:
                    logger.debug(f"AnalysisTaskState.get_all: skipping task {state.get('analysis_id')} - user mismatch ({state.get('user_id')} != {user_id})")
                    continue
                # For completed/failed tasks, only include recent ones
                if state["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    finished = state.get("finished_at")
                    if finished:
                        try:
                            finished_dt = datetime.fromisoformat(finished.replace('Z', '+00:00'))
                            if finished_dt < cutoff:
                                logger.debug(f"AnalysisTaskState.get_all: skipping old completed task {state.get('analysis_id')}")
                                continue
                        except Exception:
                            pass
                results.append(state.copy())
            if results:
                logger.debug(f"AnalysisTaskState.get_all: returning {len(results)} tasks: {[(r.get('analysis_id'), r.get('status')) for r in results]}")
            return results

    async def cleanup_old(self, max_age_hours: int = 24):
        """Remove old completed/failed tasks from memory."""
        async with self._lock:
            cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
            to_remove = []
            for aid, state in self._tasks.items():
                if state["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    finished = state.get("finished_at")
                    if finished:
                        try:
                            finished_ts = datetime.fromisoformat(finished.replace('Z', '+00:00')).timestamp()
                            if finished_ts < cutoff:
                                to_remove.append(aid)
                        except Exception:
                            pass
            for aid in to_remove:
                del self._tasks[aid]


# Global analysis task state manager
_analysis_state = AnalysisTaskState()


def get_analysis_state() -> AnalysisTaskState:
    """Get the global analysis state manager."""
    return _analysis_state


class AnalysisRequest(BaseModel):
    """Request body for running analysis on a task."""
    metrics: List[str] = ["accuracy", "precision", "recall", "specificity", "f1", "auc"]
    charts: List[str] = ["roc_curve", "confusion_matrix", "loss_curve"]
    description: Optional[str] = None
    bootstrap_ci_metrics: List[str] = []  # List of metrics to compute 95% CI for (e.g., ["accuracy", "auc"])
    # Legacy support: compute_bootstrap_ci=True will compute CI for all requested metrics
    compute_bootstrap_ci: bool = False


@router.get("")
async def get_all_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all AI results with associated WSI labels for analysis.
    Users see only their own results, admin sees all.
    Users with temporary elevated dataset permissions can also see results for WSIs in those datasets.

    Returns:
        List of results with predictions and ground truth labels
    """
    # Query results with WSI info
    query = (
        select(AIResult, WSISlide)
        .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
    )
    # Filter by user_id if not admin (include results for elevated datasets)
    if not user.is_admin():
        elevated_dataset_ids = await _get_elevated_dataset_ids(user, db)
        conditions = [AIResult.user_id == str(user.id)]
        if elevated_dataset_ids:
            conditions.append(WSISlide.dataset_id.in_(elevated_dataset_ids))
        query = query.where(or_(*conditions))
    query = query.order_by(AIResult.created_at.desc()).offset(skip).limit(limit)

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
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive analysis statistics for all predictions.
    Users see only stats for their own data, admin sees all.

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
    # Filter by user_id if not admin (include results for elevated datasets)
    if not user.is_admin():
        elevated_dataset_ids = await _get_elevated_dataset_ids(user, db)
        conditions = [AIResult.user_id == str(user.id)]
        if elevated_dataset_ids:
            conditions.append(WSISlide.dataset_id.in_(elevated_dataset_ids))
        query = query.where(or_(*conditions))
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

    # Use sklearn for metrics calculation
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        confusion_matrix as sklearn_confusion_matrix, roc_curve, auc
    )

    all_classes = sorted(set(labels) | set(predictions))
    n_classes = len(all_classes)
    is_binary = n_classes == 2

    # Build confusion matrix using sklearn
    cm = sklearn_confusion_matrix(labels, predictions, labels=all_classes)

    # Convert to serializable format
    cm_dict = {
        "matrix": {
            all_classes[i]: {all_classes[j]: int(cm[i, j]) for j in range(n_classes)}
            for i in range(n_classes)
        },
        "classes": all_classes
    }

    # Per-class metrics using sklearn
    precision_per_class = precision_score(labels, predictions, labels=all_classes, average=None, zero_division=0)
    recall_per_class = recall_score(labels, predictions, labels=all_classes, average=None, zero_division=0)
    f1_per_class = f1_score(labels, predictions, labels=all_classes, average=None, zero_division=0)

    class_metrics = {}
    for i, cls in enumerate(all_classes):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        tn = cm.sum() - tp - fp - fn
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0

        class_metrics[cls] = {
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
            "precision": round(float(precision_per_class[i]), 4),
            "recall": round(float(recall_per_class[i]), 4),
            "sensitivity": round(float(recall_per_class[i]), 4),
            "specificity": round(float(specificity), 4),
            "f1": round(float(f1_per_class[i]), 4),
            "support": int(tp + fn)
        }

    # Overall metrics using sklearn
    accuracy = accuracy_score(labels, predictions)
    macro_precision = precision_score(labels, predictions, average='macro', zero_division=0)
    macro_recall = recall_score(labels, predictions, average='macro', zero_division=0)
    macro_f1 = f1_score(labels, predictions, average='macro', zero_division=0)
    macro_specificity = sum(m["specificity"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0

    weighted_precision = precision_score(labels, predictions, average='weighted', zero_division=0)
    weighted_recall = recall_score(labels, predictions, average='weighted', zero_division=0)
    weighted_f1 = f1_score(labels, predictions, average='weighted', zero_division=0)

    overall_metrics = {
        "accuracy": round(float(accuracy), 4),
        "macro_precision": round(float(macro_precision), 4),
        "macro_recall": round(float(macro_recall), 4),
        "macro_sensitivity": round(float(macro_recall), 4),
        "macro_specificity": round(float(macro_specificity), 4),
        "macro_f1": round(float(macro_f1), 4),
        "weighted_precision": round(float(weighted_precision), 4),
        "weighted_recall": round(float(weighted_recall), 4),
        "weighted_f1": round(float(weighted_f1), 4),
    }

    # ROC/AUC using sklearn
    roc_data = {}
    for i, cls in enumerate(all_classes):
        scores = []
        binary_labels = []
        for j, probs in enumerate(probs_list):
            if cls in probs:
                scores.append(probs[cls])
                binary_labels.append(1 if labels[j] == cls else 0)

        if scores and sum(binary_labels) > 0 and sum(binary_labels) < len(binary_labels):
            fpr, tpr, _ = roc_curve(binary_labels, scores)
            roc_auc = auc(fpr, tpr)
            roc_points = [{"fpr": float(f), "tpr": float(t)} for f, t in zip(fpr, tpr)]
            roc_data[cls] = {"points": roc_points, "auc": round(float(roc_auc), 4)}
            # Add per-class AUC to class_metrics
            if cls in class_metrics:
                class_metrics[cls]["auc"] = round(float(roc_auc), 4)

    if roc_data:
        overall_metrics["macro_auc"] = round(sum(r["auc"] for r in roc_data.values()) / len(roc_data), 4)

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


async def _check_task_resources_batch(task_ids: List[str], db: AsyncSession) -> Dict[str, dict]:
    """Batch check resources for multiple tasks.

    Uses database queries instead of file system scanning for better performance.
    Returns a dict mapping task_id -> resource info.

    NOTE: ai_results_count only counts results for test set WSIs to match
    the analysis behavior which only evaluates on test set.

    Task type handling:
    - WSI classification/survival: requires features/*.pt and aggregator.pth
    - Patch classification: requires linear_probe.pth only (features extracted on-the-fly)
    """
    if not task_ids:
        return {}

    uploads_dir = Config.get_uploads_dir()
    results = {}

    # Step 0: Get data_type and aggregation_level (via DataGroup) for all tasks
    task_types_query = (
        select(TrainingTask.task_id, DataGroup.data_type, DataGroup.aggregation_level)
        .join(DataGroup, TrainingTask.group_id == DataGroup.group_id)
        .where(TrainingTask.task_id.in_(task_ids))
    )
    task_types_result = await db.execute(task_types_query)
    # data_type is 'wsi' or 'patch', aggregation_level is 'file' or 'case'
    task_data_types = {}
    task_aggregation_levels = {}
    for row in task_types_result.all():
        task_data_types[row[0]] = row[1]
        task_aggregation_levels[row[0]] = row[2]

    # Step 0.5: Get total WSI count for all tasks (for external validation display)
    total_wsi_count_query = (
        select(
            TrainingTaskWSI.task_id,
            func.count(TrainingTaskWSI.wsi_id).label('count')
        )
        .where(TrainingTaskWSI.task_id.in_(task_ids))
        .group_by(TrainingTaskWSI.task_id)
    )
    total_wsi_count_result = await db.execute(total_wsi_count_query)
    total_wsi_by_task = {row[0]: row[1] for row in total_wsi_count_result.all()}

    # Step 0.6: For case-level tasks, count distinct case_ids
    case_level_task_ids = [tid for tid in task_ids if task_aggregation_levels.get(tid) == "case"]
    total_case_by_task = {}
    if case_level_task_ids:
        total_case_count_query = (
            select(
                TrainingTaskWSI.task_id,
                func.count(func.distinct(WSISlide.case_id)).label('count')
            )
            .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(TrainingTaskWSI.task_id.in_(case_level_task_ids))
            .group_by(TrainingTaskWSI.task_id)
        )
        total_case_count_result = await db.execute(total_case_count_query)
        total_case_by_task = {row[0]: row[1] for row in total_case_count_result.all()}

    # Step 1: Find which tasks have test sets defined
    tasks_with_test_set_query = (
        select(TrainingTaskWSI.task_id)
        .where(TrainingTaskWSI.task_id.in_(task_ids))
        .where(TrainingTaskWSI.split == "test")
        .distinct()
    )
    tasks_with_test_set_result = await db.execute(tasks_with_test_set_query)
    tasks_with_test_set = {row[0] for row in tasks_with_test_set_result.all()}

    # Step 1.5: Count test WSIs per task (for 100% AI results completeness check)
    test_wsi_count_by_task = {}
    if tasks_with_test_set:
        test_wsi_count_query = (
            select(
                TrainingTaskWSI.task_id,
                func.count(TrainingTaskWSI.wsi_id).label('count')
            )
            .where(TrainingTaskWSI.task_id.in_(list(tasks_with_test_set)))
            .where(TrainingTaskWSI.split == "test")
            .group_by(TrainingTaskWSI.task_id)
        )
        test_wsi_count_result = await db.execute(test_wsi_count_query)
        test_wsi_count_by_task = {row[0]: row[1] for row in test_wsi_count_result.all()}

    # Step 2: For tasks WITH test set, count AI results joined with test WSIs
    ai_count_with_test = {}
    if tasks_with_test_set:
        ai_count_with_test_query = (
            select(
                AIResult.task_id,
                func.count(AIResult.id).label('count')
            )
            .join(
                TrainingTaskWSI,
                and_(
                    AIResult.task_id == TrainingTaskWSI.task_id,
                    AIResult.wsi_id == TrainingTaskWSI.wsi_id,
                    TrainingTaskWSI.split == "test"
                )
            )
            .where(AIResult.task_id.in_(list(tasks_with_test_set)))
            .group_by(AIResult.task_id)
        )
        ai_count_with_test_result = await db.execute(ai_count_with_test_query)
        ai_count_with_test = {row[0]: row[1] for row in ai_count_with_test_result.all()}

    # Step 3: For tasks WITHOUT test set, count all AI results
    tasks_without_test_set = set(task_ids) - tasks_with_test_set
    ai_count_without_test = {}
    if tasks_without_test_set:
        ai_count_without_test_query = (
            select(
                AIResult.task_id,
                func.count(AIResult.id).label('count')
            )
            .where(AIResult.task_id.in_(list(tasks_without_test_set)))
            .group_by(AIResult.task_id)
        )
        ai_count_without_test_result = await db.execute(ai_count_without_test_query)
        ai_count_without_test = {row[0]: row[1] for row in ai_count_without_test_result.all()}

    # Combine AI results counts
    ai_results_by_task = {**ai_count_with_test, **ai_count_without_test}

    # Step 4: Check features and models for each task (file system, but minimal operations)
    models_dir = uploads_dir / "models"
    model_dirs_cache = []
    if models_dir.exists():
        model_dirs_cache = [d for d in models_dir.iterdir() if d.is_dir()]

    for task_id in task_ids:
        data_type = task_data_types.get(task_id, "wsi")
        is_patch_task = data_type == "patch"

        # Check features (not needed for patch classification)
        if is_patch_task:
            # Patch classification doesn't store pre-extracted features
            has_features = True  # Mark as True since it's not required
        else:
            features_dir = uploads_dir / "training" / task_id / "features"
            has_features = features_dir.exists() and any(features_dir.glob("*.pt"))

        # Check model (use cached directory list)
        # Support both regular training (aggregator.pth in model_dir) and
        # K-Fold training (aggregator.pth in model_dir/fold_X/)
        # Patch classification uses linear_probe.pth
        has_model = False
        model_id = None
        for model_dir in model_dirs_cache:
            if task_id in model_dir.name:
                # Check regular checkpoint location
                if (model_dir / "aggregator.pth").exists() or (model_dir / "linear_probe.pth").exists():
                    has_model = True
                    model_id = model_dir.name
                    break
                # Check K-Fold checkpoint location
                fold_checkpoints = list(model_dir.glob("fold_*/aggregator.pth")) + list(model_dir.glob("fold_*/linear_probe.pth"))
                if fold_checkpoints:
                    has_model = True
                    model_id = model_dir.name
                    break

        # Get AI results count from batch query
        ai_results_count = ai_results_by_task.get(task_id, 0)
        # 100% check: all expected WSIs must have AI results to skip GPU inference
        if task_id in tasks_with_test_set:
            expected_wsi_count = test_wsi_count_by_task.get(task_id, 0)
        else:
            expected_wsi_count = total_wsi_by_task.get(task_id, 0)
        has_ai_results = expected_wsi_count > 0 and ai_results_count >= expected_wsi_count

        # Get total WSI count and case count for this task
        total_wsi_count = total_wsi_by_task.get(task_id, 0)
        total_case_count = total_case_by_task.get(task_id, 0)
        aggregation_level = task_aggregation_levels.get(task_id, "file")

        results[task_id] = {
            "has_features": has_features,
            "has_model": has_model,
            "model_id": model_id,
            "has_ai_results": has_ai_results,
            "ai_results_count": ai_results_count,
            "total_wsi_count": total_wsi_count,
            "total_case_count": total_case_count,
            "aggregation_level": aggregation_level,
        }

    return results


async def _check_task_resources(task_id: str, db: AsyncSession) -> dict:
    """Check if task has features, model, and ai_results.

    NOTE: This is a wrapper around _check_task_resources_batch for single task use.
    For multiple tasks, use _check_task_resources_batch directly for better performance.
    """
    results = await _check_task_resources_batch([task_id], db)
    return results.get(task_id, {
        "has_features": False,
        "has_model": False,
        "model_id": None,
        "has_ai_results": False,
        "ai_results_count": 0,
        "total_wsi_count": 0,
        "total_case_count": 0,
        "aggregation_level": "file",
    })


@router.get("/tasks")
async def get_analysis_tasks(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of tasks available for analysis.
    Users see only their own tasks, admin sees all.
    Users with temporary elevated dataset permissions can also see tasks for those datasets.

    Only returns tasks that have both features and model available.
    Also indicates whether ai_results exist (needed before running analysis).

    OPTIMIZED: Uses batch query for AI results count instead of per-task file scanning.
    """
    task_list = []

    # Get completed tasks from database
    # Use selectinload to eagerly load data_group relationship to avoid lazy loading in async context
    query = select(TrainingTask).options(
        selectinload(TrainingTask.data_group)
    ).where(TrainingTask.status == TaskStatus.COMPLETED)
    # Filter by user_id if not admin (include tasks for elevated datasets)
    if not user.is_admin():
        elevated_dataset_ids = await _get_elevated_dataset_ids(user, db)
        conditions = [TrainingTask.user_id == str(user.id)]
        if elevated_dataset_ids:
            # Include tasks that have WSIs in elevated datasets
            elevated_task_ids_subquery = (
                select(TrainingTaskWSI.task_id)
                .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.dataset_id.in_(elevated_dataset_ids))
                .distinct()
            )
            conditions.append(TrainingTask.task_id.in_(elevated_task_ids_subquery))
        query = query.where(or_(*conditions))
    query = query.order_by(TrainingTask.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    if not tasks:
        return {"items": [], "total": 0}

    # Batch check resources for all tasks at once
    task_ids = [task.task_id for task in tasks]
    all_resources = await _check_task_resources_batch(task_ids, db)

    # Batch get WSI IDs for all tasks (for frontend WSI overlap detection)
    all_wsi_ids_by_task = await TrainingTaskRepository.get_wsi_ids_batch(db, task_ids)

    for task in tasks:
        resources = all_resources.get(task.task_id, {
            "has_features": False,
            "has_model": False,
            "model_id": None,
            "has_ai_results": False,
            "ai_results_count": 0,
            "total_wsi_count": 0,
            "total_case_count": 0,
            "aggregation_level": "file",
        })

        # Get data_type and task_type from DataGroup relationship
        data_group = task.data_group
        data_type = data_group.data_type if data_group else "wsi"
        task_type = data_group.task_type if data_group else "classification"

        # For WSI-level tasks: require both features and model
        # For patch-level tasks: only require model (features extracted on-the-fly during training)
        if data_type == "patch":
            if not resources["has_model"]:
                continue
        else:
            # WSI-level: need both features and model
            if not (resources["has_features"] and resources["has_model"]):
                continue

        analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task.task_id
        has_analysis = analysis_dir.exists() and any(analysis_dir.iterdir()) if analysis_dir.exists() else False

        # Extract feature_extractor and split_strategy from preprocessing_config
        feature_extractor = None
        is_kfold = False
        if task.preprocessing_config and isinstance(task.preprocessing_config, dict):
            feature_extractor = task.preprocessing_config.get("feature_extractor")
            # Check split strategy to determine if K-Fold training
            split_config = task.preprocessing_config.get("split_config", {})
            is_kfold = split_config.get("strategy") == "k_fold"

        # Determine display count based on aggregation_level
        aggregation_level = resources.get("aggregation_level", "file")
        if aggregation_level == "case":
            display_count = resources["total_case_count"]
        else:
            display_count = resources["total_wsi_count"]

        task_list.append({
            "task_id": task.task_id,
            "name": task.task_name or task.task_id,
            "task_type": task_type,
            "data_type": data_type,  # 'wsi' or 'patch'
            "aggregation_level": aggregation_level,  # 'file' or 'case'
            "status": task.status,
            "created_at": task.created_at.isoformat() + 'Z' if task.created_at else None,
            "has_analysis": has_analysis,
            "feature_extractor": feature_extractor,
            "has_features": resources["has_features"],
            "has_model": resources["has_model"],
            "model_id": resources["model_id"],
            "has_ai_results": resources["has_ai_results"],
            "ai_results_count": resources["ai_results_count"],
            "total_wsi_count": resources["total_wsi_count"],
            "total_case_count": resources["total_case_count"],
            "display_count": display_count,  # Count based on aggregation level
            "wsi_ids": all_wsi_ids_by_task.get(task.task_id, []),  # For WSI overlap detection
            "is_kfold": is_kfold,
            "source": "database"
        })

    return {"items": task_list, "total": len(task_list)}





def _split_case_attention_to_slides_static(
    attention: Optional[Any],
    case_id: str,
    case_wsi_patch_counts: Dict[str, List[int]],
    case_to_wsi: Dict[str, List[str]],
) -> Dict[str, Optional[Any]]:
    """
    Split case-level attention weights back to individual slides.
    Static version for use in results.py inference.
    """
    import numpy as np

    if attention is None:
        wsi_ids = case_to_wsi.get(case_id, [])
        return {wsi_id: None for wsi_id in wsi_ids}

    wsi_ids = case_to_wsi.get(case_id, [])
    patch_counts = case_wsi_patch_counts.get(case_id, [])

    if len(wsi_ids) != len(patch_counts):
        return {wsi_id: None for wsi_id in wsi_ids}

    slide_attentions: Dict[str, Optional["np.ndarray"]] = {}
    start_idx = 0

    for wsi_id, count in zip(wsi_ids, patch_counts):
        end_idx = start_idx + count
        if attention.ndim == 1:
            slide_attentions[wsi_id] = attention[start_idx:end_idx]
        elif attention.ndim == 2:
            slide_attentions[wsi_id] = attention[:, start_idx:end_idx]
        else:
            slide_attentions[wsi_id] = None
        start_idx = end_idx

    return slide_attentions


async def _run_inference_if_needed(
    task, db: AsyncSession, progress_callback: Optional[Callable[[float], Any]] = None
) -> bool:
    """
    Check if AI results are missing and run GPU inference if needed.

    This is the unified entry point for auto-inference in the analysis pipeline.
    Returns True if inference was run (or AI results already exist), False if inference failed.

    Args:
        task: The training task
        db: Database session
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)

    Raises:
        ValueError: If model or required resources are missing
    """
    task_id = task.task_id
    # Get data_type and task_type from DataGroup relationship
    data_group = task.data_group
    task_type = data_group.task_type if data_group else "classification"
    data_type = data_group.data_type if data_group else "wsi"

    # Check resources
    resources = await _check_task_resources(task_id, db)

    # If AI results already exist, no need to run inference
    if resources["has_ai_results"]:
        logger.info(f"AI results already exist for task {task_id}, skipping inference")
        if progress_callback:
            await progress_callback(1.0)
        return True

    # Check if we have model to run inference
    if not resources["has_model"]:
        raise ValueError(f"No model found for task {task_id}. Cannot run inference.")

    # Get WSI IDs from the task
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
    if not wsi_ids:
        raise ValueError(f"No WSI IDs found for task {task_id}")

    logger.info(f"AI results missing for task {task_id}, running GPU inference...")

    if progress_callback:
        await progress_callback(0.05)  # Starting inference

    # Route to appropriate inference handler based on data_type and task_type
    if data_type == "patch":
        await _run_inference_patch_classification(task, wsi_ids, resources, db, progress_callback)
    elif task_type in ("wsi_survival", "survival"):
        await _run_inference_wsi_survival(task, wsi_ids, resources, db, progress_callback)
    else:
        # Default: WSI classification
        await _run_inference_wsi_classification(task, wsi_ids, resources, db, progress_callback)

    logger.info(f"GPU inference completed for task {task_id}")
    if progress_callback:
        await progress_callback(1.0)
    return True


async def _run_inference_wsi_classification(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None
):
    """
    Run GPU inference to generate AI results for WSI classification task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses pre-extracted features and aggregator model to run inference.
    Saves classification results with attention weights.

    For case-level datasets, features are concatenated by case before inference,
    then attention is split back to per-slide for saving.

    Uses WSIFeatureDataset/CaseFeatureDataset for memory-efficient on-demand loading.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import torch.nn.functional as F
    import numpy as np
    from torch.utils.data import DataLoader
    from backend.ai.aggregators import get_aggregator
    from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset
    from backend.database.repositories import AIResultRepository

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Check features requirement for WSI tasks
    if not resources["has_features"]:
        raise HTTPException(status_code=400, detail="No features found for this task")

    # Load model
    model_dir = uploads_dir / "models" / resources["model_id"]
    ckpt_path = model_dir / "aggregator.pth"
    config_path = model_dir / "config.json"

    if not ckpt_path.exists():
        raise HTTPException(status_code=500, detail="Model checkpoint not found")

    # Load config
    config = {}
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)

    # Check if case-level from config
    aggregation_level = config.get("aggregation_level", "file")
    is_case_level = (aggregation_level == "case")

    # Determine classes from WSI labels
    classes = []
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi and wsi.label and wsi.label not in classes:
            classes.append(wsi.label)
    classes = sorted(classes)

    if len(classes) == 0:
        raise HTTPException(status_code=400, detail="Could not determine classes from WSI labels")

    # Build labels dict
    labels = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi and wsi.label:
            labels[wsi_id] = classes.index(wsi.label)

    # Features directory
    features_dir = uploads_dir / "training" / task_id / "features"

    # Filter wsi_ids to only those with existing features
    valid_wsi_ids = [wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()]
    if not valid_wsi_ids:
        raise HTTPException(status_code=400, detail="Could not find any feature files")

    # Load model checkpoint
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(ckpt_path, map_location=device)

    # Get aggregator
    aggregator_name = config.get("model", "abmil")
    model = get_aggregator(
        aggregator_name,
        in_dim=checkpoint["in_dim"],
        num_classes=checkpoint["num_classes"]
    ).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    has_raw_attention = hasattr(model, 'forward_with_raw_attention')

    # Delete old AIResult records before regenerating to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Run inference and save results
    ai_results_root = uploads_dir / "ai_results"
    results_saved = 0

    feature_extractor = None
    if task.preprocessing_config and isinstance(task.preprocessing_config, dict):
        feature_extractor = task.preprocessing_config.get("feature_extractor")

    # Prepare case-level structures if needed
    case_to_wsi: Dict[str, List[str]] = {}
    case_wsi_patch_counts: Dict[str, List[int]] = {}

    with torch.inference_mode():
        if is_case_level:
            # Get case_id mapping and build case-level structures
            wsi_case_map = await TrainingTaskRepository.get_wsi_case_ids(db, task_id)

            # Group WSIs by case_id (only valid ones)
            for wsi_id in valid_wsi_ids:
                case_id = wsi_case_map.get(wsi_id, wsi_id)
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # Build case_labels
            case_labels: Dict[str, int] = {}
            for case_id, case_wsi_ids in case_to_wsi.items():
                if case_wsi_ids[0] in labels:
                    case_labels[case_id] = labels[case_wsi_ids[0]]

            # Create CaseFeatureDataset for on-demand loading
            case_ids = list(case_to_wsi.keys())
            dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=case_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_type="classification",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)

            logger.info(f"Case-level inference: {len(case_ids)} cases from {len(valid_wsi_ids)} slides")
            total_items = len(case_ids)

            # Run inference per case using DataLoader
            for idx, (features, label, case_id, batch_wsi_ids, batch_patch_counts) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                if progress_callback and total_items > 0:
                    await progress_callback(0.1 + 0.8 * (idx / total_items))
                # Unpack batch (batch_size=1)
                H = features.squeeze(0).to(device)
                case_id = case_id[0]
                wsi_ids_in_case = list(batch_wsi_ids[0]) if isinstance(batch_wsi_ids[0], (list, tuple)) else [batch_wsi_ids[0]]
                patch_counts = [int(c) for c in batch_patch_counts[0]]
                case_wsi_patch_counts[case_id] = patch_counts

                # Forward pass
                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())
                pred_label = classes[pred_idx]
                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}

                # Split attention back to per-slide
                attention_np = attention.cpu().numpy() if attention is not None else None
                raw_attention_np = raw_attention.cpu().numpy() if raw_attention is not None else None

                slide_attentions = _split_case_attention_to_slides_static(
                    attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )
                slide_raw_attentions = _split_case_attention_to_slides_static(
                    raw_attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )

                # Save result for each slide in the case
                for wsi_id in case_to_wsi[case_id]:
                    gt_label = classes[labels.get(wsi_id, 0)] if wsi_id in labels else "unknown"

                    wsi_result_dir = ai_results_root / wsi_id
                    wsi_result_dir.mkdir(parents=True, exist_ok=True)

                    slide_att = slide_attentions.get(wsi_id)
                    slide_raw_att = slide_raw_attentions.get(wsi_id)

                    attention_shape = list(slide_att.shape) if slide_att is not None else None
                    attention_type = "none"
                    if slide_att is not None:
                        attention_type = "multi_class" if slide_att.ndim == 2 else "single"

                    result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "task_name": task.task_name or task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "feature_extractor": feature_extractor,
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "case_id": case_id,
                        "aggregation_level": "case",
                    }

                    result_file = wsi_result_dir / f"train_{task_id}_result.json"
                    with open(result_file, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)

                    attention_file_path = None
                    if slide_raw_att is not None:
                        raw_att_file = wsi_result_dir / f"train_{task_id}_attention_raw.npy"
                        np.save(raw_att_file, slide_raw_att)

                    if slide_att is not None:
                        att_file = wsi_result_dir / f"train_{task_id}_attention.npy"
                        np.save(att_file, slide_att)
                        attention_file_path = str(att_file)

                    db_result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "extra_metadata": {
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label,
                            "classes": classes,
                            "task_type": "wsi_classification",
                            "aggregator": aggregator_name,
                            "attention_type": attention_type,
                            "attention_shape": attention_shape,
                            "result_file": str(result_file),
                            "attention_file": attention_file_path,
                            "case_id": case_id,
                            "aggregation_level": "case",
                        }
                    }
                    await AIResultRepository.create(db, db_result_data)
                    results_saved += 1
        else:
            # Slide-level inference using WSIFeatureDataset
            dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=valid_wsi_ids,
                labels=labels,
                task_type="classification",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
            total_items = len(valid_wsi_ids)

            for idx, (features, label, wsi_id) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                if progress_callback and total_items > 0:
                    await progress_callback(0.1 + 0.8 * (idx / total_items))

                # Unpack batch (batch_size=1)
                H = features.squeeze(0).to(device)
                wsi_id = wsi_id[0]

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())
                pred_label = classes[pred_idx]

                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                gt_label = classes[labels.get(wsi_id, 0)] if wsi_id in labels else "unknown"

                wsi_result_dir = ai_results_root / wsi_id
                wsi_result_dir.mkdir(parents=True, exist_ok=True)

                attention_shape = None
                attention_type = "none"
                attention_file_path = None
                if attention is not None:
                    attention_np = attention.cpu().numpy()
                    attention_shape = list(attention_np.shape)
                    attention_type = "multi_class" if attention_np.ndim == 2 else "single"

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "task_name": task.task_name or task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "ground_truth": gt_label,
                    "correct": pred_label == gt_label,
                    "classes": classes,
                    "feature_extractor": feature_extractor,
                    "aggregator": aggregator_name,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                }

                result_file = wsi_result_dir / f"train_{task_id}_result.json"
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                if raw_attention is not None:
                    raw_attention_np = raw_attention.cpu().numpy()
                    raw_att_file = wsi_result_dir / f"train_{task_id}_attention_raw.npy"
                    np.save(raw_att_file, raw_attention_np)

                if attention is not None:
                    att_file = wsi_result_dir / f"train_{task_id}_attention.npy"
                    np.save(att_file, attention_np)
                    attention_file_path = str(att_file)

                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "extra_metadata": {
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "task_type": "wsi_classification",
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "result_file": str(result_file),
                        "attention_file": attention_file_path,
                    }
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1

    await db.commit()
    logger.info(f"Generated AI results for WSI classification task {task_id}: {results_saved} WSIs")

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "wsi_classification",
        "wsi_count": results_saved,
        "classes": classes,
    }


async def _run_inference_patch_classification(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None
):
    """
    Run GPU inference to generate AI results for patch classification task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses feature extractor + linear probe on images directly.
    Generates CAM heatmaps for visualization.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import numpy as np
    from PIL import Image
    from backend.ai.extractors import get_extractor
    from backend.ai.utils.cam_utils import get_cam_extractor, get_cam_spatial_size, is_cnn_extractor
    from backend.database.repositories import AIResultRepository

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Load model
    model_dir = uploads_dir / "models" / resources["model_id"]
    ckpt_path = model_dir / "linear_probe.pth"
    config_path = model_dir / "config.json"

    if not ckpt_path.exists():
        raise HTTPException(status_code=500, detail="Model checkpoint (linear_probe.pth) not found")

    # Load config
    config = {}
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)

    # Determine classes from WSI labels or config
    classes = config.get("classes", [])
    if not classes:
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if wsi and wsi.label and wsi.label not in classes:
                classes.append(wsi.label)
        classes = sorted(classes)

    if len(classes) == 0:
        raise HTTPException(status_code=400, detail="Could not determine classes")

    # Build labels dict and image paths
    labels = {}
    image_paths = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi:
            if wsi.label and wsi.label in classes:
                labels[wsi_id] = classes.index(wsi.label)
            image_paths[wsi_id] = wsi.wsi_path

    if not image_paths:
        raise HTTPException(status_code=400, detail="No image paths found")

    # Load checkpoint
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(ckpt_path, map_location=device)

    extractor_name = checkpoint.get("extractor_name", config.get("extractor", "resnet50"))
    extractor_dim = checkpoint["extractor_dim"]
    num_classes = checkpoint["num_classes"]

    # Build model: extractor + linear probe
    extractor = get_extractor(extractor_name, pretrained=True)
    extractor = extractor.to(device)
    extractor.eval()

    linear_probe = nn.Linear(extractor_dim, num_classes).to(device)
    linear_probe.load_state_dict(checkpoint["state_dict"])
    linear_probe.eval()

    # Get transforms
    fm_transform = extractor.get_transforms()

    # Get CAM extractor
    cam_extractor = get_cam_extractor(extractor_name)
    cam_size = get_cam_spatial_size(extractor_name)
    use_gradients = is_cnn_extractor(extractor_name)

    # Combined model for CAM extraction
    class CombinedModel(nn.Module):
        def __init__(self, extractor, linear_probe):
            super().__init__()
            self.extractor = extractor
            self.linear_probe = linear_probe

        def forward(self, x):
            features = self.extractor(x)
            return self.linear_probe(features)

    combined_model = CombinedModel(extractor, linear_probe).to(device)
    combined_model.eval()

    # Delete old AIResult records before regenerating to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Run inference
    ai_results_root = uploads_dir / "ai_results"
    results_saved = 0
    total_items = len(image_paths)

    with torch.set_grad_enabled(use_gradients):
        for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
            # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
            if progress_callback and total_items > 0:
                await progress_callback(0.1 + 0.8 * (idx / total_items))

            try:
                img = Image.open(img_path).convert("RGB")
                img_tensor = fm_transform(img).unsqueeze(0).to(device)

                # Forward pass
                with torch.inference_mode():
                    logits = combined_model(img_tensor)
                    probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                    pred_idx = int(probs.argmax())
                    pred_label = classes[pred_idx]

                # Extract CAM
                try:
                    cam_map = cam_extractor.extract_cam(
                        model=combined_model,
                        input_tensor=img_tensor,
                        target_class=pred_idx,
                    )
                    cam_map = cam_map.squeeze(0)
                except Exception:
                    cam_map = np.ones(cam_size, dtype=np.float32) / (cam_size[0] * cam_size[1])

                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                gt_label = classes[labels[wsi_id]] if wsi_id in labels else "unknown"

                wsi_result_dir = ai_results_root / wsi_id
                wsi_result_dir.mkdir(parents=True, exist_ok=True)

                # Save CAM
                cam_file = wsi_result_dir / f"train_{task_id}_cam.npy"
                np.save(cam_file, cam_map)

                # Save result JSON
                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "ground_truth": gt_label,
                    "correct": pred_label == gt_label,
                    "classes": classes,
                    "cam_file": str(cam_file),
                    "cam_size": list(cam_size),
                }

                result_file = wsi_result_dir / f"train_{task_id}_result.json"
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                # Save to database
                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "extra_metadata": {
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "task_type": "patch_classification",
                        "cam_file": str(cam_file),
                        "cam_size": list(cam_size),
                        "result_file": str(result_file),
                    }
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1

            except Exception as e:
                logger.warning(f"Failed to process {wsi_id}: {e}")
                continue

    await db.commit()
    logger.info(f"Generated AI results for patch classification task {task_id}: {results_saved} images")

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "patch_classification",
        "wsi_count": results_saved,
        "classes": classes,
    }


async def _run_inference_wsi_survival(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None
):
    """
    Run GPU inference to generate AI results for WSI survival prediction task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses pre-extracted features and aggregator model to compute risk scores,
    hazards, and survival probabilities.

    For case-level datasets, features are concatenated by case before inference,
    then attention is split back to per-slide for saving.

    Uses WSIFeatureDataset/CaseFeatureDataset for memory-efficient on-demand loading.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import numpy as np
    from torch.utils.data import DataLoader
    from backend.ai.aggregators import get_aggregator
    from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset
    from backend.database.repositories import AIResultRepository

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Check features requirement for WSI tasks
    if not resources["has_features"]:
        raise HTTPException(status_code=400, detail="No features found for this task")

    # Load model
    model_dir = uploads_dir / "models" / resources["model_id"]
    ckpt_path = model_dir / "aggregator.pth"
    config_path = model_dir / "config.json"

    if not ckpt_path.exists():
        raise HTTPException(status_code=500, detail="Model checkpoint not found")

    # Load config
    config = {}
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)

    # Check if case-level from config
    aggregation_level = config.get("aggregation_level", "file")
    is_case_level = (aggregation_level == "case")

    # Features directory
    features_dir = uploads_dir / "training" / task_id / "features"

    # Filter wsi_ids to only those with existing features
    valid_wsi_ids = [wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()]
    if not valid_wsi_ids:
        raise HTTPException(status_code=400, detail="Could not find any feature files")

    # Get survival metadata (event_time, event_status) for each WSI
    # Batch fetch all WSIs to avoid N+1 query problem
    times_map: Dict[str, float] = {}
    statuses_map: Dict[str, int] = {}

    wsi_map = await WSIRepository.get_by_ids(db, valid_wsi_ids)
    for wsi_id in valid_wsi_ids:
        wsi = wsi_map.get(wsi_id)
        if wsi:
            times_map[wsi_id] = float(wsi.event_time) if wsi.event_time is not None else 0.0
            statuses_map[wsi_id] = int(wsi.event_status) if wsi.event_status is not None else 0
        else:
            times_map[wsi_id] = 0.0
            statuses_map[wsi_id] = 0

    # Load model checkpoint
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(ckpt_path, map_location=device)

    # Get bin_edges from checkpoint (required for survival)
    bin_edges = checkpoint.get("bin_edges", None)
    if bin_edges is None:
        raise HTTPException(status_code=500, detail="Checkpoint missing bin_edges for survival task")
    if isinstance(bin_edges, torch.Tensor):
        bin_edges = bin_edges.cpu().numpy()

    # Get aggregator
    aggregator_name = config.get("model", "abmil")
    model = get_aggregator(
        aggregator_name,
        in_dim=checkpoint["in_dim"],
        num_classes=checkpoint["num_classes"]
    ).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    has_raw_attention = hasattr(model, 'forward_with_raw_attention')

    # Delete old AIResult records before regenerating to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Run inference and collect results
    ai_results_root = uploads_dir / "ai_results"

    bin_edges_list = bin_edges.tolist() if hasattr(bin_edges, 'tolist') else list(bin_edges)

    # Collect all risk scores first (for median calculation)
    all_risks: List[float] = []
    # Store inference results for later saving
    case_results: List[Dict[str, Any]] = []

    # Prepare case-level structures if needed
    case_to_wsi: Dict[str, List[str]] = {}
    case_wsi_patch_counts: Dict[str, List[int]] = {}

    with torch.inference_mode():
        if is_case_level:
            # Get case_id mapping and build case-level structures
            wsi_case_map = await TrainingTaskRepository.get_wsi_case_ids(db, task_id)

            # Group WSIs by case_id (only valid ones)
            for wsi_id in valid_wsi_ids:
                case_id = wsi_case_map.get(wsi_id, wsi_id)
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # Build case_times and case_statuses
            case_times: Dict[str, float] = {}
            case_statuses: Dict[str, int] = {}
            for case_id, case_wsi_ids in case_to_wsi.items():
                first_wsi = case_wsi_ids[0]
                case_times[case_id] = times_map.get(first_wsi, 0.0)
                case_statuses[case_id] = statuses_map.get(first_wsi, 0)

            # Create CaseFeatureDataset for on-demand loading
            case_ids = list(case_to_wsi.keys())
            dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=case_ids,
                case_to_wsi=case_to_wsi,
                times=case_times,
                statuses=case_statuses,
                task_type="survival",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)

            logger.info(f"Case-level inference: {len(case_ids)} cases from {len(valid_wsi_ids)} slides")
            total_items = len(case_ids)

            # Case-level inference using DataLoader
            for idx, (features, time_val, status_val, case_id, batch_wsi_ids, batch_patch_counts) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                if progress_callback and total_items > 0:
                    await progress_callback(0.1 + 0.8 * (idx / total_items))
                # Unpack batch (batch_size=1)
                H = features.squeeze(0).to(device)
                case_id = case_id[0]
                patch_counts = [int(c) for c in batch_patch_counts[0]]
                case_wsi_patch_counts[case_id] = patch_counts

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                surv = np.cumprod(1 - hazards)
                risk_score = float(np.sum(hazards))
                all_risks.append(risk_score)

                attention_np = attention.cpu().numpy() if attention is not None else None
                raw_attention_np = raw_attention.cpu().numpy() if raw_attention is not None else None

                case_results.append({
                    "case_id": case_id,
                    "risk_score": risk_score,
                    "hazards": hazards.tolist(),
                    "surv_probs": surv.tolist(),
                    "event_time": float(time_val.item()),
                    "event_status": int(status_val.item()),
                    "attention_np": attention_np,
                    "raw_attention_np": raw_attention_np,
                })
        else:
            # Slide-level inference using WSIFeatureDataset
            dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=valid_wsi_ids,
                times=times_map,
                statuses=statuses_map,
                task_type="survival",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
            total_items = len(valid_wsi_ids)

            for idx, (features, time_val, status_val, wsi_id) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                if progress_callback and total_items > 0:
                    await progress_callback(0.1 + 0.8 * (idx / total_items))

                # Unpack batch (batch_size=1)
                H = features.squeeze(0).to(device)
                wsi_id = wsi_id[0]

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                surv = np.cumprod(1 - hazards)
                risk_score = float(np.sum(hazards))
                all_risks.append(risk_score)

                attention_np = attention.cpu().numpy() if attention is not None else None
                raw_attention_np = raw_attention.cpu().numpy() if raw_attention is not None else None

                case_results.append({
                    "wsi_id": wsi_id,
                    "risk_score": risk_score,
                    "hazards": hazards.tolist(),
                    "surv_probs": surv.tolist(),
                    "event_time": float(time_val.item()),
                    "event_status": int(status_val.item()),
                    "attention_np": attention_np,
                    "raw_attention_np": raw_attention_np,
                })

    # Calculate median risk score for stratification
    median_risk_score = float(np.median(all_risks)) if all_risks else 0.0

    # Save results
    results_saved = 0

    if is_case_level:
        # Save per-slide results for case-level
        for case_result in case_results:
            case_id = case_result["case_id"]
            risk_score = case_result["risk_score"]
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            # Split attention back to per-slide
            slide_attentions = _split_case_attention_to_slides_static(
                case_result["attention_np"], case_id, case_wsi_patch_counts, case_to_wsi
            )
            slide_raw_attentions = _split_case_attention_to_slides_static(
                case_result["raw_attention_np"], case_id, case_wsi_patch_counts, case_to_wsi
            )

            for wsi_id in case_to_wsi[case_id]:
                result_dir = ai_results_root / wsi_id
                result_dir.mkdir(parents=True, exist_ok=True)

                slide_att = slide_attentions.get(wsi_id)
                slide_raw_att = slide_raw_attentions.get(wsi_id)

                attention_shape = list(slide_att.shape) if slide_att is not None else None
                attention_type = "none"
                if slide_att is not None:
                    attention_type = "multi_class" if slide_att.ndim == 2 else "single"

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "risk_score": risk_score,
                    "hazards": case_result["hazards"],
                    "surv_probs": case_result["surv_probs"],
                    "event_time": times_map.get(wsi_id, case_result["event_time"]),
                    "event_status": statuses_map.get(wsi_id, case_result["event_status"]),
                    "bin_edges": bin_edges_list,
                    "aggregator": aggregator_name,
                    "median_risk_score": median_risk_score,
                    "risk_group": risk_group,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                    "case_id": case_id,
                    "aggregation_level": "case",
                }

                result_file = result_dir / f"train_{task_id}_result.json"
                with open(result_file, 'w') as f:
                    json.dump(result_data, f, indent=2)

                attention_file_path = None
                if slide_att is not None:
                    att_file = result_dir / f"train_{task_id}_attention.npy"
                    np.save(att_file, slide_att)
                    attention_file_path = str(att_file)

                if slide_raw_att is not None:
                    raw_att_file = result_dir / f"train_{task_id}_attention_raw.npy"
                    np.save(raw_att_file, slide_raw_att)

                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": risk_group,
                    "probs": None,
                    "extra_metadata": {
                        "task_type": "survival",
                        "risk_score": risk_score,
                        "risk_group": risk_group,
                        "median_risk_score": median_risk_score,
                        "hazards": case_result["hazards"],
                        "surv_probs": case_result["surv_probs"],
                        "event_time": result_data["event_time"],
                        "event_status": result_data["event_status"],
                        "bin_edges": bin_edges_list,
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "result_file": str(result_file),
                        "attention_file": attention_file_path,
                        "case_id": case_id,
                        "aggregation_level": "case",
                    }
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1
    else:
        # Slide-level saving (original logic)
        for slide_result in case_results:
            wsi_id = slide_result["wsi_id"]
            risk_score = slide_result["risk_score"]
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            result_dir = ai_results_root / wsi_id
            result_dir.mkdir(parents=True, exist_ok=True)

            attention_np = slide_result["attention_np"]
            raw_attention_np = slide_result["raw_attention_np"]

            attention_shape = list(attention_np.shape) if attention_np is not None else None
            attention_type = "none"
            if attention_np is not None:
                attention_type = "multi_class" if attention_np.ndim == 2 else "single"

            result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "risk_score": risk_score,
                "hazards": slide_result["hazards"],
                "surv_probs": slide_result["surv_probs"],
                "event_time": slide_result["event_time"],
                "event_status": slide_result["event_status"],
                "bin_edges": bin_edges_list,
                "aggregator": aggregator_name,
                "median_risk_score": median_risk_score,
                "risk_group": risk_group,
                "attention_type": attention_type,
                "attention_shape": attention_shape,
            }

            result_file = result_dir / f"train_{task_id}_result.json"
            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            attention_file_path = None
            if attention_np is not None:
                att_file = result_dir / f"train_{task_id}_attention.npy"
                np.save(att_file, attention_np)
                attention_file_path = str(att_file)

            if raw_attention_np is not None:
                raw_att_file = result_dir / f"train_{task_id}_attention_raw.npy"
                np.save(raw_att_file, raw_attention_np)

            db_result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "pred": risk_group,
                "probs": None,
                "extra_metadata": {
                    "task_type": "survival",
                    "risk_score": risk_score,
                    "risk_group": risk_group,
                    "median_risk_score": median_risk_score,
                    "hazards": slide_result["hazards"],
                    "surv_probs": slide_result["surv_probs"],
                    "event_time": slide_result["event_time"],
                    "event_status": slide_result["event_status"],
                    "bin_edges": bin_edges_list,
                    "aggregator": aggregator_name,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                    "result_file": str(result_file),
                    "attention_file": attention_file_path,
                }
            }
            await AIResultRepository.create(db, db_result_data)
            results_saved += 1

    await db.commit()
    logger.info(f"Generated AI results for WSI survival task {task_id}: {results_saved} WSIs")

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "wsi_survival",
        "wsi_count": results_saved,
        "median_risk_score": median_risk_score,
    }


@router.get("/datasets-for-validation")
async def get_datasets_for_validation(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all datasets available for external validation selection.
    Returns dataset metadata including aggregation_level, task_type, data_type,
    slide/case counts, distinct label count, and WSI IDs (for overlap detection).

    WSI datasets are only included if ALL their WSIs have feature_extracted=True
    in the database. Patch datasets are exempt from this check.
    """
    datasets = await DatasetRepository.get_all(db)
    result = []
    for ds in datasets:
        dg = ds.data_group
        if not dg:
            continue

        # Skip external_validation datasets - only show real datasets
        if dg.task_type == "external_validation":
            continue

        dataset_id = ds.dataset_id

        # Get WSI IDs
        wsi_ids = await DatasetRepository.get_wsi_ids(db, dataset_id)
        if not wsi_ids:
            continue  # Skip empty datasets

        # For WSI datasets, require ALL WSIs to have pre-extracted features.
        # Patch datasets are exempt (models process images directly).
        if dg.data_type != "patch":
            extracted_count = await DatasetRepository.get_feature_extracted_count(db, dataset_id)
            if extracted_count < len(wsi_ids):
                continue  # Skip datasets with missing features

        # Get distinct label count (for classification matching)
        distinct_label_count = await DatasetRepository.get_distinct_label_count(db, dataset_id)

        # Get case count for case-level datasets
        total_wsi_count = len(wsi_ids)
        total_case_count = total_wsi_count
        if dg.aggregation_level == "case":
            case_map = await DatasetRepository.get_wsi_case_ids(db, dataset_id)
            total_case_count = len(set(case_map.values()))

        # Determine display count based on aggregation_level
        display_count = total_case_count if dg.aggregation_level == "case" else total_wsi_count

        result.append({
            "dataset_id": dataset_id,
            "name": ds.name,
            "data_type": dg.data_type,
            "aggregation_level": dg.aggregation_level,
            "task_type": dg.task_type,
            "total_wsi_count": total_wsi_count,
            "total_case_count": total_case_count,
            "display_count": display_count,
            "distinct_label_count": distinct_label_count,
            "wsi_ids": wsi_ids,
        })

    return {"items": result, "total": len(result)}


class ExternalValidationRequest(BaseModel):
    """Request for external validation - use a trained model on a dataset."""
    model_id: str  # TrainedModel ID from the models table
    dataset_id: str   # Dataset whose WSIs will be used for validation
    # Analysis options
    metrics: Optional[List[str]] = None  # Metrics to compute (default: accuracy, precision, recall, f1, auc)
    charts: Optional[List[str]] = None  # Charts to generate (default: confusion_matrix, roc_curve)
    compute_bootstrap_ci: Optional[bool] = False  # Whether to compute 95% CI via bootstrap



@router.post("/external-validation")
async def start_external_validation(
    req: ExternalValidationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start external validation: use a trained model to run inference on WSIs from a dataset.
    Requires pathologist/admin role OR temporary elevated permission for the dataset.
    Users can only validate with models/data they own.

    Creates a TrainingTask record with task_type="external_validation" and submits to the
    GPU task queue for execution. Progress is tracked via SSE like training tasks.

    Returns the task_id that can be used to track progress.
    """
    import uuid as uuid_module
    from ..task_queue import get_task_queue, TaskType

    # Validate model exists
    trained_model = await TrainedModelRepository.get_by_id(db, req.model_id)
    if not trained_model:
        raise HTTPException(status_code=404, detail=f"Model not found: {req.model_id}")

    # Check ownership of the model (supports temporary elevated dataset permissions)
    # First get model's training task to check dataset_id for temp permission
    model_task = await TrainingTaskRepository.get_by_id(db, trained_model.task_id)
    if not model_task:
        raise HTTPException(status_code=404, detail=f"Model's training task not found: {trained_model.task_id}")
    model_mc = model_task.model_config or {}
    if not await check_task_access_permission(user, trained_model.user_id, model_mc.get("dataset_id"), db):
        raise HTTPException(status_code=403, detail="You don't have permission to use this model")

    if not trained_model.is_active:
        raise HTTPException(status_code=400, detail=f"Model is not active: {req.model_id}")

    # Validate target dataset exists
    target_dataset = await DatasetRepository.get_by_id(db, req.dataset_id)
    if not target_dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {req.dataset_id}")

    # Check ownership of the dataset (supports temporary elevated dataset permissions)
    if target_dataset.user_id and not check_data_ownership(target_dataset.user_id, user):
        # Fallback: check temporary elevated permission for the target dataset
        has_temp_dataset_perm = await DatasetPermissionRepository.has_valid_permission(
            db, req.dataset_id, str(user.id), "pathologist"
        )
        if not has_temp_dataset_perm:
            raise HTTPException(status_code=403, detail="You don't have permission to use this dataset")

    # Check GPU permission for the target dataset
    has_permission = await check_dataset_gpu_permission(user, req.dataset_id, db)
    if not has_permission and not user.can_use_gpu():
        raise HTTPException(
            status_code=403,
            detail="You don't have GPU permission for this dataset. Contact admin for temporary access."
        )

    # ========================================================================
    # COMPATIBILITY VALIDATION
    # ========================================================================

    # Get data_type and task_type from DataGroup relationships
    model_data_group = model_task.data_group
    target_data_group = target_dataset.data_group

    # 1. Validate data_type compatibility (WSI model <-> WSI data, Patch model <-> Patch data)
    model_data_type = model_data_group.data_type if model_data_group else "wsi"
    target_data_type = target_data_group.data_type if target_data_group else "wsi"
    if model_data_type != target_data_type:
        raise HTTPException(
            status_code=400,
            detail=f"Data type mismatch: Model trained on '{model_data_type}' data cannot validate '{target_data_type}' data. "
                   f"Please select a dataset with '{model_data_type}' data type."
        )

    # 2. Validate task_type compatibility (Classification <-> Classification, Survival <-> Survival)
    # Normalize task types for comparison
    def is_classification_task(task_type: str) -> bool:
        return task_type in ("classification", "wsi_classification", "patch_classification")

    def is_survival_task(task_type: str) -> bool:
        return task_type in ("wsi_survival", "survival")

    model_task_type = model_data_group.task_type if model_data_group else "classification"
    target_task_type = target_data_group.task_type if target_data_group else "classification"

    model_is_classification = is_classification_task(model_task_type)
    target_is_classification = is_classification_task(target_task_type)
    model_is_survival = is_survival_task(model_task_type)
    target_is_survival = is_survival_task(target_task_type)

    if model_is_classification and not target_is_classification:
        raise HTTPException(
            status_code=400,
            detail=f"Task type mismatch: Classification model cannot validate survival data. "
                   f"Model type: '{model_task_type}', Target dataset type: '{target_task_type}'. "
                   f"Please select a classification dataset."
        )

    if model_is_survival and not target_is_survival:
        raise HTTPException(
            status_code=400,
            detail=f"Task type mismatch: Survival model cannot validate classification data. "
                   f"Model type: '{model_task_type}', Target dataset type: '{target_task_type}'. "
                   f"Please select a survival dataset."
        )

    # 3. Validate class count matching (for classification tasks)
    if model_is_classification and target_is_classification:
        model_class_count = len(trained_model.classes) if trained_model.classes else 0
        dataset_label_count = await DatasetRepository.get_distinct_label_count(db, req.dataset_id)
        if model_class_count != dataset_label_count:
            raise HTTPException(
                status_code=400,
                detail=f"Class count mismatch: Model predicts {model_class_count} classes, "
                       f"but dataset has {dataset_label_count} distinct labels. "
                       f"Please select a dataset with {model_class_count} classes."
            )

    # Get WSI IDs from target dataset
    wsi_ids = await DatasetRepository.get_wsi_ids(db, req.dataset_id)
    if not wsi_ids:
        raise HTTPException(status_code=400, detail=f"No WSI IDs found for dataset: {req.dataset_id}")

    # 4. Prevent validating on data that overlaps with training data (WSI-level check)
    model_wsi_ids = set(await TrainingTaskRepository.get_wsi_ids(db, trained_model.task_id))
    data_wsi_ids = set(wsi_ids)
    overlapping_wsi_ids = model_wsi_ids & data_wsi_ids
    if overlapping_wsi_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Data leakage detected: {len(overlapping_wsi_ids)} WSI(s) in the selected dataset "
                   f"were also used in the model's training data. "
                   f"Please select a dataset with no overlapping slides for external validation."
        )

    # Check if inference results already exist for this model + data combination
    # Look for existing extval_*_result.json files in the WSI ai_results directories
    uploads_dir = Config.get_uploads_dir()
    existing_results_count = 0
    existing_validation_id = None

    def _check_existing_results():
        """Check for existing external validation results."""
        nonlocal existing_results_count, existing_validation_id
        for wsi_id in wsi_ids:
            ai_results_dir = uploads_dir / "ai_results" / wsi_id
            if ai_results_dir.exists():
                # Look for extval_*_result.json files
                for result_file in ai_results_dir.glob("extval_*_result.json"):
                    try:
                        with open(result_file, 'r') as f:
                            result_data = json.load(f)
                        # Check if this result is from the same model
                        if result_data.get("task_id") == trained_model.task_id:
                            existing_results_count += 1
                            # Extract validation_task_id from the result
                            if existing_validation_id is None:
                                existing_validation_id = result_data.get("validation_task_id")
                            break  # Found result for this WSI, move to next
                    except Exception:
                        continue
        return existing_results_count, existing_validation_id

    await asyncio.to_thread(_check_existing_results)

    # Prepare analysis options
    analysis_metrics = req.metrics or ["accuracy", "precision", "recall", "f1", "auc"]
    analysis_charts = req.charts or ["confusion_matrix", "roc_curve"]
    bootstrap_ci_metrics = analysis_metrics if req.compute_bootstrap_ci else []

    # If we have existing results for ALL WSIs, skip GPU inference and run analysis directly.
    # BUT: verify the referenced task still exists in the database first.
    # If the DB was reset or the task was deleted, the cached task ID is stale — fall through
    # to create a new task instead.
    if existing_results_count >= len(wsi_ids) and existing_validation_id:
        existing_task = await TrainingTaskRepository.get_by_id(db, existing_validation_id)
        if existing_task is None:
            logger.warning(
                f"Existing results reference task {existing_validation_id} which no longer exists in DB. "
                f"Ignoring cached results and creating a new task."
            )
        else:
            logger.info(f"Found existing inference results for {existing_results_count}/{len(wsi_ids)} WSIs, skipping GPU inference")
            logger.info(f"  - Existing validation task: {existing_validation_id}")

            # Check if analysis results also already exist
            analysis_dir = uploads_dir / "logs" / "analysis" / existing_validation_id
            analysis_exists = False
            if analysis_dir.exists():
                for item in sorted(analysis_dir.iterdir(), reverse=True):
                    if item.is_dir() and (item / "summary.json").exists():
                        analysis_exists = True
                        break

            if analysis_exists:
                logger.info(f"Both inference and analysis exist for {existing_validation_id}, skipping entirely")
                return {
                    "task_id": existing_validation_id,
                    "status": TaskStatus.COMPLETED,
                    "total_wsi": len(wsi_ids),
                    "existing_results": existing_results_count,
                    "message": "External validation already completed (inference + analysis exist)",
                }

            logger.info(f"  - Running analysis directly with bootstrap_ci={req.compute_bootstrap_ci}")

            # Run analysis directly on existing results
            await _auto_trigger_external_validation_analysis(
                task_id=existing_validation_id,
                model_task_id=trained_model.task_id,
                model_id=req.model_id,
                dataset_id=req.dataset_id,
                metrics=analysis_metrics,
                charts=analysis_charts,
                bootstrap_ci_metrics=bootstrap_ci_metrics,
            )

            return {
                "task_id": existing_validation_id,
                "status": "analysis_started",
                "total_wsi": len(wsi_ids),
                "existing_results": existing_results_count,
                "message": f"Found existing inference results. Running analysis directly on {existing_results_count} WSIs.",
            }

    # Create validation task ID
    validation_id = f"extval_{uuid_module.uuid4().hex[:16]}"

    # Get or create DataGroup for external validation
    # Use the same data_type as the target dataset, with "external_validation" task_type
    # and the target dataset's aggregation level
    target_aggregation_level = target_data_group.aggregation_level if target_data_group else "file"
    validation_data_group = await DataGroupRepository.get_or_create(
        db,
        data_type=target_data_type,
        aggregation_level=target_aggregation_level,
        task_type="external_validation"
    )

    # Create task record in database (reuse TrainingTask table)
    from backend.database.models import TrainingTask
    validation_task = TrainingTask(
        task_id=validation_id,
        task_name=f"External Validation: {trained_model.model_name} → {target_dataset.name or req.dataset_id}",
        group_id=validation_data_group.group_id,
        user_id=str(user.id),
        task_description=f"Validate model '{trained_model.model_name}' on dataset '{target_dataset.name}'",
        status=TaskStatus.PENDING,
        progress=0,
        classes=trained_model.classes,
        preprocessing_config=model_task.preprocessing_config or {
            "feature_extractor": trained_model.feature_extractor,
        },
        model_config={
            "model_id": req.model_id,
            "model_task_id": trained_model.task_id,
            "dataset_id": req.dataset_id,
            "total_wsi": len(wsi_ids),
            "aggregator": trained_model.aggregator,  # Store aggregator name for task list display
            # Store analysis options for auto-triggered analysis
            "analysis_metrics": analysis_metrics,
            "analysis_charts": analysis_charts,
            "bootstrap_ci_metrics": bootstrap_ci_metrics,
        },
    )
    db.add(validation_task)
    await db.flush()
    await db.commit()

    logger.info(f"Created external validation task: {validation_id}")
    logger.info(f"  - Model: {trained_model.model_name} ({req.model_id})")
    logger.info(f"  - Target dataset: {target_dataset.name} ({req.dataset_id})")
    logger.info(f"  - WSI count: {len(wsi_ids)}")
    logger.info(f"  - Bootstrap CI: {req.compute_bootstrap_ci}")

    # Submit to task queue for execution
    task_queue = get_task_queue()
    pipeline_kwargs = {
        "model_task_id": trained_model.task_id,
        "model_id": req.model_id,
        "model_classes": trained_model.classes,
        "model_task_type": model_task_type,  # Pass model's task type for survival vs classification handling
        "model_data_type": model_data_type,  # "wsi" or "patch"
        "dataset_id": req.dataset_id,
        "wsi_ids": wsi_ids,
    }
    await task_queue.submit(
        task_id=validation_id,
        task_type=TaskType.EXTERNAL_VALIDATION,
        coro_func=_run_external_validation,
        **pipeline_kwargs
    )

    return {
        "task_id": validation_id,
        "status": TaskStatus.PENDING,
        "total_wsi": len(wsi_ids),
        "message": f"External validation queued. Use model '{trained_model.model_name}' on {len(wsi_ids)} WSIs from '{target_dataset.name or req.dataset_id}'",
    }


@router.get("/external-validation/{task_id}")
async def get_validation_progress(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the progress of an external validation task. Users can only view their own tasks."""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Validation task not found: {task_id}")

    # Check ownership (supports temporary elevated dataset permissions)
    mc = task.model_config or {}
    if not await check_task_access_permission(user, task.user_id, mc.get("dataset_id"), db):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task")

    # Check if this is an external validation task via DataGroup
    task_data_group = task.data_group
    task_type = task_data_group.task_type if task_data_group else None
    if task_type != "external_validation":
        raise HTTPException(status_code=400, detail=f"Task {task_id} is not an external validation task")

    model_config = task.model_config or {}

    # Overlay file-based progress if available (more up-to-date than DB during inference).
    # This mirrors the pattern used in the training SSE endpoint (training.py lines 306-308).
    from backend.common.progress_store import get_progress
    file_prog = get_progress(task_id)
    progress = file_prog if file_prog is not None else task.progress

    # Calculate processed_wsi from progress when DB value is stale.
    # During chunked inference, set_progress() updates file-based progress (0-90%)
    # but update_task_progress() only writes to DB at milestones, so processed_wsi stays at 0.
    total_wsi = model_config.get("total_wsi", 0)
    processed_wsi = model_config.get("processed_wsi", 0)
    if processed_wsi == 0 and progress > 0 and total_wsi > 0:
        # 0-90% maps to inference progress, 90-100% is post-processing
        if progress <= 90:
            processed_wsi = int(total_wsi * progress / 90)
        else:
            processed_wsi = total_wsi

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": progress,
        "total_wsi": total_wsi,
        "processed_wsi": processed_wsi,
        "model_id": model_config.get("model_id"),
        "model_task_id": model_config.get("model_task_id"),
        "dataset_id": model_config.get("dataset_id"),
        "error": task.error_message,
        "results_count": model_config.get("results_count"),
    }


@router.get("/external-validation/completed")
async def get_completed_external_validations(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all completed external validation tasks with their analysis status.
    Used by the frontend to restore previously completed results when the user
    returns to the External Validation tab.

    Returns a list of completed extval tasks with model_id, dataset_id,
    and whether analysis results exist.
    """
    # Query completed external validation tasks
    query = (
        select(TrainingTask)
        .join(DataGroup, TrainingTask.group_id == DataGroup.group_id)
        .where(
            and_(
                DataGroup.task_type == "external_validation",
                TrainingTask.status == TaskStatus.COMPLETED,
            )
        )
    )
    # Filter by user_id if not admin (include tasks for elevated datasets)
    if not user.is_admin():
        elevated_dataset_ids = await _get_elevated_dataset_ids(user, db)
        conditions = [TrainingTask.user_id == str(user.id)]
        if elevated_dataset_ids:
            elevated_task_ids_subquery = (
                select(TrainingTaskWSI.task_id)
                .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.dataset_id.in_(elevated_dataset_ids))
                .distinct()
            )
            conditions.append(TrainingTask.task_id.in_(elevated_task_ids_subquery))
        query = query.where(or_(*conditions))
    query = query.order_by(TrainingTask.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    items = []
    for task in tasks:
        mc = task.model_config or {}
        # Check if analysis results exist on disk
        analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task.task_id
        has_analysis = False
        if analysis_dir.exists():
            for item in analysis_dir.iterdir():
                if item.is_dir() and (item / "summary.json").exists():
                    has_analysis = True
                    break

        items.append({
            "task_id": task.task_id,
            "model_id": mc.get("model_id"),
            "model_task_id": mc.get("model_task_id"),
            "dataset_id": mc.get("dataset_id"),
            "total_wsi": mc.get("total_wsi", 0),
            "results_count": mc.get("results_count", 0),
            "has_analysis": has_analysis,
            "created_at": task.created_at.isoformat() + "Z" if task.created_at else None,
        })

    return {"items": items}


async def _run_external_validation_patch_classification(
    task_id: str,
    model_task_id: str,
    model_id: str,
    model_classes: List[str],
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: str,
    logger_manager,
    update_task_progress,
):
    """Run external validation for patch classification models.

    Loads the feature extractor + linear probe, runs inference on each image,
    generates CAM heatmaps, and saves results. Pattern follows
    _run_inference_patch_classification but adapted for external validation context.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import numpy as np
    from PIL import Image
    from backend.ai.extractors import get_extractor
    from backend.ai.utils.cam_utils import get_cam_extractor, get_cam_spatial_size, is_cnn_extractor
    from backend.database.repositories import AIResultRepository, WSIRepository
    from backend.database.database import safe_session
    from backend.common.progress_store import clear_progress

    uploads_dir = Config.get_uploads_dir()
    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")

    try:
        # Load model checkpoint(s)
        model_dir = uploads_dir / "models" / model_id
        config_path = model_dir / "config.json"

        config = {}
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)

        classes = model_classes or config.get("classes", [])
        if not classes:
            raise ValueError("Could not determine model classes")

        is_kfold = config.get("split_type") == "kfold"
        num_folds = config.get("num_folds", 5) if is_kfold else 1

        async with logger_manager.session() as (tl, _db):
            kfold_msg = f" (k-fold: {num_folds} folds)" if is_kfold else ""
            await tl.info(f"Patch classification: loading model {model_id} with {len(classes)} classes{kfold_msg}")

        # Load checkpoint(s) and build model(s) (in thread to avoid blocking event loop)
        def _load_models():
            _extractor_name = config.get("extractor", "resnet50")
            _models = []

            if is_kfold:
                # K-fold: load each fold's linear_probe and build a combined model
                for fold_idx in range(num_folds):
                    fold_ckpt_path = model_dir / f"fold_{fold_idx}" / "linear_probe.pth"
                    if not fold_ckpt_path.exists():
                        raise FileNotFoundError(f"Fold {fold_idx} checkpoint not found: {fold_ckpt_path}")

                    checkpoint = torch.load(fold_ckpt_path, map_location=device)
                    # K-fold checkpoints use "feature_dim" instead of "extractor_dim"
                    extractor_dim = checkpoint.get("feature_dim") or checkpoint.get("extractor_dim")
                    _num_classes = checkpoint["num_classes"]

                    fold_probe = nn.Linear(extractor_dim, _num_classes).to(device)
                    fold_probe.load_state_dict(checkpoint["state_dict"])
                    fold_probe.eval()
                    _models.append(fold_probe)
            else:
                # Regular: single checkpoint at root
                ckpt_path = model_dir / "linear_probe.pth"
                if not ckpt_path.exists():
                    raise FileNotFoundError(f"Model checkpoint (linear_probe.pth) not found at {ckpt_path}")

                checkpoint = torch.load(ckpt_path, map_location=device)
                _extractor_name = checkpoint.get("extractor_name", _extractor_name)
                extractor_dim = checkpoint.get("extractor_dim") or checkpoint.get("feature_dim")
                _num_classes = checkpoint["num_classes"]

                probe = nn.Linear(extractor_dim, _num_classes).to(device)
                probe.load_state_dict(checkpoint["state_dict"])
                probe.eval()
                _models.append(probe)

            # Build shared extractor (frozen, shared across all folds)
            _extractor = get_extractor(_extractor_name, pretrained=True)
            _extractor = _extractor.to(device)
            _extractor.eval()

            return _extractor, _models, _extractor_name

        extractor, linear_probes, extractor_name = await asyncio.to_thread(_load_models)

        # Get transforms and CAM extractor
        fm_transform = extractor.get_transforms()
        cam_extractor = get_cam_extractor(extractor_name)
        cam_size = get_cam_spatial_size(extractor_name)
        use_gradients = is_cnn_extractor(extractor_name)

        # Combined model for CAM extraction (uses first probe for CAM; ensemble for prediction)
        class CombinedModel(nn.Module):
            def __init__(self, ext, probe):
                super().__init__()
                self.extractor = ext
                self.linear_probe = probe

            def forward(self, x):
                features = self.extractor(x)
                return self.linear_probe(features)

        # For CAM, use the first linear probe (all folds share the same extractor)
        combined_model = CombinedModel(extractor, linear_probes[0]).to(device)
        combined_model.eval()

        # Build labels dict and image paths from target dataset WSIs
        labels = {}
        image_paths = {}
        task_user_id = None
        async with safe_session() as db:
            for wsi_id in wsi_ids:
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if wsi:
                    if wsi.label and wsi.label in classes:
                        labels[wsi_id] = classes.index(wsi.label)
                    image_paths[wsi_id] = wsi.wsi_path

            # Get user_id from the task for saving results later
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = str(task_record.user_id) if task_record and task_record.user_id else None

        if not image_paths:
            raise ValueError("No image paths found for target WSIs")

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Running inference on {len(image_paths)} images (extractor: {extractor_name})")

        await update_task_progress(TaskStatus.RUNNING, 10)

        # Delete old AIResult records for this task
        async with safe_session() as db:
            deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
            await db.commit()
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

        # Run inference (in thread to avoid blocking event loop)
        ai_results_root = uploads_dir / "ai_results"
        results_saved = 0
        total_items = len(image_paths)

        def _run_inference():
            nonlocal results_saved
            all_results = []
            with torch.set_grad_enabled(use_gradients):
                for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
                    try:
                        img = Image.open(img_path).convert("RGB")
                        img_tensor = fm_transform(img).unsqueeze(0).to(device)

                        # K-fold ensemble: average logits across all folds
                        if is_kfold:
                            with torch.inference_mode():
                                features = extractor(img_tensor)
                                all_logits = []
                                for fold_probe in linear_probes:
                                    fold_logits = fold_probe(features)
                                    all_logits.append(fold_logits)
                                avg_logits = torch.mean(torch.stack(all_logits), dim=0)
                                probs = F.softmax(avg_logits, dim=-1).squeeze(0).cpu().numpy()
                                pred_idx = int(probs.argmax())
                                pred_label = classes[pred_idx]
                        else:
                            with torch.inference_mode():
                                logits = combined_model(img_tensor)
                                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                                pred_idx = int(probs.argmax())
                                pred_label = classes[pred_idx]

                        # Extract CAM (uses combined_model with first probe)
                        try:
                            cam_map = cam_extractor.extract_cam(
                                model=combined_model,
                                input_tensor=img_tensor,
                                target_class=pred_idx,
                            )
                            cam_map = cam_map.squeeze(0)
                        except Exception:
                            cam_map = np.ones(cam_size, dtype=np.float32) / (cam_size[0] * cam_size[1])

                        probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                        gt_label = classes[labels[wsi_id]] if wsi_id in labels else "unknown"

                        wsi_result_dir = ai_results_root / wsi_id
                        wsi_result_dir.mkdir(parents=True, exist_ok=True)

                        # Save CAM
                        cam_file = wsi_result_dir / f"extval_{task_id}_cam.npy"
                        np.save(cam_file, cam_map)

                        # Save result JSON (aligned with WSI branch fields)
                        result_data = {
                            "wsi_id": wsi_id,
                            "task_id": model_task_id,
                            "validation_source": dataset_id,
                            "validation_task_id": task_id,
                            "task_type": "patch_classification",
                            "aggregation_level": "file",
                            "pred": pred_label,
                            "probs": probs_dict,
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label if gt_label != "unknown" else None,
                            "classes": classes,
                            "cam_file": str(cam_file),
                            "cam_size": list(cam_size),
                            "is_kfold": is_kfold,
                            "num_folds": num_folds if is_kfold else None,
                        }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        with open(result_file, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        all_results.append({
                            "wsi_id": wsi_id,
                            "pred": pred_label,
                            "probs": probs_dict,
                            "gt_label": gt_label,
                            "correct": pred_label == gt_label if gt_label != "unknown" else None,
                            "cam_file": str(cam_file),
                            "cam_size": list(cam_size),
                            "result_file": str(result_file),
                        })
                        results_saved += 1
                    except Exception as e:
                        logger.warning(f"Failed to process {wsi_id}: {e}")
                        continue
            return all_results

        all_results = await asyncio.to_thread(_run_inference)

        # Save to database (aligned with WSI branch fields)
        async with safe_session() as db:
            for r in all_results:
                db_result_data = {
                    "wsi_id": r["wsi_id"],
                    "task_id": task_id,
                    "user_id": task_user_id,
                    "pred": r["pred"],
                    "probs": r["probs"],
                    "extra_metadata": {
                        "validation_type": "external",
                        "model_task_id": model_task_id,
                        "dataset_id": dataset_id,
                        "aggregation_level": "file",
                        "ground_truth": r["gt_label"],
                        "correct": r["correct"],
                        "classes": classes,
                        "task_type": "patch_classification",
                        "cam_file": r["cam_file"],
                        "cam_size": r["cam_size"],
                        "result_file": r["result_file"],
                    }
                }
                await AIResultRepository.create(db, db_result_data)
            await db.commit()

        clear_progress(task_id)
        await update_task_progress(TaskStatus.COMPLETED, 100, results_saved, results_saved)

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Patch classification external validation completed: {results_saved}/{total_items} images processed")

        # Auto-trigger analysis
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
        )

    except Exception as e:
        import traceback
        logger.error(f"Patch classification external validation {task_id} failed: {e}\n{traceback.format_exc()}")
        try:
            clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"Patch classification external validation failed: {e}")
        except Exception:
            pass
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=str(e))
    finally:
        try:
            import gc
            gc.collect()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as cleanup_err:
            logger.warning(f"Patch ext-val {task_id}: VRAM cleanup failed: {cleanup_err}")


async def _run_external_validation(
    task_id: str,
    model_task_id: str,
    model_id: str,
    model_classes: List[str],
    model_task_type: str,  # "classification", "wsi_classification", "survival", "wsi_survival", "patch_classification"
    model_data_type: str = "wsi",  # "wsi" or "patch"
    dataset_id: str = "",
    wsi_ids: List[str] = None,
    assigned_device: str = None,  # GPU device assigned by task queue (e.g., "cuda:0")
):
    """Background task to run external validation.

    This function is called by the task queue and updates progress in the database.
    Supports WSI classification, WSI survival, and patch classification models.
    Supports case-level inference based on the target dataset's aggregation_level.

    Architecture:
    - Pre-inference DB queries run in async context (fast, short-lived sessions)
    - Synchronous DataLoader + model inference runs in a thread via asyncio.to_thread()
      to avoid blocking the event loop (which would cause DB lock + frontend freeze)
    - Progress updates during inference use file-based progress_store (no DB needed)
    - Post-inference: results are batch-inserted into ai_results table
    """
    import torch
    import torch.nn.functional as F
    import numpy as np
    import httpx
    from sqlalchemy import update as sql_update
    from backend.database.models import TrainingTask
    from backend.database.database import safe_session
    from backend.common.progress_store import set_progress, clear_progress
    from gateway.pipeline import ScopedLogger
    from gateway.dependencies import PREPROCESSING_SERVICE_URL, AI_SERVICE_URL
    from backend.ai.tasks.feature_cache import compute_params_hash, find_cached_features, create_symlink_to_cache

    wsi_ids = wsi_ids or []

    # ScopedLogger writes to training_logs table so SSE log stream works
    logger_manager = ScopedLogger(task_id)

    # Determine if this is a survival task
    is_survival = model_task_type in ("survival", "wsi_survival")

    async def update_task_progress(status: str, progress: int, processed_wsi: int = 0,
                                   results_count: int = 0, error_msg: str = None):
        """Helper to update task status in database. Uses safe_session for background tasks."""
        async with safe_session() as db:
            # Update status and progress
            await TrainingTaskRepository.update_status(db, task_id, status, progress, error_msg)

            # Update model_config with processed_wsi and results_count
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if task:
                model_config = task.model_config or {}
                model_config["processed_wsi"] = processed_wsi
                model_config["results_count"] = results_count
                await db.execute(
                    sql_update(TrainingTask)
                    .where(TrainingTask.task_id == task_id)
                    .values(model_config=model_config)
                )
            await db.commit()

    try:
        # Mark as running and log start
        await update_task_progress(TaskStatus.RUNNING, 0)
        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Starting external validation for task: {task_id}")
            await tl.info(f"Model: {model_id} | Dataset: {dataset_id} | WSIs: {len(wsi_ids)} | Data type: {model_data_type} | Task type: {model_task_type}")

        uploads_dir = Config.get_uploads_dir()

        # ================================================================
        # Patch-level tasks: branch to dedicated handlers
        # ================================================================
        if model_data_type == "patch":
            is_patch_segmentation = model_task_type in ("patch_segmentation", "segmentation")
            if is_patch_segmentation:
                # TODO: Patch segmentation external validation not yet implemented.
                # The patch segmentation training module does not register TrainedModel
                # in the database, so this code path should not be reachable in practice.
                raise NotImplementedError(
                    "Patch segmentation external validation is not yet supported. "
                    "This module is still under development."
                )

            # Patch classification external validation
            await _run_external_validation_patch_classification(
                task_id=task_id,
                model_task_id=model_task_id,
                model_id=model_id,
                model_classes=model_classes,
                dataset_id=dataset_id,
                wsi_ids=wsi_ids,
                assigned_device=assigned_device,
                logger_manager=logger_manager,
                update_task_progress=update_task_progress,
            )
            return

        # Load model - wrapped in asyncio.to_thread because torch.load() is
        # CPU-intensive (pickle deserialization) and would block the event loop.
        model_dir = uploads_dir / "models" / model_id
        config_path = model_dir / "config.json"
        device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")

        def _sync_load_models():
            """Load model config and checkpoint(s). Runs in thread to avoid blocking event loop."""
            from backend.ai.aggregators import get_aggregator

            _config = {}
            if config_path.exists():
                with open(config_path, 'r') as f:
                    _config = json.load(f)

            _is_kfold = _config.get("split_type") == "kfold"
            _num_folds = _config.get("num_folds", 5) if _is_kfold else 1
            _aggregator_name = _config.get("model", "abmil")

            _models = []
            _bin_edges = None

            if _is_kfold:
                logger.info(f"K-fold model detected with {_num_folds} folds, loading all checkpoints")
                _all_fold_bin_edges = []
                for fold_idx in range(_num_folds):
                    fold_ckpt_path = model_dir / f"fold_{fold_idx}" / "aggregator.pth"
                    if not fold_ckpt_path.exists():
                        raise FileNotFoundError(f"Fold {fold_idx} checkpoint not found: {fold_ckpt_path}")

                    checkpoint = torch.load(fold_ckpt_path, map_location=device)
                    fold_model = get_aggregator(
                        _aggregator_name,
                        in_dim=checkpoint["in_dim"],
                        num_classes=checkpoint["num_classes"]
                    ).to(device)
                    fold_model.load_state_dict(checkpoint["state_dict"])
                    fold_model.eval()
                    _models.append(fold_model)

                    if is_survival:
                        fold_be = checkpoint.get("bin_edges")
                        if fold_be is not None:
                            fold_be = np.array(fold_be) if not isinstance(fold_be, np.ndarray) else fold_be
                            _all_fold_bin_edges.append(fold_be)

                # Average bin_edges across all folds for ensemble survival model
                if is_survival and _all_fold_bin_edges:
                    if len(_all_fold_bin_edges) == 1:
                        _bin_edges = _all_fold_bin_edges[0]
                    else:
                        # All folds should have same number of bins; average the edges
                        min_len = min(len(be) for be in _all_fold_bin_edges)
                        trimmed = [be[:min_len] for be in _all_fold_bin_edges]
                        _bin_edges = np.mean(trimmed, axis=0)
            else:
                ckpt_path = model_dir / "aggregator.pth"
                if not ckpt_path.exists():
                    raise FileNotFoundError(f"Model checkpoint not found: {ckpt_path}")

                checkpoint = torch.load(ckpt_path, map_location=device)
                _model = get_aggregator(
                    _aggregator_name,
                    in_dim=checkpoint["in_dim"],
                    num_classes=checkpoint["num_classes"]
                ).to(device)
                _model.load_state_dict(checkpoint["state_dict"])
                _model.eval()
                _models.append(_model)

                if is_survival:
                    _bin_edges = checkpoint.get("bin_edges")
                    if _bin_edges is not None:
                        _bin_edges = np.array(_bin_edges) if not isinstance(_bin_edges, np.ndarray) else _bin_edges

            _has_raw_attention = hasattr(_models[0], 'forward_with_raw_attention')
            return _models, _bin_edges, _has_raw_attention, _config, _is_kfold, _num_folds, _aggregator_name

        models, bin_edges, has_raw_attention, config, is_kfold, num_folds, aggregator_name = await asyncio.to_thread(_sync_load_models)

        async with logger_manager.session() as (tl, _db):
            if is_kfold:
                await tl.info(f"Loaded k-fold model ({num_folds} folds) on device: {device}, aggregator: {aggregator_name}")
            else:
                await tl.info(f"Loaded model on device: {device}, aggregator: {aggregator_name}")

        # Use classes from TrainedModel directly (for classification)
        classes = model_classes

        # Get test dataset's data_level and ground truth data
        is_case_level = False
        wsi_case_map: Dict[str, str] = {}

        async with safe_session() as db:
            # Get aggregation_level from target dataset
            aggregation_level = await DatasetRepository.get_aggregation_level(db, dataset_id)
            is_case_level = aggregation_level == "case"
            logger.info(f"External validation: target dataset aggregation_level = {aggregation_level}, is_case_level = {is_case_level}")

            if is_case_level:
                # Get case_id mapping for case-level inference
                wsi_case_map = await DatasetRepository.get_wsi_case_ids(db, dataset_id)
                logger.info(f"External validation: loaded case_id mapping for {len(wsi_case_map)} WSIs")

            # Batch-fetch all WSI metadata in one query (avoids N+1 query problem)
            wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)

            # Get user_id from the task for saving results later
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = str(task_record.user_id) if task_record and task_record.user_id else None

            if is_survival:
                # For survival: get event_time and event_status from WSI metadata
                survival_data = {}
                for wsi_id in wsi_ids:
                    wsi = wsi_map.get(wsi_id)
                    if wsi:
                        event_time = getattr(wsi, 'event_time', None) or (wsi.extra_metadata or {}).get('event_time')
                        event_status = getattr(wsi, 'event_status', None) or (wsi.extra_metadata or {}).get('event_status')
                        if event_time is not None:
                            survival_data[wsi_id] = {
                                "event_time": float(event_time),
                                "event_status": int(event_status or 0)
                            }
            else:
                # For classification: get class labels
                labels = {}
                for wsi_id in wsi_ids:
                    wsi = wsi_map.get(wsi_id)
                    if wsi and wsi.label and wsi.label in classes:
                        labels[wsi_id] = classes.index(wsi.label)

        # ================================================================
        # Build features directory using global cache (params_hash based).
        # If features are missing, automatically extract them via
        # preprocessing + AI services (same pattern as pipeline.py).
        # ================================================================
        features_dir = uploads_dir / "training" / task_id / "features"
        features_dir.mkdir(parents=True, exist_ok=True)

        # Get preprocessing_config from the validation task record
        async with safe_session() as db:
            val_task = await TrainingTaskRepository.get_by_id(db, task_id)
            preprocessing_config = (val_task.preprocessing_config if val_task else {}) or {}

        feature_extractor = preprocessing_config.get("feature_extractor", "resnet50")

        # Compute params_hash from preprocessing config
        seg_params = {
            "sthresh": preprocessing_config.get("sthresh", 8),
            "mthresh": preprocessing_config.get("mthresh", 7),
            "close": preprocessing_config.get("close", 4),
            "use_otsu": preprocessing_config.get("use_otsu", False),
        }
        filter_params = {
            "a_t": preprocessing_config.get("a_t", 1),
            "a_h": preprocessing_config.get("a_h", 256),
            "max_n_holes": preprocessing_config.get("max_n_holes", 100),
        }
        level = preprocessing_config.get("level", 0)
        contour_fn = preprocessing_config.get("contour_fn", "four_pt")
        use_padding = preprocessing_config.get("use_padding", True)

        params_hash = compute_params_hash(
            level=level,
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=contour_fn,
            use_padding=use_padding,
        )

        # Step 1: Check global feature cache for each WSI
        cached_wsi_ids = []
        missing_wsi_ids = []

        def _check_feature_cache():
            for wsi_id in wsi_ids:
                cached_path = find_cached_features(uploads_dir, feature_extractor, params_hash, wsi_id)
                if cached_path is not None:
                    create_symlink_to_cache(features_dir, wsi_id, cached_path)
                    cached_wsi_ids.append(wsi_id)
                else:
                    missing_wsi_ids.append(wsi_id)

        await asyncio.to_thread(_check_feature_cache)

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Feature cache: {len(cached_wsi_ids)}/{len(wsi_ids)} WSIs found in global cache (hash={params_hash})")

        # Step 2: If features are missing, extract them via preprocessing + AI services
        if missing_wsi_ids:
            async with logger_manager.session() as (tl, _db):
                await tl.info(f"Extracting features for {len(missing_wsi_ids)} WSIs missing from cache...")

            # Update status to EXTRACTING so frontend shows feature extraction stage
            await update_task_progress(TaskStatus.EXTRACTING, 5)

            # Step 2a: Patch extraction via preprocessing service
            total_missing = len(missing_wsi_ids)
            for idx, wsi_id in enumerate(missing_wsi_ids, 1):
                await asyncio.sleep(0)  # Yield to event loop
                try:
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        response = await client.post(
                            f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                            params={
                                "level": level,
                                "force_recompute": False,
                                "sthresh": seg_params["sthresh"],
                                "mthresh": seg_params["mthresh"],
                                "close": seg_params["close"],
                                "use_otsu": seg_params["use_otsu"],
                                "contour_fn": contour_fn,
                                "use_padding": use_padding,
                                "a_t": filter_params["a_t"],
                                "a_h": filter_params["a_h"],
                                "max_n_holes": filter_params["max_n_holes"],
                                "save_mask": True,
                            },
                        )
                        response.raise_for_status()
                except Exception as e:
                    async with logger_manager.session() as (tl, _db):
                        await tl.error(f"Failed to extract patches from {wsi_id}: {e}")
                    raise

                # Update progress (5-30% for patch extraction)
                progress = 5 + int((idx / total_missing) * 25)
                await update_task_progress(TaskStatus.EXTRACTING, progress)

            async with logger_manager.session() as (tl, _db):
                await tl.info(f"Patch extraction completed for {total_missing} WSIs")

            # Step 2b: Feature extraction via AI service
            feature_batch_size = preprocessing_config.get("feature_batch_size", 64)
            from gateway.pipeline import get_training_timeout
            timeout = get_training_timeout()

            async with logger_manager.session() as (tl, _db):
                await tl.info(f"Calling AI service for feature extraction (using {feature_extractor})")

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/training/extract_features",
                        json={
                            "task_id": task_id,
                            "wsi_ids": missing_wsi_ids,
                            "feature_extractor": feature_extractor,
                            "batch_size": feature_batch_size,
                            "force_recompute": False,
                            "huggingface_token": "",
                            "preprocessing_config": preprocessing_config,
                            "device": assigned_device or "",
                        },
                    )
                    resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text if e.response is not None else str(e)
                async with logger_manager.session() as (tl, _db):
                    await tl.error(f"Feature extraction failed: {e}", metadata={"body": body})
                raise
            except httpx.TimeoutException as e:
                async with logger_manager.session() as (tl, _db):
                    await tl.error(f"Feature extraction timeout: {e}")
                raise

            async with logger_manager.session() as (tl, _db):
                await tl.info(f"Feature extraction completed for {total_missing} WSIs")

            # After extraction, symlink newly created features
            def _symlink_newly_extracted():
                for wsi_id in missing_wsi_ids:
                    cached_path = find_cached_features(uploads_dir, feature_extractor, params_hash, wsi_id)
                    if cached_path is not None:
                        create_symlink_to_cache(features_dir, wsi_id, cached_path)

            await asyncio.to_thread(_symlink_newly_extracted)

        # Update status back to RUNNING for inference phase
        await update_task_progress(TaskStatus.RUNNING, 35)
        async with logger_manager.session() as (tl, _db):
            await tl.info(f"All features ready. Starting inference...")

        ai_results_root = uploads_dir / "ai_results"

        # Import Dataset classes for memory-efficient loading
        from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset

        # ================================================================
        # Data preparation: build Dataset objects (fast, pure Python)
        # Moved OUTSIDE the sync function so dataset is created in async context.
        # ================================================================
        case_to_wsi: Dict[str, List[str]] = {}
        case_wsi_patch_counts: Dict[str, List[int]] = {}
        case_labels_map: Dict[str, int] = {}

        if is_case_level:
            # Group WSIs by case_id and validate feature existence
            valid_wsi_ids = []
            for wsi_id in wsi_ids:
                feat_path = features_dir / f"{wsi_id}.pt"
                if not feat_path.exists():
                    logger.warning(f"Features not found for {wsi_id}, skipping")
                    continue
                valid_wsi_ids.append(wsi_id)
                case_id = wsi_case_map.get(wsi_id, wsi_id)
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # Build case-level survival/label data
            if is_survival:
                case_times: Dict[str, float] = {}
                case_statuses: Dict[str, int] = {}
                for case_id, case_wsi_ids in case_to_wsi.items():
                    first_wsi = case_wsi_ids[0]
                    if first_wsi in survival_data:
                        case_times[case_id] = survival_data[first_wsi]["event_time"]
                        case_statuses[case_id] = survival_data[first_wsi]["event_status"]
                    else:
                        case_times[case_id] = 0.0
                        case_statuses[case_id] = 0
            else:
                for case_id, case_wsi_ids in case_to_wsi.items():
                    first_wsi = case_wsi_ids[0]
                    if first_wsi in labels:
                        case_labels_map[case_id] = labels[first_wsi]

            case_ids = list(case_to_wsi.keys())
            if is_survival:
                dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=case_ids,
                    case_to_wsi=case_to_wsi,
                    times=case_times,
                    statuses=case_statuses,
                    task_type="survival",
                    device=device,
                )
            else:
                dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=case_ids,
                    case_to_wsi=case_to_wsi,
                    labels=case_labels_map,
                    task_type="classification",
                    device=device,
                )
            total = len(case_ids)
            logger.info(f"External validation case-level: {total} cases from {len(valid_wsi_ids)} WSIs")

        else:
            # Slide-level: validate feature existence and create dataset
            valid_wsi_ids = [wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()]
            if not valid_wsi_ids:
                raise FileNotFoundError("No feature files found for any WSI")

            if is_survival:
                times_map: Dict[str, float] = {}
                statuses_map: Dict[str, int] = {}
                for wsi_id in valid_wsi_ids:
                    if wsi_id in survival_data:
                        times_map[wsi_id] = survival_data[wsi_id]["event_time"]
                        statuses_map[wsi_id] = survival_data[wsi_id]["event_status"]
                    else:
                        times_map[wsi_id] = 0.0
                        statuses_map[wsi_id] = 0
                dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=valid_wsi_ids,
                    times=times_map,
                    statuses=statuses_map,
                    task_type="survival",
                    device=device,
                )
            else:
                dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=valid_wsi_ids,
                    labels=labels,
                    task_type="classification",
                    device=device,
                )
            total = len(valid_wsi_ids)
            logger.info(f"External validation slide-level: {total} WSIs")

        if total == 0:
            raise FileNotFoundError("No valid items to process after filtering")

        # ================================================================
        # Define chunk-based inference function.
        # Instead of processing ALL items in one giant asyncio.to_thread call
        # (which holds the GIL for minutes and blocks the event loop),
        # we process CHUNK_SIZE items at a time, yielding to the event loop
        # between chunks. This follows the same pattern as trainer.py which
        # calls asyncio.to_thread per-epoch.
        # ================================================================
        CHUNK_SIZE = 30

        def _sync_run_chunk(start_idx: int, end_idx: int):
            """Process dataset[start_idx:end_idx]. Returns partial results."""
            _chunk_saved = 0
            _chunk_risk_scores = []
            _chunk_result_files = []
            _chunk_db_records = []

            with torch.inference_mode():
                for idx in range(start_idx, end_idx):
                    # Load item from dataset (triggers torch.load for features)
                    item = dataset[idx]

                    if is_case_level:
                        # CaseFeatureDataset returns:
                        #   survival: (features, time, status, case_id, wsi_ids, patch_counts)
                        #   classification: (features, label, case_id, wsi_ids, patch_counts)
                        if is_survival:
                            features, _time, _status, item_id, item_wsi_ids, patch_counts = item
                        else:
                            features, _label, item_id, item_wsi_ids, patch_counts = item
                        case_wsi_patch_counts[item_id] = patch_counts
                        agg_level = "case"
                    else:
                        # WSIFeatureDataset returns:
                        #   survival: (features, time, status, wsi_id)
                        #   classification: (features, label, wsi_id)
                        if is_survival:
                            features, _time, _status, item_id = item
                        else:
                            features, _label, item_id = item
                        item_wsi_ids = [item_id]
                        agg_level = "file"

                    H = features.to(device)

                    # --- Model inference ---
                    if is_kfold:
                        if is_survival:
                            all_hazards = []
                            all_attentions = []
                            for fold_model in models:
                                if has_raw_attention:
                                    logits_f, attn_f, _ = fold_model.forward_with_raw_attention(H)
                                else:
                                    logits_f, attn_f = fold_model(H)
                                hazards_f = torch.sigmoid(logits_f).cpu().numpy().flatten()
                                all_hazards.append(hazards_f)
                                if attn_f is not None:
                                    all_attentions.append(attn_f.cpu().numpy())
                            hazards = np.mean(all_hazards, axis=0)
                            surv_probs = np.cumprod(1 - hazards).tolist()
                            risk_score = float(np.sum(hazards))
                            attention = np.mean(all_attentions, axis=0) if all_attentions else None
                            raw_attention = None
                        else:
                            all_logits = []
                            all_attentions = []
                            for fold_model in models:
                                if has_raw_attention:
                                    logits_f, attn_f, _ = fold_model.forward_with_raw_attention(H)
                                else:
                                    logits_f, attn_f = fold_model(H)
                                all_logits.append(logits_f)
                                if attn_f is not None:
                                    all_attentions.append(attn_f.cpu().numpy())
                            avg_logits = torch.mean(torch.stack(all_logits), dim=0)
                            probs = F.softmax(avg_logits, dim=-1).squeeze(0).cpu().numpy()
                            attention = np.mean(all_attentions, axis=0) if all_attentions else None
                            raw_attention = None
                    else:
                        _model = models[0]
                        if has_raw_attention:
                            logits, attention_t, raw_attention_t = _model.forward_with_raw_attention(H)
                        else:
                            logits, attention_t = _model(H)
                            raw_attention_t = None

                        if is_survival:
                            hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                            surv_probs = np.cumprod(1 - hazards).tolist()
                            risk_score = float(np.sum(hazards))
                            attention = attention_t.cpu().numpy() if attention_t is not None else None
                            raw_attention = raw_attention_t.cpu().numpy() if raw_attention_t is not None else None
                        else:
                            probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                            attention = attention_t.cpu().numpy() if attention_t is not None else None
                            raw_attention = raw_attention_t.cpu().numpy() if raw_attention_t is not None else None

                    # --- Split attention for case-level ---
                    if is_case_level:
                        slide_attentions = _split_case_attention_to_slides_static(
                            attention, item_id, case_wsi_patch_counts, case_to_wsi
                        )
                        slide_raw_attentions = _split_case_attention_to_slides_static(
                            raw_attention, item_id, case_wsi_patch_counts, case_to_wsi
                        )

                    # --- Build prediction data ---
                    if is_survival:
                        gt_data = survival_data.get(item_id, {})
                        _chunk_risk_scores.append(float(np.sum(hazards)) if isinstance(hazards, np.ndarray) else risk_score)
                        pred_label = None
                        probs_dict = None
                        gt_label = None
                    else:
                        pred_idx = int(probs.argmax())
                        pred_label = classes[pred_idx] if pred_idx < len(classes) else "unknown"
                        probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                        if is_case_level:
                            gt_label = classes[case_labels_map[item_id]] if item_id in case_labels_map else "unknown"
                        else:
                            gt_label = classes[labels[item_id]] if item_id in labels else "unknown"

                    # --- Save per-WSI results ---
                    for wsi_id in item_wsi_ids:
                        wsi_result_dir = ai_results_root / wsi_id
                        wsi_result_dir.mkdir(parents=True, exist_ok=True)

                        if is_survival:
                            result_data = {
                                "wsi_id": wsi_id,
                                "case_id": item_id if is_case_level else None,
                                "task_id": model_task_id,
                                "validation_source": dataset_id,
                                "validation_task_id": task_id,
                                "task_type": "survival",
                                "aggregation_level": agg_level,
                                "risk_score": risk_score,
                                "hazards": hazards.tolist() if isinstance(hazards, np.ndarray) else hazards,
                                "surv_probs": surv_probs,
                                "event_time": gt_data.get("event_time"),
                                "event_status": gt_data.get("event_status"),
                                "bin_edges": bin_edges.tolist() if bin_edges is not None else None,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds if is_kfold else None,
                            }
                        else:
                            result_data = {
                                "wsi_id": wsi_id,
                                "case_id": item_id if is_case_level else None,
                                "task_id": model_task_id,
                                "validation_source": dataset_id,
                                "validation_task_id": task_id,
                                "task_type": "classification",
                                "aggregation_level": agg_level,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "ground_truth": gt_label,
                                "correct": pred_label == gt_label if gt_label != "unknown" else None,
                                "classes": classes,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds if is_kfold else None,
                            }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        with open(result_file, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        if is_survival:
                            _chunk_result_files.append((str(result_file), wsi_id))

                        # Save attention
                        if is_case_level:
                            slide_attn = slide_attentions.get(wsi_id)
                            slide_raw_attn = slide_raw_attentions.get(wsi_id)
                        else:
                            slide_attn = attention
                            slide_raw_attn = raw_attention

                        if slide_raw_attn is not None:
                            np.save(wsi_result_dir / f"extval_{task_id}_attention_raw.npy", slide_raw_attn)
                        if slide_attn is not None:
                            np.save(wsi_result_dir / f"extval_{task_id}_attention.npy", slide_attn)

                        _chunk_saved += 1

                        # Collect DB record
                        _chunk_db_records.append({
                            "wsi_id": wsi_id,
                            "task_id": task_id,
                            "user_id": task_user_id,
                            "pred": pred_label,
                            "probs": probs_dict,
                            "extra_metadata": {
                                "validation_type": "external",
                                "model_task_id": model_task_id,
                                "dataset_id": dataset_id,
                                "aggregation_level": agg_level,
                                "case_id": item_id if is_case_level else None,
                                "task_type": "survival" if is_survival else "classification",
                                "result_file": str(result_file),
                            },
                        })

            return _chunk_saved, _chunk_risk_scores, _chunk_result_files, _chunk_db_records

        # ================================================================
        # Run inference in CHUNKS to avoid blocking the event loop.
        # Between each chunk, we yield to the event loop via await asyncio.sleep(0)
        # so SSE streams, DB queries, and other tasks can proceed.
        # ================================================================
        async with logger_manager.session() as (tl, _db):
            level_msg = "case-level" if is_case_level else "slide-level"
            await tl.info(f"Running {level_msg} inference in chunks of {CHUNK_SIZE}...")

        results_saved = 0
        all_risk_scores = []
        saved_result_files = []
        db_records = []

        for chunk_start in range(0, total, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total)
            chunk_saved, chunk_risk_scores, chunk_result_files, chunk_db_records = await asyncio.to_thread(
                _sync_run_chunk, chunk_start, chunk_end
            )
            results_saved += chunk_saved
            db_records.extend(chunk_db_records)
            if is_survival:
                all_risk_scores.extend(chunk_risk_scores)
                saved_result_files.extend(chunk_result_files)

            # Update progress via file-based store
            progress = int(chunk_end / total * 90)
            set_progress(task_id, progress)

            # Yield to event loop - this is the KEY fix that prevents blocking
            await asyncio.sleep(0)

        # For survival: compute median risk score and update all result files with risk_group
        # NOTE: This loop reads+writes potentially thousands of JSON files.
        # Run in thread to avoid blocking the event loop.
        if is_survival and all_risk_scores:
            median_risk_score = float(np.median(all_risk_scores))
            logger.info(f"Survival external validation: median risk score = {median_risk_score:.4f}")

            def _sync_update_survival_result_files():
                for result_file, wsi_id in saved_result_files:
                    with open(result_file, 'r') as f:
                        result_data = json.load(f)

                    risk_group = "High Risk" if result_data["risk_score"] >= median_risk_score else "Low Risk"
                    result_data["median_risk_score"] = median_risk_score
                    result_data["risk_group"] = risk_group

                    with open(result_file, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(_sync_update_survival_result_files)

        # Batch-insert results into database so Results page can display them
        if db_records:
            logger.info(f"Saving {len(db_records)} results to database...")
            async with safe_session() as db:
                await AIResultRepository.bulk_create(db, db_records, batch_size=100)
                await db.commit()
            logger.info(f"Saved {len(db_records)} results to database")

        await update_task_progress(TaskStatus.RUNNING, 95, results_saved, results_saved)

        # Clear file-based progress (task is finishing)
        clear_progress(task_id)

        # Mark as completed
        await update_task_progress(TaskStatus.COMPLETED, 100, results_saved, results_saved)
        case_level_msg = " (case-level)" if is_case_level else ""
        kfold_msg = f" (k-fold: {num_folds} folds averaged)" if is_kfold else ""
        logger.info(f"External validation {task_id} completed: {results_saved} results (type: {'survival' if is_survival else 'classification'}){case_level_msg}{kfold_msg}")

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"External validation completed: {results_saved} results saved{case_level_msg}{kfold_msg}")

        # Auto-trigger analysis after inference completes
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
        )

    except Exception as e:
        import traceback
        logger.error(f"External validation {task_id} failed: {e}\n{traceback.format_exc()}")
        try:
            clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"External validation failed: {e}")
        except Exception:
            pass  # Don't let logging failure mask the original error
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=str(e))
    finally:
        # Clean up GPU memory regardless of success/failure.
        # This mirrors cleanup_training_scoped() in backend/ai/routes/training.py.
        try:
            import gc
            from backend.ai.utils.feature_dataset import clear_feature_cache
            clear_feature_cache()
            gc.collect()
            gc.collect()  # Second pass for cyclic references
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info(f"External validation {task_id}: GPU memory cleaned up")
            else:
                logger.info(f"External validation {task_id}: gc.collect() done (no GPU)")
        except Exception as cleanup_err:
            logger.warning(f"External validation {task_id}: VRAM cleanup failed: {cleanup_err}")


async def _auto_trigger_external_validation_analysis(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    metrics: Optional[List[str]] = None,
    charts: Optional[List[str]] = None,
    bootstrap_ci_metrics: Optional[List[str]] = None,
):
    """
    Auto-trigger analysis after external validation inference completes.

    This makes External Validation a one-click complete operation:
    1. GPU inference runs first (via _run_external_validation)
    2. Then CPU analysis runs automatically (via this function)

    The analysis task will appear in the Background Task Panel and be merged
    with the External Validation task in the frontend display.

    Args:
        task_id: The external validation task ID
        model_task_id: The original training task ID of the model
        model_id: The trained model ID
        dataset_id: The target dataset ID
        metrics: Optional list of metrics to compute (default: accuracy, precision, recall, f1, auc)
        charts: Optional list of charts to generate (default: confusion_matrix, roc_curve)
        bootstrap_ci_metrics: Optional list of metrics to compute 95% CI for
    """
    from backend.database.database import async_session

    # Check if analysis already exists for this task
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id
    if analysis_dir.exists():
        for item in sorted(analysis_dir.iterdir(), reverse=True):
            if item.is_dir() and (item / "summary.json").exists():
                logger.info(f"Analysis already exists for external validation {task_id}, skipping auto-trigger")
                return

    state = get_analysis_state()

    # Generate analysis ID
    analysis_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_auto"

    try:
        # Use safe_session for proper cleanup in background task
        async with safe_session() as db:
            # Get the external validation task to get user_id and other info
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if not task:
                logger.error(f"Auto-trigger analysis failed: task {task_id} not found")
                return

            user_id = str(task.user_id)

            # Build title for the analysis
            model_config = task.model_config or {}
            source_name = model_id
            target_name = dataset_id

            try:
                model = await TrainedModelRepository.get_by_id(db, model_id)
                if model:
                    source_name = model.model_name or model_id
                target_ds = await DatasetRepository.get_by_id(db, dataset_id)
                if target_ds:
                    target_name = target_ds.name or dataset_id
            except Exception:
                pass

            title = f"{source_name} → {target_name}"

            # Use provided options or get from model_config or use defaults
            analysis_metrics = metrics or model_config.get("analysis_metrics") or ["accuracy", "precision", "recall", "f1", "auc"]
            analysis_charts = charts or model_config.get("analysis_charts") or ["confusion_matrix", "roc_curve"]
            analysis_bootstrap_ci = bootstrap_ci_metrics if bootstrap_ci_metrics is not None else (model_config.get("bootstrap_ci_metrics") or [])

            # Create analysis state entry
            await state.create(
                analysis_id=analysis_id,
                task_id=task_id,
                user_id=user_id,
                title=title,
                analysis_type="external"
            )

            # Start analysis pipeline as asyncio task (CPU-only)
            analysis_task = asyncio.create_task(
                run_analysis_pipeline(
                    task_id=analysis_id,
                    analysis_id=analysis_id,
                    training_task_id=task_id,
                    task_type_str="external_validation",
                    metrics=analysis_metrics,
                    charts=analysis_charts,
                    description="Auto-triggered after external validation inference",
                    bootstrap_ci_metrics=analysis_bootstrap_ci,
                    submitted_by=user_id,
                )
            )
            # Register task for potential cancellation
            state.register_task(analysis_id, analysis_task)
            logger.info(f"Auto-triggered analysis for external validation: task_id={task_id}, analysis_id={analysis_id}, bootstrap_ci={len(analysis_bootstrap_ci) > 0}")

    except Exception as e:
        logger.error(f"Failed to auto-trigger analysis for external validation {task_id}: {e}")


@router.get("/tasks/{task_id}/analysis")
async def get_task_analysis(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get existing analysis results for a task. Users can only view their own tasks.
    """
    # Check task ownership (supports temporary elevated dataset permissions)
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        task_dataset_id = await _resolve_task_dataset_id(task, db)
        if not await check_task_access_permission(user, task.user_id, task_dataset_id, db):
            raise HTTPException(status_code=403, detail="You don't have permission to view this task's analysis")

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id

    if not analysis_dir.exists():
        return {"task_id": task_id, "analyses": []}

    def _read_analyses():
        """Synchronous function to read analysis files."""
        result = []
        for item in sorted(analysis_dir.iterdir(), reverse=True):
            if item.is_dir():
                # Each analysis run is in a timestamped directory
                summary_file = item / "summary.json"
                if summary_file.exists():
                    with open(summary_file, 'r') as f:
                        summary = json.load(f)
                        summary["analysis_id"] = item.name
                        result.append(summary)
        return result

    # Run file operations in thread pool to avoid blocking event loop
    analyses = await asyncio.to_thread(_read_analyses)

    # Filter and resolve usernames based on user role
    if user.is_admin():
        # Admin sees all analyses with submitter info resolved to nickname
        user_ids = set()
        for analysis in analyses:
            submitted_by_id = analysis.get("submitted_by")
            if submitted_by_id:
                user_ids.add(submitted_by_id)

        # Batch lookup nicknames for all submitters
        user_map = {}
        if user_ids:
            result = await db.execute(
                select(User.id, User.nickname, User.email)
                .where(cast(User.id, String).in_(list(user_ids)))
            )
            for row in result.all():
                uid_str = str(row[0])
                user_map[uid_str] = row[1] or row[2]  # nickname or email

        # Resolve submitted_by from user_id to display name
        for analysis in analyses:
            submitted_by_id = analysis.get("submitted_by")
            if submitted_by_id:
                analysis["submitted_by"] = user_map.get(submitted_by_id, submitted_by_id)
    else:
        # Non-admin: only show their own analyses, remove submitted_by field
        user_id_str = str(user.id)
        filtered = []
        for analysis in analyses:
            if analysis.get("submitted_by") == user_id_str:
                analysis.pop("submitted_by", None)
                filtered.append(analysis)
        analyses = filtered

    return {"task_id": task_id, "analyses": analyses}


@router.post("/tasks/{task_id}/analysis")
async def run_task_analysis(
    task_id: str,
    request: AnalysisRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit analysis on a completed training task to background queue.
    Returns immediately with analysis_id for tracking via SSE.

    Requires pathologist/admin role OR temporary elevated permission for the dataset.
    Users can only analyze their own tasks.

    Args:
        task_id: Training task ID to analyze
        request: Analysis configuration (metrics, charts to generate)

    Returns:
        Submission confirmation with analysis_id and status
    """
    from gateway.task_queue import get_task_queue, TaskType

    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    # Check ownership (supports temporary elevated dataset permissions)
    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if not await check_task_access_permission(user, task.user_id, task_dataset_id, db):
        raise HTTPException(status_code=403, detail="You don't have permission to analyze this task")

    # Check GPU permission (pathologist/admin OR temporary elevated permission)
    wsi_ids_for_check = await TrainingTaskRepository.get_wsi_ids(db, task_id)
    if wsi_ids_for_check:
        # Get dataset_id from first WSI
        first_wsi = await WSIRepository.get_by_id(db, wsi_ids_for_check[0])
        if first_wsi and first_wsi.dataset_id:
            has_permission = await check_dataset_gpu_permission(user, first_wsi.dataset_id, db)
            if not has_permission:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have GPU permission for this dataset. Contact admin for temporary access."
                )
    elif not user.can_use_gpu():
        # No WSIs found, fall back to role check
        raise HTTPException(status_code=403, detail="GPU operations require pathologist or admin role")

    # Generate analysis_id (timestamp format)
    analysis_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Check if there's already a pending/queued/running analysis for this task
    state = get_analysis_state()
    existing_analyses = await state.get_by_task_id(task_id)
    for existing in existing_analyses:
        if existing["status"] in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING):
            # Return existing pending/queued/running analysis
            return {
                "task_id": task_id,
                "analysis_id": existing["analysis_id"],
                "status": existing["status"],
                "progress": existing["progress"],
                "message": "Analysis is already in progress"
            }

    # Get task_type from DataGroup relationship
    task_data_group = task.data_group
    task_type_str = task_data_group.task_type if task_data_group else "classification"

    # Build meaningful title based on task type
    is_external = task_type_str == "external_validation"
    if is_external:
        # External validation: task_name already has format "External Validation: model → dataset"
        # Extract source and target from task_name or model_config
        model_config = task.model_config or {}
        model_id = model_config.get("model_id", "")
        dataset_id = model_config.get("dataset_id", "")

        # Try to get model name and dataset name
        source_name = model_id
        target_name = dataset_id
        try:
            model = await TrainedModelRepository.get_by_id(db, model_id)
            if model:
                source_name = model.model_name or model_id
            if dataset_id:
                target_ds = await DatasetRepository.get_by_id(db, dataset_id)
                if target_ds:
                    target_name = target_ds.name or dataset_id
        except Exception:
            pass

        title = f"{source_name} → {target_name}"
        analysis_type = "external"
    else:
        # Internal analysis: use task name with validation type
        task_type_label = "Survival" if task_type_str in ("wsi_survival", "survival") else "Classification"
        title = f"{task.task_name} ({task_type_label})"
        analysis_type = "internal"

    # Create analysis state entry
    await state.create(analysis_id, task_id, str(user.id), title=title, analysis_type=analysis_type)

    # Check if GPU inference is needed (AI results missing)
    # External validation does not need GPU check here as it handles its own inference flow
    needs_gpu = False
    if not is_external:
        resources = await _check_task_resources(task_id, db)
        needs_gpu = not resources["has_ai_results"]

    task_queue = get_task_queue()

    if needs_gpu:
        # GPU inference needed - submit to GPU queue for queuing
        await state.set_queued(analysis_id)
        await task_queue.submit_task(
            task_id=analysis_id,
            task_type=TaskType.ANALYSIS,
            coro_func=run_analysis_pipeline,
            analysis_id=analysis_id,
            training_task_id=task_id,
            task_type_str=task_type_str,
            metrics=request.metrics,
            charts=request.charts,
            description=request.description,
            bootstrap_ci_metrics=request.bootstrap_ci_metrics or [],
            submitted_by=str(user.id),
        )
        logger.info(f"Analysis task queued (needs GPU): task_id={task_id}, analysis_id={analysis_id}")
    else:
        # No GPU needed - run directly without queuing
        analysis_task = asyncio.create_task(
            run_analysis_pipeline(
                task_id=analysis_id,
                analysis_id=analysis_id,
                training_task_id=task_id,
                task_type_str=task_type_str,
                metrics=request.metrics,
                charts=request.charts,
                description=request.description,
                bootstrap_ci_metrics=request.bootstrap_ci_metrics or [],
                submitted_by=str(user.id),
            )
        )
        # Register task for potential cancellation
        state.register_task(analysis_id, analysis_task)
        logger.info(f"Analysis task started (CPU-only, no queue): task_id={task_id}, analysis_id={analysis_id}")

    # Return immediately with pending/queued status
    return {
        "task_id": task_id,
        "analysis_id": analysis_id,
        "status": TaskStatus.QUEUED if needs_gpu else TaskStatus.PENDING,
        "progress": 0,
        "message": "Analysis submitted successfully"
    }


@router.get("/analysis/stream")
async def stream_analysis_tasks(user: User = Depends(get_user_from_token_param)):
    """
    Server-Sent Events endpoint for real-time analysis task updates.
    Streams task status and progress updates to connected clients.
    Users see only their own tasks, admin sees all.

    Note: Uses token query parameter for authentication since EventSource API
    doesn't support custom headers. Token is passed via URL: ?token=<jwt>
    """
    # Capture user info before SSE stream starts
    user_id_filter = None if user.is_admin() else str(user.id)
    state = get_analysis_state()

    async def event_generator():
        """Generate SSE events with analysis task updates"""
        logger.debug(f"Analysis SSE connected for user_id_filter={user_id_filter}")
        try:
            while True:
                try:
                    # Get all analysis tasks for this user
                    tasks = await state.get_all(user_id=user_id_filter, max_age_minutes=10)

                    # Send SSE event
                    data = json.dumps({"items": tasks})
                    yield f"data: {data}\n\n"
                except Exception as e:
                    logger.error(f"Error fetching analysis tasks in SSE: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Wait 2 seconds before next update
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info("Analysis SSE client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


class QuickAnalysisRequest(BaseModel):
    """Request body for quick analysis - specify what metrics/charts to return."""
    metrics: Optional[List[str]] = None  # If None, return all available metrics
    charts: Optional[List[str]] = None   # If None, return all available charts
    run_if_missing: bool = True           # If True, run analysis if not available


@router.get("/tasks/{task_id}/quick-analysis")
async def get_quick_analysis(
    task_id: str,
    metrics: Optional[str] = Query(None, description="Comma-separated metrics to return (e.g., accuracy,auc,f1)"),
    charts: Optional[str] = Query(None, description="Comma-separated charts to return (e.g., roc_curve,confusion_matrix)"),
    run_if_missing: bool = Query(True, description="Run analysis if not available"),
    bootstrap_ci_metrics: Optional[str] = Query(None, description="Comma-separated metrics to compute 95% CI for (e.g., accuracy,auc)"),
    compute_bootstrap_ci: bool = Query(False, description="Legacy: compute CI for all metrics if true"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get quick analysis results for a task.

    If analysis results exist, returns the most recent.
    If not and run_if_missing=True, automatically runs analysis first.

    Supports filtering to only return requested metrics/charts.
    """
    # Check task ownership
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if not await check_task_access_permission(user, task.user_id, task_dataset_id, db):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task's analysis")

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id

    # Parse metrics and charts from query params
    requested_metrics = [m.strip() for m in metrics.split(",")] if metrics else None
    requested_charts = [c.strip() for c in charts.split(",")] if charts else None

    # Check for existing analysis
    latest_summary = None
    analysis_id = None

    if analysis_dir.exists():
        def _read_latest_analysis():
            for item in sorted(analysis_dir.iterdir(), reverse=True):
                if item.is_dir():
                    summary_file = item / "summary.json"
                    if summary_file.exists():
                        with open(summary_file, 'r') as f:
                            return item.name, json.load(f)
            return None, None

        analysis_id, latest_summary = await asyncio.to_thread(_read_latest_analysis)

    # If no analysis exists and run_if_missing is True, submit analysis task to queue
    if latest_summary is None and run_if_missing:
        from gateway.task_queue import get_task_queue, TaskType

        # Check GPU permission
        wsi_ids_for_check = await TrainingTaskRepository.get_wsi_ids(db, task_id)
        if wsi_ids_for_check:
            first_wsi = await WSIRepository.get_by_id(db, wsi_ids_for_check[0])
            if first_wsi and first_wsi.dataset_id:
                has_permission = await check_dataset_gpu_permission(user, first_wsi.dataset_id, db)
                if not has_permission:
                    raise HTTPException(
                        status_code=403,
                        detail="No existing analysis and you don't have GPU permission to run analysis."
                    )
        elif not user.can_use_gpu():
            raise HTTPException(
                status_code=403,
                detail="No existing analysis and GPU operations require pathologist or admin role"
            )

        # Generate analysis_id (timestamp format)
        analysis_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Check if there's already a pending/queued/running analysis for this task
        state = get_analysis_state()
        existing_analyses = await state.get_by_task_id(task_id)
        for existing in existing_analyses:
            if existing["status"] in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING):
                # Return existing pending/queued/running analysis
                return {
                    "task_id": task_id,
                    "analysis_id": existing["analysis_id"],
                    "has_analysis": False,
                    "status": existing["status"],
                    "progress": existing["progress"],
                    "message": "Analysis is in progress"
                }

        # Create analysis state entry
        await state.create(analysis_id, task_id, str(user.id))

        # Get task_type from DataGroup relationship
        quick_task_data_group = task.data_group
        quick_task_type_str = quick_task_data_group.task_type if quick_task_data_group else "classification"

        # Default metrics and charts based on task type
        is_survival_task = quick_task_type_str in ("wsi_survival", "survival")
        if is_survival_task:
            default_metrics = ["c_index", "integrated_brier_score"]
            default_charts = ["km_curve", "loss_curve"]
        else:
            default_metrics = ["accuracy", "precision", "recall", "specificity", "f1", "auc"]
            default_charts = ["roc_curve", "confusion_matrix", "loss_curve"]

        # Parse bootstrap_ci_metrics from query param or use legacy compute_bootstrap_ci
        ci_metrics_list = []
        if bootstrap_ci_metrics:
            ci_metrics_list = [m.strip() for m in bootstrap_ci_metrics.split(",")]
        elif compute_bootstrap_ci:
            # Legacy: compute CI for all default metrics
            ci_metrics_list = default_metrics

        # Check if GPU inference is needed (AI results missing)
        resources = await _check_task_resources(task_id, db)
        needs_gpu = not resources["has_ai_results"]

        task_queue = get_task_queue()

        if needs_gpu:
            # GPU inference needed - submit to GPU queue for queuing
            await state.set_queued(analysis_id)
            await task_queue.submit_task(
                task_id=analysis_id,
                task_type=TaskType.ANALYSIS,
                coro_func=run_analysis_pipeline,
                analysis_id=analysis_id,
                training_task_id=task_id,
                task_type_str=quick_task_type_str,
                metrics=default_metrics,
                charts=default_charts,
                description=None,
                bootstrap_ci_metrics=ci_metrics_list,
                submitted_by=str(user.id),
            )
            logger.info(f"Analysis task queued (needs GPU): task_id={task_id}, analysis_id={analysis_id}")
        else:
            # No GPU needed - run directly without queuing
            analysis_task = asyncio.create_task(
                run_analysis_pipeline(
                    task_id=analysis_id,
                    analysis_id=analysis_id,
                    training_task_id=task_id,
                    task_type_str=quick_task_type_str,
                    metrics=default_metrics,
                    charts=default_charts,
                    description=None,
                    bootstrap_ci_metrics=ci_metrics_list,
                    submitted_by=str(user.id),
                )
            )
            # Register task for potential cancellation
            state.register_task(analysis_id, analysis_task)
            logger.info(f"Analysis task started (CPU-only, no queue): task_id={task_id}, analysis_id={analysis_id}")

        # Return immediately with pending/queued status
        return {
            "task_id": task_id,
            "analysis_id": analysis_id,
            "has_analysis": False,
            "status": TaskStatus.QUEUED if needs_gpu else TaskStatus.PENDING,
            "progress": 0,
            "message": "Analysis submitted to queue"
        }

    if latest_summary is None:
        return {
            "task_id": task_id,
            "has_analysis": False,
            "message": "No analysis results available. Set run_if_missing=true to generate."
        }

    # Filter metrics if requested
    result_metrics = latest_summary.get("metrics", {})
    if requested_metrics:
        result_metrics = {k: v for k, v in result_metrics.items() if k in requested_metrics or k.replace("macro_", "") in requested_metrics}

    # Merge bootstrap CI into metrics if available
    # Frontend expects: MetricValue = number | { value: number; ci_lower: number; ci_upper: number }
    bootstrap_ci = latest_summary.get("bootstrap_ci", {})
    metrics_ci = bootstrap_ci.get("metrics_ci", {})
    if metrics_ci:
        merged_metrics = {}
        for metric_name, metric_value in result_metrics.items():
            # Check if we have CI for this metric (try both with and without macro_ prefix)
            ci_data = metrics_ci.get(metric_name) or metrics_ci.get(metric_name.replace("macro_", ""))
            if ci_data and isinstance(ci_data, dict) and "ci_lower" in ci_data and "ci_upper" in ci_data:
                # Merge CI data with the metric value
                merged_metrics[metric_name] = {
                    "value": ci_data.get("value", metric_value),
                    "ci_lower": ci_data["ci_lower"],
                    "ci_upper": ci_data["ci_upper"]
                }
            else:
                merged_metrics[metric_name] = metric_value
        result_metrics = merged_metrics

    # Filter charts if requested
    result_chart_data = latest_summary.get("chart_data", {})
    if requested_charts:
        result_chart_data = {k: v for k, v in result_chart_data.items() if k in requested_charts}

    response = {
        "task_id": task_id,
        "analysis_id": analysis_id,
        "has_analysis": True,
        "timestamp": latest_summary.get("timestamp"),
        "task_type": latest_summary.get("task_type", "classification"),
        "num_samples": latest_summary.get("num_samples"),
        "classes": latest_summary.get("classes", []),
        "is_binary": latest_summary.get("is_binary", False),
        "metrics": result_metrics,
        "class_metrics": latest_summary.get("class_metrics", {}),
        "chart_data": result_chart_data,
        # Provide URLs for chart images (with token support for img tags)
        "chart_urls": {
            chart: f"/results/tasks/{task_id}/analysis/{analysis_id}/file/{chart}.png"
            for chart in (latest_summary.get("chart_paths", {}).keys())
            if not requested_charts or chart in requested_charts
        }
    }

    # Include K-Fold training details if available
    kfold_training = latest_summary.get("kfold_training")
    if kfold_training:
        response["kfold_training"] = kfold_training

    return response


@router.get("/tasks/{task_id}/analysis/{analysis_id}/file/{filename}")
async def get_analysis_file(
    task_id: str,
    analysis_id: str,
    filename: str,
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific file from an analysis run. Users can only view their own task's files.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)
    """
    # Check task ownership (supports temporary elevated dataset permissions)
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        task_dataset_id = await _resolve_task_dataset_id(task, db)
        if not await check_task_access_permission(user, task.user_id, task_dataset_id, db):
            raise HTTPException(status_code=403, detail="You don't have permission to view this file")

    file_path = Config.get_uploads_dir() / "logs" / "analysis" / task_id / analysis_id / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(file_path)


@router.delete("/tasks/{task_id}/analysis/{analysis_id}")
async def delete_task_analysis(
    task_id: str,
    analysis_id: str,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a specific analysis run for a task.
    Requires pathologist or admin role. Users can only delete their own task's analysis.

    Args:
        task_id: Training task ID
        analysis_id: Analysis run ID (timestamp directory name)

    Returns:
        Success message
    """
    # Check task ownership
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task and not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this analysis")

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / analysis_id

    if not analysis_dir.exists():
        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    if not analysis_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid analysis ID: {analysis_id}")

    try:
        # Run in thread pool to avoid blocking event loop
        await asyncio.to_thread(shutil.rmtree, analysis_dir)
        logger.info(f"Deleted analysis {analysis_id} for task {task_id}")
        return {"message": f"Analysis {analysis_id} deleted successfully", "task_id": task_id, "analysis_id": analysis_id}
    except Exception as e:
        logger.error(f"Failed to delete analysis {analysis_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete analysis: {str(e)}")


@router.get("/analysis/{analysis_id}/status")
async def get_analysis_status(
    analysis_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the status of an analysis task.

    Used for polling the progress of async analysis tasks.

    Args:
        analysis_id: Analysis ID returned when analysis was submitted

    Returns:
        Analysis status including: status, progress, error_message, timestamps
    """
    state = get_analysis_state()
    analysis_state = await state.get(analysis_id)

    if not analysis_state:
        # Check if analysis exists on disk (completed before server restart)
        # Search in all task directories
        analysis_base_dir = Config.get_uploads_dir() / "logs" / "analysis"
        if analysis_base_dir.exists():
            for task_dir in analysis_base_dir.iterdir():
                if task_dir.is_dir():
                    analysis_dir = task_dir / analysis_id
                    if analysis_dir.exists() and (analysis_dir / "summary.json").exists():
                        # Analysis exists on disk, check ownership (supports temp permissions)
                        task = await TrainingTaskRepository.get_by_id(db, task_dir.name)
                        if task:
                            mc = task.model_config or {}
                            if not await check_task_access_permission(user, task.user_id, mc.get("dataset_id"), db):
                                raise HTTPException(status_code=403, detail="You don't have permission to view this analysis")

                        return {
                            "analysis_id": analysis_id,
                            "task_id": task_dir.name,
                            "status": TaskStatus.COMPLETED,
                            "progress": 100,
                            "error_message": None,
                            "message": "Analysis completed"
                        }

        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    # Check ownership (supports temporary elevated dataset permissions)
    task_id = analysis_state.get("task_id")
    if task_id:
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if task:
            mc = task.model_config or {}
            if not await check_task_access_permission(user, task.user_id, mc.get("dataset_id"), db):
                raise HTTPException(status_code=403, detail="You don't have permission to view this analysis")

    return {
        "analysis_id": analysis_id,
        "task_id": analysis_state.get("task_id"),
        "status": analysis_state.get("status"),
        "progress": analysis_state.get("progress"),
        "error_message": analysis_state.get("error_message"),
        "created_at": analysis_state.get("created_at"),
        "started_at": analysis_state.get("started_at"),
        "finished_at": analysis_state.get("finished_at"),
        "message": _get_analysis_status_message(analysis_state.get("status"), analysis_state.get("progress"))
    }


def _get_analysis_status_message(status: str, progress: int) -> str:
    """Get human-readable status message for analysis."""
    if status == TaskStatus.PENDING:
        return "Analysis queued, waiting to start..."
    elif status == TaskStatus.RUNNING:
        if progress < 30:
            return "Initializing analysis..."
        elif progress < 60:
            return "Computing metrics..."
        elif progress < 90:
            return "Generating charts..."
        else:
            return "Finalizing results..."
    elif status == TaskStatus.COMPLETED:
        return "Analysis completed"
    elif status == TaskStatus.FAILED:
        return "Analysis failed"
    return "Unknown status"


def _calculate_all_metrics(
    labels: List[str],
    predictions: List[str],
    probs_list: List[Dict],
    all_classes: List[str],
    requested_metrics: List[str]
) -> Dict[str, Any]:
    """Calculate all requested metrics using sklearn."""
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        confusion_matrix as sklearn_confusion_matrix, roc_curve, auc
    )

    n_classes = len(all_classes)

    # Use sklearn for metrics
    accuracy = accuracy_score(labels, predictions)

    # Per-class and macro metrics
    precision_per_class = precision_score(labels, predictions, labels=all_classes, average=None, zero_division=0)
    recall_per_class = recall_score(labels, predictions, labels=all_classes, average=None, zero_division=0)
    f1_per_class = f1_score(labels, predictions, labels=all_classes, average=None, zero_division=0)

    macro_precision = precision_score(labels, predictions, average='macro', zero_division=0)
    macro_recall = recall_score(labels, predictions, average='macro', zero_division=0)
    macro_f1 = f1_score(labels, predictions, average='macro', zero_division=0)

    # Build confusion matrix using sklearn
    cm = sklearn_confusion_matrix(labels, predictions, labels=all_classes)

    # Calculate per-class metrics including specificity
    class_metrics = {}
    for i, cls in enumerate(all_classes):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        tn = cm.sum() - tp - fp - fn
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0

        class_metrics[cls] = {
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
            "precision": round(float(precision_per_class[i]), 4),
            "recall": round(float(recall_per_class[i]), 4),
            "sensitivity": round(float(recall_per_class[i]), 4),
            "specificity": round(float(specificity), 4),
            "f1": round(float(f1_per_class[i]), 4),
            "support": int(tp + fn)
        }

    macro_specificity = sum(m["specificity"] for m in class_metrics.values()) / n_classes if n_classes > 0 else 0

    metrics = {
        "accuracy": round(float(accuracy), 4),
        "macro_precision": round(float(macro_precision), 4),
        "macro_recall": round(float(macro_recall), 4),
        "macro_sensitivity": round(float(macro_recall), 4),
        "macro_specificity": round(float(macro_specificity), 4),
        "macro_f1": round(float(macro_f1), 4)
    }

    # ROC/AUC if requested - use sklearn
    roc_data = {}
    if "auc" in requested_metrics:
        for i, cls in enumerate(all_classes):
            scores = []
            binary_labels = []
            for j, probs in enumerate(probs_list):
                if cls in probs:
                    scores.append(probs[cls])
                    binary_labels.append(1 if labels[j] == cls else 0)

            if scores and sum(binary_labels) > 0 and sum(binary_labels) < len(binary_labels):
                fpr, tpr, _ = roc_curve(binary_labels, scores)
                roc_auc = auc(fpr, tpr)
                # Convert to list of points for frontend
                roc_points = [{"fpr": float(f), "tpr": float(t)} for f, t in zip(fpr, tpr)]
                roc_data[cls] = {"points": roc_points, "auc": round(float(roc_auc), 4)}
                # Add per-class AUC to class_metrics
                if cls in class_metrics:
                    class_metrics[cls]["auc"] = round(float(roc_auc), 4)

        if roc_data:
            metrics["macro_auc"] = round(sum(r["auc"] for r in roc_data.values()) / len(roc_data), 4)

    return {
        "metrics": metrics,
        "class_metrics": class_metrics,
        "roc_data": roc_data
    }


def _calculate_bootstrap_ci(
    labels: List[str],
    predictions: List[str],
    probs_list: List[Dict],
    all_classes: List[str],
    requested_metrics: List[str],
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    progress_callback: Optional[Callable[[float], None]] = None
) -> Dict[str, Any]:
    """Calculate 95% confidence intervals for metrics using bootstrap resampling.

    Args:
        labels: List of true labels
        predictions: List of predicted labels
        probs_list: List of probability dictionaries
        all_classes: List of all class names
        requested_metrics: List of requested metrics
        n_bootstrap: Number of bootstrap samples (default 1000)
        confidence_level: Confidence level for CI (default 0.95)
        progress_callback: Optional sync callback for progress updates (0.0 to 1.0)

    Returns:
        Dict with 'metrics_ci' (macro-level CIs) and 'class_metrics_ci' (per-class CIs)
    """
    import numpy as np
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        confusion_matrix as sklearn_confusion_matrix, roc_curve, auc
    )

    n_samples = len(labels)
    if n_samples < 2:
        logger.warning("Bootstrap CI requires at least 2 samples")
        return {"metrics_ci": {}, "class_metrics_ci": {}}

    # Arrays to store bootstrap results
    boot_accuracy = []
    boot_macro_precision = []
    boot_macro_recall = []
    boot_macro_f1 = []
    boot_macro_specificity = []
    boot_macro_auc = []

    # Per-class bootstrap results
    boot_class_metrics = {cls: {
        "precision": [], "recall": [], "sensitivity": [],
        "specificity": [], "f1": [], "auc": []
    } for cls in all_classes}

    # ROC curve bootstrap results - store interpolated TPR values at common FPR grid
    fpr_grid = np.linspace(0, 1, 101)  # 101 points from 0 to 1
    boot_roc_tpr = {cls: [] for cls in all_classes}  # Will store TPR values interpolated at fpr_grid

    # Convert to numpy arrays for efficient resampling
    labels_arr = np.array(labels)
    preds_arr = np.array(predictions)

    np.random.seed(42)  # For reproducibility

    for iter_idx in range(n_bootstrap):
        # Report progress every 50 iterations
        if progress_callback and iter_idx % 50 == 0:
            progress_callback(iter_idx / n_bootstrap)

        # Bootstrap resample with replacement
        indices = np.random.choice(n_samples, size=n_samples, replace=True)
        boot_labels = labels_arr[indices].tolist()
        boot_preds = preds_arr[indices].tolist()
        boot_probs = [probs_list[i] for i in indices]

        # Skip if any class is missing in this bootstrap sample
        boot_classes_in_labels = set(boot_labels)
        boot_classes_in_preds = set(boot_preds)
        if len(boot_classes_in_labels) < 2 or len(boot_classes_in_preds) < 2:
            continue  # Skip degenerate samples

        # Calculate metrics for this bootstrap sample
        try:
            boot_accuracy.append(accuracy_score(boot_labels, boot_preds))
            boot_macro_precision.append(precision_score(boot_labels, boot_preds, average='macro', zero_division=0))
            boot_macro_recall.append(recall_score(boot_labels, boot_preds, average='macro', zero_division=0))
            boot_macro_f1.append(f1_score(boot_labels, boot_preds, average='macro', zero_division=0))

            # Per-class metrics
            precision_per_class = precision_score(boot_labels, boot_preds, labels=all_classes, average=None, zero_division=0)
            recall_per_class = recall_score(boot_labels, boot_preds, labels=all_classes, average=None, zero_division=0)
            f1_per_class = f1_score(boot_labels, boot_preds, labels=all_classes, average=None, zero_division=0)

            cm = sklearn_confusion_matrix(boot_labels, boot_preds, labels=all_classes)
            specificities = []

            for i, cls in enumerate(all_classes):
                tp = cm[i, i]
                fp = cm[:, i].sum() - tp
                fn = cm[i, :].sum() - tp
                tn = cm.sum() - tp - fp - fn
                spec = tn / (tn + fp) if (tn + fp) > 0 else 0
                specificities.append(spec)

                boot_class_metrics[cls]["precision"].append(float(precision_per_class[i]))
                boot_class_metrics[cls]["recall"].append(float(recall_per_class[i]))
                boot_class_metrics[cls]["sensitivity"].append(float(recall_per_class[i]))
                boot_class_metrics[cls]["specificity"].append(float(spec))
                boot_class_metrics[cls]["f1"].append(float(f1_per_class[i]))

            boot_macro_specificity.append(np.mean(specificities))

            # AUC if requested
            if "auc" in requested_metrics:
                class_aucs = []
                for i, cls in enumerate(all_classes):
                    scores = []
                    binary_labels = []
                    for j, probs in enumerate(boot_probs):
                        if cls in probs:
                            scores.append(probs[cls])
                            binary_labels.append(1 if boot_labels[j] == cls else 0)

                    if scores and sum(binary_labels) > 0 and sum(binary_labels) < len(binary_labels):
                        fpr, tpr, _ = roc_curve(binary_labels, scores)
                        roc_auc = auc(fpr, tpr)
                        boot_class_metrics[cls]["auc"].append(float(roc_auc))
                        class_aucs.append(roc_auc)

                        # Interpolate TPR at fpr_grid for ROC CI calculation
                        # np.interp requires monotonically increasing xp, which fpr is
                        tpr_interp = np.interp(fpr_grid, fpr, tpr)
                        boot_roc_tpr[cls].append(tpr_interp)

                if class_aucs:
                    boot_macro_auc.append(np.mean(class_aucs))

        except Exception as e:
            logger.debug(f"Bootstrap iteration failed: {e}")
            continue

    # Calculate percentiles for confidence intervals
    alpha = 1 - confidence_level
    lower_percentile = alpha / 2 * 100
    upper_percentile = (1 - alpha / 2) * 100

    def calc_ci(values):
        if len(values) < 10:  # Need enough samples for meaningful CI
            return None
        arr = np.array(values)
        return {
            "lower": round(float(np.percentile(arr, lower_percentile)), 4),
            "upper": round(float(np.percentile(arr, upper_percentile)), 4),
            "n_samples": len(values)
        }

    # Macro-level CIs
    metrics_ci = {}
    if boot_accuracy:
        metrics_ci["accuracy"] = calc_ci(boot_accuracy)
    if boot_macro_precision:
        metrics_ci["macro_precision"] = calc_ci(boot_macro_precision)
    if boot_macro_recall:
        metrics_ci["macro_recall"] = calc_ci(boot_macro_recall)
        metrics_ci["macro_sensitivity"] = calc_ci(boot_macro_recall)
    if boot_macro_specificity:
        metrics_ci["macro_specificity"] = calc_ci(boot_macro_specificity)
    if boot_macro_f1:
        metrics_ci["macro_f1"] = calc_ci(boot_macro_f1)
    if boot_macro_auc:
        metrics_ci["macro_auc"] = calc_ci(boot_macro_auc)

    # Per-class CIs
    class_metrics_ci = {}
    for cls in all_classes:
        class_metrics_ci[cls] = {}
        for metric_name in ["precision", "recall", "sensitivity", "specificity", "f1", "auc"]:
            values = boot_class_metrics[cls][metric_name]
            if values:
                class_metrics_ci[cls][metric_name] = calc_ci(values)

    # Calculate ROC curve CI - TPR confidence intervals at each FPR grid point
    roc_ci = {}
    for cls in all_classes:
        if boot_roc_tpr[cls] and len(boot_roc_tpr[cls]) >= 10:  # Need enough samples
            tpr_array = np.array(boot_roc_tpr[cls])  # Shape: (n_valid_samples, 101)
            tpr_lower = np.percentile(tpr_array, lower_percentile, axis=0)
            tpr_upper = np.percentile(tpr_array, upper_percentile, axis=0)
            roc_ci[cls] = {
                "fpr_grid": fpr_grid.tolist(),
                "tpr_lower": tpr_lower.tolist(),
                "tpr_upper": tpr_upper.tolist(),
                "n_samples": len(boot_roc_tpr[cls])
            }

    logger.info(f"Bootstrap CI calculated with {len(boot_accuracy)} valid samples out of {n_bootstrap} attempts")
    if roc_ci:
        logger.info(f"ROC CI calculated for {len(roc_ci)} classes")

    return {
        "metrics_ci": metrics_ci,
        "class_metrics_ci": class_metrics_ci,
        "roc_ci": roc_ci,
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level
    }


def _calculate_survival_bootstrap_ci(
    risks: List[float],
    times: List[float],
    events: List[int],
    surv_probs: Optional[List[List[float]]],
    bin_edges: Optional[List[float]],
    requested_metrics: List[str],
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    progress_callback: Optional[Callable[[float], None]] = None
) -> Dict:
    """
    Calculate bootstrap confidence intervals for survival metrics (C-Index, IBS).

    Args:
        risks: List of risk scores
        times: List of event times
        events: List of event indicators (0 or 1)
        surv_probs: Optional list of survival probability arrays per sample
        bin_edges: Optional time bin edges for IBS calculation
        requested_metrics: List of requested metrics
        n_bootstrap: Number of bootstrap samples (default: 1000)
        confidence_level: Confidence level (default: 0.95)
        progress_callback: Optional sync callback for progress updates (0.0 to 1.0)

    Returns:
        Dictionary with CI for each metric
    """
    import numpy as np
    from sksurv.metrics import concordance_index_censored

    n_samples = len(risks)
    if n_samples < 10:
        logger.warning(f"Too few samples ({n_samples}) for reliable bootstrap CI")
        return None

    risks_arr = np.array(risks, dtype=float)
    times_arr = np.array(times, dtype=float)
    events_arr = np.array(events, dtype=bool)
    surv_probs_arr = np.array(surv_probs) if surv_probs and len(surv_probs) == n_samples else None

    # Storage for bootstrap metrics
    c_index_values = []
    ibs_values = []

    alpha = 1 - confidence_level
    lower_percentile = (alpha / 2) * 100
    upper_percentile = (1 - alpha / 2) * 100

    np.random.seed(42)  # For reproducibility

    for i in range(n_bootstrap):
        # Report progress every 50 iterations
        if progress_callback and i % 50 == 0:
            progress_callback(i / n_bootstrap)

        # Sample with replacement
        indices = np.random.choice(n_samples, size=n_samples, replace=True)

        boot_risks = risks_arr[indices]
        boot_times = times_arr[indices]
        boot_events = events_arr[indices]

        # Calculate C-Index for this bootstrap sample
        try:
            # Need at least one event and one non-event for C-Index
            if np.sum(boot_events) > 0 and np.sum(~boot_events) > 0:
                c_idx, _, _, _, _ = concordance_index_censored(
                    boot_events, boot_times, boot_risks
                )
                c_index_values.append(c_idx)
        except Exception as e:
            # Skip this bootstrap sample if C-Index calculation fails
            pass

        # Calculate IBS if requested and data is available
        if "integrated_brier_score" in requested_metrics and surv_probs_arr is not None and bin_edges is not None:
            try:
                boot_surv_probs = surv_probs_arr[indices]
                ibs = _calculate_integrated_brier_score(
                    boot_times.tolist(),
                    boot_events.astype(int).tolist(),
                    boot_surv_probs.tolist(),
                    bin_edges
                )
                if ibs is not None:
                    ibs_values.append(ibs)
            except Exception:
                pass

    # Calculate confidence intervals
    metrics_ci = {}

    if len(c_index_values) >= n_bootstrap * 0.5:  # At least 50% successful
        c_index_values = np.array(c_index_values)
        metrics_ci["c_index"] = {
            "lower": round(float(np.percentile(c_index_values, lower_percentile)), 4),
            "upper": round(float(np.percentile(c_index_values, upper_percentile)), 4),
            "n_samples": len(c_index_values)
        }
    else:
        metrics_ci["c_index"] = None

    if "integrated_brier_score" in requested_metrics:
        if len(ibs_values) >= n_bootstrap * 0.5:
            ibs_values = np.array(ibs_values)
            metrics_ci["integrated_brier_score"] = {
                "lower": round(float(np.percentile(ibs_values, lower_percentile)), 4),
                "upper": round(float(np.percentile(ibs_values, upper_percentile)), 4),
                "n_samples": len(ibs_values)
            }
        else:
            metrics_ci["integrated_brier_score"] = None

    return {
        "metrics_ci": metrics_ci,
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level
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


def _generate_roc_chart(roc_data, classes, output_path, roc_ci=None) -> Optional[Path]:
    """Generate ROC curve chart with high DPI for export.

    Args:
        roc_data: Dict with ROC curve points and AUC per class
        classes: List of class names
        output_path: Path to save the chart
        roc_ci: Optional dict with 95% CI data per class (fpr_grid, tpr_lower, tpr_upper)
    """
    try:
        plt = _setup_matplotlib_font()
        import numpy as np

        # Larger figure size for better text visibility
        fig, ax = plt.subplots(figsize=(12, 10))

        colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

        for i, cls in enumerate(classes):
            if cls in roc_data:
                points = roc_data[cls]["points"]
                auc_val = roc_data[cls]["auc"]
                fpr = [p["fpr"] for p in points]
                tpr = [p["tpr"] for p in points]
                color = colors[i % len(colors)]

                # Plot CI band if available
                if roc_ci and cls in roc_ci:
                    ci_data = roc_ci[cls]
                    fpr_grid = np.array(ci_data["fpr_grid"])
                    tpr_lower = np.array(ci_data["tpr_lower"])
                    tpr_upper = np.array(ci_data["tpr_upper"])
                    ax.fill_between(fpr_grid, tpr_lower, tpr_upper,
                                   color=color, alpha=0.15, label=f'{cls} 95% CI')

                # Plot ROC curve
                ax.plot(fpr, tpr, color=color, lw=3,
                       label=f'{cls} (AUC = {auc_val:.3f})')

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
    """Get loss data for ECharts rendering. Supports both regular and K-Fold training."""
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

        # Check if this is K-Fold training
        if metrics.get("is_kfold"):
            # Return K-Fold loss data structure
            folds = metrics.get("folds", {})
            fold_loss_data = {}

            for fold_name, fold_data in folds.items():
                history = fold_data.get("history", {})
                # Support both "loss" and "train_loss" keys
                loss = history.get("loss", history.get("train_loss", []))
                if loss:
                    fold_loss_data[fold_name] = {
                        "epochs": list(range(1, len(loss) + 1)),
                        "loss": loss,
                        "val_loss": history.get("val_loss", []),
                        "c_index": history.get("c_index", []),
                        "val_accuracy": history.get("val_accuracy", []),
                    }

            if not fold_loss_data:
                return None

            return {
                "is_kfold": True,
                "num_folds": metrics.get("num_folds", len(fold_loss_data)),
                "folds": fold_loss_data,
                "aggregated": metrics.get("aggregated", {}),
            }
        else:
            # Regular training
            history = metrics.get("history", {})
            loss = history.get("loss", history.get("train_loss", []))

            if not loss:
                return None

            return {
                "is_kfold": False,
                "epochs": list(range(1, len(loss) + 1)),
                "loss": loss,
                "val_loss": history.get("val_loss", []),
                "accuracy": history.get("accuracy", []),
                "val_accuracy": history.get("val_accuracy", []),
                "c_index": history.get("c_index", history.get("train_c_index", [])),
                "val_c_index": history.get("val_c_index", []),
            }
    except Exception as e:
        logger.error(f"Failed to get loss data: {e}")
        return None


async def _get_kfold_metrics(task_id: str) -> Optional[Dict[str, Any]]:
    """Get K-Fold aggregated metrics if available."""
    try:
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

        if not metrics.get("is_kfold"):
            return None

        return {
            "is_kfold": True,
            "num_folds": metrics.get("num_folds"),
            "folds": metrics.get("folds", {}),
            "aggregated": metrics.get("aggregated", {}),
        }
    except Exception as e:
        logger.error(f"Failed to get K-Fold metrics: {e}")
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
async def get_results(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI analysis results for a WSI from database.
    Users can view results for their own WSI or WSI in datasets they have elevated permissions for.

    Args:
        wsi_id: The WSI ID to get results for

    Returns:
        AI result data including predictions and probabilities
    """
    # Check WSI access permission (ownership or elevated dataset permission)
    wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    if wsi:
        has_access = await check_wsi_access_permission(user, wsi.dataset_id, wsi.user_id, db)
        if not has_access:
            raise HTTPException(status_code=403, detail="You don't have permission to view results for this WSI")

    # Get from database
    result = await AIResultRepository.get_by_wsi_id(db, wsi_id)
    if result:
        return result.to_dict()

    # No result found
    return {"wsi_id": wsi_id, "pred": None, "probs": None}


@router.delete("/wsi/{wsi_id}")
async def delete_wsi_results(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Delete results for specific task only"),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete AI analysis results for a WSI.
    Requires pathologist or admin role. Users can only delete their own WSI's results.

    This will:
    1. Delete AI result records from database
    2. Delete AI result files (attention weights, result JSONs) from disk

    Args:
        wsi_id: The WSI ID to delete results for
        task_id: Optional - if provided, only delete results for this specific task

    Returns:
        {
            "message": str,
            "wsi_id": str,
            "task_id": str | None,
            "database_deleted": int,
            "storage_cleanup": dict
        }
    """
    from sqlalchemy import delete as sql_delete

    try:
        # Verify WSI exists
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Check ownership
        if not check_data_ownership(wsi.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to delete results for this WSI")

        # Delete from database
        database_deleted = 0
        if task_id:
            # Delete specific task result
            result = await db.execute(
                sql_delete(AIResult).where(
                    AIResult.wsi_id == wsi_id,
                    AIResult.task_id == task_id
                )
            )
            database_deleted = result.rowcount
        else:
            # Delete all results for this WSI
            result = await db.execute(
                sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
            )
            database_deleted = result.rowcount

        await db.commit()

        # Delete files from disk
        storage_cleanup = storage_manager.delete_wsi_ai_results(wsi_id, task_id)
        logger.info(storage_cleanup['summary'])

        return {
            "message": "AI results deleted successfully",
            "wsi_id": wsi_id,
            "task_id": task_id,
            "database_deleted": database_deleted,
            "storage_cleanup": storage_cleanup
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete AI results for WSI {wsi_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete AI results: {str(e)}")


# =============================================================================
# Helper Functions
# =============================================================================

def _get_random_seed_from_task(task) -> Optional[int]:
    """Extract random seed from task's preprocessing_config.

    The seed is stored in preprocessing_config.split_config.seed and serves
    as both a reproducibility parameter and an invisible watermark for model provenance.
    """
    if not task or not task.preprocessing_config:
        return None
    split_config = task.preprocessing_config.get("split_config", {})
    return split_config.get("seed")


async def _resolve_task_dataset_id(task, db) -> Optional[str]:
    """Resolve dataset_id for a training task.

    For external validation tasks, dataset_id is stored in model_config.
    For regular training tasks, dataset_id must be derived from the task's WSIs
    through the TrainingTaskWSI junction table.

    Args:
        task: TrainingTask object
        db: Database session

    Returns:
        dataset_id string or None
    """
    mc = task.model_config or {}
    # External validation tasks have dataset_id in model_config
    dataset_id = mc.get("dataset_id")
    if dataset_id:
        return dataset_id

    # For regular training tasks, derive from WSIs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
    if wsi_ids:
        first_wsi = await WSIRepository.get_by_id(db, wsi_ids[0])
        if first_wsi and first_wsi.dataset_id:
            return first_wsi.dataset_id

    return None


# =============================================================================
# Classification Analysis
# =============================================================================

async def _run_classification_analysis(task, request, db, progress_callback=None, progress_config=None, submitted_by=None):
    """Run analysis for classification task.

    NOTE: Analysis is performed ONLY on the test set to provide unbiased metrics.
    Training and validation sets are excluded to avoid data leakage.
    For case-level datasets, metrics are calculated per case (one case = one sample).

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
    predictions = []
    labels = []
    probs_list = []
    wsi_results = []

    # Check if this is a case-level dataset
    aggregation_level = await TrainingTaskRepository.get_dataset_aggregation_level(db, task_id)
    is_case_level = aggregation_level == "case"
    logger.info(f"Classification analysis for task {task_id}: aggregation_level = {aggregation_level}, is_case_level = {is_case_level}")

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
            logger.info(f"Analysis for task {task_id}: using {len(test_wsi_ids)} test set WSIs")
        elif is_kfold:
            logger.info(f"Analysis for task {task_id}: K-Fold training detected ({len(kfold_splits)} folds), using all validation results")
        else:
            logger.warning(f"Analysis for task {task_id}: no test set found, using all WSIs")

        result = await db.execute(query)
        rows = result.all()

        for ai_result, wsi in rows:
            predictions.append(ai_result.pred)
            labels.append(wsi.label)
            probs_list.append(ai_result.probs or {})
            wsi_results.append({
                "wsi_id": ai_result.wsi_id,
                "case_id": wsi.case_id or ai_result.wsi_id,
                "label": wsi.label,
                "pred": ai_result.pred,
                "correct": ai_result.pred == wsi.label,
                "probs": ai_result.probs
            })

    # If no results from database, try to load from ai_results directory
    if not predictions:
        # Get test set WSI IDs for file-based fallback
        test_wsi_query = (
            select(TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
            .where(TrainingTaskWSI.split == "test")
        )
        test_wsi_result = await db.execute(test_wsi_query)
        test_wsi_ids = {row[0] for row in test_wsi_result.all()}

        ai_results_dir = Config.get_uploads_dir() / "ai_results"
        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    for json_file in wsi_dir.glob("*.json"):
                         # Add explicit yield to event loop to keep server responsive during large CPU file I/O
                        await asyncio.sleep(0.001)
                        try:
                            with open(json_file, 'r') as f:
                                data = json.load(f)
                                wsi_id = data.get("wsi_id", wsi_dir.name)
                                # Only include if task matches and (no test set defined OR wsi is in test set)
                                if data.get("task_id") == task_id and data.get("pred"):
                                    if test_wsi_ids and wsi_id not in test_wsi_ids:
                                        continue  # Skip non-test set WSIs
                                    predictions.append(data["pred"])
                                    labels.append(data.get("ground_truth", "unknown"))
                                    probs_list.append(data.get("probs", {}))
                                    wsi_results.append({
                                        "wsi_id": wsi_id,
                                        "case_id": data.get("case_id", wsi_id),
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

        logger.info(f"Case-level classification analysis: aggregated {len(wsi_results)} slides to {len(case_results)} cases")

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
            labels=labels, predictions=predictions, probs_list=probs_list,
            all_classes=all_classes, requested_metrics=request.metrics
        )
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
    ci_metrics = request.bootstrap_ci_metrics if request.bootstrap_ci_metrics else (request.metrics if request.compute_bootstrap_ci else [])

    # Skip Bootstrap CI for K-Fold tasks - they use mean ± std instead
    if is_kfold and ci_metrics:
        logger.info(f"Skipping bootstrap CI for K-Fold task {task_id} - using mean ± std instead")
        ci_metrics = []

    if ci_metrics:
        logger.info(f"Computing bootstrap 95% CI for task {task_id} with {len(predictions)} samples, metrics: {ci_metrics}...")
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
        logger.info(f"Bootstrap CI calculation completed for task {task_id}")

    # Update progress - bootstrap CI done (or skipped)
    if progress_callback:
        await progress_callback(p_ci_end)

    # Create analysis output directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Check for K-Fold training metrics
    kfold_metrics = await _get_kfold_metrics(task_id)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Save summary
    summary = {
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
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
        # Get ROC CI from bootstrap_ci_result if available
        roc_ci = bootstrap_ci_result.get("roc_ci", {}) if bootstrap_ci_result else {}
        for cls, data in metrics_result["roc_data"].items():
            roc_chart_data[cls] = {
                "fpr": [p["fpr"] for p in data["points"]],
                "tpr": [p["tpr"] for p in data["points"]],
                "auc": data["auc"]
            }
            # Add CI data if available for this class
            if cls in roc_ci:
                roc_chart_data[cls]["fpr_grid"] = roc_ci[cls]["fpr_grid"]
                roc_chart_data[cls]["tpr_lower"] = roc_ci[cls]["tpr_lower"]
                roc_chart_data[cls]["tpr_upper"] = roc_ci[cls]["tpr_upper"]
        chart_data["roc_curve"] = {
            "classes": all_classes,
            "data": roc_chart_data
        }

        roc_path = _generate_roc_chart(
            metrics_result["roc_data"], all_classes, analysis_dir / "roc_curve.png",
            roc_ci=roc_ci
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

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

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


# =============================================================================
# Survival Analysis
# =============================================================================

async def _run_survival_analysis(task, request, db, progress_callback=None, progress_config=None, submitted_by=None):
    """Run analysis for survival task.

    NOTE: Analysis is performed ONLY on the test set to provide unbiased metrics.
    Training and validation sets are excluded to avoid data leakage.
    For case-level datasets, metrics are calculated per case (one case = one sample).

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

    # Check if this is a case-level dataset
    aggregation_level = await TrainingTaskRepository.get_dataset_aggregation_level(db, task_id)
    is_case_level = aggregation_level == "case"
    logger.info(f"Survival analysis for task {task_id}: aggregation_level = {aggregation_level}, is_case_level = {is_case_level}")

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
        logger.info(f"Survival analysis for task {task_id}: using {len(test_wsi_ids)} test set WSIs")
    elif is_kfold:
        logger.info(f"Survival analysis for task {task_id}: K-Fold training detected ({len(kfold_splits)} folds), using all validation results")
    else:
        logger.warning(f"Survival analysis for task {task_id}: no test set found, using all WSIs")

    # We load result JSONs from ai_results dir since survival results structure is different
    # and might not be fully in DB (AIResult table is optimized for classification)

    ai_results_dir = Config.get_uploads_dir() / "ai_results"

    risks = []
    times = []
    events = []
    wsi_results = []
    surv_probs = [] # list of lists
    bin_edges = None

    if ai_results_dir.exists():
        for wsi_dir in ai_results_dir.iterdir():
            if wsi_dir.is_dir():
                # Match both regular (train_{task_id}_result.json) and K-Fold (train_{task_id}_fold_*_result.json) files
                matched_files = list(wsi_dir.glob(f"train_{task_id}*_result.json"))
                if matched_files:
                    logger.debug(f"Found {len(matched_files)} result files in {wsi_dir.name}: {[f.name for f in matched_files]}")
                for json_file in matched_files:
                    try:
                        with open(json_file, 'r') as f:
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
                                case_id = wsi_case_map.get(wsi_id, wsi_id) if is_case_level else wsi_id

                                risks.append(data["risk_score"])
                                times.append(data["event_time"])
                                events.append(data.get("event_status", 0))

                                if "surv_probs" in data:
                                    surv_probs.append(data["surv_probs"])
                                else:
                                    logger.warning(f"No surv_probs in {json_file.name}")

                                if "bin_edges" in data and bin_edges is None:
                                    bin_edges = data["bin_edges"]

                                wsi_results.append({
                                    "wsi_id": wsi_id,
                                    "case_id": case_id,
                                    "risk_score": data["risk_score"],
                                    "event_time": data["event_time"],
                                    "event_status": data.get("event_status", 0),
                                    "surv_probs": data.get("surv_probs")
                                })
                    except Exception as e:
                        logger.warning(f"Failed to load survival result from {json_file}: {e}")
                        continue

    if not risks:
        # Check database if not found in files (fallback)
        pass
        if not risks:
             raise HTTPException(status_code=400, detail="No analyzed survival results found for this task")

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

        logger.info(f"Case-level survival analysis: aggregated to {len(case_results_map)} cases")

    logger.info(f"Survival analysis for task {task_id}: loaded {len(risks)} samples for C-Index calculation")
    logger.info(f"  surv_probs count: {len(surv_probs)}, bin_edges available: {bin_edges is not None}")

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
    c_index, _, _, _, _ = concordance_index_censored(
        events_bool, times_arr, risks_arr
    )
    logger.info(f"  Calculated C-Index (scikit-survival): {c_index}")

    # Create analysis directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
    analysis_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "c_index": round(c_index, 4)
    }

    # Calculate Integrated Brier Score if requested
    if "integrated_brier_score" in request.metrics:
        logger.info(f"IBS requested. surv_probs count: {len(surv_probs)}, bin_edges available: {bin_edges is not None}, "
                    f"bin_edges length: {len(bin_edges) if bin_edges else 0}")
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
    ci_metrics = request.bootstrap_ci_metrics if request.bootstrap_ci_metrics else (request.metrics if request.compute_bootstrap_ci else [])

    # Skip Bootstrap CI for K-Fold tasks - they use mean ± std instead
    if is_kfold and ci_metrics:
        logger.info(f"Skipping bootstrap CI for K-Fold survival task {task_id} - using mean ± std instead")
        ci_metrics = []

    if ci_metrics:
        logger.info(f"Computing bootstrap 95% CI for survival task {task_id}, metrics: {ci_metrics}...")
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

    # Generate Charts
    chart_paths = {}
    chart_data = {}

    if "km_curve" in request.charts:
        # Generate KM Curve - include CI bands only if user selected C-index 95% CI
        km_path = analysis_dir / "km_curve.png"
        include_km_ci = "c_index" in ci_metrics
        km_data = _generate_km_analysis(times, events, risks, km_path, include_ci=include_km_ci)
        if km_data:
            chart_paths["km_curve"] = str(km_path)
            chart_data["km_curve"] = km_data # For frontend rendering

    if "loss_curve" in request.charts:
        # Load loss history from model metrics (supports K-Fold)
        loss_data = await _get_loss_data(task_id)
        if loss_data:
            chart_data["loss_curve"] = loss_data

    # Check for K-Fold training metrics
    kfold_metrics = await _get_kfold_metrics(task_id)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Save Summary
    summary = {
        "task_id": task_id,
        "task_type": "survival",
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
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

    with open(analysis_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    with open(analysis_dir / "results.json", 'w') as f:
        json.dump({
            "wsi_results": wsi_results,
            "metrics": metrics
        }, f, indent=2)

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths
    }

def _generate_km_analysis(times, events, risks, output_path, include_ci: bool = False):
    """
    Generate KM curves for High vs Low risk groups using scikit-survival.
    Returns data for frontend ECharts.

    Args:
        times: Event times
        events: Event indicators (0/1)
        risks: Risk scores
        output_path: Path to save the PNG chart
        include_ci: Whether to include 95% CI bands (only when user selects C-index 95% CI)
    """
    try:
        import numpy as np
        from sksurv.nonparametric import kaplan_meier_estimator

        times = np.array(times, dtype=float)
        events = np.array(events, dtype=bool)
        risks = np.array(risks, dtype=float)

        # Split into High/Low risk based on median risk score
        median_risk = np.median(risks)
        high_mask = risks >= median_risk
        low_mask = ~high_mask

        # Calculate KM curves using scikit-survival
        # kaplan_meier_estimator returns (time, survival_prob, conf_int)
        t_high, s_high, conf_high = kaplan_meier_estimator(
            events[high_mask], times[high_mask], conf_type="log-log"
        )
        t_low, s_low, conf_low = kaplan_meier_estimator(
            events[low_mask], times[low_mask], conf_type="log-log"
        )

        # Add t=0, s=1 point at start for frontend
        t_high_list = [0.0] + t_high.tolist()
        s_high_list = [1.0] + s_high.tolist()
        t_low_list = [0.0] + t_low.tolist()
        s_low_list = [1.0] + s_low.tolist()

        # CI values (add 1.0 for t=0) - only if include_ci is True
        if include_ci:
            ci_high_lower = [1.0] + conf_high[0].tolist()
            ci_high_upper = [1.0] + conf_high[1].tolist()
            ci_low_lower = [1.0] + conf_low[0].tolist()
            ci_low_upper = [1.0] + conf_low[1].tolist()

        # Plotting using matplotlib with step plot
        plt = _setup_matplotlib_font()
        fig, ax = plt.subplots(figsize=(12, 8))

        # Low risk group (green)
        ax.step(t_low, s_low, where="post", color='#10b981', lw=3, label='Low Risk Group')
        if include_ci:
            ax.fill_between(t_low, conf_low[0], conf_low[1], alpha=0.25, step="post", color='#10b981')

        # High risk group (red)
        ax.step(t_high, s_high, where="post", color='#ef4444', lw=3, label='High Risk Group')
        if include_ci:
            ax.fill_between(t_high, conf_high[0], conf_high[1], alpha=0.25, step="post", color='#ef4444')

        ax.set_xlabel('Time (Months)', fontsize=20, fontweight='bold')
        ax.set_ylabel('Survival Probability', fontsize=20, fontweight='bold')
        ax.set_title('Kaplan-Meier Survival Curve', fontsize=24, fontweight='bold', pad=20)
        ax.set_ylim([0.0, 1.05])
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=16, loc='lower left')
        ax.tick_params(axis='both', labelsize=16)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        plt.close(fig)

        # Build result - only include CI data if include_ci is True
        result = {
            "high_risk": {
                "times": t_high_list,
                "probs": s_high_list
            },
            "low_risk": {
                "times": t_low_list,
                "probs": s_low_list
            },
            "cutoff": float(median_risk)
        }

        if include_ci:
            result["high_risk"]["ci_lower"] = ci_high_lower
            result["high_risk"]["ci_upper"] = ci_high_upper
            result["low_risk"]["ci_lower"] = ci_low_lower
            result["low_risk"]["ci_upper"] = ci_low_upper

        return result

    except Exception as e:
        logger.error(f"KM Analysis failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def _calculate_integrated_brier_score(times, events, surv_probs_list, bin_edges):
    """
    Calculate Integrated Brier Score (IBS) for survival predictions using scikit-survival.

    Args:
        times: List of event times
        events: List of event indicators (1=event, 0=censored)
        surv_probs_list: List of survival probability arrays for each sample
        bin_edges: Bin edges used for discrete-time survival model

    Returns:
        Integrated Brier Score (lower is better)
    """
    try:
        import numpy as np
        # Compatibility shim: scikit-survival >= 0.23 uses np.trapezoid (NumPy >= 2.0)
        # but older NumPy versions only have np.trapz
        if not hasattr(np, 'trapezoid'):
            np.trapezoid = np.trapz
        from sksurv.metrics import integrated_brier_score

        if not surv_probs_list or len(surv_probs_list) == 0:
            logger.warning("No survival probabilities available for IBS calculation")
            return None

        times_arr = np.array(times, dtype=float)
        events_arr = np.array(events, dtype=bool)
        surv_probs_arr = np.array(surv_probs_list)  # Shape: (n_samples, n_bins)

        if bin_edges is None:
            logger.warning("No bin edges available for IBS calculation")
            return None

        bin_edges = np.array(bin_edges)

        # Create structured array for scikit-survival
        # dtype: [('event', bool), ('time', float)]
        y_struct = np.array(
            [(e, t) for e, t in zip(events_arr, times_arr)],
            dtype=[('event', bool), ('time', float)]
        )

        # Evaluation time points (bin midpoints)
        # For discrete survival, we use the upper bound of each bin as the time point
        eval_times = bin_edges[1:]  # Skip first edge (usually 0)

        # Filter eval_times to be within observed time range
        # scikit-survival requires times to be in (min_time, max_time)
        min_time = times_arr.min()
        max_time = times_arr.max()
        valid_mask = (eval_times > min_time) & (eval_times < max_time)
        eval_times = eval_times[valid_mask]

        if len(eval_times) < 2:
            logger.warning("Not enough valid time points for IBS calculation")
            return None

        # Filter surv_probs to match valid eval_times using the same mask
        # surv_probs_arr[i][j] = S(t_j | x_i) for sample i at time bin j
        # Must use valid_mask (not positional slicing) to keep alignment with eval_times
        surv_probs_filtered = surv_probs_arr[:, valid_mask]

        logger.info(f"IBS calculation: {len(eval_times)} valid time points out of {len(bin_edges)-1} bins, "
                    f"surv_probs shape: {surv_probs_filtered.shape}, eval_times range: [{eval_times[0]:.2f}, {eval_times[-1]:.2f}]")

        # Calculate IBS using scikit-survival
        # integrated_brier_score expects:
        # - survival_train: structured array of training data (same as test for our case)
        # - survival_test: structured array of test data
        # - estimate: 2D array of predicted survival probabilities (n_samples, n_times)
        # - times: 1D array of evaluation time points
        ibs = integrated_brier_score(y_struct, y_struct, surv_probs_filtered, eval_times)

        return float(ibs)

    except Exception as e:
        logger.error(f"IBS calculation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


# =============================================================================
# External Validation Analysis
# =============================================================================

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
    dataset_id = model_config.get("dataset_id")

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

    # Generate charts
    chart_paths = {}
    chart_data = {}

    if "km_curve" in request.charts and len(risks) > 0:
        # Include CI bands only if user selected C-index 95% CI
        km_path = analysis_dir / "km_curve.png"
        include_km_ci = "c_index" in ci_metrics
        # NOTE: matplotlib chart generation is CPU-intensive — run in thread
        km_data = await asyncio.to_thread(_generate_km_analysis, times, events, risks, km_path, include_km_ci)
        if km_data:
            chart_data["km_curve"] = km_data
            chart_paths["km_curve"] = str(km_path)

    # Note: loss_curve is skipped for external validation (training-only)

    # Extract random seed (serves as invisible watermark for model provenance)
    random_seed = _get_random_seed_from_task(task)

    # Check for K-Fold training metrics from the original model
    kfold_metrics = None
    if model_task_id:
        kfold_metrics = await _get_kfold_metrics(model_task_id)

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

    with open(analysis_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    # Save detailed results
    with open(analysis_dir / "results.json", 'w') as f:
        json.dump({
            "wsi_results": wsi_results,
            "metrics": metrics
        }, f, indent=2)

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

        # NOTE: matplotlib chart generation is CPU-intensive — run in thread
        cm_path = await asyncio.to_thread(
            _generate_confusion_matrix_chart,
            confusion_matrix, all_classes, analysis_dir / "confusion_matrix.png"
        )
        if cm_path:
            chart_paths["confusion_matrix"] = str(cm_path)

    if "roc_curve" in request.charts and metrics_result.get("roc_data"):
        # Prepare ROC curve data for ECharts
        roc_chart_data = {}
        # Get ROC CI from bootstrap_ci_result if available
        roc_ci = bootstrap_ci_result.get("roc_ci", {}) if bootstrap_ci_result else {}
        for cls, data in metrics_result["roc_data"].items():
            roc_chart_data[cls] = {
                "fpr": [p["fpr"] for p in data["points"]],
                "tpr": [p["tpr"] for p in data["points"]],
                "auc": data["auc"]
            }
            # Add CI data if available for this class
            if cls in roc_ci:
                roc_chart_data[cls]["fpr_grid"] = roc_ci[cls]["fpr_grid"]
                roc_chart_data[cls]["tpr_lower"] = roc_ci[cls]["tpr_lower"]
                roc_chart_data[cls]["tpr_upper"] = roc_ci[cls]["tpr_upper"]
        chart_data["roc_curve"] = {
            "classes": all_classes,
            "data": roc_chart_data
        }

        # NOTE: matplotlib chart generation is CPU-intensive — run in thread
        roc_path = await asyncio.to_thread(
            _generate_roc_chart,
            metrics_result["roc_data"], all_classes, analysis_dir / "roc_curve.png",
            roc_ci
        )
        if roc_path:
            chart_paths["roc_curve"] = str(roc_path)

    # Note: loss_curve is skipped for external validation (training-only)

    # Update progress - charts generated
    if progress_callback:
        await progress_callback(97)

    # Update summary with chart paths and chart data
    summary["chart_paths"] = chart_paths
    summary["chart_data"] = chart_data
    with open(analysis_dir / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info(f"External validation classification analysis completed for task {task_id}, saved to {analysis_dir}")

    return {
        "task_id": task_id,
        "analysis_id": timestamp,
        "analysis_dir": str(analysis_dir),
        "summary": summary,
        "chart_paths": chart_paths
    }


# =============================================================================
# Async Analysis Pipeline
# =============================================================================

async def run_analysis_pipeline(
    task_id: str,
    analysis_id: str,
    training_task_id: str,
    task_type_str: str,
    metrics: List[str],
    charts: List[str],
    description: Optional[str] = None,
    bootstrap_ci_metrics: Optional[List[str]] = None,
    submitted_by: Optional[str] = None,
):
    """
    Async pipeline for running analysis in background.

    This function is submitted to the task queue and runs asynchronously.
    It updates the analysis state as it progresses.

    The pipeline automatically runs GPU inference if AI results are missing:
    1. Check if AI results exist
    2. If missing, run GPU inference to generate intermediate results
    3. Calculate metrics on CPU using the intermediate results

    Progress bar allocation based on workload:
    - Scenario 1 (GPU + CI): inference 0-40%, CI 40-95%
    - Scenario 2 (GPU only): inference 0-80%, metrics 80-95%
    - Scenario 3 (CI only): loading 0-20%, CI 20-95%
    - Scenario 4 (neither): loading 0-30%, metrics 30-90%

    Args:
        task_id: The queue task ID (same as analysis_id for analysis tasks)
        analysis_id: Unique analysis ID
        training_task_id: The training task to analyze
        task_type_str: Type of training task (classification, survival, etc.)
        metrics: List of metrics to compute
        charts: List of charts to generate
        description: Optional description
        bootstrap_ci_metrics: List of metrics to compute 95% CI for
        submitted_by: User ID of the person who initiated the analysis
    """
    from backend.database.database import async_session

    state = get_analysis_state()

    try:
        # Mark as running
        await state.set_running(analysis_id)
        logger.info(f"Starting analysis pipeline for task {training_task_id}, analysis_id={analysis_id}")

        # Create database session with proper cleanup - use safe_session for background task
        async with safe_session() as db:
            # Get training task
            task = await TrainingTaskRepository.get_by_id(db, training_task_id)
            if not task:
                raise ValueError(f"Training task not found: {training_task_id}")

            # Determine workload: check if GPU inference and/or CI calculation is needed
            needs_gpu_inference = False
            has_ci_calculation = bool(bootstrap_ci_metrics and len(bootstrap_ci_metrics) > 0)

            # Check if K-Fold (K-Fold skips CI, uses mean ± std instead)
            # split_strategy is stored in preprocessing_config.split_config.strategy
            split_config = task.preprocessing_config.get("split_config", {}) if task.preprocessing_config else {}
            split_strategy = split_config.get("strategy", "random")
            is_kfold = split_strategy == "k_fold"
            if is_kfold and has_ci_calculation:
                has_ci_calculation = False  # K-Fold doesn't use Bootstrap CI

            if task_type_str != "external_validation":
                # Check if AI results exist
                resources = await _check_task_resources(task.task_id, db)
                needs_gpu_inference = not resources["has_ai_results"]

            # Determine progress ranges based on workload
            # 4 scenarios for optimal progress bar UX
            if needs_gpu_inference and has_ci_calculation:
                # Scenario 1: Both slow operations
                inference_end = 40
                analysis_start = 40
                analysis_ci_start = 45
                analysis_ci_end = 95
            elif needs_gpu_inference and not has_ci_calculation:
                # Scenario 2: GPU inference only (no CI)
                inference_end = 80
                analysis_start = 80
                analysis_ci_start = 85  # Not used but set for consistency
                analysis_ci_end = 95
            elif not needs_gpu_inference and has_ci_calculation:
                # Scenario 3: CI calculation only (no GPU)
                inference_end = 0  # Not used
                analysis_start = 20
                analysis_ci_start = 25
                analysis_ci_end = 95
            else:
                # Scenario 4: Neither (fast path)
                inference_end = 0  # Not used
                analysis_start = 30
                analysis_ci_start = 35  # Not used
                analysis_ci_end = 90

            logger.info(f"Analysis pipeline workload: needs_gpu={needs_gpu_inference}, has_ci={has_ci_calculation}, "
                       f"is_kfold={is_kfold}, progress_ranges: inference_end={inference_end}, "
                       f"analysis_start={analysis_start}, ci_range={analysis_ci_start}-{analysis_ci_end}")

            # Step 1: Run GPU inference if needed
            if needs_gpu_inference:
                # Create inference progress callback (0% to inference_end%)
                async def inference_progress(fraction: float):
                    progress = int(fraction * inference_end)
                    await state.update(analysis_id, progress=progress)

                await _run_inference_if_needed(task, db, progress_callback=inference_progress)
                await state.update(analysis_id, progress=inference_end)

            # Create analysis request
            request = AnalysisRequest(
                metrics=metrics,
                charts=charts,
                description=description,
                bootstrap_ci_metrics=bootstrap_ci_metrics or []
            )

            # Update progress - starting analysis phase
            await state.update(analysis_id, progress=analysis_start)

            # Create progress callback for analysis functions with dynamic ranges
            # Pass the CI range info to analysis functions
            async def update_progress(progress: int):
                await state.update(analysis_id, progress=progress)

            # Step 2: Route to appropriate analysis handler based on task type
            # Analysis functions calculate metrics on CPU using the intermediate AI results
            # Pass progress range info for dynamic allocation
            progress_config = {
                "start": analysis_start,
                "ci_start": analysis_ci_start,
                "ci_end": analysis_ci_end,
                "has_ci": has_ci_calculation,
            }

            match task_type_str:
                case "wsi_survival" | "survival":
                    result = await _run_survival_analysis(
                        task, request, db, progress_callback=update_progress, progress_config=progress_config, submitted_by=submitted_by
                    )
                case "external_validation":
                    result = await _run_external_validation_analysis(
                        task, request, db, progress_callback=update_progress, progress_config=progress_config, submitted_by=submitted_by
                    )
                case _:
                    result = await _run_classification_analysis(
                        task, request, db, progress_callback=update_progress, progress_config=progress_config, submitted_by=submitted_by
                    )

            # Mark as completed
            await state.set_completed(analysis_id)
            logger.info(f"Analysis pipeline completed for task {training_task_id}, analysis_id={analysis_id}")

    except asyncio.CancelledError:
        # Task was cancelled by user
        logger.info(f"Analysis pipeline cancelled for task {training_task_id}, analysis_id={analysis_id}")
        await state.set_cancelled(analysis_id)
        raise  # Re-raise to properly handle task cancellation

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Analysis pipeline failed for task {training_task_id}: {error_msg}")
        await state.set_failed(analysis_id, error_msg)
        raise

    finally:
        # Always unregister task when done (completed, failed, or cancelled)
        state.unregister_task(analysis_id)
