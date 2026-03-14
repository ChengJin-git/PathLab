"""
Analysis Metrics Module

Contains metric calculation, bootstrap CI computation, and chart generation
for classification and survival analysis results.
"""
import asyncio
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from backend.common.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process pool for CPU-intensive chart rendering (matplotlib at DPI 600).
#
# Why ProcessPoolExecutor instead of ThreadPoolExecutor / asyncio.to_thread?
#   Threads share the GIL with the event-loop thread.  Matplotlib's Python-
#   level figure layout, tight_layout(), and text rendering hold the GIL for
#   seconds at high DPI, which *effectively* blocks the event loop even when
#   the rendering itself runs in a background thread.  A separate **process**
#   has its own GIL, so the main event loop stays fully responsive.
# ---------------------------------------------------------------------------
_chart_process_pool: Optional[ProcessPoolExecutor] = None


def _get_chart_process_pool() -> ProcessPoolExecutor:
    """Return (lazily-created) process pool for chart generation."""
    global _chart_process_pool
    if _chart_process_pool is None:
        _chart_process_pool = ProcessPoolExecutor(max_workers=2)
    return _chart_process_pool


async def run_chart_in_process(func, *args):
    """Run *func* in a separate **process** so the event loop is never blocked.

    All arguments and return values must be picklable (top-level functions,
    plain dicts / lists / Paths – no lambdas, no defaultdicts).
    """
    loop = asyncio.get_event_loop()
    pool = _get_chart_process_pool()
    return await loop.run_in_executor(pool, func, *args)


def _write_json_sync(path, data):
    """Write *data* as JSON to *path* (sync – for ``asyncio.to_thread``)."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _calculate_all_metrics(
    labels: List[str],
    predictions: List[str],
    probs_list: List[Dict[str, Any]],
    all_classes: List[str],
    requested_metrics: List[str]
) -> Dict[str, Any]:
    """Calculate all requested metrics using sklearn."""
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        cohen_kappa_score,
        confusion_matrix as sklearn_confusion_matrix, roc_curve, auc
    )
    import numpy as np

    def safe_weighted_kappa(y_true: List[str], y_pred: List[str]) -> float:
        try:
            score = cohen_kappa_score(y_true, y_pred, labels=all_classes, weights="quadratic")
            return 0.0 if np.isnan(score) else float(score)
        except Exception as exc:
            logger.debug(f"Failed to compute weighted kappa: {exc}")
            return 0.0

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

    if "weighted_kappa" in requested_metrics:
        metrics["weighted_kappa"] = round(safe_weighted_kappa(labels, predictions), 4)

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
    probs_list: List[Dict[str, Any]],
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
        cohen_kappa_score,
        confusion_matrix as sklearn_confusion_matrix, roc_curve, auc
    )

    def safe_weighted_kappa(y_true: List[str], y_pred: List[str]) -> Optional[float]:
        try:
            score = cohen_kappa_score(y_true, y_pred, labels=all_classes, weights="quadratic")
            return None if np.isnan(score) else float(score)
        except Exception as exc:
            logger.debug(f"Bootstrap weighted kappa failed: {exc}")
            return None

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
    boot_weighted_kappa = []

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

            if "weighted_kappa" in requested_metrics:
                weighted_kappa = safe_weighted_kappa(boot_labels, boot_preds)
                if weighted_kappa is not None:
                    boot_weighted_kappa.append(weighted_kappa)

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
    if boot_weighted_kappa:
        metrics_ci["weighted_kappa"] = calc_ci(boot_weighted_kappa)

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
) -> Dict[str, Any]:
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
        plt.savefig(output_path, dpi=300)
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
        plt.savefig(output_path, dpi=300)
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to generate ROC chart: {e}")
        return None


def _get_loss_data_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """Sync file-I/O implementation for loss data retrieval."""
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

        # Check if this is K-Fold training
        if metrics.get("is_kfold"):
            folds = metrics.get("folds", {})
            fold_loss_data = {}

            for fold_name, fold_data in folds.items():
                history = fold_data.get("history", {})
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


async def _get_loss_data(task_id: str) -> Optional[Dict[str, Any]]:
    """Get loss data for ECharts rendering (file I/O offloaded to thread)."""
    return await asyncio.to_thread(_get_loss_data_sync, task_id)


def _get_kfold_metrics_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """Sync file-I/O implementation for K-Fold metrics retrieval."""
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


async def _get_kfold_metrics(task_id: str) -> Optional[Dict[str, Any]]:
    """Get K-Fold aggregated metrics (file I/O offloaded to thread)."""
    return await asyncio.to_thread(_get_kfold_metrics_sync, task_id)


def _render_loss_chart_sync(loss_data: Dict[str, Any], output_path: Path) -> Optional[Path]:
    """Render loss curve chart using matplotlib (sync, CPU-intensive).

    This is a pure sync function designed to be called via asyncio.to_thread().
    """
    try:
        plt = _setup_matplotlib_font()

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
        plt.savefig(output_path, dpi=300)
        plt.close(fig)

        return output_path
    except Exception as e:
        logger.error(f"Failed to render loss chart: {e}")
        return None


async def _generate_loss_chart(task_id: str, output_path: Path) -> Optional[Path]:
    """Generate loss curve chart from training metrics.

    Fetches data asynchronously, then offloads matplotlib rendering to a
    **separate process** so the GIL-heavy rendering never blocks the event loop.
    """
    try:
        loss_data = await _get_loss_data(task_id)
        if not loss_data or not loss_data.get("loss"):
            return None

        # NOTE: matplotlib chart generation is CPU-intensive — run in process
        return await run_chart_in_process(_render_loss_chart_sync, loss_data, output_path)
    except Exception as e:
        logger.error(f"Failed to generate loss chart: {e}")
        return None


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