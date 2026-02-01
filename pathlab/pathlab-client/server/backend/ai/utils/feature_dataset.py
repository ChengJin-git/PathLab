"""
WSI Feature Dataset for aggregator training.

This module provides PyTorch Dataset classes for loading pre-extracted WSI features
from .pt files. Features are loaded on-demand to prevent memory exhaustion with
large datasets (e.g., 2697 WSIs with 224GB total features).

Classes:
    WSIFeatureDataset: Basic dataset for slide-level training
    CaseFeatureDataset: Dataset for case-level training (concatenates features from slides in same case)

Performance optimization:
    When device is specified (e.g., 'cuda:0'), features are loaded directly to GPU,
    avoiding the CPU -> GPU transfer overhead in the training loop.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import torch
from torch.utils.data import Dataset

from backend.ai.tasks.feature_cache import safe_load_features


class WSIFeatureDataset(Dataset):
    """
    Dataset for loading pre-extracted WSI features on-demand.

    For classification: returns (features, label, wsi_id)
    For survival: returns (features, time, status, wsi_id)

    Features are loaded from disk when accessed and NOT cached in memory,
    allowing training on datasets larger than available RAM.

    Args:
        features_dir: Directory containing .pt feature files
        wsi_ids: List of WSI IDs to include in dataset
        labels: Dict mapping wsi_id -> label (int), for classification
        times: Dict mapping wsi_id -> event_time (float), for survival
        statuses: Dict mapping wsi_id -> event_status (int), for survival
        task_type: "classification" or "survival"
        device: Target device for features (e.g., 'cuda:0'). If specified,
                features are loaded directly to this device, avoiding
                CPU -> GPU transfer overhead in the training loop.
    """

    def __init__(
        self,
        features_dir: Path,
        wsi_ids: List[str],
        labels: Optional[Dict[str, int]] = None,
        times: Optional[Dict[str, float]] = None,
        statuses: Optional[Dict[str, int]] = None,
        task_type: str = "classification",
        device: Optional[str] = None,
    ):
        self.features_dir = Path(features_dir)
        self.wsi_ids = list(wsi_ids)
        self.labels = labels or {}
        self.times = times or {}
        self.statuses = statuses or {}
        self.task_type = task_type
        self.device = device
        self._feature_dim: Optional[int] = None

        # Validate all feature files exist
        for wsi_id in self.wsi_ids:
            feat_path = self.features_dir / f"{wsi_id}.pt"
            if not feat_path.exists():
                raise FileNotFoundError(f"Features not found for {wsi_id}: {feat_path}")

    def __len__(self) -> int:
        return len(self.wsi_ids)

    def __getitem__(self, idx: int) -> Tuple:
        """
        Load and return sample for the given index.

        Classification: (features, label, wsi_id)
        Survival: (features, time, status, wsi_id)

        When device is specified, features are loaded directly to GPU.
        """
        wsi_id = self.wsi_ids[idx]
        feat_path = self.features_dir / f"{wsi_id}.pt"

        # Direct GPU loading when device is specified - avoids CPU->GPU transfer overhead
        loaded_feats, load_error = safe_load_features(
            feat_path, delete_if_corrupted=False, device=self.device
        )
        if loaded_feats is None:
            raise RuntimeError(f"Corrupted feature file for {wsi_id}: {load_error}")

        if self.task_type == "survival":
            time = self.times.get(wsi_id, 0.0)
            status = self.statuses.get(wsi_id, 0)
            return loaded_feats, time, status, wsi_id
        else:
            label = self.labels.get(wsi_id, -1)
            return loaded_feats, label, wsi_id

    def get_feature_dim(self) -> int:
        """Get feature dimension by loading first sample."""
        if self._feature_dim is not None:
            return self._feature_dim

        if len(self.wsi_ids) == 0:
            raise ValueError("No WSI IDs in dataset")

        feat_path = self.features_dir / f"{self.wsi_ids[0]}.pt"
        loaded_feats, _ = safe_load_features(feat_path, delete_if_corrupted=False)
        if loaded_feats is None:
            raise RuntimeError(f"Cannot load features from {feat_path}")

        self._feature_dim = loaded_feats.shape[1]
        return self._feature_dim


class CaseFeatureDataset(Dataset):
    """
    Dataset for case-level training with on-demand feature loading and concatenation.

    For case-level datasets, slides with the same case_id have their features
    concatenated into a single tensor when accessed.

    For classification: returns (features, label, case_id, wsi_ids, patch_counts)
    For survival: returns (features, time, status, case_id, wsi_ids, patch_counts)

    Args:
        features_dir: Directory containing .pt feature files
        case_ids: List of case IDs to include in dataset
        case_to_wsi: Dict mapping case_id -> list of wsi_ids
        labels: Dict mapping case_id -> label (int), for classification
        times: Dict mapping case_id -> event_time (float), for survival
        statuses: Dict mapping case_id -> event_status (int), for survival
        task_type: "classification" or "survival"
        device: Target device for features (e.g., 'cuda:0'). If specified,
                features are loaded directly to this device, avoiding
                CPU -> GPU transfer overhead in the training loop.
    """

    def __init__(
        self,
        features_dir: Path,
        case_ids: List[str],
        case_to_wsi: Dict[str, List[str]],
        labels: Optional[Dict[str, int]] = None,
        times: Optional[Dict[str, float]] = None,
        statuses: Optional[Dict[str, int]] = None,
        task_type: str = "classification",
        device: Optional[str] = None,
    ):
        self.features_dir = Path(features_dir)
        self.case_ids = list(case_ids)
        self.case_to_wsi = case_to_wsi
        self.labels = labels or {}
        self.times = times or {}
        self.statuses = statuses or {}
        self.task_type = task_type
        self.device = device
        self._feature_dim: Optional[int] = None

        # Validate all feature files exist
        for case_id in self.case_ids:
            for wsi_id in self.case_to_wsi.get(case_id, []):
                feat_path = self.features_dir / f"{wsi_id}.pt"
                if not feat_path.exists():
                    raise FileNotFoundError(f"Features not found for {wsi_id}: {feat_path}")

    def __len__(self) -> int:
        return len(self.case_ids)

    def __getitem__(self, idx: int) -> Tuple:
        """
        Load, concatenate, and return features for a case.

        Classification: (features, label, case_id, wsi_ids, patch_counts)
        Survival: (features, time, status, case_id, wsi_ids, patch_counts)

        When device is specified, features are loaded directly to GPU.
        """
        case_id = self.case_ids[idx]
        wsi_ids = self.case_to_wsi.get(case_id, [])

        slide_feats = []
        patch_counts = []

        for wsi_id in wsi_ids:
            feat_path = self.features_dir / f"{wsi_id}.pt"
            # Direct GPU loading when device is specified
            loaded_feats, load_error = safe_load_features(
                feat_path, delete_if_corrupted=False, device=self.device
            )
            if loaded_feats is None:
                raise RuntimeError(f"Corrupted feature file for {wsi_id}: {load_error}")
            slide_feats.append(loaded_feats)
            patch_counts.append(loaded_feats.shape[0])

        # Concatenate all slide features (already on target device if specified)
        features = torch.cat(slide_feats, dim=0) if slide_feats else torch.empty(0)

        if self.task_type == "survival":
            time = self.times.get(case_id, 0.0)
            status = self.statuses.get(case_id, 0)
            return features, time, status, case_id, wsi_ids, patch_counts
        else:
            label = self.labels.get(case_id, -1)
            return features, label, case_id, wsi_ids, patch_counts

    def get_feature_dim(self) -> int:
        """Get feature dimension by loading first sample."""
        if self._feature_dim is not None:
            return self._feature_dim

        if len(self.case_ids) == 0:
            raise ValueError("No case IDs in dataset")

        case_id = self.case_ids[0]
        wsi_ids = self.case_to_wsi.get(case_id, [])
        if not wsi_ids:
            raise ValueError(f"No WSI IDs for case {case_id}")

        feat_path = self.features_dir / f"{wsi_ids[0]}.pt"
        loaded_feats, _ = safe_load_features(feat_path, delete_if_corrupted=False)
        if loaded_feats is None:
            raise RuntimeError(f"Cannot load features from {feat_path}")

        self._feature_dim = loaded_feats.shape[1]
        return self._feature_dim

