"""
Shared training utilities for all trainer implementations.

Common functionality extracted from individual trainers to avoid code duplication:
- Short-lived database session management
- K-fold split detection helpers
- Classification metrics aggregation for K-fold training
"""

from __future__ import annotations

import json
import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import numpy as np
from sklearn.metrics import (
    roc_auc_score,
    precision_score,
    recall_score,
    f1_score,
    cohen_kappa_score,
    confusion_matrix as sklearn_confusion_matrix,
)
import anyio

from backend.common.config import Config
from backend.ai.result_store import AIResultStore

_scoped_db_logger = logging.getLogger("ai.scoped_db")


def calculate_progress_update_interval(
    total_items: int,
    target_updates: int = 20,
    max_interval: int = 200,
) -> int:
    """Return a throttled update interval for smoother progress reporting."""
    if total_items <= 0:
        return 1
    if target_updates <= 0:
        target_updates = 1
    return max(
        1, min((total_items + target_updates - 1) // target_updates, max_interval)
    )


def interpolate_progress(
    progress_start: int,
    progress_end: int,
    completed_items: int,
    total_items: int,
) -> int:
    """Interpolate a monotonic integer progress value within a stage."""
    if progress_end <= progress_start:
        return progress_end
    if total_items <= 0:
        return progress_end

    bounded_completed = max(0, min(completed_items, total_items))
    return progress_start + int(
        (bounded_completed / total_items) * (progress_end - progress_start)
    )


def save_ai_result_artifacts(
    uploads_root: Path,
    task_id: str,
    wsi_id: str,
    result_data: dict[str, Any],
    arrays: dict[str, np.ndarray[Any, Any]] | None = None,
    fold_suffix: str = "",
    finalize: bool = True,
    update_index: bool = True,
) -> Path | None:
    """Persist one WSI/image AI result into the task-level bundle."""
    fold_key = fold_suffix.removeprefix("_") if fold_suffix else None
    return AIResultStore(uploads_root).write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result=result_data,
        arrays=arrays,
        fold_key=fold_key,
        finalize=finalize,
        update_index=update_index,
    )


def finalize_ai_result_artifacts(uploads_root: Path, task_id: str) -> Path:
    """Finalize staged AI result artifacts for a training task."""
    return AIResultStore(uploads_root).write_task_bundle(task_id=task_id)


@asynccontextmanager
async def scoped_db(session_maker):
    """Create a short-lived database session for a single operation.

    Follows the same pattern as safe_session() in database.py:
    - The main operation is NOT shielded (allows timeout/cancellation to work)
    - Only cleanup (rollback/close) is shielded to ensure proper resource release

    Includes timeout protection to prevent indefinite blocking on
    long-running database operations.
    """
    timeout = Config.DB_OPERATION_TIMEOUT
    session = session_maker()
    try:
        async with asyncio.timeout(timeout):
            yield session
            await session.commit()
    except TimeoutError:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        _scoped_db_logger.error(f"Database operation timed out after {timeout}s.")
        raise
    except Exception:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await session.close()


def is_kfold_splits(splits_map: Dict[str, List[str]]) -> bool:
    """Check if splits_map represents k-fold configuration."""
    return any(key.startswith("fold_") for key in splits_map.keys())


def get_num_folds(splits_map: Dict[str, List[str]]) -> int:
    """Get number of folds from k-fold splits_map."""
    fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
    return len(fold_keys)


def should_load_resume_checkpoint(
    checkpoint: Mapping[str, object], fold_idx: Optional[int] = None
) -> bool:
    """Return whether a checkpoint may restore model state for this run.

    Regular training may load only regular checkpoints. K-fold training may load
    model/optimizer/history state only for the exact fold that wrote it.
    """
    checkpoint_type = checkpoint.get("type")
    if fold_idx is None:
        return checkpoint_type != "kfold"
    return checkpoint_type == "kfold" and checkpoint.get("fold_idx") == fold_idx


def classification_metrics_from_fold_results(
    fold_results: Mapping[str, Mapping[str, Mapping[str, float | None]]],
) -> Dict[str, List[float]]:
    """Rebuild aggregate classification metric arrays from completed folds."""
    metrics: Dict[str, List[float]] = {"accuracy": [], "auc": [], "loss": []}
    for fold_key in sorted(fold_results.keys()):
        val_metrics = fold_results.get(fold_key, {}).get("val_metrics", {})
        accuracy = val_metrics.get("accuracy")
        auc = val_metrics.get("auc")
        loss = val_metrics.get("loss")
        if accuracy is not None:
            metrics["accuracy"].append(accuracy)
        if auc is not None:
            metrics["auc"].append(auc)
        if loss is not None:
            metrics["loss"].append(loss)
    return metrics


def calculate_kfold_classification_metrics(
    uploads_root: Path,
    task_id: str,
    fold_keys: List[str],
    classes: List[str],
    splits_map: Optional[Dict[str, List[str]]] = None,
) -> tuple[Any, ...]:
    """
    Calculate comprehensive metrics for K-Fold classification training.

    Reads per-sample result JSON files saved during K-Fold training and
    calculates metrics using sklearn.

    Shared by WSI classification and patch classification trainers.

    Args:
        uploads_root: Root uploads directory (Path)
        task_id: Training task ID
        fold_keys: List of fold keys (e.g., ["fold_0", "fold_1"])
        classes: List of class names
        splits_map: Optional dict mapping fold_key to list of sample IDs.
                   If provided, directly reads files for known IDs (fast).
                   If None, falls back to scanning directory (slow, backward compat).

    Returns:
        Tuple of:
        - Dict with metric names as keys and {"mean": float, "std": float} as values
        - Dict with fold_key as keys and {metric_name: value} as values (per-fold)
        Metrics include: precision, sensitivity (recall), specificity, f1, auc
    """
    result_store = AIResultStore(uploads_root)
    n_classes = len(classes)

    # Per-fold metrics (for aggregated calculation)
    fold_metrics = {
        "precision": [],
        "sensitivity": [],
        "specificity": [],
        "f1": [],
        "auc": [],
        "weighted_kappa": [],
    }
    # Per-fold detailed values
    per_fold_metrics = {}

    for fold_key in fold_keys:
        # Collect predictions for this fold from saved JSON files
        all_preds = []
        all_labels = []
        all_probs = []  # For AUC calculation

        # Fast path: directly read files for known sample IDs
        if splits_map and fold_key in splits_map:
            wsi_ids = splits_map[fold_key]
            for wsi_id in wsi_ids:
                try:
                    data = result_store.read_result(
                        task_id, wsi_id, fold_key=fold_key, strict=True
                    )
                    pred = data.get("pred")
                    gt = data.get("ground_truth")
                    probs = data.get("probs", {})
                    if pred and gt:
                        pred_idx = classes.index(pred) if pred in classes else -1
                        gt_idx = classes.index(gt) if gt in classes else -1
                        if pred_idx >= 0 and gt_idx >= 0:
                            all_preds.append(pred_idx)
                            all_labels.append(gt_idx)
                            probs_arr = [probs.get(cls, 0.0) for cls in classes]
                            all_probs.append(probs_arr)
                except Exception:
                    continue
        # No filesystem scan fallback: migrated train artifacts must be read via result store.

        if not all_preds:
            continue

        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)
        all_probs = np.array(all_probs)

        # Calculate metrics using sklearn
        precision = precision_score(
            all_labels, all_preds, average="macro", zero_division=0
        )
        recall = recall_score(all_labels, all_preds, average="macro", zero_division=0)
        f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0)
        try:
            weighted_kappa = cohen_kappa_score(
                all_labels,
                all_preds,
                labels=list(range(n_classes)),
                weights="quadratic",
            )
            if np.isnan(weighted_kappa):
                weighted_kappa = None
        except Exception:
            weighted_kappa = None

        # Specificity calculation (macro average)
        cm = sklearn_confusion_matrix(
            all_labels, all_preds, labels=list(range(n_classes))
        )
        specificities = []
        for i in range(n_classes):
            tp = cm[i, i]
            fp = cm[:, i].sum() - tp
            fn = cm[i, :].sum() - tp
            tn = cm.sum() - tp - fp - fn
            spec = tn / (tn + fp) if (tn + fp) > 0 else 0
            specificities.append(spec)
        specificity = np.mean(specificities) if specificities else 0.0

        # AUC calculation
        try:
            if n_classes == 2:
                auc_val = roc_auc_score(all_labels, all_probs[:, 1])
            else:
                auc_val = roc_auc_score(
                    all_labels, all_probs, multi_class="ovr", average="macro"
                )
        except ValueError:
            auc_val = None

        # Filter out nan values before appending
        if not np.isnan(precision):
            fold_metrics["precision"].append(precision)
        if not np.isnan(recall):
            fold_metrics["sensitivity"].append(recall)
        if not np.isnan(specificity):
            fold_metrics["specificity"].append(specificity)
        if not np.isnan(f1):
            fold_metrics["f1"].append(f1)
        if auc_val is not None and not np.isnan(auc_val):
            fold_metrics["auc"].append(auc_val)
        if weighted_kappa is not None:
            fold_metrics["weighted_kappa"].append(weighted_kappa)

        # Store per-fold values (rounded to 4 decimal places), skip nan values
        per_fold_metrics[fold_key] = {}
        if not np.isnan(precision):
            per_fold_metrics[fold_key]["precision"] = round(float(precision), 4)
        if not np.isnan(recall):
            per_fold_metrics[fold_key]["sensitivity"] = round(float(recall), 4)
        if not np.isnan(specificity):
            per_fold_metrics[fold_key]["specificity"] = round(float(specificity), 4)
        if not np.isnan(f1):
            per_fold_metrics[fold_key]["f1"] = round(float(f1), 4)
        if auc_val is not None and not np.isnan(auc_val):
            per_fold_metrics[fold_key]["auc"] = round(float(auc_val), 4)
        if weighted_kappa is not None:
            per_fold_metrics[fold_key]["weighted_kappa"] = round(
                float(weighted_kappa), 4
            )

    # Calculate mean and std for each metric (rounded to 4 decimal places)
    aggregated = {}
    for metric_name, values in fold_metrics.items():
        if values:
            mean_val = float(np.mean(values))
            std_val = float(np.std(values))
            if not np.isnan(mean_val) and not np.isnan(std_val):
                aggregated[metric_name] = {
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                }

    return aggregated, per_fold_metrics


# ---------------------------------------------------------------------------
# Resume-checkpoint helpers
# ---------------------------------------------------------------------------


def save_resume_checkpoint_sync(path: Path, data: dict) -> None:
    """Atomically save a resume checkpoint via tmp-file + rename.

    Uses a sibling ``*.pth.tmp`` file so a crash mid-write never leaves a
    partially-written checkpoint.  Errors are silently swallowed so a failed
    save never aborts training.
    """
    import torch as _torch

    try:
        tmp = path.with_suffix(".pth.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        _torch.save(data, tmp)
        tmp.replace(path)
    except Exception:
        pass


def delete_resume_checkpoint(path: Path) -> None:
    """Delete the resume checkpoint if it exists.  Errors are silently ignored."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def check_training_interruption(task_id: str) -> Optional[str]:
    """Check for cancellation or permission revocation.

    Returns:
        "cancelled"          if cancellation was requested,
        "permission_revoked" if permission was revoked,
        None                 if no interruption.

    Call this inside training loops (e.g. every 50 batches).
    """
    from backend.ai.cancellation import is_task_cancelled
    from backend.ai.permission_revocation import is_permission_revoked

    if is_task_cancelled(task_id):
        return "cancelled"
    if is_permission_revoked(task_id):
        return "permission_revoked"
    return None
