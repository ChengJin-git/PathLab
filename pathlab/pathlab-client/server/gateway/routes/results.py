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
from typing import List, Dict, Any, Optional, Callable, Tuple, cast as type_cast
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.orm import selectinload

from backend.ai.schemas.base import TaskStatus
from backend.database import get_db, safe_session
from backend.database.models import (
    AIResult,
    AITask,
    WSISlide,
    TrainingTask,
    TrainedModel,
    TrainingTaskWSI,
    DataGroup,
    Dataset,
    AnalysisRun,
)
from backend.database.repositories import (
    AIResultRepository,
    WSIRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    DataGroupRepository,
    DatasetRepository,
    DatasetGrantRepository,
)
from backend.common.config import Config
from ..dependencies import make_sse_response
from backend.common.redis_client import get_redis, make_key
from backend.storage import StorageManager
from backend.auth import (
    current_active_user,
    User,
    get_user_from_header_or_param,
    get_user_from_token_param,
)
from backend.auth.dependencies import (
    require_pathologist_or_admin,
    check_dataset_access_permission,
    check_dataset_gpu_permission,
    check_wsi_access_permission,
)
from .access_control import assert_owner
from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi
from backend.preprocessing.heatmap_preview_cache import (
    ensure_recommendation_preview_cache,
)
from gateway.models import ExternalValidationRequest, QuickAnalysisRequest

# Analysis modules (extracted from this file for maintainability)
from .analysis_state import get_analysis_state, AnalysisRequest
from .analysis_utils import (
    _get_random_seed_from_task,
    _get_task_with_access,
    _require_task_access,
    _require_task_gpu_permission,
    _coerce_str,
    _coerce_str_list,
    _normalize_label_names,
    _split_case_attention_to_slides_static,
)
from .classification_analysis import _run_classification_analysis
from .segmentation_analysis import _run_segmentation_analysis
from .survival_analysis import _run_survival_analysis
from .external_validation_analysis import (
    _run_external_validation_analysis,
    check_extval_compatibility,
    ExtvalModelInfo,
    ExtvalDatasetInfo,
    _is_extval_segmentation_task,
)
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
from .inference_wsi_classification import _run_inference_wsi_classification
from .inference_patch_classification import _run_inference_patch_classification
from .inference_patch_segmentation import _run_inference_patch_segmentation
from .inference_wsi_survival import _run_inference_wsi_survival
from .inference_external_validation import (
    _run_external_validation_patch_segmentation,
    _run_external_validation_patch_classification,
    _run_external_validation,
    _auto_trigger_external_validation_analysis,
)

# Initialize storage manager
storage_manager = StorageManager(str(Config.get_uploads_dir()))

router = APIRouter(prefix="/results", tags=["AI Results"])
logger = logging.getLogger(__name__)


def _extract_segmentation_label_names(categories: List[Dict[str, Any]]) -> List[str]:
    return _normalize_label_names(
        [
            str(category.get("name", "")).strip()
            for category in categories
            if category.get("name")
        ]
    )


def _coerce_path(path_value: Any) -> Optional[Path]:
    if not path_value:
        return None
    try:
        return Path(path_value)
    except (TypeError, ValueError):
        return None


async def _has_external_validation_dataset_access(
    user: User, dataset: Dataset, db: AsyncSession
) -> bool:
    return await check_dataset_access_permission(
        user,
        _coerce_str(dataset.dataset_id),
        _coerce_str(dataset.user_id),
        db,
        is_public=bool(getattr(dataset, "is_public", False)),
        parent_dataset_id=getattr(dataset, "parent_dataset_id", None),
    )


def _candidate_metrics_paths(
    task_id: str, trained_model: Optional[Dict[str, Any]]
) -> List[Path]:
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

    candidates.extend(
        [
            uploads_dir / "training" / task_id / "checkpoints" / "metrics.json",
            uploads_dir / "training" / task_id / "metrics.json",
        ]
    )

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
        return result_file.with_name(
            f"{result_name[: -len('_result.json')]}{artifact_suffix}"
        )
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

    result_file = _coerce_path(metadata.get("result_file")) or (
        result_dir / f"train_{task_id}_result.json"
    )
    artifacts: List[Tuple[str, Path]] = [("result_file", result_file)]

    if task_type in ("segmentation", "patch_segmentation"):
        pred_mask_file = _coerce_path(
            metadata.get("pred_mask_file")
        ) or _derive_companion_artifact_path(result_file, "_pred_mask.npy")
        cam_file = _coerce_path(
            metadata.get("cam_file")
        ) or _derive_companion_artifact_path(result_file, "_cam.npy")
        artifacts.extend(
            [
                ("pred_mask_file", pred_mask_file),
                ("cam_file", cam_file),
            ]
        )
        return artifacts

    if data_type == "patch":
        cam_file = _coerce_path(
            metadata.get("cam_file")
        ) or _derive_companion_artifact_path(result_file, "_cam.npy")
        artifacts.append(("cam_file", cam_file))
        return artifacts

    if _expects_wsi_attention(metadata):
        attention_file = _coerce_path(
            metadata.get("attention_file")
        ) or _derive_companion_artifact_path(result_file, "_attention.npy")
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

    for artifact_name, artifact_path in _required_ai_result_artifacts(
        task_id, task_type, data_type, wsi_id, metadata
    ):
        if artifact_path.exists():
            continue
        missing_count += 1
        if len(missing_artifacts) < sample_limit:
            missing_artifacts.append(
                {
                    "wsi_id": wsi_id,
                    "artifact": artifact_name,
                    "path": str(artifact_path),
                }
            )

    if data_type != "patch" and _expects_wsi_attention(metadata):
        coords_file = find_any_cached_coords_for_wsi(Config.get_uploads_dir(), wsi_id)
        if coords_file is None:
            missing_count += 1
            if len(missing_artifacts) < sample_limit:
                missing_artifacts.append(
                    {
                        "wsi_id": wsi_id,
                        "artifact": "coords_file",
                        "path": f"[cache lookup] coords.h5 for {wsi_id}",
                    }
                )

    return missing_count, missing_artifacts


def _analysis_has_required_files(analysis_run_dir: Path) -> bool:
    if not analysis_run_dir.is_dir():
        return False
    return (analysis_run_dir / "summary.json").exists() and (
        analysis_run_dir / "results.json"
    ).exists()


def _iter_complete_analysis_runs(analysis_dir: Path):
    if not analysis_dir.exists() or not analysis_dir.is_dir():
        return
    for item in sorted(analysis_dir.iterdir(), reverse=True):
        if _analysis_has_required_files(item):
            yield item


def _read_latest_complete_analysis_sync(
    analysis_dir: Path,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    for item in _iter_complete_analysis_runs(analysis_dir):
        with open(item / "summary.json", "r") as f:
            return item.name, json.load(f)
    return None, None


def _analysis_requires_training_metrics(
    task_type: str, charts: Optional[List[str]], is_kfold: bool
) -> bool:
    if is_kfold:
        return True

    requested_charts = set(charts or [])
    required_charts = {"loss_curve"}
    if task_type in ("segmentation", "patch_segmentation"):
        required_charts.update({"iou_curve", "dice_curve"})
    return bool(requested_charts & required_charts)


def _missing_training_metrics_message(
    task_id: str, resources: Dict[str, Any], charts: Optional[List[str]], is_kfold: bool
) -> str:
    requested_parts = []
    requested_charts = sorted(set(charts or []))
    if requested_charts:
        requested_parts.append(f"requested charts={', '.join(requested_charts)}")
    if is_kfold:
        requested_parts.append("task uses k-fold training summary")
    requested_detail = (
        "; ".join(requested_parts)
        if requested_parts
        else "analysis requires training metrics"
    )
    metrics_path = resources.get("metrics_file") or "metrics.json"
    return (
        f"Training metrics artifact is missing for task {task_id}: {metrics_path}. "
        f"ResultsViewer cannot build this analysis because {requested_detail}. "
        "Please restore metrics.json or rerun training."
    )


async def _enrich_single_task_resources(
    task_id: str, db: AsyncSession, base_resources: Dict[str, Any]
) -> Dict[str, Any]:
    resources = dict(base_resources)
    resources.setdefault(
        "has_complete_ai_results", resources.get("has_ai_results", False)
    )
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
    resources["metrics_file"] = (
        str(metrics_file or metrics_candidates[0]) if metrics_candidates else None
    )
    resources["has_training_metrics"] = metrics_file is not None
    if not resources["has_training_metrics"]:
        resources["missing_training_artifacts"] = [
            resources["metrics_file"] or "metrics.json"
        ]

    if resources.get("ai_results_count", 0) <= 0:
        resources["has_ai_results"] = False
        resources["has_complete_ai_results"] = False
        return resources

    ai_result_rows = (
        await db.execute(
            select(AIResult.wsi_id, AIResult.extra_metadata).where(
                AIResult.task_id == task_id
            )
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


async def _get_elevated_dataset_ids(
    user: User, db: AsyncSession
) -> Optional[List[str]]:
    """
    Get dataset IDs for which the user has temporary elevated permissions.
    Returns None for admin users (no filtering needed).
    Returns empty list if no elevated permissions.
    """
    if user.is_admin():
        return None
    permissions = await DatasetGrantRepository.get_valid_by_user(db, str(user.id))
    return [
        _coerce_str(p.dataset_id) for p in permissions if p.is_valid() and p.can_use_gpu
    ]


def _build_owned_ai_result_filter(user: User):
    """
    Restrict AI result visibility to the current user's own derived artifacts.

    Some historical AIResult rows do not have user_id populated, so we also fall
    back to task ownership for both inference tasks (AITask) and training tasks.
    """
    user_id = str(user.id)
    owned_ai_task_ids = select(AITask.task_id).where(AITask.user_id == user_id)
    owned_training_task_ids = select(TrainingTask.task_id).where(
        TrainingTask.user_id == user_id
    )
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
    db: AsyncSession = Depends(get_db),
):
    """
    Get all AI results with associated WSI labels for analysis.
    Users see only their own results, admin sees all.

    Returns:
        List of results with predictions and ground truth labels
    """
    # Query results with WSI info
    query = select(AIResult, WSISlide).join(
        WSISlide, AIResult.wsi_id == WSISlide.wsi_id
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
    db: AsyncSession = Depends(get_db),
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
            "classes": [],
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
            "classes": [],
        }

    # Use sklearn for metrics calculation
    from sklearn.metrics import (
        accuracy_score,
        precision_recall_fscore_support,
        confusion_matrix as sklearn_confusion_matrix,
        roc_curve,
        auc,
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
        "classes": all_classes,
    }

    # Per-class metrics using sklearn
    zero_division_value = type_cast("Any", 0)
    per_class_scores = type_cast(
        "tuple[Any, Any, Any, Any]",
        precision_recall_fscore_support(
            labels,
            predictions,
            labels=all_classes,
            average=None,
            zero_division=zero_division_value,
        ),
    )
    precision_per_class, recall_per_class, f1_per_class, _ = per_class_scores

    class_metrics = {}
    for i, cls in enumerate(all_classes):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        tn = cm.sum() - tp - fp - fn
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0

        class_metrics[cls] = {
            "tp": int(tp),
            "fp": int(fp),
            "fn": int(fn),
            "tn": int(tn),
            "precision": round(float(precision_per_class[i]), 4),
            "recall": round(float(recall_per_class[i]), 4),
            "sensitivity": round(float(recall_per_class[i]), 4),
            "specificity": round(float(specificity), 4),
            "f1": round(float(f1_per_class[i]), 4),
            "support": int(tp + fn),
        }

    # Overall metrics using sklearn
    accuracy = accuracy_score(labels, predictions)
    macro_scores = type_cast(
        "tuple[Any, Any, Any, Any]",
        precision_recall_fscore_support(
            labels,
            predictions,
            average="macro",
            zero_division=zero_division_value,
        ),
    )
    macro_precision, macro_recall, macro_f1, _ = macro_scores
    macro_specificity = (
        sum(m["specificity"] for m in class_metrics.values()) / n_classes
        if n_classes > 0
        else 0
    )

    weighted_scores = type_cast(
        "tuple[Any, Any, Any, Any]",
        precision_recall_fscore_support(
            labels,
            predictions,
            average="weighted",
            zero_division=zero_division_value,
        ),
    )
    weighted_precision, weighted_recall, weighted_f1, _ = weighted_scores

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

        if (
            scores
            and sum(binary_labels) > 0
            and sum(binary_labels) < len(binary_labels)
        ):
            fpr, tpr, _ = roc_curve(binary_labels, scores)
            roc_auc = auc(fpr, tpr)
            roc_points = [{"fpr": float(f), "tpr": float(t)} for f, t in zip(fpr, tpr)]
            roc_data[cls] = {"points": roc_points, "auc": round(float(roc_auc), 4)}
            # Add per-class AUC to class_metrics
            if cls in class_metrics:
                class_metrics[cls]["auc"] = round(float(roc_auc), 4)

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
        "prediction_distribution": dict(pred_dist),
    }


async def _check_task_resources_batch(
    task_ids: List[str], db: AsyncSession
) -> Dict[str, dict[str, Any]]:
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
            TrainingTaskWSI.task_id, func.count(TrainingTaskWSI.wsi_id).label("count")
        )
        .where(TrainingTaskWSI.task_id.in_(task_ids))
        .group_by(TrainingTaskWSI.task_id)
    )
    total_wsi_count_result = await db.execute(total_wsi_count_query)
    total_wsi_by_task = {row[0]: row[1] for row in total_wsi_count_result.all()}

    # Step 0.6: For case-level tasks, count distinct case_ids
    case_level_task_ids = [
        tid for tid in task_ids if task_aggregation_levels.get(tid) == "case"
    ]
    total_case_by_task = {}
    if case_level_task_ids:
        total_case_count_query = (
            select(
                TrainingTaskWSI.task_id,
                func.count(func.distinct(WSISlide.case_id)).label("count"),
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
                func.count(TrainingTaskWSI.wsi_id).label("count"),
            )
            .where(TrainingTaskWSI.task_id.in_(list(tasks_with_test_set)))
            .where(TrainingTaskWSI.split == "test")
            .group_by(TrainingTaskWSI.task_id)
        )
        test_wsi_count_result = await db.execute(test_wsi_count_query)
        test_wsi_count_by_task = {row[0]: row[1] for row in test_wsi_count_result.all()}

    # Step 1.6: For case-level tasks, count distinct test case_ids
    test_case_count_by_task = {}
    test_case_level_task_ids = [
        tid for tid in tasks_with_test_set if task_aggregation_levels.get(tid) == "case"
    ]
    if test_case_level_task_ids:
        test_case_count_query = (
            select(
                TrainingTaskWSI.task_id,
                func.count(func.distinct(WSISlide.case_id)).label("count"),
            )
            .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(TrainingTaskWSI.task_id.in_(test_case_level_task_ids))
            .where(TrainingTaskWSI.split == "test")
            .group_by(TrainingTaskWSI.task_id)
        )
        test_case_count_result = await db.execute(test_case_count_query)
        test_case_count_by_task = {
            row[0]: row[1] for row in test_case_count_result.all()
        }

    # Step 2: For tasks WITH test set, count AI results joined with test WSIs
    ai_count_with_test = {}
    if tasks_with_test_set:
        ai_count_with_test_query = (
            select(AIResult.task_id, func.count(AIResult.id).label("count"))
            .join(
                TrainingTaskWSI,
                and_(
                    AIResult.task_id == TrainingTaskWSI.task_id,
                    AIResult.wsi_id == TrainingTaskWSI.wsi_id,
                    TrainingTaskWSI.split == "test",
                ),
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
            select(AIResult.task_id, func.count(AIResult.id).label("count"))
            .where(AIResult.task_id.in_(list(tasks_without_test_set)))
            .group_by(AIResult.task_id)
        )
        ai_count_without_test_result = await db.execute(ai_count_without_test_query)
        ai_count_without_test = {
            row[0]: row[1] for row in ai_count_without_test_result.all()
        }

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

        if is_patch_task:
            has_features = True
        else:
            features_dir = uploads_dir / "training" / task_id / "features"
            sentinel = features_dir / ".done"
            if sentinel.exists():
                has_features = True
            elif features_dir.exists() and any(features_dir.glob("*.pt")):
                has_features = True
                try:
                    sentinel.touch()
                except OSError:
                    pass
            else:
                has_features = False

        # Check model (use cached directory list)
        # Support both regular training (aggregator.pth in model_dir) and
        # K-Fold training (aggregator.pth in model_dir/fold_X/)
        # Patch classification uses linear_probe.pth
        has_model = False
        model_id = None
        for model_dir in model_dirs_cache:
            if task_id in model_dir.name:
                # Check regular checkpoint location
                if (model_dir / "aggregator.pth").exists() or (
                    model_dir / "linear_probe.pth"
                ).exists():
                    has_model = True
                    model_id = model_dir.name
                    break
                # Check K-Fold checkpoint location
                fold_checkpoints = list(model_dir.glob("fold_*/aggregator.pth")) + list(
                    model_dir.glob("fold_*/linear_probe.pth")
                )
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
        test_display_count = (
            test_case_count if aggregation_level == "case" else test_wsi_count
        )

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


async def _check_task_resources(task_id: str, db: AsyncSession) -> dict[str, Any]:
    """Check if task has features, model, and ai_results.

    NOTE: This is a wrapper around _check_task_resources_batch for single task use.
    For multiple tasks, use _check_task_resources_batch directly for better performance.
    """
    results = await _check_task_resources_batch([task_id], db)
    base_resources = results.get(
        task_id,
        {
            "has_features": False,
            "has_model": False,
            "model_id": None,
            "has_ai_results": False,
            "ai_results_count": 0,
            "total_wsi_count": 0,
            "total_case_count": 0,
            "aggregation_level": "file",
        },
    )
    return await _enrich_single_task_resources(task_id, db, base_resources)


_RESULTS_TASKS_CACHE_TTL = 5 * 60


@router.get("/tasks")
async def get_analysis_tasks(
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    cache_key = make_key("results_tasks", "admin" if user.is_admin() else str(user.id))
    try:
        r = get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    task_list = []

    # Get completed tasks from database
    # Use selectinload to eagerly load data_group relationship to avoid lazy loading in async context
    query = (
        select(TrainingTask)
        .options(selectinload(TrainingTask.data_group))
        .where(TrainingTask.status == TaskStatus.COMPLETED)
    )
    # Filter to the current user's own tasks if not admin.
    if not user.is_admin():
        query = query.where(TrainingTask.user_id == str(user.id))
    query = query.order_by(TrainingTask.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    if not tasks:
        return {"items": [], "total": 0}

    task_ids = [_coerce_str(task.task_id) for task in tasks]
    all_resources = await _check_task_resources_batch(task_ids, db)
    source_dataset_ids = await TrainingTaskRepository.get_source_dataset_ids_batch(
        db, task_ids
    )

    for task in tasks:
        task_id = _coerce_str(task.task_id)
        resources = all_resources.get(
            task_id,
            {
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
            },
        )

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

        analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id
        has_analysis = False
        if analysis_dir.exists():
            for item in _iter_complete_analysis_runs(analysis_dir):
                has_analysis = True
                break

        # Extract feature_extractor and split_strategy from preprocessing_config
        feature_extractor = None
        is_segmentation_task = task_type in ("segmentation", "patch_segmentation")
        is_kfold = False
        if isinstance(task.preprocessing_config, dict):
            feature_extractor = task.preprocessing_config.get("feature_extractor")
            # Check split strategy to determine if K-Fold training
            split_config = task.preprocessing_config.get("split_config", {})
            is_kfold = (
                not is_segmentation_task and split_config.get("strategy") == "k_fold"
            )

        # Determine display count based on aggregation_level
        aggregation_level = resources.get("aggregation_level", "file")
        if aggregation_level == "case":
            display_count = resources["total_case_count"]
        else:
            display_count = resources["total_wsi_count"]

        task_list.append(
            {
                "task_id": task_id,
                "name": task.task_name or task_id,
                "task_type": task_type,
                "data_type": data_type,  # 'wsi' or 'patch'
                "aggregation_level": aggregation_level,  # 'file' or 'case'
                "status": task.status,
                "created_at": (
                    task.created_at.isoformat() + "Z"
                    if isinstance(task.created_at, datetime)
                    else None
                ),
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
                "wsi_ids": [],
                "classes": task.classes,
                "model_config": task.model_config,
                "source_dataset_id": source_dataset_ids.get(task_id),
                "is_kfold": is_kfold,
                "source": "database",
            }
        )

    response = {"items": task_list, "total": len(task_list)}
    try:
        r = get_redis()
        await r.set(cache_key, json.dumps(response), ex=_RESULTS_TASKS_CACHE_TTL)
    except Exception:
        pass
    return response


async def _run_inference_if_needed(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
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
            await _run_inference_patch_segmentation(
                task,
                wsi_ids,
                resources,
                db,
                progress_callback,
                assigned_device=assigned_device,
            )
        else:
            await _run_inference_patch_classification(
                task,
                wsi_ids,
                resources,
                db,
                progress_callback,
                assigned_device=assigned_device,
            )
    elif task_type in ("wsi_survival", "survival"):
        await _run_inference_wsi_survival(
            task,
            wsi_ids,
            resources,
            db,
            progress_callback,
            assigned_device=assigned_device,
        )
    else:
        # Default: WSI classification
        await _run_inference_wsi_classification(
            task,
            wsi_ids,
            resources,
            db,
            progress_callback,
            assigned_device=assigned_device,
        )

    logger.info(f"GPU inference completed for task {task_id}")
    if progress_callback:
        await progress_callback(1.0)
    return True


@router.get("/datasets-for-validation")
async def get_datasets_for_validation(
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    List all datasets available for external validation selection.
    Returns dataset metadata including aggregation_level, task_type, data_type,
    slide/case counts, distinct label count, and WSI IDs (for overlap detection).

    available_feature_extractors lists extractors with cached features for the
    dataset's first WSI. Datasets are not filtered on feature availability —
    missing features are extracted automatically when validation starts.
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

        dataset_id = _coerce_str(ds.dataset_id)

        if not user.is_admin():
            owns_dataset = _coerce_str(ds.user_id) == str(user.id)
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

        available_feature_extractors: list[Any] = []
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
                                    available_feature_extractors.append(
                                        extractor_dir.name
                                    )
                                    break  # Found for this extractor, move to next

        # Get case count for case-level datasets
        total_wsi_count = len(wsi_ids)
        total_case_count = total_wsi_count
        if dg.aggregation_level == "case":
            case_map = await DatasetRepository.get_wsi_case_ids(db, dataset_id)
            total_case_count = len(set(case_map.values()))

        # Determine display count based on aggregation_level
        display_count = (
            total_case_count if dg.aggregation_level == "case" else total_wsi_count
        )
        segmentation_labels: List[str] = []
        if dg.task_type in ("segmentation", "patch_segmentation"):
            coco_categories = await WSIRepository._get_coco_categories_for_dataset(
                db, dataset_id
            )
            segmentation_labels = _extract_segmentation_label_names(coco_categories)

        result.append(
            {
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
            }
        )

    return {"items": result, "total": len(result)}


@router.post("/external-validation")
async def start_external_validation(
    req: ExternalValidationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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

    effective_task_owner_user_id = str(user.id)

    if user.is_admin() and req.rerun_from_task_id:
        source_task = await TrainingTaskRepository.get_by_id(db, req.rerun_from_task_id)
        if not source_task:
            raise HTTPException(
                status_code=404,
                detail="Source training task not found for rerun",
            )
        source_task_user_id = _coerce_str(source_task.user_id)
        if source_task_user_id:
            effective_task_owner_user_id = source_task_user_id

    # Validate model exists
    trained_model = await TrainedModelRepository.get_by_id(db, req.model_id)
    if not trained_model:
        raise HTTPException(status_code=404, detail=f"Model not found: {req.model_id}")

    # Check ownership of the model via its training task.
    trained_model_task_id = _coerce_str(trained_model.task_id)
    model_task = await TrainingTaskRepository.get_by_id(db, trained_model_task_id)
    if not model_task:
        raise HTTPException(
            status_code=404,
            detail=f"Model's training task not found: {trained_model_task_id}",
        )
    await _require_task_access(
        user,
        model_task,
        db,
        owner_user_id=_coerce_str(trained_model.user_id),
        forbidden_detail="You don't have permission to use this model",
    )

    if not bool(trained_model.is_active):
        raise HTTPException(
            status_code=400, detail=f"Model is not active: {req.model_id}"
        )

    # Validate target dataset exists
    target_dataset = await DatasetRepository.get_by_id(db, req.dataset_id)
    if not target_dataset:
        raise HTTPException(
            status_code=404, detail=f"Dataset not found: {req.dataset_id}"
        )

    has_dataset_access = await _has_external_validation_dataset_access(
        user, target_dataset, db
    )
    if not has_dataset_access:
        raise HTTPException(
            status_code=403, detail="You don't have permission to use this dataset"
        )

    # Check GPU permission for the target dataset
    has_permission = await check_dataset_gpu_permission(user, req.dataset_id, db)
    if not has_permission and not user.can_use_gpu():
        raise HTTPException(
            status_code=403,
            detail="You don't have GPU permission for this dataset. Contact admin for temporary access.",
        )

    # ========================================================================
    # COMPATIBILITY VALIDATION
    # ========================================================================

    model_data_group = model_task.data_group
    target_data_group = target_dataset.data_group

    model_data_type = model_data_group.data_type if model_data_group else "wsi"
    target_data_type = target_data_group.data_type if target_data_group else "wsi"
    model_task_type = (
        model_data_group.task_type if model_data_group else "classification"
    )
    target_task_type = (
        target_data_group.task_type if target_data_group else "classification"
    )
    target_aggregation_level = (
        target_data_group.aggregation_level if target_data_group else "file"
    )

    wsi_ids = await DatasetRepository.get_wsi_ids(db, req.dataset_id)
    if not wsi_ids:
        raise HTTPException(
            status_code=400, detail=f"No WSI IDs found for dataset: {req.dataset_id}"
        )

    model_wsi_ids = set(
        await TrainingTaskRepository.get_wsi_ids(db, _coerce_str(trained_model.task_id))
    )
    training_dataset_ids: set[str] = set()
    training_ds_rows = await db.execute(
        select(WSISlide.dataset_id)
        .join(TrainingTaskWSI, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
        .where(
            TrainingTaskWSI.task_id == trained_model_task_id,
            WSISlide.dataset_id.isnot(None),
        )
        .distinct()
    )
    training_dataset_ids = {
        _coerce_str(row[0]) for row in training_ds_rows.all() if _coerce_str(row[0])
    }

    dataset_labels = await DatasetRepository.get_distinct_labels(db, req.dataset_id)
    dataset_feature_extractors: List[str] = []
    if target_data_type != "patch" and wsi_ids:
        first_wsi_id = wsi_ids[0]
        features_root = Config.get_uploads_dir() / "features"
        if features_root.exists():
            for extractor_dir in features_root.iterdir():
                if not extractor_dir.is_dir():
                    continue
                for params_hash_dir in extractor_dir.iterdir():
                    if not params_hash_dir.is_dir():
                        continue
                    if (params_hash_dir / f"{first_wsi_id}.pt").exists():
                        dataset_feature_extractors.append(extractor_dir.name)
                        break

    source_dataset_id: Optional[str] = None
    target_seg_labels: List[str] = []
    model_config = (
        model_task.model_config if isinstance(model_task.model_config, dict) else {}
    )
    if _is_extval_segmentation_task(model_task_type):
        source_task_id = _coerce_str(trained_model.task_id)
        source_dataset_id = (
            await TrainingTaskRepository.get_source_dataset_ids_batch(
                db, [source_task_id]
            )
        ).get(source_task_id)
        target_seg_labels = _extract_segmentation_label_names(
            await WSIRepository._get_coco_categories_for_dataset(db, req.dataset_id)
        )

    compat_error = check_extval_compatibility(
        model_info=ExtvalModelInfo(
            data_type=model_data_type,
            task_type=model_task_type,
            classes=_coerce_str_list(trained_model.classes),
            feature_extractor=str(trained_model.feature_extractor or ""),
            wsi_ids=model_wsi_ids,
            source_dataset_id=source_dataset_id,
            seg_task_architecture=str(model_config.get("architecture") or "").strip(),
            seg_task_backbone=str(model_config.get("backbone") or "").strip(),
            seg_saved_architecture=str(trained_model.aggregator or "").strip(),
            seg_saved_backbone=str(trained_model.feature_extractor or "").strip(),
            segmentation_labels=_coerce_str_list(
                model_task.classes or trained_model.classes or []
            ),
            training_dataset_ids=training_dataset_ids,
        ),
        dataset_info=ExtvalDatasetInfo(
            dataset_id=req.dataset_id,
            data_type=target_data_type,
            task_type=target_task_type,
            aggregation_level=target_aggregation_level,
            labels=dataset_labels,
            segmentation_labels=target_seg_labels,
            feature_extractors=dataset_feature_extractors,
            wsi_ids=set(wsi_ids),
        ),
    )
    if compat_error:
        raise HTTPException(status_code=400, detail=compat_error)

    # Check if inference results already exist for this model + data combination
    # Look for existing extval_*_result.json files in the WSI ai_results directories
    uploads_dir = Config.get_uploads_dir()
    existing_results_count = 0
    existing_validation_id = None
    incomplete_existing_examples: List[Dict[str, Any]] = []

    def _check_existing_results():
        """Check for existing external validation results."""
        nonlocal \
            existing_results_count, \
            existing_validation_id, \
            incomplete_existing_examples
        for wsi_id in wsi_ids:
            ai_results_dir = uploads_dir / "ai_results" / wsi_id
            if ai_results_dir.exists():
                # Look for extval_*_result.json files
                for result_file in ai_results_dir.glob("extval_*_result.json"):
                    try:
                        with open(result_file, "r") as f:
                            result_data = json.load(f)
                        # Check if this result is from the same model
                        if result_data.get("task_id") == trained_model.task_id:
                            validation_task_id = result_data.get("validation_task_id")
                            if not validation_task_id and result_file.name.endswith(
                                "_result.json"
                            ):
                                validation_task_id = result_file.name[
                                    : -len("_result.json")
                                ]

                            result_metadata = dict(result_data)
                            result_metadata["result_file"] = str(result_file)
                            derived_attention_file = _derive_companion_artifact_path(
                                result_file, "_attention.npy"
                            )
                            if (
                                model_data_type != "patch"
                                and not result_metadata.get("attention_file")
                                and derived_attention_file.exists()
                            ):
                                result_metadata["attention_file"] = str(
                                    derived_attention_file
                                )
                                result_metadata.setdefault("attention_type", "derived")

                            missing_count, missing_examples = (
                                _collect_missing_ai_result_artifacts(
                                    task_id=validation_task_id
                                    or result_file.name[: -len("_result.json")],
                                    task_type=str(
                                        result_data.get("task_type") or model_task_type
                                    ),
                                    data_type=model_data_type,
                                    wsi_id=wsi_id,
                                    extra_metadata=result_metadata,
                                    sample_limit=1,
                                )
                            )
                            if missing_count > 0:
                                if (
                                    len(incomplete_existing_examples) < 5
                                    and missing_examples
                                ):
                                    incomplete_existing_examples.extend(
                                        missing_examples
                                    )
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
    if _is_extval_segmentation_task(model_task_type):
        analysis_metrics = req.metrics or [
            "iou",
            "dice",
            "accuracy",
            "precision",
            "recall",
        ]
        analysis_charts = req.charts or ["per_class_iou", "per_class_dice"]
    else:
        analysis_metrics = req.metrics or [
            "accuracy",
            "precision",
            "recall",
            "f1",
            "auc",
            "weighted_kappa",
        ]
        analysis_charts = req.charts or ["confusion_matrix", "roc_curve"]
    bootstrap_ci_metrics = analysis_metrics if req.compute_bootstrap_ci else []

    # If we have existing results for ALL WSIs, skip GPU inference and run analysis directly.
    # BUT: verify the referenced task still exists in the database first.
    # If the DB was reset or the task was deleted, the cached task ID is stale — fall through
    # to create a new task instead.
    if existing_results_count >= len(wsi_ids) and existing_validation_id:
        existing_task = await TrainingTaskRepository.get_by_id(
            db, existing_validation_id
        )
        if existing_task is None:
            logger.warning(
                f"Existing results reference task {existing_validation_id} which no longer exists in DB. "
                f"Ignoring cached results and creating a new task."
            )
        else:
            logger.info(
                f"Found existing inference results for {existing_results_count}/{len(wsi_ids)} WSIs, skipping GPU inference"
            )
            logger.info(f"  - Existing validation task: {existing_validation_id}")

            # Check if analysis results also already exist
            analysis_dir = uploads_dir / "logs" / "analysis" / existing_validation_id
            analysis_exists = False
            if analysis_dir.exists():
                for item in _iter_complete_analysis_runs(analysis_dir):
                    analysis_exists = True
                    break

            if analysis_exists:
                logger.info(
                    f"Both inference and analysis exist for {existing_validation_id}, skipping entirely"
                )
                return {
                    "task_id": existing_validation_id,
                    "status": TaskStatus.COMPLETED,
                    "total_wsi": len(wsi_ids),
                    "existing_results": existing_results_count,
                    "message": "External validation already completed (inference + analysis exist)",
                }

            logger.info(
                f"  - Running analysis directly with bootstrap_ci={req.compute_bootstrap_ci}"
            )

            # Run analysis directly on existing results
            await _auto_trigger_external_validation_analysis(
                task_id=existing_validation_id,
                model_task_id=trained_model_task_id,
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
    target_aggregation_level = (
        target_data_group.aggregation_level if target_data_group else "file"
    )
    validation_data_group = await DataGroupRepository.get_or_create(
        db,
        data_type=target_data_type,
        aggregation_level=target_aggregation_level,
        task_type="external_validation",
    )

    # Create task record in database (reuse TrainingTask table)
    from backend.database.models import TrainingTask

    validation_task = TrainingTask(
        task_id=validation_id,
        task_name=f"{model_task.task_name} → {target_dataset.name or req.dataset_id}",
        group_id=validation_data_group.group_id,
        user_id=effective_task_owner_user_id,
        task_description=f"Validate model '{trained_model.model_name}' on dataset '{target_dataset.name}'",
        status=TaskStatus.PENDING,
        progress=0,
        classes=trained_model.classes,
        preprocessing_config=model_task.preprocessing_config
        or {
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
            # Store pipeline params needed to re-submit after system restart (resume_interrupted_tasks)
            "model_task_type": model_task_type,  # e.g. "classification", "survival", "wsi_survival"
            "model_data_type": model_data_type,  # "wsi" or "patch"
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
        **pipeline_kwargs,
    )

    return {
        "task_id": validation_id,
        "status": TaskStatus.PENDING,
        "total_wsi": len(wsi_ids),
        "message": f"External validation queued. Use model '{trained_model.model_name}' on {len(wsi_ids)} WSIs from '{target_dataset.name or req.dataset_id}'",
    }


@router.get("/external-validation/completed")
async def get_completed_external_validations(
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
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
        task_id_str = _coerce_str(task.task_id)
        mc = task.model_config if isinstance(task.model_config, dict) else {}
        # Check if analysis results exist on disk
        analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id_str
        has_analysis = False
        if analysis_dir.exists():
            for item in _iter_complete_analysis_runs(analysis_dir):
                has_analysis = True
                break

        items.append(
            {
                "task_id": task_id_str,
                "model_id": mc.get("model_id"),
                "model_task_id": mc.get("model_task_id"),
                "dataset_id": mc.get("dataset_id"),
                "total_wsi": mc.get("total_wsi", 0),
                "results_count": mc.get("results_count", 0),
                "has_analysis": has_analysis,
                "created_at": (
                    task.created_at.isoformat() + "Z"
                    if isinstance(task.created_at, datetime)
                    else None
                ),
            }
        )

    return {"items": items}


@router.get("/external-validation/{task_id}")
async def get_validation_progress(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
        raise HTTPException(
            status_code=400, detail=f"Task {task_id} is not an external validation task"
        )

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


@router.get("/tasks/{task_id}/wsi-ids")
async def get_task_wsi_ids(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        await _require_task_access(
            user,
            task,
            db,
            forbidden_detail="You don't have permission to view this task",
        )
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
    return {"wsi_ids": wsi_ids}


@router.get("/tasks/{task_id}/analysis")
async def get_task_analysis(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
            with open(summary_file, "r") as f:
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
                select(User).where(cast(User.id, String).in_(list(user_ids)))
            )
            for row in result.all():
                user_obj = row[0]
                uid_str = str(user_obj.id)
                user_map[uid_str] = (
                    user_obj.nickname or user_obj.email
                )  # nickname or email

        # Resolve submitted_by from user_id to display name
        for analysis in analyses:
            submitted_by_id = analysis.get("submitted_by")
            if submitted_by_id:
                analysis["submitted_by"] = user_map.get(
                    submitted_by_id, submitted_by_id
                )
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
    db: AsyncSession = Depends(get_db),
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

    task, task_dataset_id = await _get_task_with_access(
        task_id,
        user,
        db,
        forbidden_detail="You don't have permission to analyze this task",
    )

    # Verify dataset read access is still valid. A pathologist's role-level GPU
    # capability bypasses _require_task_gpu_permission, so we need an explicit
    # dataset-access check here to honour grant revocations.
    if task_dataset_id and not user.is_admin():
        dataset = await DatasetRepository.get_by_id(db, task_dataset_id)
        if dataset:
            has_dataset_access = await check_dataset_access_permission(
                user,
                task_dataset_id,
                dataset.user_id,
                db,
                is_public=dataset.is_public,
                parent_dataset_id=dataset.parent_dataset_id,
            )
            if not has_dataset_access:
                raise HTTPException(
                    status_code=403,
                    detail="Dataset access has been revoked. Cannot submit new analysis.",
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
        if existing["status"] in (
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
            TaskStatus.PATCHING,
        ):
            # Return existing pending/queued/running analysis
            return {
                "task_id": task_id,
                "analysis_id": existing["analysis_id"],
                "status": existing["status"],
                "progress": existing["progress"],
                "message": "Analysis is already in progress",
            }

    # Get task_type from DataGroup relationship
    task_data_group = task.data_group
    task_type_str = task_data_group.task_type if task_data_group else "classification"

    # Build meaningful title based on task type
    is_external = task_type_str == "external_validation"
    if is_external:
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
    await state.create(
        analysis_id,
        task_id,
        str(user.id),
        title=title,
        analysis_type=analysis_type,
        task_category=task_category,
    )

    # Persist internal analysis run to DB for usage statistics.
    # External validation is already tracked via TrainingTask, so we only write here
    # for internal analyses to avoid double-counting.
    if not is_external:
        try:
            run_record = AnalysisRun(
                analysis_id=analysis_id,
                task_id=task_id,
                user_id=str(user.id),
            )
            db.add(run_record)
            await db.flush()
        except Exception as _ar_err:
            logger.warning(f"Failed to persist AnalysisRun record: {_ar_err}")

    # Check if GPU inference is needed (AI results missing)
    # External validation does not need GPU check here as it handles its own inference flow
    needs_gpu = False
    if not is_external:
        resources = await _check_task_resources(task_id, db)
        split_config = (
            task.preprocessing_config.get("split_config", {})
            if task.preprocessing_config
            else {}
        )
        is_kfold = (
            task_type_str not in ("segmentation", "patch_segmentation")
            and split_config.get("strategy", "random") == "k_fold"
        )
        if _analysis_requires_training_metrics(
            task_type_str, request.charts, is_kfold
        ) and not resources.get("has_training_metrics", True):
            raise HTTPException(
                status_code=409,
                detail=_missing_training_metrics_message(
                    task_id, resources, request.charts, is_kfold
                ),
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
        logger.info(
            f"Analysis task queued (needs GPU): task_id={task_id}, analysis_id={analysis_id}"
        )
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
        logger.info(
            f"Analysis task started (CPU-only, no queue): task_id={task_id}, analysis_id={analysis_id}"
        )

    # Return immediately with pending/queued status
    return {
        "task_id": task_id,
        "analysis_id": analysis_id,
        "status": TaskStatus.QUEUED if needs_gpu else TaskStatus.PENDING,
        "progress": 0,
        "message": "Analysis submitted successfully",
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
                    tasks = await state.get_all(
                        user_id=user_id_filter, max_age_minutes=10
                    )

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

    return make_sse_response(event_generator())


@router.get("/tasks/{task_id}/quick-analysis")
async def get_quick_analysis(
    task_id: str,
    metrics: Optional[str] = Query(
        None, description="Comma-separated metrics to return (e.g., accuracy,auc,f1)"
    ),
    charts: Optional[str] = Query(
        None,
        description="Comma-separated charts to return (e.g., roc_curve,confusion_matrix)",
    ),
    run_if_missing: bool = Query(True, description="Run analysis if not available"),
    bootstrap_ci_metrics: Optional[str] = Query(
        None,
        description="Comma-separated metrics to compute 95% CI for (e.g., accuracy,auc)",
    ),
    compute_bootstrap_ci: bool = Query(
        False, description="Legacy: compute CI for all metrics if true"
    ),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
            if existing["status"] in (
                TaskStatus.PENDING,
                TaskStatus.QUEUED,
                TaskStatus.PATCHING,
            ):
                # Return existing pending/queued/running analysis
                return {
                    "task_id": task_id,
                    "analysis_id": existing["analysis_id"],
                    "has_analysis": False,
                    "status": existing["status"],
                    "progress": existing["progress"],
                    "message": "Analysis is in progress",
                }

        # Get task_type from DataGroup relationship
        quick_task_data_group = task.data_group
        quick_task_type_str = (
            quick_task_data_group.task_type
            if quick_task_data_group
            else "classification"
        )

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
            default_metrics = [
                "accuracy",
                "precision",
                "recall",
                "specificity",
                "f1",
                "auc",
            ]
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
        split_config = (
            task.preprocessing_config.get("split_config", {})
            if task.preprocessing_config
            else {}
        )
        is_kfold = (
            quick_task_type_str not in ("segmentation", "patch_segmentation")
            and split_config.get("strategy", "random") == "k_fold"
        )
        if _analysis_requires_training_metrics(
            quick_task_type_str, default_charts, is_kfold
        ) and not resources.get("has_training_metrics", True):
            raise HTTPException(
                status_code=409,
                detail=_missing_training_metrics_message(
                    task_id, resources, default_charts, is_kfold
                ),
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
            logger.info(
                f"Analysis task queued (needs GPU): task_id={task_id}, analysis_id={analysis_id}"
            )
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
            logger.info(
                f"Analysis task started (CPU-only, no queue): task_id={task_id}, analysis_id={analysis_id}"
            )

        # Return immediately with pending/queued status
        return {
            "task_id": task_id,
            "analysis_id": analysis_id,
            "has_analysis": False,
            "status": TaskStatus.QUEUED if needs_gpu else TaskStatus.PENDING,
            "progress": 0,
            "message": "Analysis submitted to queue",
        }

    if latest_summary is None:
        return {
            "task_id": task_id,
            "has_analysis": False,
            "message": "No analysis results available. Set run_if_missing=true to generate.",
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
            k: v
            for k, v in result_metrics.items()
            if k in requested_metric_keys
            or k.replace("macro_", "") in requested_metric_keys
        }

    # Merge bootstrap CI into metrics if available
    # Frontend expects: MetricValue = number | { value: number; ci_lower: number; ci_upper: number }
    bootstrap_ci = latest_summary.get("bootstrap_ci", {})
    metrics_ci = bootstrap_ci.get("metrics_ci", {})
    if metrics_ci:
        merged_metrics = {}
        for metric_name, metric_value in result_metrics.items():
            # Check if we have CI for this metric (try both with and without macro_ prefix)
            ci_data = metrics_ci.get(metric_name) or metrics_ci.get(
                metric_name.replace("macro_", "")
            )
            if (
                ci_data
                and isinstance(ci_data, dict)
                and "ci_lower" in ci_data
                and "ci_upper" in ci_data
            ):
                # Merge CI data with the metric value
                merged_metrics[metric_name] = {
                    "value": ci_data.get("value", metric_value),
                    "ci_lower": ci_data["ci_lower"],
                    "ci_upper": ci_data["ci_upper"],
                }
            else:
                merged_metrics[metric_name] = metric_value
        result_metrics = merged_metrics

    # Filter charts if requested
    result_chart_data = latest_summary.get("chart_data", {})
    if requested_charts:
        result_chart_data = {
            k: v for k, v in result_chart_data.items() if k in requested_charts
        }

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
        },
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
    db: AsyncSession = Depends(get_db),
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

    file_path = (
        Config.get_uploads_dir()
        / "logs"
        / "analysis"
        / task_id
        / analysis_id
        / filename
    )

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(file_path)


@router.delete("/tasks/{task_id}/analysis/{analysis_id}")
async def delete_task_analysis(
    task_id: str,
    analysis_id: str,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
):
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task is not None:
        assert_owner(
            _coerce_str(task.user_id),
            user,
            "You don't have permission to delete this analysis",
        )

    analysis_dir = (
        Config.get_uploads_dir() / "logs" / "analysis" / task_id / analysis_id
    )

    if not analysis_dir.exists():
        raise HTTPException(
            status_code=404, detail=f"Analysis not found: {analysis_id}"
        )

    if not analysis_dir.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Invalid analysis ID: {analysis_id}"
        )

    if not user.is_admin():
        summary_file = analysis_dir / "summary.json"
        if summary_file.exists():
            try:
                with open(summary_file, "r") as f:
                    summary = json.load(f)
                submitted_by = summary.get("submitted_by")
                if submitted_by and submitted_by != str(user.id):
                    raise HTTPException(
                        status_code=403,
                        detail="You don't have permission to delete this analysis",
                    )
            except HTTPException:
                raise
            except Exception:
                pass

    try:
        await asyncio.to_thread(shutil.rmtree, analysis_dir)
        logger.info(f"Deleted analysis {analysis_id} for task {task_id}")
        return {
            "message": f"Analysis {analysis_id} deleted successfully",
            "task_id": task_id,
            "analysis_id": analysis_id,
        }
    except Exception as e:
        logger.error(f"Failed to delete analysis {analysis_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete analysis: {str(e)}"
        )


@router.get("/analysis/{analysis_id}/status")
async def get_analysis_status(
    analysis_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
                            "message": "Analysis completed",
                        }

        raise HTTPException(
            status_code=404, detail=f"Analysis not found: {analysis_id}"
        )

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
        "message": _get_analysis_status_message(
            str(analysis_state.get("status") or TaskStatus.PENDING),
            int(analysis_state.get("progress") or 0),
        ),
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
    db: AsyncSession = Depends(get_db),
):
    """
    Get AI analysis results for a WSI from database.
    Users can access the WSI itself via ownership or temporary dataset grant,
    but only admins can see all derived results; non-admins only see their own
    results for that WSI.

    Args:
        wsi_id: The WSI ID to get results for

    Returns:
        AI result data including predictions and probabilities
    """
    # Check WSI access permission (ownership or elevated dataset grant)
    wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    if wsi:
        has_access = await check_wsi_access_permission(
            user, _coerce_str(wsi.dataset_id), _coerce_str(wsi.user_id), db
        )
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view results for this WSI",
            )

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
    task_id: Optional[str] = Query(
        None, description="Delete results for specific task only"
    ),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
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

        assert_owner(
            _coerce_str(wsi.user_id),
            user,
            "You don't have permission to delete results for this WSI",
        )

        # Delete from database
        database_deleted = 0
        if task_id:
            # Delete specific task result
            result = await db.execute(
                sql_delete(AIResult).where(
                    AIResult.wsi_id == wsi_id, AIResult.task_id == task_id
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
        logger.info(storage_cleanup["summary"])

        return {
            "message": "AI results deleted successfully",
            "wsi_id": wsi_id,
            "task_id": task_id,
            "database_deleted": database_deleted,
            "storage_cleanup": storage_cleanup,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete AI results for WSI {wsi_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete AI results: {str(e)}"
        )


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
        logger.info(
            f"Starting analysis pipeline for task {training_task_id}, analysis_id={analysis_id}"
        )

        # Create database session with proper cleanup - use safe_session for background task
        async with safe_session() as db:
            # Get training task
            task = await TrainingTaskRepository.get_by_id(db, training_task_id)
            if not task:
                raise ValueError(f"Training task not found: {training_task_id}")

            # Determine workload: check if GPU inference and/or CI calculation is needed
            needs_gpu_inference = False
            has_ci_calculation = bool(
                bootstrap_ci_metrics and len(bootstrap_ci_metrics) > 0
            )

            # Check if K-Fold (K-Fold skips CI, uses mean ± std instead)
            # split_strategy is stored in preprocessing_config.split_config.strategy
            # NOTE: Only skip CI for internal analysis. External validation always allows CI
            # because it measures uncertainty on the new dataset, independent of training method.
            split_config = (
                task.preprocessing_config.get("split_config", {})
                if isinstance(task.preprocessing_config, dict)
                else {}
            )
            split_strategy = split_config.get("strategy", "random")
            is_segmentation_task = task_type_str in (
                "segmentation",
                "patch_segmentation",
            )
            is_kfold = not is_segmentation_task and split_strategy == "k_fold"
            if (
                is_kfold
                and has_ci_calculation
                and task_type_str != "external_validation"
            ):
                has_ci_calculation = (
                    False  # K-Fold doesn't use Bootstrap CI (internal analysis only)
                )

            if task_type_str != "external_validation":
                # Check if AI results exist
                task_id_str = _coerce_str(task.task_id)
                resources = await _check_task_resources(task_id_str, db)
                if _analysis_requires_training_metrics(
                    task_type_str, charts, is_kfold
                ) and not resources.get("has_training_metrics", True):
                    raise ValueError(
                        _missing_training_metrics_message(
                            task_id_str, resources, charts, is_kfold
                        )
                    )
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

            logger.info(
                f"Analysis pipeline workload: needs_gpu={needs_gpu_inference}, has_ci={has_ci_calculation}, "
                f"is_kfold={is_kfold}, progress_ranges: inference_end={inference_end}, "
                f"analysis_start={analysis_start}, ci_range={analysis_ci_start}-{analysis_ci_end}"
            )

            # Step 1: Run GPU inference if needed
            if needs_gpu_inference:
                # Create inference progress callback (0% to inference_end%)
                async def inference_progress(fraction: float):
                    progress = int(fraction * inference_end)
                    await state.update(analysis_id, progress=progress)

                await _run_inference_if_needed(
                    task,
                    db,
                    progress_callback=inference_progress,
                    assigned_device=assigned_device,
                )
                await state.update(analysis_id, progress=inference_end)

            # Create analysis request
            request = AnalysisRequest(
                metrics=metrics,
                charts=charts,
                description=description,
                bootstrap_ci_metrics=bootstrap_ci_metrics or [],
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
                        task,
                        request,
                        db,
                        progress_callback=update_progress,
                        progress_config=progress_config,
                        submitted_by=submitted_by,
                    )
                case "external_validation":
                    result = await _run_external_validation_analysis(
                        task,
                        request,
                        db,
                        progress_callback=update_progress,
                        progress_config=progress_config,
                        submitted_by=submitted_by,
                    )
                case "segmentation" | "patch_segmentation":
                    result = await _run_segmentation_analysis(
                        task,
                        request,
                        db,
                        progress_callback=update_progress,
                        progress_config=progress_config,
                        submitted_by=submitted_by,
                    )
                case _:
                    result = await _run_classification_analysis(
                        task,
                        request,
                        db,
                        progress_callback=update_progress,
                        progress_config=progress_config,
                        submitted_by=submitted_by,
                    )

            # Mark as completed
            await state.set_completed(analysis_id)
            logger.info(
                f"Analysis pipeline completed for task {training_task_id}, analysis_id={analysis_id}"
            )

    except asyncio.CancelledError:
        # Task was cancelled by user
        logger.info(
            f"Analysis pipeline cancelled for task {training_task_id}, analysis_id={analysis_id}"
        )
        await state.set_cancelled(analysis_id)
        raise  # Re-raise to properly handle task cancellation

    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Analysis pipeline failed for task {training_task_id}: {error_msg}"
        )
        await state.set_failed(analysis_id, error_msg)
        raise

    finally:
        # Always unregister task when done (completed, failed, or cancelled)
        state.unregister_task(analysis_id)
