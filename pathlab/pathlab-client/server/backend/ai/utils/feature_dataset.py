"""
WSI Feature Dataset for aggregator training.

This module provides PyTorch Dataset classes for loading pre-extracted WSI features
from .pt files.

Features are loaded on-demand from disk. A **module-level lazy cache** transparently
keeps recently-loaded tensors in CPU RAM (up to 50 % of available memory at import
time). This makes epoch 2+ dramatically faster when features live on a slow HDD,
while the first epoch still streams from disk.

Classes:
    WSIFeatureDataset: Basic dataset for slide-level training
    CaseFeatureDataset: Dataset for case-level training (concatenates features from slides in same case)

Cache API:
    clear_feature_cache()  – free all cached tensors (call after training).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import torch
from torch.utils.data import Dataset

from backend.ai.tasks.feature_cache import safe_load_features

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Module-level feature cache (shared across all Dataset instances)
# ---------------------------------------------------------------------------
_feature_cache: Dict[str, torch.Tensor] = {}   # cache_key -> CPU tensor
_cache_bytes: int = 0
_cache_budget: Optional[int] = None             # lazy-initialised


def _get_cache_budget() -> int:
    """Return the memory budget in bytes (50 % of available RAM, computed once)."""
    global _cache_budget
    if _cache_budget is None:
        try:
            page = os.sysconf("SC_PAGE_SIZE")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            avail = page * avail_pages
        except (ValueError, OSError):
            avail = 32 * (1024 ** 3)            # fallback: 32 GB
        _cache_budget = avail // 2
        logger.info(
            "Feature cache budget: %.1f GB (50%% of %.1f GB available)",
            _cache_budget / (1024 ** 3),
            avail / (1024 ** 3),
        )
    return _cache_budget


def _try_cache(key: str, tensor: torch.Tensor) -> None:
    """Store *tensor* (as a CPU copy) in the cache if budget allows."""
    global _cache_bytes
    if key in _feature_cache:
        return
    nbytes = tensor.nelement() * tensor.element_size()
    if _cache_bytes + nbytes > _get_cache_budget():
        return
    cpu_tensor = tensor.cpu() if tensor.device.type != "cpu" else tensor.clone()
    _feature_cache[key] = cpu_tensor
    _cache_bytes += nbytes


def _get_cached(key: str) -> Optional[torch.Tensor]:
    """Return the cached CPU tensor for *key*, or ``None``."""
    return _feature_cache.get(key)


def clear_feature_cache() -> None:
    """Release **all** cached feature tensors and reset the byte counter."""
    global _cache_bytes
    _feature_cache.clear()
    _cache_bytes = 0
    logger.info("Feature cache cleared")


class WSIFeatureDataset(Dataset[Any]):
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

    def __getitem__(self, idx: int) -> Tuple[Any, ...]:
        """
        Load and return sample for the given index.

        Classification: (features, label, wsi_id)
        Survival: (features, time, status, wsi_id)

        Uses the module-level lazy cache: on first access the tensor is loaded
        from disk and (if budget allows) stored on CPU.  Subsequent accesses
        read from the cache and do a fast CPU→GPU copy.
        """
        wsi_id = self.wsi_ids[idx]
        feat_path = self.features_dir / f"{wsi_id}.pt"
        cache_key = str(feat_path)

        # Fast path: cache hit → CPU→device copy
        cached = _get_cached(cache_key)
        if cached is not None:
            loaded_feats = cached.to(self.device, non_blocking=True) if self.device else cached
        else:
            # Slow path: load from disk (HDD)
            loaded_feats, load_error = safe_load_features(
                feat_path, delete_if_corrupted=True, device=self.device
            )
            if loaded_feats is None:
                raise RuntimeError(f"Corrupted feature file for {wsi_id}: {load_error}")
            # Try to cache on CPU for next epoch
            _try_cache(cache_key, loaded_feats)

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
        loaded_feats, _ = safe_load_features(feat_path, delete_if_corrupted=True)
        if loaded_feats is None:
            raise RuntimeError(f"Cannot load features from {feat_path}")

        self._feature_dim = loaded_feats.shape[1]
        return self._feature_dim

    def validate_features(self, min_patches: int = 0) -> Tuple[List[str], List[str]]:
        """
        Validate all feature files can be loaded. Delete corrupted files.
        Optionally check for minimum patch count.

        Args:
            min_patches: Minimum number of patches required. WSIs with fewer
                         patches are considered low-quality. 0 = no threshold.

        Returns:
            Tuple of (corrupted_ids, low_patch_ids):
            - corrupted_ids: wsi_ids with corrupted/missing feature files (deleted)
            - low_patch_ids: wsi_ids with fewer than min_patches patches
        """
        corrupted_ids = []
        low_patch_ids = []
        for wsi_id in self.wsi_ids:
            feat_path = self.features_dir / f"{wsi_id}.pt"
            if not feat_path.exists():
                corrupted_ids.append(wsi_id)
                continue
            loaded_feats, load_error = safe_load_features(
                feat_path, delete_if_corrupted=True
            )
            if loaded_feats is None:
                logger.warning(f"Corrupted feature file for {wsi_id}: {load_error}")
                corrupted_ids.append(wsi_id)
            elif min_patches > 0 and loaded_feats.shape[0] < min_patches:
                logger.warning(
                    f"Low-quality features for {wsi_id}: {loaded_feats.shape[0]} patches "
                    f"< minimum {min_patches}"
                )
                low_patch_ids.append(wsi_id)
        return corrupted_ids, low_patch_ids


class CaseFeatureDataset(Dataset[Any]):
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

    def __getitem__(self, idx: int) -> Tuple[Any, ...]:
        """
        Load, concatenate, and return features for a case.

        Classification: (features, label, case_id, wsi_ids, patch_counts)
        Survival: (features, time, status, case_id, wsi_ids, patch_counts)

        Uses the module-level lazy cache (same as WSIFeatureDataset).
        """
        case_id = self.case_ids[idx]
        wsi_ids = self.case_to_wsi.get(case_id, [])

        slide_feats = []
        patch_counts = []

        for wsi_id in wsi_ids:
            feat_path = self.features_dir / f"{wsi_id}.pt"
            cache_key = str(feat_path)

            cached = _get_cached(cache_key)
            if cached is not None:
                loaded_feats = cached.to(self.device, non_blocking=True) if self.device else cached
            else:
                loaded_feats, load_error = safe_load_features(
                    feat_path, delete_if_corrupted=True, device=self.device
                )
                if loaded_feats is None:
                    raise RuntimeError(f"Corrupted feature file for {wsi_id}: {load_error}")
                _try_cache(cache_key, loaded_feats)

            slide_feats.append(loaded_feats)
            patch_counts.append(loaded_feats.shape[0])

        # Concatenate all slide features
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
        loaded_feats, _ = safe_load_features(feat_path, delete_if_corrupted=True)
        if loaded_feats is None:
            raise RuntimeError(f"Cannot load features from {feat_path}")

        self._feature_dim = loaded_feats.shape[1]
        return self._feature_dim

    def validate_features(self, min_patches: int = 0) -> Tuple[List[str], List[str]]:
        """
        Validate all feature files can be loaded. Delete corrupted files.
        Optionally check for minimum patch count.

        Args:
            min_patches: Minimum number of patches required. WSIs with fewer
                         patches are considered low-quality. 0 = no threshold.

        Returns:
            Tuple of (corrupted_ids, low_patch_ids):
            - corrupted_ids: wsi_ids with corrupted/missing feature files (deleted)
            - low_patch_ids: wsi_ids with fewer than min_patches patches
        """
        corrupted_ids = []
        low_patch_ids = []
        for case_id in self.case_ids:
            for wsi_id in self.case_to_wsi.get(case_id, []):
                feat_path = self.features_dir / f"{wsi_id}.pt"
                if not feat_path.exists():
                    corrupted_ids.append(wsi_id)
                    continue
                loaded_feats, load_error = safe_load_features(
                    feat_path, delete_if_corrupted=True
                )
                if loaded_feats is None:
                    logger.warning(f"Corrupted feature file for {wsi_id}: {load_error}")
                    corrupted_ids.append(wsi_id)
                elif min_patches > 0 and loaded_feats.shape[0] < min_patches:
                    logger.warning(
                        f"Low-quality features for {wsi_id}: {loaded_feats.shape[0]} patches "
                        f"< minimum {min_patches}"
                    )
                    low_patch_ids.append(wsi_id)
        return corrupted_ids, low_patch_ids
