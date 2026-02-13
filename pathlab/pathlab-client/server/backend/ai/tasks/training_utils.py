"""
Shared training utilities for all trainer implementations.

Common functionality extracted from individual trainers to avoid code duplication:
- Progress reporting via file-based progress store
- Short-lived database session management
- K-fold split detection helpers
- Classification metrics aggregation for K-fold training
"""
from __future__ import annotations

import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

import numpy as np
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
    confusion_matrix as sklearn_confusion_matrix,
)
import anyio

from backend.common.config import Config

_scoped_db_logger = logging.getLogger("ai.scoped_db")


async def safe_update_progress(session_maker, task_id: str, status: str, progress: int):
    """Write progress to shared file. Gateway reads the file directly — no DB, no HTTP.

    File: {uploads_dir}/progress/{task_id}  (atomic write via tmpfile + rename)
    Crash recovery: file persists on disk, Gateway reads last written value.
    Non-fatal: if file write fails, training continues.
    """
    from backend.common.progress_store import set_progress

    set_progress(task_id, progress)


# Keep backward-compatible alias
_safe_update_progress = safe_update_progress


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
        _scoped_db_logger.error(
            f"Database operation timed out after {timeout}s."
        )
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


def calculate_kfold_classification_metrics(
    uploads_root: Path,
    task_id: str,
    fold_keys: List[str],
    classes: List[str],
    splits_map: Optional[Dict[str, List[str]]] = None,
) -> tuple:
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
    ai_results_root = uploads_root / "ai_results"
    n_classes = len(classes)

    # Per-fold metrics (for aggregated calculation)
    fold_metrics = {
        "precision": [],
        "sensitivity": [],
        "specificity": [],
        "f1": [],
        "auc": [],
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
                result_file = ai_results_root / wsi_id / f"train_{task_id}_{fold_key}_result.json"
                if result_file.exists():
                    try:
                        with open(result_file, 'r') as f:
                            data = json.load(f)
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
        # Slow path: scan directory (fallback for backward compatibility)
        elif ai_results_root.exists():
            for wsi_dir in ai_results_root.iterdir():
                if wsi_dir.is_dir():
                    result_file = wsi_dir / f"train_{task_id}_{fold_key}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                if data.get("task_id") == task_id and data.get("fold_key") == fold_key:
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

        if not all_preds:
            continue

        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)
        all_probs = np.array(all_probs)

        # Calculate metrics using sklearn
        precision = precision_score(all_labels, all_preds, average='macro', zero_division=0)
        recall = recall_score(all_labels, all_preds, average='macro', zero_division=0)
        f1 = f1_score(all_labels, all_preds, average='macro', zero_division=0)

        # Specificity calculation (macro average)
        cm = sklearn_confusion_matrix(all_labels, all_preds, labels=list(range(n_classes)))
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
                auc_val = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
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

