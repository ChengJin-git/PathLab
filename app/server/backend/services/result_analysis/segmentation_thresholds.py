"""Exact 0.01-step threshold statistics, independent of image size at analysis time."""

import numpy as np

GRID = np.arange(101, dtype=np.float64) / 100


def probability_bins(probabilities):
    """Lossless decisions for the supported threshold grid, one byte per pixel."""
    probabilities = np.asarray(probabilities)
    return np.searchsorted(
        GRID.astype(probabilities.dtype), probabilities, side="left"
    ).astype(np.uint8)


def threshold_counts(probabilities, target):
    probabilities, target = np.asarray(probabilities), np.asarray(target)
    if probabilities.shape != target.shape or probabilities.ndim != 3:
        raise ValueError(
            "Segmentation probabilities and targets must have matching C×H×W shapes"
        )
    if not np.isfinite(probabilities).all() or np.any(
        (probabilities < 0) | (probabilities > 1)
    ):
        raise ValueError("Segmentation probabilities must be finite and in [0,1]")
    positive, negative = [], []
    for channel, mask in zip(probabilities, target):
        # Bin i contains scores exceeding exactly i grid thresholds. The grid is
        # cast to the prediction dtype to match torch's strict > comparison.
        bins = probability_bins(channel).ravel()
        mask = mask.ravel().astype(bool)
        positive.append(np.bincount(bins[mask], minlength=102).tolist())
        negative.append(np.bincount(bins[~mask], minlength=102).tolist())
    return {"positive": positive, "negative": negative}


def metrics_at_threshold(metadata, threshold):
    counts = metadata.get("threshold_counts")
    if not counts:
        if threshold != 0.5 and metadata.get("has_ground_truth"):
            raise ValueError(
                "Segmentation threshold statistics are missing; regenerate predictions"
            )
        return metadata.get("metrics", {})
    index = round(threshold * 100)
    if abs(threshold - index / 100) > 1e-8:
        raise ValueError("Segmentation thresholds must use increments of 0.01")
    positive, negative = np.asarray(counts["positive"], dtype=np.int64), np.asarray(
        counts["negative"], dtype=np.int64
    )
    if (
        positive.shape != negative.shape
        or positive.ndim != 2
        or positive.shape[1] != 102
        or np.any(positive < 0)
        or np.any(negative < 0)
    ):
        raise ValueError("Invalid segmentation threshold statistics")
    tp, fp = positive[:, index + 1 :].sum(1), negative[:, index + 1 :].sum(1)
    fn, tn = positive.sum(1) - tp, negative.sum(1) - fp

    def ratio(a, b):
        return np.divide(
            a, b, out=np.ones_like(np.asarray(a), dtype=float), where=b != 0
        )

    iou = ratio(tp, tp + fp + fn)
    dice = ratio(2 * tp, 2 * tp + fp + fn)
    return {
        "iou": float(iou.mean()),
        "miou": float(iou.mean()),
        "dice": float(dice.mean()),
        "f1": float(dice.mean()),
        "accuracy": float(ratio((tp + tn).sum(), (tp + fp + fn + tn).sum())),
        "precision": float(ratio(tp.sum(), (tp + fp).sum())),
        "recall": float(ratio(tp.sum(), (tp + fn).sum())),
    }
