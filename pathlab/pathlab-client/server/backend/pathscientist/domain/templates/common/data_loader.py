"""
FIXED — WSI Feature Data Loading

Loads pre-extracted feature tensors and split definitions.
This module runs inside the Docker sandbox and must NOT import any backend.* modules.

Expected data layout:
    /data/features/{wsi_id}.pt   — Tensor of shape (N_patches, D)
    /data/splits.json            — Split definitions (see below)

splits.json format:
{
    "train": ["wsi_001", "wsi_002", ...],
    "val":   ["wsi_010", ...],
    "test":  ["wsi_020", ...],
    "labels": {"wsi_001": 0, "wsi_002": 1, ...},
    "survival_times": {"wsi_001": 365.0, ...},   // optional
    "event_status":   {"wsi_001": 1, ...}         // optional
}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch

logger = logging.getLogger(__name__)


def load_features(
    features_dir: str = "/data/features",
    split_file: str = "/data/splits.json",
) -> Tuple[Dict[str, torch.Tensor], Dict[str, int], Dict[str, List[str]]]:
    """
    Load feature tensors and classification labels.

    Returns:
        features: {wsi_id: Tensor(N, D)}
        labels:   {wsi_id: int}
        splits:   {"train": [...], "val": [...], "test": [...]}
    """
    splits_data = _read_splits(split_file)

    labels: Dict[str, int] = splits_data.get("labels", {})
    splits: Dict[str, List[str]] = {
        k: splits_data[k] for k in ("train", "val", "test") if k in splits_data
    }

    # Collect all WSI IDs referenced in splits
    all_ids: set[str] = set()
    for ids in splits.values():
        all_ids.update(ids)

    features = _load_feature_tensors(features_dir, all_ids)

    logger.info(
        f"Loaded {len(features)} feature files, "
        f"{len(labels)} labels, "
        f"splits: {{{', '.join(f'{k}: {len(v)}' for k, v in splits.items())}}}"
    )

    return features, labels, splits


def load_survival_data(
    features_dir: str = "/data/features",
    split_file: str = "/data/splits.json",
) -> Tuple[
    Dict[str, torch.Tensor],
    Dict[str, float],
    Dict[str, int],
    Dict[str, List[str]],
]:
    """
    Load feature tensors and survival data.

    Returns:
        features: {wsi_id: Tensor(N, D)}
        times:    {wsi_id: float}  (survival times)
        events:   {wsi_id: int}    (event status: 1=event, 0=censored)
        splits:   {"train": [...], "val": [...], "test": [...]}
    """
    splits_data = _read_splits(split_file)

    times: Dict[str, float] = {
        k: float(v) for k, v in splits_data.get("survival_times", {}).items()
    }
    events: Dict[str, int] = {
        k: int(v) for k, v in splits_data.get("event_status", {}).items()
    }
    splits: Dict[str, List[str]] = {
        k: splits_data[k] for k in ("train", "val", "test") if k in splits_data
    }

    all_ids: set[str] = set()
    for ids in splits.values():
        all_ids.update(ids)

    features = _load_feature_tensors(features_dir, all_ids)

    logger.info(
        f"Loaded {len(features)} feature files, "
        f"{len(times)} survival times, "
        f"{len(events)} event statuses"
    )

    return features, times, events, splits


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_splits(split_file: str) -> dict:
    """Read and validate splits.json."""
    path = Path(split_file)
    if not path.exists():
        raise FileNotFoundError(f"Split file not found: {split_file}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Validate required keys
    for key in ("train", "val", "test"):
        if key not in data:
            raise ValueError(f"splits.json missing required key: {key!r}")

    return data


def _load_feature_tensors(
    features_dir: str,
    wsi_ids: set[str],
) -> Dict[str, torch.Tensor]:
    """Load .pt feature files for the given WSI IDs."""
    feat_dir = Path(features_dir)
    features: Dict[str, torch.Tensor] = {}

    for wsi_id in sorted(wsi_ids):
        pt_file = feat_dir / f"{wsi_id}.pt"
        if not pt_file.exists():
            # Try with .pth extension
            pt_file = feat_dir / f"{wsi_id}.pth"

        if pt_file.exists():
            tensor = torch.load(pt_file, map_location="cpu", weights_only=True)
            if isinstance(tensor, dict):
                # Some extractors save {"features": tensor, ...}
                tensor = tensor.get("features", tensor.get("feats", tensor))
            if isinstance(tensor, torch.Tensor):
                features[wsi_id] = tensor
            else:
                logger.warning(f"Skipping {wsi_id}: loaded object is not a Tensor")
        else:
            logger.warning(f"Feature file not found for {wsi_id}")

    if not features:
        raise RuntimeError(
            f"No feature files found in {features_dir} "
            f"for {len(wsi_ids)} requested WSI IDs"
        )

    return features
