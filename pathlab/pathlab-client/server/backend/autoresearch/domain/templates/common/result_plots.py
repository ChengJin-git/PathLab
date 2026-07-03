"""Result plot helpers for AutoResearch training templates."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np


def _class_names_for_indices(class_names: Sequence[str] | None, n_classes: int) -> list[str]:
    if class_names:
        names = [str(name) for name in class_names]
        if len(names) >= n_classes:
            return names[:n_classes]
    return [str(index) for index in range(n_classes)]


def _score_matrix(y_score: Sequence[Any], n_samples: int, n_classes: int) -> np.ndarray | None:
    if n_samples == 0:
        return None
    scores = np.asarray(y_score, dtype=float)
    if scores.size == 0:
        return None
    if scores.ndim == 1:
        if scores.shape[0] != n_samples:
            return None
        if n_classes <= 2:
            return np.column_stack([1.0 - scores, scores])
        return None
    if scores.ndim == 2 and scores.shape[0] == n_samples and scores.shape[1] >= n_classes:
        return scores[:, :n_classes]
    return None


def _write_roc_curve(
    *,
    y_true: Sequence[int],
    y_score: Sequence[Any],
    output_path: Path,
    title: str,
    class_names: Sequence[str] | None = None,
) -> bool:
    from sklearn.metrics import auc, roc_curve
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    y_true_arr = np.asarray(y_true, dtype=int)
    classes = sorted(int(item) for item in set(y_true_arr.tolist()))
    if len(classes) < 2:
        return False
    n_classes = max(classes) + 1
    score_mat = _score_matrix(y_score, len(y_true_arr), n_classes)
    if score_mat is None:
        return False

    fig, ax = plt.subplots(figsize=(5.8, 4.6), dpi=160)
    if len(classes) == 2:
        positive = classes[-1]
        fpr, tpr, _ = roc_curve((y_true_arr == positive).astype(int), score_mat[:, positive])
        ax.plot(fpr, tpr, lw=2, label=f"AUC {auc(fpr, tpr):.3f}")
    else:
        names = _class_names_for_indices(class_names, n_classes)
        for class_idx in classes:
            fpr, tpr, _ = roc_curve((y_true_arr == class_idx).astype(int), score_mat[:, class_idx])
            ax.plot(fpr, tpr, lw=1.8, label=f"{names[class_idx]} AUC {auc(fpr, tpr):.3f}")

    ax.plot([0, 1], [0, 1], linestyle="--", color="#94a3b8", lw=1)
    ax.set_title(title)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return True


def _write_confusion_matrix(
    *,
    y_true: Sequence[int],
    y_pred: Sequence[int],
    output_path: Path,
    title: str,
    class_names: Sequence[str] | None = None,
) -> bool:
    from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    y_true_arr = np.asarray(y_true, dtype=int)
    y_pred_arr = np.asarray(y_pred, dtype=int)
    if y_true_arr.size == 0 or y_pred_arr.size == 0:
        return False
    labels = sorted(set(y_true_arr.tolist()) | set(y_pred_arr.tolist()))
    if not labels:
        return False
    n_classes = max(labels) + 1
    names = _class_names_for_indices(class_names, n_classes)
    display_labels = [names[index] for index in labels]
    cm = confusion_matrix(y_true_arr, y_pred_arr, labels=labels)
    fig, ax = plt.subplots(figsize=(5.2, 4.8), dpi=160)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=display_labels)
    disp.plot(ax=ax, cmap="Blues", colorbar=True, values_format="d")
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=35)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return True


def write_classification_result_figures(
    *,
    y_true: Sequence[int],
    y_pred: Sequence[int],
    y_score: Sequence[Any],
    output_dir: Path | str,
    prefix: str,
    class_names: Sequence[str] | None = None,
) -> dict[str, str]:
    """Write ROC and confusion-matrix PNGs for classification outputs.

    Returns a mapping of artifact kind to path for the figures that were
    actually written. ROC is skipped when labels/scores are insufficient.
    """
    out = Path(output_dir)
    written: dict[str, str] = {}
    display_prefix = prefix.replace("_", " ").title()
    roc_path = out / f"{prefix}_roc_curve.png"
    if _write_roc_curve(
        y_true=y_true,
        y_score=y_score,
        output_path=roc_path,
        title=f"{display_prefix} ROC Curve",
        class_names=class_names,
    ):
        written["roc_curve"] = str(roc_path)

    cm_path = out / f"{prefix}_confusion_matrix.png"
    if _write_confusion_matrix(
        y_true=y_true,
        y_pred=y_pred,
        output_path=cm_path,
        title=f"{display_prefix} Confusion Matrix",
        class_names=class_names,
    ):
        written["confusion_matrix"] = str(cm_path)
    return written
