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
import traceback
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Callable, Tuple
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.orm import selectinload

from backend.ai.schemas.base import TaskStatus
from backend.database import get_db, safe_session
from backend.database.models import AIResult, AITask, WSISlide, TrainingTask, TrainedModel, TrainingTaskWSI, DataGroup, Dataset
from backend.database.repositories import AIResultRepository, WSIRepository, TrainingTaskRepository, TrainedModelRepository, DataGroupRepository, DatasetRepository, DatasetPermissionRepository
from backend.common.config import Config
from backend.storage import StorageManager
from backend.auth import current_active_user, User, get_user_from_header_or_param, get_user_from_token_param
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership, check_dataset_gpu_permission, check_wsi_access_permission
from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi
from backend.preprocessing.heatmap_preview_cache import ensure_recommendation_preview_cache

# Analysis modules (extracted from this file for maintainability)
from .analysis_state import get_analysis_state, AnalysisRequest
from .analysis_helpers import (
    _get_random_seed_from_task,
    _get_task_with_access,
    _require_task_access,
    _require_task_gpu_permission,
)
from .classification_analysis import _run_classification_analysis
from .segmentation_analysis import _run_segmentation_analysis
from .survival_analysis import _run_survival_analysis
from .external_validation_analysis import _run_external_validation_analysis
from .analysis_metrics import (
    _calculate_all_metrics,
    _calculate_bootstrap_ci,
    _calculate_survival_bootstrap_ci,
    _setup_matplotlib_font,
    _generate_confusion_matrix_chart,
    _generate_roc_chart,
    _get_loss_data,
    _get_kfold_metrics,
    _generate_loss_chart,
    _generate_km_analysis,
    _calculate_integrated_brier_score,
)

# Initialize storage manager
storage_manager = StorageManager(str(Config.get_uploads_dir()))

router = APIRouter(prefix="/results", tags=["AI Results"])
logger = logging.getLogger(__name__)


def _normalize_label_names(labels: List[str]) -> List[str]:
    return sorted({str(label).strip() for label in labels if str(label).strip()})


def _extract_segmentation_label_names(categories: List[Dict[str, Any]]) -> List[str]:
    return _normalize_label_names([
        str(category.get("name", "")).strip()
        for category in categories
        if category.get("name")
    ])


def _coerce_path(path_value: Any) -> Optional[Path]:
    if not path_value:
        return None
    try:
        return Path(path_value)
    except (TypeError, ValueError):
        return None


def _candidate_metrics_paths(task_id: str, trained_model: Optional[Dict[str, Any]]) -> List[Path]:
    uploads_dir = Config.get_uploads_dir()
    candidates: List[Path] = []

    if trained_model:
        for key in ("model_path", "config_path"):
            model_related_path = _coerce_path(trained_model.get(key))
            if model_related_path:
                candidates.append(model_related_path.parent / "metrics.json")

        model_id = trained_model.get("model_id")
        if model_id:
            candidates.append(uploads_dir / "models" / str(model_id) / "metrics.json")

    candidates.extend([
        uploads_dir / "training" / task_id / "checkpoints" / "metrics.json",
        uploads_dir / "training" / task_id / "metrics.json",
    ])

    deduped: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str not in seen:
            deduped.append(candidate)
            seen.add(candidate_str)
    return deduped


def _derive_companion_artifact_path(result_file: Path, artifact_suffix: str) -> Path:
    result_name = result_file.name
    if result_name.endswith("_result.json"):
        return result_file.with_name(f"{result_name[:-len('_result.json')]}{artifact_suffix}")
    return result_file.with_name(f"{result_file.stem}{artifact_suffix}")


def _expects_wsi_attention(extra_metadata: Optional[Dict[str, Any]]) -> bool:
    metadata = extra_metadata if isinstance(extra_metadata, dict) else {}
    if metadata.get("attention_file"):
        return True

    attention_type = str(metadata.get("attention_type") or "").strip().lower()
    if attention_type and attention_type != "none":
        return True

    return metadata.get("attention_shape") is not None


def _required_ai_result_artifacts(
    task_id: str,
    task_type: str,
    data_type: str,
    wsi_id: str,
    extra_metadata: Optional[Dict[str, Any]],
) -> List[Tuple[str, Path]]:
    uploads_dir = Config.get_uploads_dir()
    result_dir = uploads_dir / "ai_results" / wsi_id
    metadata = extra_metadata if isinstance(extra_metadata, dict) else {}

    result_file = _coerce_path(metadata.get("result_file")) or (result_dir / f"train_{task_id}_result.json")
    artifacts: List[Tuple[str, Path]] = [("result_file", result_file)]

    if task_type in ("segmentation", "patch_segmentation"):
        pred_mask_file = _coerce_path(metadata.get("pred_mask_file")) or _derive_companion_artifact_path(result_file, "_pred_mask.npy")
        cam_file = _coerce_path(metadata.get("cam_file")) or _derive_companion_artifact_path(result_file, "_cam.npy")
        artifacts.extend([
            ("pred_mask_file", pred_mask_file),
            ("cam_file", cam_file),
        ])
        return artifacts

    if data_type == "patch":
        cam_file = _coerce_path(metadata.get("cam_file")) or _derive_companion_artifact_path(result_file, "_cam.npy")
        artifacts.append(("cam_file", cam_file))
        return artifacts

    if _expects_wsi_attention(metadata):
        attention_file = _coerce_path(metadata.get("attention_file")) or _derive_companion_artifact_path(result_file, "_attention.npy")
        artifacts.append(("attention_file", attention_file))
    return artifacts


def _collect_missing_ai_result_artifacts(
    task_id: str,
    task_type: str,
    data_type: str,
    wsi_id: str,
    extra_metadata: Optional[Dict[str, Any]],
    sample_limit: int = 10,
) -> Tuple[int, List[Dict[str, Any]]]:
    metadata = extra_metadata if isinstance(extra_metadata, dict) else {}
    missing_artifacts: List[Dict[str, Any]] = []
    missing_count = 0

    for artifact_name, artifact_path in _required_ai_result_artifacts(task_id, task_type, data_type, wsi_id, metadata):
        if artifact_path.exists():
            continue
        missing_count += 1
        if len(missing_artifacts) < sample_limit:
            missing_artifacts.append({
                "wsi_id": wsi_id,
                "artifact": artifact_name,
                "path": str(artifact_path),
            })

    if data_type != "patch" and _expects_wsi_attention(metadata):
        coords_file = find_any_cached_coords_for_wsi(Config.get_uploads_dir(), wsi_id)
        if coords_file is None:
            missing_count += 1
            if len(missing_artifacts) < sample_limit:
                missing_artifacts.append({
                    "wsi_id": wsi_id,
                    "artifact": "coords_file",
                    "path": f"[cache lookup] coords.h5 for {wsi_id}",
                })

    return missing_count, missing_artifacts


def _analysis_has_required_files(analysis_run_dir: Path) -> bool:
    if not analysis_run_dir.is_dir():
        return False
    return (
        (analysis_run_dir / "summary.json").exists()
        and (analysis_run_dir / "results.json").exists()
    )


def _iter_complete_analysis_runs(analysis_dir: Path):
    if not analysis_dir.exists() or not analysis_dir.is_dir():
        return
    for item in sorted(analysis_dir.iterdir(), reverse=True):
        if _analysis_has_required_files(item):
            yield item


def _read_latest_complete_analysis_sync(analysis_dir: Path) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    for item in _iter_complete_analysis_runs(analysis_dir):
        with open(item / "summary.json", 'r') as f:
            return item.name, json.load(f)
    return None, None


def _analysis_requires_training_metrics(task_type: str, charts: Optional[List[str]], is_kfold: bool) -> bool:
    if is_kfold:
        return True

    requested_charts = set(charts or [])
    required_charts = {"loss_curve"}
    if task_type in ("segmentation", "patch_segmentation"):
        required_charts.update({"iou_curve", "dice_curve"})
    return bool(requested_charts & required_charts)


def _missing_training_metrics_message(task_id: str, resources: Dict[str, Any], charts: Optional[List[str]], is_kfold: bool) -> str:
    requested_parts = []
    requested_charts = sorted(set(charts or []))
    if requested_charts:
        requested_parts.append(f"requested charts={', '.join(requested_charts)}")
    if is_kfold:
        requested_parts.append("task uses k-fold training summary")
    requested_detail = "; ".join(requested_parts) if requested_parts else "analysis requires training metrics"
    metrics_path = resources.get("metrics_file") or "metrics.json"
    return (
        f"Training metrics artifact is missing for task {task_id}: {metrics_path}. "
        f"ResultsViewer cannot build this analysis because {requested_detail}. "
        "Please restore metrics.json or rerun training."
    )


async def _enrich_single_task_resources(task_id: str, db: AsyncSession, base_resources: Dict[str, Any]) -> Dict[str, Any]:
    resources = dict(base_resources)
    resources.setdefault("has_complete_ai_results", resources.get("has_ai_results", False))
    resources.setdefault("missing_ai_result_artifacts", [])
    resources.setdefault("missing_ai_result_artifact_count", 0)
    resources.setdefault("has_training_metrics", False)
    resources.setdefault("metrics_file", None)
    resources.setdefault("missing_training_artifacts", [])

    task_meta_query = (
        select(DataGroup.task_type, DataGroup.data_type)
        .select_from(TrainingTask)
        .join(DataGroup, TrainingTask.group_id == DataGroup.group_id)
        .where(TrainingTask.task_id == task_id)
    )
    task_meta = (await db.execute(task_meta_query)).first()
    if not task_meta:
        return resources

    task_type, data_type = task_meta

    trained_model_query = (
        select(TrainedModel.model_id, TrainedModel.model_path, TrainedModel.config_path)
        .where(TrainedModel.task_id == task_id)
        .where(TrainedModel.is_active == True)
    )
    trained_model_rows = (await db.execute(trained_model_query)).all()
    trained_model = None
    if trained_model_rows:
        trained_model = {
            "model_id": trained_model_rows[0][0],
            "model_path": trained_model_rows[0][1],
            "config_path": trained_model_rows[0][2],
        }

    metrics_candidates = _candidate_metrics_paths(task_id, trained_model)
    metrics_file = next((path for path in metrics_candidates if path.exists()), None)
    resources["metrics_file"] = str(metrics_file or metrics_candidates[0]) if metrics_candidates else None
    resources["has_training_metrics"] = metrics_file is not None
    if not resources["has_training_metrics"]:
        resources["missing_training_artifacts"] = [resources["metrics_file"] or "metrics.json"]

    if resources.get("ai_results_count", 0) <= 0:
        resources["has_ai_results"] = False
        resources["has_complete_ai_results"] = False
        return resources

    ai_result_rows = (
        await db.execute(
            select(AIResult.wsi_id, AIResult.extra_metadata)
            .where(AIResult.task_id == task_id)
        )
    ).all()

    missing_artifacts: List[Dict[str, Any]] = []
    missing_count = 0
    for wsi_id, extra_metadata in ai_result_rows:
        row_missing_count, row_missing_artifacts = _collect_missing_ai_result_artifacts(
            task_id=task_id,
            task_type=task_type,
            data_type=data_type,
            wsi_id=wsi_id,
            extra_metadata=extra_metadata,
            sample_limit=max(0, 10 - len(missing_artifacts)),
        )
        missing_count += row_missing_count
        if row_missing_artifacts:
            missing_artifacts.extend(row_missing_artifacts)

    resources["missing_ai_result_artifact_count"] = missing_count
    resources["missing_ai_result_artifacts"] = missing_artifacts
    resources["has_complete_ai_results"] = missing_count == 0
    if missing_count > 0:
        resources["has_ai_results"] = False

    return resources


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


def _build_owned_ai_result_filter(user: User):
    """
    Restrict AI result visibility to the current user's own derived artifacts.

    Some historical AIResult rows do not have user_id populated, so we also fall
    back to task ownership for both inference tasks (AITask) and training tasks.
    """
    user_id = str(user.id)
    owned_ai_task_ids = select(AITask.task_id).where(AITask.user_id == user_id)
    owned_training_task_ids = select(TrainingTask.task_id).where(TrainingTask.user_id == user_id)
    return or_(
        AIResult.user_id == user_id,
        AIResult.task_id.in_(owned_ai_task_ids),
        AIResult.task_id.in_(owned_training_task_ids),
    )



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

    Returns:
        List of results with predictions and ground truth labels
    """
    # Query results with WSI info
    query = (
        select(AIResult, WSISlide)
        .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
    )
    # Filter to the current user's own derived results if not admin.
    if not user.is_admin():
        query = query.where(_build_owned_ai_result_filter(user))
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
    # Filter to the current user's own derived results if not admin.
    if not user.is_admin():
        query = query.where(_build_owned_ai_result_filter(user))
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

    NOTE: ai_results_count counts results for test set WSIs (when test set is
    defined) or all WSIs. has_ai_results uses > 0 check because some WSIs may
    be skipped during patch extraction (no valid tissue patches).

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

    # Step 1.5: Count test WSIs per task (for results viewer display / completeness check)
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

    # Step 1.6: For case-level tasks, count distinct test case_ids
    test_case_count_by_task = {}
    test_case_level_task_ids = [tid for tid in tasks_with_test_set if task_aggregation_levels.get(tid) == "case"]
    if test_case_level_task_ids:
        test_case_count_query = (
            select(
                TrainingTaskWSI.task_id,
                func.count(func.distinct(WSISlide.case_id)).label('count')
            )
            .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(TrainingTaskWSI.task_id.in_(test_case_level_task_ids))
            .where(TrainingTaskWSI.split == "test")
            .group_by(TrainingTaskWSI.task_id)
        )
        test_case_count_result = await db.execute(test_case_count_query)
        test_case_count_by_task = {row[0]: row[1] for row in test_case_count_result.all()}

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

    # Step 4: Query TrainedModel table for all tasks (covers all task types including segmentation)
    trained_model_query = (
        select(TrainedModel.task_id, TrainedModel.model_id, TrainedModel.model_path)
        .where(TrainedModel.task_id.in_(task_ids))
        .where(TrainedModel.is_active == True)
    )
    trained_model_result = await db.execute(trained_model_query)
    trained_models_by_task = {}
    for row in trained_model_result.all():
        # Keep the first (most recent) model per task
        if row[0] not in trained_models_by_task:
            trained_models_by_task[row[0]] = {"model_id": row[1], "model_path": row[2]}

    # Step 4b: Check features and models for each task (file system, but minimal operations)
    models_dir = uploads_dir / "models"
    model_dirs_cache = []
    if models_dir.exists():
        model_dirs_cache = [d for d in models_dir.iterdir() if d.is_dir()]

    for task_id in task_ids:
        data_type = task_data_types.get(task_id, "wsi")
        is_patch_task = data_type == "patch"

        # Check features (not needed for patch classification/segmentation)
        if is_patch_task:
            # Patch tasks don't store pre-extracted features
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

        # Fallback: check TrainedModel table (covers segmentation models
        # whose checkpoints live outside the models/ directory)
        if not has_model and task_id in trained_models_by_task:
            tm = trained_models_by_task[task_id]
            model_path = Path(tm["model_path"])
            if model_path.exists():
                has_model = True
                model_id = tm["model_id"]

        # Get AI results count from batch query
        ai_results_count = ai_results_by_task.get(task_id, 0)
        # Some WSIs may be skipped during patch extraction (no valid tissue),
        # so ai_results_count can be less than total WSI count.
        # Use > 0 to check if inference has been run at all.
        has_ai_results = ai_results_count > 0

        # Get total WSI count and case count for this task
        total_wsi_count = total_wsi_by_task.get(task_id, 0)
        total_case_count = total_case_by_task.get(task_id, 0)
        aggregation_level = task_aggregation_levels.get(task_id, "file")
        test_wsi_count = test_wsi_count_by_task.get(task_id, 0)
        test_case_count = test_case_count_by_task.get(task_id, 0)
        test_display_count = test_case_count if aggregation_level == "case" else test_wsi_count

        results[task_id] = {
            "has_features": has_features,
            "has_model": has_model,
            "model_id": model_id,
            "has_ai_results": has_ai_results,
            "ai_results_count": ai_results_count,
            "total_wsi_count": total_wsi_count,
            "total_case_count": total_case_count,
            "test_wsi_count": test_wsi_count,
            "test_case_count": test_case_count,
            "test_display_count": test_display_count,
            "aggregation_level": aggregation_level,
        }

    return results


async def _check_task_resources(task_id: str, db: AsyncSession) -> dict:
    """Check if task has features, model, and ai_results.

    NOTE: This is a wrapper around _check_task_resources_batch for single task use.
    For multiple tasks, use _check_task_resources_batch directly for better performance.
    """
    results = await _check_task_resources_batch([task_id], db)
    base_resources = results.get(task_id, {
        "has_features": False,
        "has_model": False,
        "model_id": None,
        "has_ai_results": False,
        "ai_results_count": 0,
        "total_wsi_count": 0,
        "total_case_count": 0,
        "aggregation_level": "file",
    })
    return await _enrich_single_task_resources(task_id, db, base_resources)


@router.get("/tasks")
async def get_analysis_tasks(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of tasks available for analysis.
    Users see only their own tasks, admin sees all.

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
    # Filter to the current user's own tasks if not admin.
    if not user.is_admin():
        query = query.where(TrainingTask.user_id == str(user.id))
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
    source_dataset_ids = await TrainingTaskRepository.get_source_dataset_ids_batch(db, task_ids)

    for task in tasks:
        resources = all_resources.get(task.task_id, {
            "has_features": False,
            "has_model": False,
            "model_id": None,
            "has_ai_results": False,
            "ai_results_count": 0,
            "total_wsi_count": 0,
            "total_case_count": 0,
            "test_wsi_count": 0,
            "test_case_count": 0,
            "test_display_count": 0,
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
        has_analysis = False
        if analysis_dir.exists():
            for item in _iter_complete_analysis_runs(analysis_dir):
                has_analysis = True
                break

        # Extract feature_extractor and split_strategy from preprocessing_config
        feature_extractor = None
        is_segmentation_task = task_type in ("segmentation", "patch_segmentation")
        is_kfold = False
        if task.preprocessing_config and isinstance(task.preprocessing_config, dict):
            feature_extractor = task.preprocessing_config.get("feature_extractor")
            # Check split strategy to determine if K-Fold training
            split_config = task.preprocessing_config.get("split_config", {})
            is_kfold = not is_segmentation_task and split_config.get("strategy") == "k_fold"

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
            "test_wsi_count": resources["test_wsi_count"],
            "test_case_count": resources["test_case_count"],
            "test_display_count": resources["test_display_count"],
            "display_count": display_count,  # Count based on aggregation level
            "wsi_ids": all_wsi_ids_by_task.get(task.task_id, []),  # For WSI overlap detection
            "classes": task.classes,
            "model_config": task.model_config,
            "source_dataset_id": source_dataset_ids.get(task.task_id),
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
    task, db: AsyncSession, progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
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

    missing_artifacts = resources.get("missing_ai_result_artifacts") or []
    if missing_artifacts:
        logger.info(
            f"AI result artifacts incomplete for task {task_id}, rerunning GPU inference. "
            f"examples={missing_artifacts[:3]}"
        )
    else:
        logger.info(f"AI results missing for task {task_id}, running GPU inference...")

    if progress_callback:
        await progress_callback(0.05)  # Starting inference

    # Route to appropriate inference handler based on data_type and task_type
    if data_type == "patch":
        if task_type in ("segmentation", "patch_segmentation"):
            await _run_inference_patch_segmentation(task, wsi_ids, resources, db, progress_callback, assigned_device=assigned_device)
        else:
            await _run_inference_patch_classification(task, wsi_ids, resources, db, progress_callback, assigned_device=assigned_device)
    elif task_type in ("wsi_survival", "survival"):
        await _run_inference_wsi_survival(task, wsi_ids, resources, db, progress_callback, assigned_device=assigned_device)
    else:
        # Default: WSI classification
        await _run_inference_wsi_classification(task, wsi_ids, resources, db, progress_callback, assigned_device=assigned_device)

    logger.info(f"GPU inference completed for task {task_id}")
    if progress_callback:
        await progress_callback(1.0)
    return True


async def _run_inference_wsi_classification(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
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
    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")
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
                        ensure_recommendation_preview_cache(wsi_id, att_file, Config.get_uploads_dir())
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
                    ensure_recommendation_preview_cache(wsi_id, att_file, Config.get_uploads_dir())
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
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
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
    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(ckpt_path, map_location=device)

    extractor_name = checkpoint.get("extractor_name", config.get("extractor", "resnet50"))
    extractor_dim = checkpoint["extractor_dim"]
    num_classes = checkpoint["num_classes"]

    # Build model: extractor + linear probe
    try:
        extractor = get_extractor(extractor_name, pretrained=True)
    except (FileNotFoundError, OSError, Exception) as exc:
        raise RuntimeError(
            f"Failed to load feature extractor '{extractor_name}'. "
            f"Please ensure the model weights are downloaded locally. "
            f"Original error: {exc}"
        ) from exc
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


def _get_seg_grad_cam_target_layers(model):
    """Determine the target layer for Grad-CAM in a segmentation model.

    Supports:
    - FMSegmentationModel: uses last decoder block (before head)
    - SMP models (UNet, etc.): uses last decoder block
    """
    import torch.nn as nn
    from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel

    if isinstance(model, FMSegmentationModel):
        # FM model: decoder is nn.Sequential of _DecoderBlock
        return [model.decoder[-1]]

    # SMP models: try common decoder structures
    if hasattr(model, 'decoder'):
        dec = model.decoder
        if hasattr(dec, 'blocks') and len(dec.blocks) > 0:
            return [dec.blocks[-1]]
        # Fallback: last child of decoder
        children = list(dec.children())
        if children:
            return [children[-1]]

    # Last resort: find the last Conv2d layer before segmentation_head
    if hasattr(model, 'segmentation_head'):
        return [model.segmentation_head[0]]

    raise ValueError("Cannot determine Grad-CAM target layer for segmentation model")


def _build_segmentation_per_image_metrics(
    iou_per_class,
    dice_per_class,
    precision_per_class,
    recall_per_class,
    accuracy,
    precision,
    recall,
) -> Dict[str, Any]:
    iou_flat = iou_per_class.squeeze(0) if getattr(iou_per_class, "dim", lambda: 0)() > 1 else iou_per_class
    dice_flat = dice_per_class.squeeze(0) if getattr(dice_per_class, "dim", lambda: 0)() > 1 else dice_per_class
    precision_flat = precision_per_class.squeeze(0) if getattr(precision_per_class, "dim", lambda: 0)() > 1 else precision_per_class
    recall_flat = recall_per_class.squeeze(0) if getattr(recall_per_class, "dim", lambda: 0)() > 1 else recall_per_class
    num_classes = int(iou_flat.numel()) if hasattr(iou_flat, "numel") else len(iou_flat)
    primary_iou_key = "miou" if num_classes > 1 else "iou"

    precision_value = precision.item()
    recall_value = recall.item()
    f1_value = (2 * precision_value * recall_value / (precision_value + recall_value)) if (precision_value + recall_value) > 0 else 0.0

    return {
        primary_iou_key: iou_flat.mean().item(),
        "iou_per_class": iou_flat.tolist() if iou_flat.dim() > 0 else [iou_flat.item()],
        "dice": dice_flat.mean().item(),
        "dice_per_class": dice_flat.tolist() if dice_flat.dim() > 0 else [dice_flat.item()],
        "f1": f1_value,
        "f1_per_class": dice_flat.tolist() if dice_flat.dim() > 0 else [dice_flat.item()],
        "accuracy": accuracy.item(),
        "precision": precision_value,
        "precision_per_class": precision_flat.tolist() if precision_flat.dim() > 0 else [precision_flat.item()],
        "recall": recall_value,
        "recall_per_class": recall_flat.tolist() if recall_flat.dim() > 0 else [recall_flat.item()],
    }



async def _run_inference_patch_segmentation(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
):
    """
    Run GPU inference to generate per-WSI AI results for patch segmentation task.

    Loads the segmentation model from TrainedModel checkpoint, runs inference on
    each image, computes per-image segmentation metrics (IoU, Dice, etc.) when
    ground truth annotations are available, and saves AIResult records to the
    database — achieving parity with patch classification tasks.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import numpy as np
    import segmentation_models_pytorch as smp
    from backend.ai.segmentors import Segmentor
    from backend.ai.utils.segmentation_dataset import SegmentationDataset, get_transforms
    from backend.database.repositories import AIResultRepository, TrainedModelRepository
    from PIL import Image
    from torchvision.transforms import v2

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Load model from TrainedModel table
    trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
    if not trained_models:
        raise ValueError(f"No trained model found for segmentation task {task_id}")
    trained_model = trained_models[0]  # Most recent
    checkpoint_path = trained_model.model_path
    class_names = _normalize_label_names(task.classes or trained_model.classes or [])

    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")

    logger.info(f"Loading segmentation model from {checkpoint_path}")

    def _load_model():
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        config = checkpoint.get("config", {})
        architecture = config.get("architecture", "unet")
        backbone = config.get("backbone", "resnet50")
        dataset_cfg = config.get("dataset", {})
        in_channels = dataset_cfg.get("channels", 3)
        num_classes = dataset_cfg.get("classes", 1)

        segmentor = Segmentor(
            architecture=architecture,
            encoder_name=backbone,
            in_channels=in_channels,
            classes=num_classes,
        )
        model = segmentor.build_model()
        if checkpoint.get("is_fm", False):
            from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel
            model.load_decoder_state_dict(checkpoint["model_state_dict"])
        else:
            model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(device)
        model.eval()

        norm_mean, norm_std = segmentor.get_normalization_params()
        return model, config, norm_mean, norm_std, num_classes

    model, model_config, norm_mean, norm_std, num_classes = await asyncio.to_thread(_load_model)
    if not class_names:
        class_names = _normalize_label_names(
            (model_config.get("dataset") or {}).get("class_names", [])
        )

    if progress_callback:
        await progress_callback(0.1)

    # Build image paths and labels from WSI records
    image_paths = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi and wsi.wsi_path:
            image_paths[wsi_id] = wsi.wsi_path

    if not image_paths:
        raise ValueError(f"No image paths found for segmentation task {task_id}")

    # Delete old AIResult records to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Discover COCO annotations for ground truth metrics
    def _discover_annotations():
        from pathlib import Path as _Path
        image_dirs = set()
        for img_path in image_paths.values():
            image_dirs.add(str(_Path(img_path).parent))
        for img_dir in image_dirs:
            dir_path = _Path(img_dir)
            for search_dir in [dir_path, dir_path.parent]:
                if not search_dir.exists():
                    continue
                for json_file in search_dir.glob("*.json"):
                    try:
                        with open(json_file, 'r') as f:
                            data = json.load(f)
                        if "images" in data and "annotations" in data and "categories" in data:
                            return str(json_file), img_dir
                    except Exception:
                        continue
        return None, None

    annotations_path, annotations_img_dir = await asyncio.to_thread(_discover_annotations)
    has_annotations = annotations_path is not None

    if has_annotations:
        logger.info(f"Found COCO annotations: {annotations_path}")
    else:
        logger.info("No COCO annotations found — running inference only (no per-image metrics)")

    # Run inference
    val_transform = get_transforms("val", normalization_mean=norm_mean, normalization_std=norm_std)
    ai_results_root = uploads_dir / "ai_results"
    results_saved = 0
    total_items = len(image_paths)

    def _run_inference():
        nonlocal results_saved
        from pathlib import Path as _Path

        all_results = []

        # Build ground truth dataset if annotations available
        gt_dataset = None
        gt_filename_map = {}
        if has_annotations:
            try:
                gt_dataset = SegmentationDataset(
                    img_dir=annotations_img_dir,
                    annotations_path=annotations_path,
                    transform=val_transform,
                )
                for idx, item in enumerate(gt_dataset.image_items):
                    fname = _Path(item["image"]).name
                    gt_filename_map[fname] = idx
            except Exception as e:
                logger.warning(f"Failed to load annotation dataset: {e}")
                gt_dataset = None

        with torch.no_grad():
            for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
                try:
                    img = Image.open(img_path).convert("RGB")
                    original_size = img.size  # (W, H)
                    img_filename = _Path(img_path).name

                    # Prepare image tensor
                    img_tensor = v2.ToImage()(img)
                    img_tensor = v2.ToDtype(torch.float32, scale=True)(img_tensor)
                    img_tensor = v2.Resize((1024, 1024), antialias=True)(img_tensor)
                    img_tensor = v2.Normalize(
                        mean=norm_mean or [0.485, 0.456, 0.406],
                        std=norm_std or [0.229, 0.224, 0.225]
                    )(img_tensor)
                    img_tensor = img_tensor.unsqueeze(0).to(device)

                    # Run inference
                    outputs = model(img_tensor)
                    preds_prob = torch.sigmoid(outputs)
                    preds_binary = (preds_prob > 0.5).float()

                    # Compute per-image metrics if ground truth is available
                    per_image_metrics = {}
                    has_gt = False
                    if gt_dataset is not None and img_filename in gt_filename_map:
                        gt_idx = gt_filename_map[img_filename]
                        _, gt_mask = gt_dataset[gt_idx]
                        gt_mask = gt_mask.unsqueeze(0).to(device)
                        has_gt = True

                        tp, fp, fn, tn = smp.metrics.get_stats(
                            preds_binary.long().cpu(), gt_mask.long().cpu(),
                            mode='multilabel', threshold=None
                        )
                        iou_per_class = smp.metrics.iou_score(tp, fp, fn, tn, reduction='none')
                        dice_per_class = smp.metrics.f1_score(tp, fp, fn, tn, reduction='none')
                        precision_per_class = smp.metrics.precision(tp, fp, fn, tn, reduction='none')
                        recall_per_class = smp.metrics.recall(tp, fp, fn, tn, reduction='none')
                        accuracy = smp.metrics.accuracy(tp, fp, fn, tn, reduction='micro')
                        precision_val = smp.metrics.precision(tp, fp, fn, tn, reduction='micro')
                        recall_val = smp.metrics.recall(tp, fp, fn, tn, reduction='micro')

                        per_image_metrics = _build_segmentation_per_image_metrics(
                            iou_per_class,
                            dice_per_class,
                            precision_per_class,
                            recall_per_class,
                            accuracy,
                            precision_val,
                            recall_val,
                        )

                    # Save prediction mask
                    wsi_result_dir = ai_results_root / wsi_id
                    wsi_result_dir.mkdir(parents=True, exist_ok=True)

                    # Keep segmentation artifacts streamed to disk during inference to avoid
                    # retaining many large masks/CAMs in memory. Store binary masks as uint8
                    # to reduce write volume without changing viewer semantics.
                    pred_mask = preds_binary.squeeze(0).to(dtype=torch.uint8).cpu().numpy()
                    mask_file = wsi_result_dir / f"train_{task_id}_pred_mask.npy"
                    np.save(mask_file, pred_mask)

                    # Extract Grad-CAM for segmentation model
                    try:
                        from pytorch_grad_cam import GradCAM
                        from pytorch_grad_cam.utils.model_targets import SemanticSegmentationTarget

                        # Determine target layer based on model type
                        target_layers = _get_seg_grad_cam_target_layers(model)

                        # Use dominant predicted class for Grad-CAM target
                        pred_mask_for_cam = pred_mask.astype(np.float32, copy=False)  # (C, H, W)
                        if pred_mask_for_cam.ndim == 3 and pred_mask_for_cam.shape[0] > 1:
                            dominant_class = int(pred_mask_for_cam.sum(axis=(1, 2)).argmax())
                        else:
                            dominant_class = 0
                        sem_mask = pred_mask_for_cam[dominant_class]  # (H, W) binary

                        targets = [SemanticSegmentationTarget(dominant_class, sem_mask)]
                        cam_input = img_tensor.clone().detach().requires_grad_(True)

                        with torch.enable_grad():
                            with GradCAM(model=model, target_layers=target_layers) as grad_cam:
                                cam_map = grad_cam(input_tensor=cam_input, targets=targets)
                        cam_map = cam_map[0]  # (H, W)
                    except Exception as cam_err:
                        logger.warning(f"Grad-CAM extraction failed for {wsi_id}: {cam_err}")
                        cam_map = np.zeros((img_tensor.shape[2], img_tensor.shape[3]), dtype=np.float32)

                    cam_file = wsi_result_dir / f"train_{task_id}_cam.npy"
                    np.save(cam_file, cam_map)

                    # Save result JSON
                    result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "task_type": "patch_segmentation",
                        "aggregation_level": "file",
                        "num_classes": num_classes,
                        "class_names": class_names,
                        "image_size": list(original_size),
                        "pred_mask_file": str(mask_file),
                        "cam_file": str(cam_file),
                        "cam_size": list(cam_map.shape),
                        "has_ground_truth": has_gt,
                        "metrics": per_image_metrics,
                    }
                    result_file = wsi_result_dir / f"train_{task_id}_result.json"
                    with open(result_file, 'w', encoding='utf-8') as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)

                    all_results.append({
                        "wsi_id": wsi_id,
                        "metrics": per_image_metrics,
                        "has_ground_truth": has_gt,
                        "class_names": class_names,
                        "pred_mask_file": str(mask_file),
                        "result_file": str(result_file),
                    })
                    results_saved += 1

                except Exception as e:
                    logger.warning(f"Failed to process {wsi_id}: {e}")
                    continue

        return all_results

    all_results = await asyncio.to_thread(_run_inference)

    if progress_callback:
        await progress_callback(0.8)

    # Save to database in batches to reduce write-transaction churn.
    db_records = []
    for r in all_results:
        db_records.append({
            "wsi_id": r["wsi_id"],
            "task_id": task_id,
            "pred": "segmentation",
            "probs": r["metrics"] if r["metrics"] else {},
            "extra_metadata": {
                "task_type": "patch_segmentation",
                "aggregation_level": "file",
                "has_ground_truth": r["has_ground_truth"],
                "class_names": r.get("class_names", []),
                "metrics": r["metrics"],
                "pred_mask_file": r["pred_mask_file"],
                "result_file": r["result_file"],
            }
        })

    if db_records:
        await AIResultRepository.bulk_create(db, db_records, batch_size=100)

    await db.commit()

    logger.info(f"Generated AI results for patch segmentation task {task_id}: {results_saved}/{total_items} images")

    if progress_callback:
        await progress_callback(1.0)

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "patch_segmentation",
        "wsi_count": results_saved,
    }


async def _run_inference_wsi_survival(
    task, wsi_ids: List[str], resources: dict, db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
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
    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")
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
                    ensure_recommendation_preview_cache(wsi_id, att_file, Config.get_uploads_dir())
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
                ensure_recommendation_preview_cache(wsi_id, att_file, Config.get_uploads_dir())
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
    elevated_dataset_ids = set()
    if not user.is_admin():
        elevated_dataset_ids = set(await _get_elevated_dataset_ids(user, db) or [])

    result = []
    for ds in datasets:
        dg = ds.data_group
        if not dg:
            continue

        # Skip external_validation datasets - only show real datasets
        if dg.task_type == "external_validation":
            continue

        dataset_id = ds.dataset_id

        if not user.is_admin():
            owns_dataset = ds.user_id == str(user.id)
            has_temp_access = dataset_id in elevated_dataset_ids
            if not owns_dataset and not has_temp_access:
                continue

        # Get WSI IDs
        wsi_ids = await DatasetRepository.get_wsi_ids(db, dataset_id)
        if not wsi_ids:
            continue  # Skip empty datasets

        # Get distinct labels (names + count, for classification matching)
        distinct_labels = await DatasetRepository.get_distinct_labels(db, dataset_id)
        distinct_label_count = len(distinct_labels)

        # For WSI datasets, scan feature cache to find which extractors have features.
        # This replaces the old feature_extracted DB column check which was inconsistent
        # with how the chat context detects features (disk-based).
        # Datasets without any features on disk for WSI are skipped.
        available_feature_extractors: list = []
        if dg.data_type != "patch" and wsi_ids:
            first_wsi_id = wsi_ids[0]
            features_root = Config.get_uploads_dir() / "features"
            if features_root.exists():
                for extractor_dir in features_root.iterdir():
                    if extractor_dir.is_dir():
                        for params_hash_dir in extractor_dir.iterdir():
                            if params_hash_dir.is_dir():
                                feat_file = params_hash_dir / f"{first_wsi_id}.pt"
                                if feat_file.exists():
                                    available_feature_extractors.append(extractor_dir.name)
                                    break  # Found for this extractor, move to next
            # WSI datasets must have at least one feature extractor available
            if not available_feature_extractors:
                continue

        # Get case count for case-level datasets
        total_wsi_count = len(wsi_ids)
        total_case_count = total_wsi_count
        if dg.aggregation_level == "case":
            case_map = await DatasetRepository.get_wsi_case_ids(db, dataset_id)
            total_case_count = len(set(case_map.values()))

        # Determine display count based on aggregation_level
        display_count = total_case_count if dg.aggregation_level == "case" else total_wsi_count
        segmentation_labels: List[str] = []
        if dg.task_type in ("segmentation", "patch_segmentation"):
            coco_categories = await WSIRepository._get_coco_categories_for_dataset(db, dataset_id)
            segmentation_labels = _extract_segmentation_label_names(coco_categories)

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
            "distinct_labels": sorted(distinct_labels),
            "segmentation_labels": segmentation_labels,
            "available_feature_extractors": available_feature_extractors,
            "wsi_ids": wsi_ids,
        })

    return {"items": result, "total": len(result)}


class ExternalValidationRequest(BaseModel):
    """Request for external validation - use a trained model on a dataset."""
    model_id: str  # TrainedModel ID from the models table
    dataset_id: str   # Dataset whose WSIs will be used for validation
    # Analysis options
    metrics: Optional[List[str]] = None  # Metrics to compute (default: accuracy, precision, recall, f1, auc, weighted_kappa)
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

    # Check ownership of the model via its training task.
    model_task = await TrainingTaskRepository.get_by_id(db, trained_model.task_id)
    if not model_task:
        raise HTTPException(status_code=404, detail=f"Model's training task not found: {trained_model.task_id}")
    await _require_task_access(
        user,
        model_task,
        db,
        owner_user_id=trained_model.user_id,
        forbidden_detail="You don't have permission to use this model",
    )

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

    def is_segmentation_task(task_type: str) -> bool:
        return task_type in ("segmentation", "patch_segmentation")

    model_task_type = model_data_group.task_type if model_data_group else "classification"
    target_task_type = target_data_group.task_type if target_data_group else "classification"

    model_is_classification = is_classification_task(model_task_type)
    target_is_classification = is_classification_task(target_task_type)
    model_is_survival = is_survival_task(model_task_type)
    target_is_survival = is_survival_task(target_task_type)
    model_is_segmentation = is_segmentation_task(model_task_type)
    target_is_segmentation = is_segmentation_task(target_task_type)

    if model_is_segmentation and not target_is_segmentation:
        raise HTTPException(
            status_code=400,
            detail=f"Task type mismatch: Segmentation model cannot validate non-segmentation data. "
                   f"Model type: '{model_task_type}', Target dataset type: '{target_task_type}'. "
                   f"Please select a segmentation dataset."
        )

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

    # 3. Validate class label name matching (for classification tasks)
    if model_is_classification and target_is_classification:
        model_classes = set(trained_model.classes) if trained_model.classes else set()
        dataset_labels = set(await DatasetRepository.get_distinct_labels(db, req.dataset_id))
        if model_classes != dataset_labels:
            missing_in_dataset = model_classes - dataset_labels
            extra_in_dataset = dataset_labels - model_classes
            detail_parts = ["Label mismatch between model and dataset."]
            if missing_in_dataset:
                detail_parts.append(f"Model classes not in dataset: {sorted(missing_in_dataset)}")
            if extra_in_dataset:
                detail_parts.append(f"Dataset labels not in model: {sorted(extra_in_dataset)}")
            raise HTTPException(
                status_code=400,
                detail=" ".join(detail_parts),
            )

    if model_is_segmentation and target_is_segmentation:
        source_dataset_id = (
            await TrainingTaskRepository.get_source_dataset_ids_batch(db, [trained_model.task_id])
        ).get(trained_model.task_id)
        if not source_dataset_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot determine the source training dataset for this segmentation model. "
                       "External validation requires a source model trained on a single dataset.",
            )

        if source_dataset_id == req.dataset_id:
            raise HTTPException(
                status_code=400,
                detail="Target dataset must be different from the source training dataset for segmentation external validation.",
            )

        model_config = model_task.model_config if isinstance(model_task.model_config, dict) else {}
        task_architecture = str(model_config.get("architecture") or "").strip()
        task_backbone = str(model_config.get("backbone") or "").strip()
        saved_architecture = str(trained_model.aggregator or "").strip()
        saved_backbone = str(trained_model.feature_extractor or "").strip()

        if not task_architecture or not task_backbone or not saved_architecture or not saved_backbone:
            raise HTTPException(
                status_code=400,
                detail="Segmentation model architecture metadata is incomplete. "
                       "The source model must include both architecture and backbone metadata for external validation.",
            )

        if task_architecture != saved_architecture or task_backbone != saved_backbone:
            raise HTTPException(
                status_code=400,
                detail="Segmentation model metadata mismatch detected. "
                       f"Task config expects architecture/backbone '{task_architecture}/{task_backbone}', "
                       f"but stored model metadata is '{saved_architecture}/{saved_backbone}'.",
            )

        model_segmentation_labels = _normalize_label_names(model_task.classes or trained_model.classes or [])
        target_segmentation_labels = _extract_segmentation_label_names(
            await WSIRepository._get_coco_categories_for_dataset(db, req.dataset_id)
        )

        if not model_segmentation_labels or not target_segmentation_labels:
            raise HTTPException(
                status_code=400,
                detail="Segmentation label metadata is incomplete. "
                       "Both the source model and target dataset must define labels for external validation.",
            )

        if model_segmentation_labels != target_segmentation_labels:
            missing_in_dataset = sorted(set(model_segmentation_labels) - set(target_segmentation_labels))
            extra_in_dataset = sorted(set(target_segmentation_labels) - set(model_segmentation_labels))
            detail_parts = ["Segmentation label mismatch between source model and target dataset."]
            if missing_in_dataset:
                detail_parts.append(f"Model labels not in dataset: {missing_in_dataset}")
            if extra_in_dataset:
                detail_parts.append(f"Dataset labels not in model: {extra_in_dataset}")
            raise HTTPException(status_code=400, detail=" ".join(detail_parts))

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
    incomplete_existing_examples: List[Dict[str, Any]] = []

    def _check_existing_results():
        """Check for existing external validation results."""
        nonlocal existing_results_count, existing_validation_id, incomplete_existing_examples
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
                            validation_task_id = result_data.get("validation_task_id")
                            if not validation_task_id and result_file.name.endswith("_result.json"):
                                validation_task_id = result_file.name[:-len("_result.json")]

                            result_metadata = dict(result_data)
                            result_metadata["result_file"] = str(result_file)
                            derived_attention_file = _derive_companion_artifact_path(result_file, "_attention.npy")
                            if model_data_type != "patch" and not result_metadata.get("attention_file") and derived_attention_file.exists():
                                result_metadata["attention_file"] = str(derived_attention_file)
                                result_metadata.setdefault("attention_type", "derived")

                            missing_count, missing_examples = _collect_missing_ai_result_artifacts(
                                task_id=validation_task_id or result_file.name[:-len("_result.json")],
                                task_type=str(result_data.get("task_type") or model_task_type),
                                data_type=model_data_type,
                                wsi_id=wsi_id,
                                extra_metadata=result_metadata,
                                sample_limit=1,
                            )
                            if missing_count > 0:
                                if len(incomplete_existing_examples) < 5 and missing_examples:
                                    incomplete_existing_examples.extend(missing_examples)
                                continue

                            existing_results_count += 1
                            # Extract validation_task_id from the result
                            if existing_validation_id is None:
                                existing_validation_id = validation_task_id
                            break  # Found result for this WSI, move to next
                    except Exception:
                        continue
        return existing_results_count, existing_validation_id

    await asyncio.to_thread(_check_existing_results)
    if incomplete_existing_examples:
        logger.info(
            f"Ignoring incomplete external validation cache entries for model {trained_model.task_id}: "
            f"examples={incomplete_existing_examples[:3]}"
        )

    # Prepare analysis options (use segmentation-specific defaults if needed)
    if model_is_segmentation:
        analysis_metrics = req.metrics or ["iou", "dice", "accuracy", "precision", "recall"]
        analysis_charts = req.charts or ["per_class_iou", "per_class_dice"]
    else:
        analysis_metrics = req.metrics or ["accuracy", "precision", "recall", "f1", "auc", "weighted_kappa"]
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
                for item in _iter_complete_analysis_runs(analysis_dir):
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
                submitted_by=str(user.id),
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
            "model_name": trained_model.model_name,  # Store model name for display
            "model_task_id": trained_model.task_id,
            "model_task_name": model_task.task_name,  # Store training task name for display
            "dataset_id": req.dataset_id,
            "dataset_name": target_dataset.name,  # Store dataset name for display
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
    # Filter to the current user's own tasks if not admin.
    if not user.is_admin():
        query = query.where(TrainingTask.user_id == str(user.id))
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
            for item in _iter_complete_analysis_runs(analysis_dir):
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


@router.get("/external-validation/{task_id}")
async def get_validation_progress(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the progress of an external validation task. Users can only view their own tasks."""
    task, _ = await _get_task_with_access(
        task_id,
        user,
        db,
        not_found_detail=f"Validation task not found: {task_id}",
        forbidden_detail="You don't have permission to view this task",
    )

    # Check if this is an external validation task via DataGroup
    task_data_group = task.data_group
    task_type = task_data_group.task_type if task_data_group else None
    if task_type != "external_validation":
        raise HTTPException(status_code=400, detail=f"Task {task_id} is not an external validation task")

    model_config = task.model_config or {}

    # Overlay file-based progress if available (more up-to-date than DB during inference).
    # This mirrors the pattern used in the training SSE endpoint (training.py lines 306-308).
    from backend.common.progress_store import get_progress
    file_prog = await get_progress(task_id)
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


async def _run_external_validation_patch_segmentation(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: str,
    logger_manager,
    update_task_progress,
):
    """Run external validation for patch segmentation models.

    Loads the segmentation model from checkpoint, discovers COCO annotations
    for the target dataset, runs inference, computes segmentation metrics
    (IoU, Dice, Accuracy, etc.), and saves per-image results.
    """
    import torch
    import numpy as np
    import segmentation_models_pytorch as smp
    from backend.ai.segmentors import Segmentor
    from backend.ai.utils.segmentation_dataset import SegmentationDataset, get_transforms
    from backend.database.repositories import WSIRepository, TrainedModelRepository
    from backend.database.database import safe_session
    from backend.common.progress_store import clear_progress

    uploads_dir = Config.get_uploads_dir()
    device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")

    try:
        # 1. Load model checkpoint and rebuild model
        async with safe_session() as db:
            trained_model = await TrainedModelRepository.get_by_id(db, model_id)
            if not trained_model:
                raise ValueError(f"Trained model not found: {model_id}")
            checkpoint_path = trained_model.model_path
            source_task = await TrainingTaskRepository.get_by_id(db, model_task_id) if model_task_id else None

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Patch segmentation: loading model from {checkpoint_path}")

        def _load_model():
            checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
            config = checkpoint.get("config", {})
            architecture = config.get("architecture", "unet")
            backbone = config.get("backbone", "resnet50")
            dataset_cfg = config.get("dataset", {})
            in_channels = dataset_cfg.get("channels", 3)
            num_classes = dataset_cfg.get("classes", 1)

            segmentor = Segmentor(
                architecture=architecture,
                encoder_name=backbone,
                in_channels=in_channels,
                classes=num_classes,
            )
            model = segmentor.build_model()
            # FM-based checkpoints contain only decoder+head weights;
            # the frozen backbone is already loaded by build_model().
            if checkpoint.get("is_fm", False):
                from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel
                model.load_decoder_state_dict(checkpoint["model_state_dict"])
            else:
                model.load_state_dict(checkpoint["model_state_dict"])
            model = model.to(device)
            model.eval()

            norm_mean, norm_std = segmentor.get_normalization_params()
            return model, config, norm_mean, norm_std, num_classes

        model, model_config, norm_mean, norm_std, num_classes = await asyncio.to_thread(_load_model)
        class_names = _normalize_label_names(
            (source_task.classes if source_task else None)
            or trained_model.classes
            or (model_config.get("dataset") or {}).get("class_names", [])
        )

        await update_task_progress(TaskStatus.PATCHING, 10)

        # 2. Get image paths and discover annotations from target dataset
        image_paths = {}
        task_user_id = None
        async with safe_session() as db:
            for wsi_id in wsi_ids:
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if wsi and wsi.wsi_path:
                    image_paths[wsi_id] = wsi.wsi_path

            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = str(task_record.user_id) if task_record and task_record.user_id else None

        if not image_paths:
            raise ValueError("No image paths found for target WSIs")

        # Discover COCO annotation files by scanning image directories
        def _discover_annotations():
            """Search for COCO-format JSON annotation files near image directories."""
            from pathlib import Path as _Path
            image_dirs = set()
            for img_path in image_paths.values():
                image_dirs.add(str(_Path(img_path).parent))

            for img_dir in image_dirs:
                dir_path = _Path(img_dir)
                # Search in the image directory and its parent
                search_dirs = [dir_path, dir_path.parent]
                for search_dir in search_dirs:
                    if not search_dir.exists():
                        continue
                    for json_file in search_dir.glob("*.json"):
                        try:
                            with open(json_file, 'r') as f:
                                data = json.load(f)
                            # Validate it's a COCO-format annotation file
                            if "images" in data and "annotations" in data and "categories" in data:
                                return str(json_file), img_dir
                        except Exception:
                            continue
            return None, None

        annotations_path, annotations_img_dir = await asyncio.to_thread(_discover_annotations)

        has_annotations = annotations_path is not None

        async with logger_manager.session() as (tl, _db):
            if has_annotations:
                await tl.info(f"Found COCO annotations: {annotations_path}")
            else:
                await tl.info("No COCO annotations found for target dataset — running inference only (no metrics)")
            await tl.info(f"Running inference on {len(image_paths)} images")

        await update_task_progress(TaskStatus.PATCHING, 20)

        # 3. Build dataset and run inference
        val_transform = get_transforms("val", normalization_mean=norm_mean, normalization_std=norm_std)
        ai_results_root = uploads_dir / "ai_results"
        results_saved = 0
        total_items = len(image_paths)

        def _run_inference():
            nonlocal results_saved
            from pathlib import Path as _Path
            from torch.cuda.amp import autocast
            from PIL import Image
            from torchvision.transforms import v2
            from torchvision import tv_tensors

            all_results = []

            # If we have annotations, build a SegmentationDataset for ground truth
            gt_dataset = None
            gt_filename_map = {}  # filename -> dataset index
            if has_annotations:
                try:
                    gt_dataset = SegmentationDataset(
                        img_dir=annotations_img_dir,
                        annotations_path=annotations_path,
                        transform=val_transform,
                    )
                    # Build filename -> index map
                    for idx, item in enumerate(gt_dataset.image_items):
                        fname = _Path(item["image"]).name
                        gt_filename_map[fname] = idx
                except Exception as e:
                    logger.warning(f"Failed to load annotation dataset: {e}")
                    gt_dataset = None

            with torch.no_grad():
                for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
                    try:
                        img = Image.open(img_path).convert("RGB")
                        original_size = img.size  # (W, H)
                        img_filename = _Path(img_path).name

                        # Prepare image tensor
                        img_tensor = v2.ToImage()(img)
                        img_tensor = v2.ToDtype(torch.float32, scale=True)(img_tensor)
                        img_tensor = v2.Resize((1024, 1024), antialias=True)(img_tensor)
                        img_tensor = v2.Normalize(
                            mean=norm_mean or [0.485, 0.456, 0.406],
                            std=norm_std or [0.229, 0.224, 0.225]
                        )(img_tensor)
                        img_tensor = img_tensor.unsqueeze(0).to(device)

                        # Run inference
                        outputs = model(img_tensor)
                        preds_prob = torch.sigmoid(outputs)
                        preds_binary = (preds_prob > 0.5).float()

                        # Compute per-image metrics if ground truth is available
                        per_image_metrics = {}
                        has_gt = False
                        if gt_dataset is not None and img_filename in gt_filename_map:
                            gt_idx = gt_filename_map[img_filename]
                            _, gt_mask = gt_dataset[gt_idx]
                            gt_mask = gt_mask.unsqueeze(0).to(device) if not isinstance(gt_mask, torch.Tensor) else gt_mask.unsqueeze(0).to(device)
                            has_gt = True

                            # Compute metrics using SMP
                            tp, fp, fn, tn = smp.metrics.get_stats(
                                preds_binary.long().cpu(), gt_mask.long().cpu(),
                                mode='multilabel', threshold=None
                            )
                            iou_per_class = smp.metrics.iou_score(tp, fp, fn, tn, reduction='none')
                            dice_per_class = smp.metrics.f1_score(tp, fp, fn, tn, reduction='none')
                            precision_per_class = smp.metrics.precision(tp, fp, fn, tn, reduction='none')
                            recall_per_class = smp.metrics.recall(tp, fp, fn, tn, reduction='none')
                            accuracy = smp.metrics.accuracy(tp, fp, fn, tn, reduction='micro')
                            precision = smp.metrics.precision(tp, fp, fn, tn, reduction='micro')
                            recall = smp.metrics.recall(tp, fp, fn, tn, reduction='micro')

                            per_image_metrics = _build_segmentation_per_image_metrics(
                                iou_per_class,
                                dice_per_class,
                                precision_per_class,
                                recall_per_class,
                                accuracy,
                                precision,
                                recall,
                            )

                        # Save prediction mask
                        wsi_result_dir = ai_results_root / wsi_id
                        wsi_result_dir.mkdir(parents=True, exist_ok=True)

                        # Keep segmentation artifacts streamed to disk during inference to avoid
                        # retaining many large masks/CAMs in memory. Store binary masks as uint8
                        # to reduce write volume without changing viewer semantics.
                        pred_mask = preds_binary.squeeze(0).to(dtype=torch.uint8).cpu().numpy()
                        mask_file = wsi_result_dir / f"extval_{task_id}_pred_mask.npy"
                        np.save(mask_file, pred_mask)

                        # Extract Grad-CAM for segmentation model
                        try:
                            from pytorch_grad_cam import GradCAM
                            from pytorch_grad_cam.utils.model_targets import SemanticSegmentationTarget

                            target_layers = _get_seg_grad_cam_target_layers(model)

                            pred_mask_for_cam = pred_mask.astype(np.float32, copy=False)  # (C, H, W)
                            if pred_mask_for_cam.ndim == 3 and pred_mask_for_cam.shape[0] > 1:
                                dominant_class = int(pred_mask_for_cam.sum(axis=(1, 2)).argmax())
                            else:
                                dominant_class = 0
                            sem_mask = pred_mask_for_cam[dominant_class]  # (H, W) binary

                            targets = [SemanticSegmentationTarget(dominant_class, sem_mask)]
                            cam_input = img_tensor.clone().detach().requires_grad_(True)

                            with torch.enable_grad():
                                with GradCAM(model=model, target_layers=target_layers) as grad_cam:
                                    cam_map = grad_cam(input_tensor=cam_input, targets=targets)
                            cam_map = cam_map[0]  # (H, W)
                        except Exception as cam_err:
                            logger.warning(f"Grad-CAM extraction failed for {wsi_id}: {cam_err}")
                            cam_map = np.zeros((img_tensor.shape[2], img_tensor.shape[3]), dtype=np.float32)

                        cam_file = wsi_result_dir / f"extval_{task_id}_cam.npy"
                        np.save(cam_file, cam_map)

                        # Save result JSON
                        result_data = {
                            "wsi_id": wsi_id,
                            "task_id": model_task_id,
                            "validation_source": dataset_id,
                            "validation_task_id": task_id,
                            "task_type": "patch_segmentation",
                            "aggregation_level": "file",
                            "num_classes": num_classes,
                            "class_names": class_names,
                            "image_size": list(original_size),
                            "pred_mask_file": str(mask_file),
                            "cam_file": str(cam_file),
                            "cam_size": list(cam_map.shape),
                            "has_ground_truth": has_gt,
                            "metrics": per_image_metrics,
                        }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        with open(result_file, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        all_results.append({
                            "wsi_id": wsi_id,
                            "metrics": per_image_metrics,
                            "has_ground_truth": has_gt,
                            "class_names": class_names,
                            "pred_mask_file": str(mask_file),
                            "result_file": str(result_file),
                        })
                        results_saved += 1

                    except Exception as e:
                        logger.warning(f"Failed to process {wsi_id}: {e}")
                        continue

            return all_results

        all_results = await asyncio.to_thread(_run_inference)

        # 4. Save to database
        async with safe_session() as db:
            from backend.database.repositories import AIResultRepository
            db_records = []
            for r in all_results:
                db_records.append({
                    "wsi_id": r["wsi_id"],
                    "task_id": task_id,
                    "user_id": task_user_id,
                    "pred": "segmentation",
                    "probs": r["metrics"] if r["metrics"] else {},
                    "extra_metadata": {
                        "validation_type": "external",
                        "model_task_id": model_task_id,
                        "dataset_id": dataset_id,
                        "aggregation_level": "file",
                        "task_type": "patch_segmentation",
                        "has_ground_truth": r["has_ground_truth"],
                        "class_names": r.get("class_names", []),
                        "metrics": r["metrics"],
                        "pred_mask_file": r["pred_mask_file"],
                        "result_file": r["result_file"],
                    }
                })

            if db_records:
                await AIResultRepository.bulk_create(db, db_records, batch_size=100)
            await db.commit()

        await clear_progress(task_id)
        await update_task_progress(TaskStatus.COMPLETED, 100, results_saved, results_saved)

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Patch segmentation external validation completed: {results_saved}/{total_items} images processed")

        # Auto-trigger analysis
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
            metrics=["iou", "dice", "accuracy", "precision", "recall"],
            charts=["per_class_iou", "per_class_dice"],
        )

    except Exception as e:
        import traceback
        logger.error(f"Patch segmentation external validation {task_id} failed: {e}\n{traceback.format_exc()}")
        try:
            await clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"Patch segmentation external validation failed: {e}")
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
            logger.warning(f"Patch seg ext-val {task_id}: VRAM cleanup failed: {cleanup_err}")


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
            try:
                _extractor = get_extractor(_extractor_name, pretrained=True)
            except (FileNotFoundError, OSError, Exception) as exc:
                raise RuntimeError(
                    f"Failed to load feature extractor '{_extractor_name}'. "
                    f"Please ensure the model weights are downloaded locally. "
                    f"Original error: {exc}"
                ) from exc
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

        await update_task_progress(TaskStatus.PATCHING, 10)

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

        await clear_progress(task_id)
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
            await clear_progress(task_id)
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

    # Minimum patches threshold for valid WSI (same as trainer.py)
    MIN_PATCHES_THRESHOLD = 100

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
        await update_task_progress(TaskStatus.PATCHING, 0)
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
                await _run_external_validation_patch_segmentation(
                    task_id=task_id,
                    model_task_id=model_task_id,
                    model_id=model_id,
                    dataset_id=dataset_id,
                    wsi_ids=wsi_ids,
                    assigned_device=assigned_device,
                    logger_manager=logger_manager,
                    update_task_progress=update_task_progress,
                )
                return

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
        # with resilient fallback: skip problematic WSIs instead of failing the entire task
        failed_wsi_ids = []  # Track WSIs that failed extraction
        failed_reasons = {}  # Track reasons for failure

        if missing_wsi_ids:
            async with logger_manager.session() as (tl, _db):
                await tl.info(f"Extracting features for {len(missing_wsi_ids)} WSIs missing from cache...")

            # Update status to EXTRACTING so frontend shows feature extraction stage
            await update_task_progress(TaskStatus.EXTRACTING, 5)
            await set_progress(task_id, 5)

            # Step 2a: Patch extraction via preprocessing service (with fallback logic)
            # This mirrors the training pipeline pattern from pipeline.py
            total_missing = len(missing_wsi_ids)
            coords_success_wsi_ids = []  # WSIs where coords extraction succeeded

            for idx, wsi_id in enumerate(missing_wsi_ids, 1):
                await asyncio.sleep(0)  # Yield to event loop

                # Retry logic: If preprocessing worker crashes, retry with backoff
                max_retries = 3
                coords_result = None
                coords_error = None

                for attempt in range(1, max_retries + 1):
                    try:
                        async with httpx.AsyncClient(timeout=600.0) as client:
                            response = await client.post(
                                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                                params={
                                    "level": level,
                                    "force_recompute": False,  # Allow cache reuse
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
                            coords_result = response.json()
                            break  # Success, exit retry loop
                    except (httpx.RemoteProtocolError, httpx.ConnectError) as retry_err:
                        # Worker crash (segfault) or connection refused (worker restarting)
                        coords_error = retry_err
                        if attempt < max_retries:
                            wait_secs = attempt * 3  # 3s, 6s, 9s backoff
                            async with logger_manager.session() as (tl, _db):
                                await tl.warning(
                                    f"[{idx}/{total_missing}] compute_patches attempt {attempt}/{max_retries} "
                                    f"failed for {wsi_id}: {type(retry_err).__name__}. "
                                    f"Retrying in {wait_secs}s (cached coords will be used on retry)...",
                                    metadata={"wsi_id": wsi_id, "attempt": attempt, "error": str(retry_err)}
                                )
                            await asyncio.sleep(wait_secs)
                        else:
                            # Final attempt failed
                            pass
                    except httpx.HTTPStatusError as http_err:
                        # HTTP error (4xx, 5xx) - likely not recoverable with retry
                        coords_error = http_err
                        try:
                            resp_body = http_err.response.text[:500] if http_err.response else ""
                        except Exception:
                            resp_body = "(unable to read response body)"
                        async with logger_manager.session() as (tl, _db):
                            await tl.warning(
                                f"[{idx}/{total_missing}] Patch extraction failed for {wsi_id}: "
                                f"HTTP {http_err.response.status_code if http_err.response else 'N/A'} - {resp_body}",
                                metadata={"wsi_id": wsi_id, "error": str(http_err), "response_body": resp_body}
                            )
                        break  # Don't retry HTTP errors
                    except Exception as e:
                        coords_error = e
                        break  # Unknown error, don't retry

                # Handle result
                if coords_result is not None:
                    num_patches = coords_result.get('num_patches', 0)
                    cached = coords_result.get('cached', False)

                    if num_patches == 0:
                        # 0 patches = no detectable tissue (even after adaptive seg_level fallback)
                        async with logger_manager.session() as (tl, _db):
                            await tl.warning(
                                f"[{idx}/{total_missing}] Skipping {wsi_id}: 0 patches extracted "
                                f"(no detectable tissue after adaptive seg_level fallback)",
                                metadata={"wsi_id": wsi_id, "num_patches": 0}
                            )
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = "0 patches (no detectable tissue)"
                    elif num_patches < MIN_PATCHES_THRESHOLD:
                        # Too few patches for reliable inference
                        async with logger_manager.session() as (tl, _db):
                            await tl.warning(
                                f"[{idx}/{total_missing}] Skipping {wsi_id}: only {num_patches} patches "
                                f"(minimum {MIN_PATCHES_THRESHOLD} required for reliable inference)",
                                metadata={"wsi_id": wsi_id, "num_patches": num_patches, "threshold": MIN_PATCHES_THRESHOLD}
                            )
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = f"low patches ({num_patches} < {MIN_PATCHES_THRESHOLD})"
                    else:
                        coords_success_wsi_ids.append(wsi_id)
                        async with logger_manager.session() as (tl, _db):
                            if cached:
                                await tl.info(
                                    f"[{idx}/{total_missing}] Coords cache hit for {wsi_id} ({num_patches} patches)",
                                    metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": True}
                                )
                            else:
                                await tl.info(
                                    f"[{idx}/{total_missing}] Extracted {num_patches} patches from {wsi_id}",
                                    metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": False}
                                )
                else:
                    # Coords extraction failed after retries
                    err_type = type(coords_error).__name__ if coords_error else "Unknown"
                    err_msg = str(coords_error) if coords_error else "Unknown error"
                    async with logger_manager.session() as (tl, _db):
                        await tl.error(
                            f"[{idx}/{total_missing}] Skipping {wsi_id}: coords extraction failed - [{err_type}] {err_msg}",
                            metadata={"wsi_id": wsi_id, "error": err_msg, "error_type": err_type}
                        )
                    failed_wsi_ids.append(wsi_id)
                    failed_reasons[wsi_id] = f"coords failed: {err_type}"

                # Update progress (5-30% for patch extraction)
                progress = 5 + int((idx / total_missing) * 25)
                await update_task_progress(TaskStatus.EXTRACTING, progress)
                await set_progress(task_id, progress)

            # Log summary of coords extraction
            async with logger_manager.session() as (tl, _db):
                await tl.info(
                    f"Patch extraction phase complete: {len(coords_success_wsi_ids)}/{total_missing} WSIs succeeded, "
                    f"{len(failed_wsi_ids)} failed/skipped",
                    metadata={
                        "success_count": len(coords_success_wsi_ids),
                        "failed_count": len(failed_wsi_ids),
                        "failed_wsi_ids": failed_wsi_ids[:20],  # Cap at 20 for log size
                    }
                )

            # Step 2b: Feature extraction via AI service (only for WSIs with valid coords)
            if coords_success_wsi_ids:
                feature_batch_size = preprocessing_config.get("feature_batch_size", 64)
                from gateway.pipeline import get_training_timeout
                timeout = get_training_timeout()

                async with logger_manager.session() as (tl, _db):
                    await tl.info(f"Calling AI service for feature extraction (using {feature_extractor}) on {len(coords_success_wsi_ids)} WSIs")

                await update_task_progress(TaskStatus.EXTRACTING, 30)
                await set_progress(task_id, 30)

                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(
                            f"{AI_SERVICE_URL}/api/ai/training/extract_features",
                            json={
                                "task_id": task_id,
                                "wsi_ids": coords_success_wsi_ids,
                                "feature_extractor": feature_extractor,
                                "batch_size": feature_batch_size,
                                "force_recompute": False,
                                "huggingface_token": "",
                                "preprocessing_config": preprocessing_config,
                                "device": assigned_device or "",
                            },
                        )
                        resp.raise_for_status()
                        feat_result = resp.json()
                        # Check for skipped WSIs from feature extraction
                        feat_skipped = feat_result.get("skipped_wsi_ids", []) if feat_result else []
                        if feat_skipped:
                            for skip_wsi in feat_skipped:
                                if skip_wsi not in failed_wsi_ids:
                                    failed_wsi_ids.append(skip_wsi)
                                    failed_reasons[skip_wsi] = "feature extraction skipped (low patches)"
                            async with logger_manager.session() as (tl, _db):
                                await tl.warning(
                                    f"AI service skipped {len(feat_skipped)} WSIs during feature extraction: {feat_skipped[:10]}",
                                    metadata={"skipped_count": len(feat_skipped), "skipped_wsi_ids": feat_skipped[:20]}
                                )
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
                    await tl.info(f"Feature extraction completed for {len(coords_success_wsi_ids)} WSIs")

                await update_task_progress(TaskStatus.EXTRACTING, 33)
                await set_progress(task_id, 33)

                # Step 2c: Validate extracted features and symlink to task directory
                from backend.ai.tasks.feature_cache import safe_load_features

                def _validate_and_symlink_features():
                    valid_wsi_ids = []
                    invalid_wsi_ids = []
                    for wsi_id in coords_success_wsi_ids:
                        cached_path = find_cached_features(uploads_dir, feature_extractor, params_hash, wsi_id)
                        if cached_path is None:
                            invalid_wsi_ids.append((wsi_id, "no cached features found"))
                            continue

                        # Validate the feature file is not corrupted/empty
                        feats, load_error = safe_load_features(cached_path, delete_if_corrupted=True)
                        if feats is None:
                            invalid_wsi_ids.append((wsi_id, f"corrupted: {load_error}"))
                            continue

                        if feats.shape[0] == 0:
                            invalid_wsi_ids.append((wsi_id, "empty [0, feat_dim]"))
                            continue

                        if feats.shape[0] < MIN_PATCHES_THRESHOLD:
                            invalid_wsi_ids.append((wsi_id, f"low patches ({feats.shape[0]} < {MIN_PATCHES_THRESHOLD})"))
                            continue

                        # Feature is valid - create symlink
                        create_symlink_to_cache(features_dir, wsi_id, cached_path)
                        valid_wsi_ids.append(wsi_id)

                    return valid_wsi_ids, invalid_wsi_ids

                valid_wsi_ids, invalid_wsi_ids = await asyncio.to_thread(_validate_and_symlink_features)

                # Update tracking for invalid features
                for wsi_id, reason in invalid_wsi_ids:
                    if wsi_id not in failed_wsi_ids:
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = f"feature validation failed: {reason}"

                if invalid_wsi_ids:
                    async with logger_manager.session() as (tl, _db):
                        await tl.warning(
                            f"Feature validation: {len(invalid_wsi_ids)} WSIs have invalid features",
                            metadata={
                                "invalid_count": len(invalid_wsi_ids),
                                "invalid_details": {w: r for w, r in invalid_wsi_ids[:20]},
                            }
                        )

                # Move valid WSIs to cached list
                for wsi_id in valid_wsi_ids:
                    if wsi_id not in cached_wsi_ids:
                        cached_wsi_ids.append(wsi_id)

            # Log final fallback summary if any WSIs were skipped
            if failed_wsi_ids:
                async with logger_manager.session() as (tl, _db):
                    await tl.warning(
                        f"[Fallback Summary] {len(failed_wsi_ids)}/{len(wsi_ids)} WSIs skipped during extraction",
                        metadata={
                            "total_wsi": len(wsi_ids),
                            "skipped_count": len(failed_wsi_ids),
                            "skipped_wsi_ids": failed_wsi_ids[:50],
                            "reasons": {k: v for k, v in list(failed_reasons.items())[:50]},
                        }
                    )
        else:
            # No missing WSIs - all features cached
            await update_task_progress(TaskStatus.TRAINING, 35)
            await set_progress(task_id, 35)

        # Update status to TRAINING for inference phase
        await update_task_progress(TaskStatus.TRAINING, 35)
        await set_progress(task_id, 35)
        async with logger_manager.session() as (tl, _db):
            valid_count = len(cached_wsi_ids)
            await tl.info(f"Features ready for {valid_count}/{len(wsi_ids)} WSIs. Starting inference...")

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

                        if is_case_level:
                            slide_attn = slide_attentions.get(wsi_id)
                            slide_raw_attn = slide_raw_attentions.get(wsi_id)
                        else:
                            slide_attn = attention
                            slide_raw_attn = raw_attention

                        attention_shape = list(slide_attn.shape) if hasattr(slide_attn, "shape") else None
                        if slide_attn is None:
                            attention_type = "none"
                        elif getattr(slide_attn, "ndim", None) == 1:
                            attention_type = "1d"
                        else:
                            attention_type = "2d"

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
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
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
                                "aggregator": aggregator_name,
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds if is_kfold else None,
                            }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        attention_file = None

                        if slide_raw_attn is not None:
                            np.save(wsi_result_dir / f"extval_{task_id}_attention_raw.npy", slide_raw_attn)
                        if slide_attn is not None:
                            attention_file = wsi_result_dir / f"extval_{task_id}_attention.npy"
                            np.save(attention_file, slide_attn)
                            ensure_recommendation_preview_cache(wsi_id, attention_file, Config.get_uploads_dir())

                        if attention_file is not None:
                            result_data["attention_file"] = str(attention_file)

                        with open(result_file, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        if is_survival:
                            _chunk_result_files.append((str(result_file), wsi_id))

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
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "attention_file": str(attention_file) if attention_file is not None else None,
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

            # Update progress via file-based store (35% to 95% for inference phase)
            progress = 35 + int(chunk_end / total * 60)
            await set_progress(task_id, progress)

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

        await update_task_progress(TaskStatus.TRAINING, 95, results_saved, results_saved)

        # Clear file-based progress (task is finishing)
        await clear_progress(task_id)

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

        # For HTTPStatusError, extract the actual error detail from the response body
        # instead of the generic "Server error '500 Internal Server Error' for url ..." message
        err_msg = str(e)
        if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
            try:
                body = json.loads(e.response.text)
                if isinstance(body, dict) and "detail" in body:
                    err_msg = body["detail"]
            except Exception:
                try:
                    err_msg = e.response.text[:2000] or err_msg
                except Exception:
                    pass

        try:
            await clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"External validation failed: {err_msg}")
        except Exception:
            pass  # Don't let logging failure mask the original error
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=err_msg)
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
    submitted_by: Optional[str] = None,
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
        for item in _iter_complete_analysis_runs(analysis_dir):
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
            # Use provided submitted_by, or fall back to task owner
            effective_submitted_by = submitted_by or user_id

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
            analysis_metrics = metrics or model_config.get("analysis_metrics") or ["accuracy", "precision", "recall", "f1", "auc", "weighted_kappa"]
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
                    submitted_by=effective_submitted_by,
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
    # Check task ownership/admin access.
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        await _require_task_access(
            user,
            task,
            db,
            forbidden_detail="You don't have permission to view this task's analysis",
        )

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id

    if not analysis_dir.exists():
        return {"task_id": task_id, "analyses": []}

    def _read_analyses():
        """Synchronous function to read analysis files."""
        result = []
        for item in _iter_complete_analysis_runs(analysis_dir):
            summary_file = item / "summary.json"
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

    task, _ = await _get_task_with_access(
        task_id,
        user,
        db,
        forbidden_detail="You don't have permission to analyze this task",
    )

    await _require_task_gpu_permission(
        user,
        task,
        db,
        forbidden_detail="You don't have GPU permission for this dataset. Contact admin for temporary access.",
        fallback_role_detail="GPU operations require pathologist or admin role",
    )

    # Generate analysis_id (timestamp format)
    analysis_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Check if there's already a pending/queued/running analysis for this task
    state = get_analysis_state()
    existing_analyses = await state.get_by_task_id(task_id)
    for existing in existing_analyses:
        if existing["status"] in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PATCHING):
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
        task_category = None
    else:
        # Internal analysis: use task name only (category sent as separate field for i18n)
        if task_type_str in ("wsi_survival", "survival"):
            task_category = "survival"
        elif task_type_str in ("segmentation", "patch_segmentation"):
            task_category = "segmentation"
        else:
            task_category = "classification"
        title = task.task_name
        analysis_type = "internal"

    # Create analysis state entry
    await state.create(analysis_id, task_id, str(user.id), title=title, analysis_type=analysis_type, task_category=task_category)

    # Check if GPU inference is needed (AI results missing)
    # External validation does not need GPU check here as it handles its own inference flow
    needs_gpu = False
    if not is_external:
        resources = await _check_task_resources(task_id, db)
        split_config = task.preprocessing_config.get("split_config", {}) if task.preprocessing_config else {}
        is_kfold = task_type_str not in ("segmentation", "patch_segmentation") and split_config.get("strategy", "random") == "k_fold"
        if _analysis_requires_training_metrics(task_type_str, request.charts, is_kfold) and not resources.get("has_training_metrics", True):
            raise HTTPException(
                status_code=409,
                detail=_missing_training_metrics_message(task_id, resources, request.charts, is_kfold),
            )
        needs_gpu = not resources["has_ai_results"]

    task_queue = get_task_queue()

    if needs_gpu:
        # GPU inference needed - submit to GPU queue for queuing
        await state.set_queued(analysis_id)
        await task_queue.submit(
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
    task, _ = await _get_task_with_access(
        task_id,
        user,
        db,
        forbidden_detail="You don't have permission to view this task's analysis",
    )

    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id

    # Parse metrics and charts from query params
    requested_metrics = [m.strip() for m in metrics.split(",")] if metrics else None
    requested_charts = [c.strip() for c in charts.split(",")] if charts else None

    # Check for existing analysis
    latest_summary = None
    analysis_id = None

    if analysis_dir.exists():
        analysis_id, latest_summary = await asyncio.to_thread(
            _read_latest_complete_analysis_sync,
            analysis_dir,
        )

    # If no analysis exists and run_if_missing is True, submit analysis task to queue
    if latest_summary is None and run_if_missing:
        from gateway.task_queue import get_task_queue, TaskType

        await _require_task_gpu_permission(
            user,
            task,
            db,
            forbidden_detail="No existing analysis and you don't have GPU permission to run analysis.",
            fallback_role_detail="No existing analysis and GPU operations require pathologist or admin role",
        )

        # Generate analysis_id (timestamp format)
        analysis_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Check if there's already a pending/queued/running analysis for this task
        state = get_analysis_state()
        existing_analyses = await state.get_by_task_id(task_id)
        for existing in existing_analyses:
            if existing["status"] in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PATCHING):
                # Return existing pending/queued/running analysis
                return {
                    "task_id": task_id,
                    "analysis_id": existing["analysis_id"],
                    "has_analysis": False,
                    "status": existing["status"],
                    "progress": existing["progress"],
                    "message": "Analysis is in progress"
                }

        # Get task_type from DataGroup relationship
        quick_task_data_group = task.data_group
        quick_task_type_str = quick_task_data_group.task_type if quick_task_data_group else "classification"

        # Build meaningful title and metadata for background task display
        is_external = quick_task_type_str == "external_validation"
        if is_external:
            model_config = task.model_config or {}
            model_id = model_config.get("model_id", "")
            dataset_id = model_config.get("dataset_id", "")

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
            task_category = None
        else:
            if quick_task_type_str in ("wsi_survival", "survival"):
                task_category = "survival"
            elif quick_task_type_str in ("segmentation", "patch_segmentation"):
                task_category = "segmentation"
            else:
                task_category = "classification"
            title = task.task_name
            analysis_type = "internal"

        # Create analysis state entry
        await state.create(
            analysis_id,
            task_id,
            str(user.id),
            title=title,
            analysis_type=analysis_type,
            task_category=task_category,
        )

        # Default metrics and charts based on task type
        is_survival_task = quick_task_type_str in ("wsi_survival", "survival")
        is_seg_task = quick_task_type_str in ("segmentation", "patch_segmentation")
        if is_survival_task:
            default_metrics = ["c_index", "integrated_brier_score"]
            default_charts = ["km_curve", "loss_curve"]
        elif is_seg_task:
            default_metrics = ["iou", "dice", "accuracy", "precision", "recall", "f1"]
            default_charts = ["loss_curve", "iou_curve", "dice_curve"]
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
        split_config = task.preprocessing_config.get("split_config", {}) if task.preprocessing_config else {}
        is_kfold = quick_task_type_str not in ("segmentation", "patch_segmentation") and split_config.get("strategy", "random") == "k_fold"
        if _analysis_requires_training_metrics(quick_task_type_str, default_charts, is_kfold) and not resources.get("has_training_metrics", True):
            raise HTTPException(
                status_code=409,
                detail=_missing_training_metrics_message(task_id, resources, default_charts, is_kfold),
            )
        needs_gpu = not resources["has_ai_results"]

        task_queue = get_task_queue()

        if needs_gpu:
            # GPU inference needed - submit to GPU queue for queuing
            await state.set_queued(analysis_id)
            await task_queue.submit(
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
        requested_metric_keys = set(requested_metrics)
        if "iou" in requested_metric_keys:
            requested_metric_keys.add("miou")
        if "miou" in requested_metric_keys:
            requested_metric_keys.add("iou")
        result_metrics = {
            k: v for k, v in result_metrics.items()
            if k in requested_metric_keys or k.replace("macro_", "") in requested_metric_keys
        }

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
    task_type = latest_summary.get("task_type", "classification")
    if task_type not in ("segmentation", "patch_segmentation") and kfold_training:
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
    # Check task ownership/admin access.
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        await _require_task_access(
            user,
            task,
            db,
            forbidden_detail="You don't have permission to view this file",
        )

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
                    if _analysis_has_required_files(analysis_dir):
                        # Analysis exists on disk, check ownership (supports temp permissions)
                        task = await TrainingTaskRepository.get_by_id(db, task_dir.name)
                        if task:
                            await _require_task_access(
                                user,
                                task,
                                db,
                                forbidden_detail="You don't have permission to view this analysis",
                            )

                        return {
                            "analysis_id": analysis_id,
                            "task_id": task_dir.name,
                            "status": TaskStatus.COMPLETED,
                            "progress": 100,
                            "error_message": None,
                            "message": "Analysis completed"
                        }

        raise HTTPException(status_code=404, detail=f"Analysis not found: {analysis_id}")

    # Check task ownership/admin access.
    task_id = analysis_state.get("task_id")
    if task_id:
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if task:
            await _require_task_access(
                user,
                task,
                db,
                forbidden_detail="You don't have permission to view this analysis",
            )

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
    elif status == TaskStatus.PATCHING:
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



@router.get("/wsi/{wsi_id}")
async def get_results(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI analysis results for a WSI from database.
    Users can access the WSI itself via ownership or temporary dataset permission,
    but only admins can see all derived results; non-admins only see their own
    results for that WSI.

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

    # Get latest derived result visible to the current user.
    result_query = select(AIResult).where(AIResult.wsi_id == wsi_id)
    if not user.is_admin():
        result_query = result_query.where(_build_owned_ai_result_filter(user))
    result_query = result_query.order_by(AIResult.created_at.desc()).limit(1)

    result = (await db.execute(result_query)).scalar_one_or_none()
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
    assigned_device: Optional[str] = None,
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
            # NOTE: Only skip CI for internal analysis. External validation always allows CI
            # because it measures uncertainty on the new dataset, independent of training method.
            split_config = task.preprocessing_config.get("split_config", {}) if task.preprocessing_config else {}
            split_strategy = split_config.get("strategy", "random")
            is_segmentation_task = task_type_str in ("segmentation", "patch_segmentation")
            is_kfold = not is_segmentation_task and split_strategy == "k_fold"
            if is_kfold and has_ci_calculation and task_type_str != "external_validation":
                has_ci_calculation = False  # K-Fold doesn't use Bootstrap CI (internal analysis only)

            if task_type_str != "external_validation":
                # Check if AI results exist
                resources = await _check_task_resources(task.task_id, db)
                if _analysis_requires_training_metrics(task_type_str, charts, is_kfold) and not resources.get("has_training_metrics", True):
                    raise ValueError(_missing_training_metrics_message(task.task_id, resources, charts, is_kfold))
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

                await _run_inference_if_needed(task, db, progress_callback=inference_progress, assigned_device=assigned_device)
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
                case "segmentation" | "patch_segmentation":
                    result = await _run_segmentation_analysis(
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
