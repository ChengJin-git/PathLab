"""Stratified train/val/test split for cleaned CSV files.

Assigns the `split` column based on a fixed ratio (default 7:1:2),
stratified by the `label` column to maintain class distribution.
"""

import logging
from collections import Counter

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_RATIO = (0.7, 0.1, 0.2)  # train : val : test


def assign_split(
    df: pd.DataFrame,
    label_col: str = "label",
    split_col: str = "split",
    ratio: tuple[float, float, float] = DEFAULT_RATIO,
    seed: int = 42,
) -> pd.DataFrame:
    """Assign train/val/test split stratified by label.

    Args:
        df: Input DataFrame (must have label_col)
        label_col: Column name containing labels for stratification
        split_col: Column name to write split assignments into
        ratio: (train, val, test) ratio, must sum to 1.0
        seed: Random seed for reproducibility

    Returns:
        DataFrame with split_col updated
    """
    train_r, val_r, test_r = ratio
    assert abs(train_r + val_r + test_r - 1.0) < 1e-6, \
        f"Ratios must sum to 1.0, got {train_r + val_r + test_r}"

    rng = np.random.RandomState(seed)
    df = df.copy()

    # Initialize split column
    df[split_col] = ""

    if label_col not in df.columns:
        logger.warning(
            f"Label column '{label_col}' not found. "
            f"Falling back to non-stratified random split."
        )
        _assign_random(df, split_col, ratio, rng)
    else:
        # Stratified split: process each label group independently
        labels = df[label_col].fillna("_unknown_")
        unique_labels = labels.unique()

        for label in unique_labels:
            mask = labels == label
            indices = df.index[mask].tolist()
            rng.shuffle(indices)

            n = len(indices)
            n_train = max(1, round(n * train_r))
            n_val = max(0, round(n * val_r))
            # test gets the remainder
            n_test = n - n_train - n_val

            # Adjust if rounding caused issues
            if n_test < 0:
                n_val = n - n_train
                n_test = 0

            train_idx = indices[:n_train]
            val_idx = indices[n_train:n_train + n_val]
            test_idx = indices[n_train + n_val:]

            df.loc[train_idx, split_col] = "train"
            df.loc[val_idx, split_col] = "val"
            df.loc[test_idx, split_col] = "test"

    # Log summary
    split_counts = df[split_col].value_counts().to_dict()
    logger.info(f"Split assignment: {split_counts}")

    if label_col in df.columns:
        for label in df[label_col].unique():
            subset = df[df[label_col] == label]
            label_splits = subset[split_col].value_counts().to_dict()
            logger.info(f"  Label '{label}': {label_splits}")

    return df


def _assign_random(
    df: pd.DataFrame,
    split_col: str,
    ratio: tuple[float, float, float],
    rng: np.random.RandomState,
):
    """Fallback: assign splits randomly without stratification."""
    train_r, val_r, test_r = ratio
    indices = df.index.tolist()
    rng.shuffle(indices)

    n = len(indices)
    n_train = max(1, round(n * train_r))
    n_val = max(0, round(n * val_r))

    df.loc[indices[:n_train], split_col] = "train"
    df.loc[indices[n_train:n_train + n_val], split_col] = "val"
    df.loc[indices[n_train + n_val:], split_col] = "test"


def apply_split(
    csv_path: str,
    label_col: str = "label",
    split_col: str = "split",
    ratio: tuple[float, float, float] = DEFAULT_RATIO,
    seed: int = 42,
) -> pd.DataFrame:
    """Read a CSV, assign splits, save back, and return the DataFrame.

    Args:
        csv_path: Path to the CSV file to process
        label_col: Column for stratification
        split_col: Column to write splits into
        ratio: (train, val, test) ratio
        seed: Random seed

    Returns:
        DataFrame with splits assigned
    """
    df = pd.read_csv(csv_path)

    if split_col not in df.columns:
        logger.warning(f"Split column '{split_col}' not found in CSV, adding it.")

    df = assign_split(df, label_col, split_col, ratio, seed)

    # Save back
    df.to_csv(csv_path, index=False)

    # Print summary
    total = len(df)
    counts = df[split_col].value_counts()
    train_n = counts.get("train", 0)
    val_n = counts.get("val", 0)
    test_n = counts.get("test", 0)

    print(f"\n{'=' * 60}")
    print("SPLIT ASSIGNMENT")
    print(f"{'=' * 60}")
    print(f"  Total:  {total}")
    if total > 0:
        print(f"  Train:  {train_n} ({train_n/total*100:.1f}%)")
        print(f"  Val:    {val_n} ({val_n/total*100:.1f}%)")
        print(f"  Test:   {test_n} ({test_n/total*100:.1f}%)")
    else:
        print("  (no data to split)")

    if label_col in df.columns:
        print(f"\n  Per-label breakdown:")
        for label in sorted(df[label_col].dropna().unique()):
            subset = df[df[label_col] == label]
            lc = subset[split_col].value_counts()
            parts = []
            for s in ["train", "val", "test"]:
                if lc.get(s, 0) > 0:
                    parts.append(f"{s}={lc[s]}")
            print(f"    {label}: {', '.join(parts)}")

    print(f"\n  Saved to: {csv_path}")
    return df
