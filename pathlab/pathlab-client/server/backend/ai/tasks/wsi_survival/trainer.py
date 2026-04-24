"""WSI Survival Analysis Trainer - Discrete Time Survival."""

from __future__ import annotations

import json
import asyncio
import time
import numpy as np
import math
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.utils.dataset import build_dataloader
from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset
from backend.ai.utils.vram_guard import (
    check_vram_before_model_load,
    check_vram_before_batch_processing,
    VRAMInsufficientError,
    VRAMExceededError,
)
from backend.ai.schemas import (
    TaskType,
    TaskStatus,
    TrainResponse,
    FeatureExtractionResponse,
)
from backend.common.coords_cache import compute_params_hash
from backend.ai.tasks.feature_cache import (
    find_cached_features,
    get_cache_save_path,
    create_symlink_to_cache,
    read_params_from_coords_h5,
    safe_load_features,
)
from backend.ai.tasks.wsi_classification.trainer import (
    WSIClassificationTrainer,
    MIN_PATCHES_THRESHOLD,
)
from backend.ai.tasks.training_utils import (
    scoped_db,
    safe_update_progress as _safe_update_progress,
    calculate_progress_update_interval,
    interpolate_progress,
    save_resume_checkpoint_sync,
    delete_resume_checkpoint,
    check_training_interruption,
)
from backend.database.repositories import (
    WSIRepository,
    TrainingTaskRepository,
    AIResultRepository,
)
from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException
from backend.ai.permission_revocation import (
    is_permission_revoked,
    PermissionRevokedException,
)
from backend.ai.tasks.wsi_survival.losses import (
    NLLSurvivalLoss,
    calculate_c_index,
    compute_risk_from_survival,
    compute_survival_from_hazards,
)
from backend.preprocessing.heatmap_preview_cache import (
    ensure_recommendation_preview_cache,
)
from backend.common.config import Config


# Throttle WSI-survival result persistence to reduce end-of-training I/O spikes.
SAVE_FILE_IO_MAX_WORKERS = 4
SAVE_FILE_IO_BATCH_SIZE = 32


class WSISurvivalTrainer(WSIClassificationTrainer):
    """
    WSI Survival Analysis Trainer.

    Inherits from WSIClassificationTrainer to reuse feature extraction logic.
    Overrides training loop for Discrete-Time Survival Analysis.
    """

    task_type = TaskType.WSI_SURVIVAL

    async def _load_survival_data(
        self,
        wsi_ids: List[str],
        session_maker: Any,
        logger: Any,
    ) -> tuple[Any, ...]:
        """Load survival data (times, statuses) for given WSI IDs."""
        times = []
        statuses = []
        valid_ids = []

        # Use batch query to avoid N+1 problem - short-lived session
        async with scoped_db(session_maker) as db:
            wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)

        for wsi_id in wsi_ids:
            wsi = wsi_map.get(wsi_id)
            if wsi and wsi.event_time is not None and wsi.event_status is not None:
                times.append(float(wsi.event_time))
                statuses.append(int(wsi.event_status))
                valid_ids.append(wsi_id)
            else:
                await logger.warning(f"Skipping WSI {wsi_id} - missing survival data")

        return times, statuses, valid_ids

    def _compute_bin_edges(
        self, times: List[float], statuses: List[int], n_bins: int
    ) -> np.ndarray[Any, Any]:
        """Compute quantile bin edges from uncensored times.
            - Ref: MOTCat: use only uncensored times for quantiles, but fall back to all times if no uncensored events.
        """
        times_arr = np.asarray(times, dtype=float)
        statuses_arr = np.asarray(statuses, dtype=int)
        if len(times_arr) == 0:
            raise ValueError("Cannot compute survival bin edges without times")

        uncensored_times = times_arr[statuses_arr == 1]
        source_times = uncensored_times if len(uncensored_times) > 0 else times_arr

        quantiles = np.linspace(0.0, 1.0, n_bins + 1)
        bin_edges = np.quantile(source_times, quantiles).astype(float)

        eps = 1e-6
        bin_edges[0] = float(times_arr.min()) - eps
        bin_edges[-1] = float(times_arr.max()) + eps

        if np.unique(bin_edges).size < n_bins + 1:
            bin_edges = np.linspace(
                float(times_arr.min()) - eps,
                float(times_arr.max()) + eps,
                n_bins + 1,
            )

        return bin_edges

    def _discretize_times(
        self, times: List[float], bin_edges: np.ndarray[Any, Any]
    ) -> List[int]:
        """Discretize times using left-closed/right-open bins.
        Ref: MOTCat uses np.searchsorted with side='right' to create left-closed/right-open bins, then subtracts 1 to get 0-based bin indices. This ensures that times exactly on a bin edge are assigned to the correct bin.
        """
        times_arr = np.asarray(times, dtype=float)
        labels = np.searchsorted(bin_edges, times_arr, side="right") - 1
        labels = np.clip(labels, 0, len(bin_edges) - 2)
        return labels.astype(int).tolist()

    def _build_survival_stratification_labels(
        self,
        sample_ids: List[str],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        n_bins: int,
    ) -> Dict[str, str]:
        """Build stratification labels: (disc_bin, censorship).
        Ref: MOTCat creates joint labels of (discrete_time_bin, censorship) for stratification, which helps ensure balanced representation of both time bins and event statuses across splits. The label format is "{disc_bin}_{1 - status}" so that censored samples (status=0) have "_1" and events (status=1) have "_0", allowing the stratification to consider both factors simultaneously.
        """
        valid_ids = [
            sample_id
            for sample_id in sample_ids
            if sample_id in times_map and sample_id in statuses_map
        ]
        if not valid_ids:
            return {}

        times = [float(times_map[sample_id]) for sample_id in valid_ids]
        statuses = [int(statuses_map[sample_id]) for sample_id in valid_ids]
        bin_edges = self._compute_bin_edges(times, statuses, n_bins)
        disc_labels = self._discretize_times(times, bin_edges)
        return {
            sample_id: f"{disc_label}_{1 - status}"
            for sample_id, disc_label, status in zip(valid_ids, disc_labels, statuses)
        }

    def _stratified_survival_split(
        self,
        sample_ids: List[str],
        stratify_map: Dict[str, Any],
        train_ratio: float = 0.7,
        val_ratio: float = 0.1,
        test_ratio: float = 0.2,
        seed: int = 42,
    ) -> tuple[Any, ...]:
        """
        Split sample_ids into train/val/test sets, stratified by provided labels.

        For survival training, callers pass joint labels of
        ``(discrete_time_bin, censorship)``
        Ref: MOTCat stratification to ensure balanced representation of both time bins and event statuses across splits
        .

        Args:
            sample_ids: List of sample IDs (case_ids or wsi_ids)
            stratify_map: Dict mapping sample_id -> stratification label
            train_ratio: Ratio for training set (default: 0.7)
            val_ratio: Ratio for validation set (default: 0.1)
            test_ratio: Ratio for test set (default: 0.2)
            seed: Random seed for reproducibility

        Returns:
            Tuple of (train_ids, val_ids, test_ids)
        """
        from sklearn.model_selection import train_test_split
        import random

        if len(sample_ids) < 3:
            # Too few samples, put all in train
            return list(sample_ids), [], []

        # Get statuses for stratification
        statuses = [stratify_map.get(sid, "0") for sid in sample_ids]

        # Check if we can do stratified split
        unique_statuses = set(statuses)
        status_counts = {s: statuses.count(s) for s in unique_statuses}
        min_count = min(status_counts.values()) if status_counts else 0
        can_stratify = len(unique_statuses) >= 2 and min_count >= 3

        if not can_stratify:
            # Fall back to random split
            random.seed(seed)
            shuffled = list(sample_ids)
            random.shuffle(shuffled)
            n = len(shuffled)
            n_train = int(n * train_ratio)
            n_val = int(n * val_ratio)
            return (
                shuffled[:n_train],
                shuffled[n_train : n_train + n_val],
                shuffled[n_train + n_val :],
            )

        try:
            # First split: separate test set
            train_val_ids, test_ids = train_test_split(
                sample_ids, test_size=test_ratio, random_state=seed, stratify=statuses
            )

            # Get labels for train_val
            train_val_statuses = [stratify_map.get(sid, "0") for sid in train_val_ids]

            # Second split: separate train and val from train_val
            # Relative val ratio within train_val
            relative_val_ratio = val_ratio / (train_ratio + val_ratio)

            train_ids, val_ids = train_test_split(
                train_val_ids,
                test_size=relative_val_ratio,
                random_state=seed,
                stratify=train_val_statuses,
            )

            return list(train_ids), list(val_ids), list(test_ids)

        except ValueError:
            # Fallback if stratification fails
            random.seed(seed)
            shuffled = list(sample_ids)
            random.shuffle(shuffled)
            n = len(shuffled)
            n_train = int(n * train_ratio)
            n_val = int(n * val_ratio)
            return (
                shuffled[:n_train],
                shuffled[n_train : n_train + n_val],
                shuffled[n_train + n_val :],
            )

    async def train_model(
        self,
        splits_map: Dict[str, List[str]],
        aggregator_name: str,
        num_classes: int,  # n_bins
        epochs: int,
        lr: float,
        weight_decay: float,
        logger: Any,
        session_maker: Any,
        optimizer: str = "adam",
        early_stopping_patience: int = 10,
        feature_extractor: str = "",
        seed: Optional[int] = 42,
    ) -> TrainResponse:
        """
        Train survival model with proper data splits.

        Args:
            num_classes: Number of discrete time bins (default: 4)
            optimizer: Optimizer type ('adam', 'sgd', 'adamw')
            weight_decay: Weight decay passed to the optimizer
            early_stopping_patience: Number of epochs to wait before early stopping
            seed: Random seed for reproducibility (default: 42)
        """
        # Set global random seeds for reproducibility
        if seed is not None:
            self._set_seed(seed)
            await logger.info(f"Random seed set to {seed} for reproducibility")

        # Collect all WSI IDs
        all_wsi_ids = []
        for ids in splits_map.values():
            all_wsi_ids.extend(ids)
        all_wsi_ids = list(set(all_wsi_ids))

        # Features directory (will be loaded on-demand by Dataset)
        features_dir = self.uploads_root / "training" / self.task_id / "features"

        # Validate feature files and re-extract any corrupted ones
        unrepaired_ids: List[str] = []
        if feature_extractor:
            unrepaired_ids = await self._validate_and_repair_features(
                features_dir, all_wsi_ids, feature_extractor, logger, session_maker
            )

        # Layer 6: Final pre-training filter — runs in thread to avoid blocking event loop
        def _final_feature_filter_sync(wsi_ids, already_invalid, feat_dir):
            invalid = set(already_invalid)
            blank_wsi_ids = []
            low_quality_details = []
            for wsi_id in wsi_ids:
                if wsi_id in invalid:
                    continue
                feat_path = feat_dir / f"{wsi_id}.pt"
                if not feat_path.exists():
                    blank_wsi_ids.append(wsi_id)
                    invalid.add(wsi_id)
                    continue
                loaded_feats, _ = safe_load_features(
                    feat_path, delete_if_corrupted=False
                )
                if loaded_feats is None:
                    invalid.add(wsi_id)
                elif loaded_feats.shape[0] < MIN_PATCHES_THRESHOLD:
                    low_quality_details.append((wsi_id, loaded_feats.shape[0]))
                    invalid.add(wsi_id)
            return invalid, blank_wsi_ids, low_quality_details

        invalid_wsi_ids, blank_wsi_ids, low_quality_details = await asyncio.to_thread(
            _final_feature_filter_sync, all_wsi_ids, unrepaired_ids, features_dir
        )

        for wsi_id in blank_wsi_ids:
            await logger.warning(
                f"Skipping {wsi_id}: no feature file (0 patches during preprocessing — blank or no detectable tissue).",
                metadata={"wsi_id": wsi_id, "reason": "no_feature_file"},
            )

        for wsi_id, patch_count in low_quality_details:
            await logger.warning(
                f"Low-quality WSI {wsi_id}: {patch_count} patches < {MIN_PATCHES_THRESHOLD}",
            )

        if invalid_wsi_ids:
            original_count = len(all_wsi_ids)
            all_wsi_ids = [wid for wid in all_wsi_ids if wid not in invalid_wsi_ids]
            valid_ratio = len(all_wsi_ids) / original_count if original_count > 0 else 0

            await logger.warning(
                f"Filtered {len(invalid_wsi_ids)} invalid WSIs: {len(all_wsi_ids)}/{original_count} remaining ({valid_ratio:.1%})",
                metadata={
                    "filtered_count": len(invalid_wsi_ids),
                    "remaining_count": len(all_wsi_ids),
                    "valid_ratio": round(valid_ratio, 4),
                    "filtered_ids": sorted(invalid_wsi_ids)[:20],
                },
            )

            if valid_ratio < 0.30:
                raise ValueError(
                    f"有效 WSI 不足 30%（当前 {valid_ratio:.1%}，{len(all_wsi_ids)}/{original_count}），"
                    f"请检查数据质量。被过滤的 WSI: {sorted(invalid_wsi_ids)[:10]}"
                )

            splits_map = {
                split_name: [wid for wid in ids if wid not in invalid_wsi_ids]
                for split_name, ids in splits_map.items()
            }

        # Load survival data using batch query (avoid N+1 problem) - short-lived session
        async with scoped_db(session_maker) as db:
            wsi_map = await WSIRepository.get_by_ids(db, all_wsi_ids)

        times_map = {}
        statuses_map = {}
        valid_ids = []

        for wsi_id in all_wsi_ids:
            wsi = wsi_map.get(wsi_id)
            if wsi and wsi.event_time is not None and wsi.event_status is not None:
                times_map[wsi_id] = float(wsi.event_time)
                statuses_map[wsi_id] = int(wsi.event_status)
                valid_ids.append(wsi_id)
            else:
                await logger.warning(f"Skipping WSI {wsi_id} - missing survival data")

        if not valid_ids:
            raise ValueError("No WSIs with valid survival data found")

        # Filter splits_map to only include valid IDs
        filtered_splits = {}
        for split_name, ids in splits_map.items():
            filtered_splits[split_name] = [
                wsi_id for wsi_id in ids if wsi_id in valid_ids
            ]

        # Check if this is a case-level dataset - short-lived session
        async with scoped_db(session_maker) as db:
            aggregation_level = (
                await TrainingTaskRepository.get_dataset_aggregation_level(
                    db, self.task_id
                )
            )
        is_case_level = aggregation_level == "case"

        # Build case_level_ctx if case-level (without loading features into memory)
        case_level_ctx = None
        if is_case_level:
            async with scoped_db(session_maker) as db:
                case_id_map = await TrainingTaskRepository.get_wsi_case_ids(
                    db, self.task_id
                )
            # Filter to only include valid_ids
            case_id_map = {k: v for k, v in case_id_map.items() if k in valid_ids}

            # Build case_to_wsi mapping and case-level times/statuses
            case_to_wsi: Dict[str, List[str]] = {}
            for wsi_id, case_id in case_id_map.items():
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # Build case-level times and statuses (use first slide's values)
            case_times: Dict[str, float] = {}
            case_statuses: Dict[str, int] = {}
            for case_id, wsi_ids in case_to_wsi.items():
                first_wsi = wsi_ids[0]
                if first_wsi in times_map:
                    case_times[case_id] = times_map[first_wsi]
                if first_wsi in statuses_map:
                    case_statuses[case_id] = statuses_map[first_wsi]

            # Convert splits to case-level
            case_splits = self._convert_splits_to_case_level(
                filtered_splits, case_id_map
            )

            case_level_ctx = {
                "case_id_map": case_id_map,
                "case_splits": case_splits,
                "case_to_wsi": case_to_wsi,
                "case_times": case_times,
                "case_statuses": case_statuses,
                "original_times": times_map,
                "original_statuses": statuses_map,
            }

            await logger.info(
                f"Case-level survival training: {len(case_to_wsi)} cases from {len(valid_ids)} slides",
                metadata={
                    "aggregation_level": "case",
                    "num_cases": len(case_to_wsi),
                    "num_slides": len(valid_ids),
                },
            )

        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        is_kfold = self._is_kfold_splits(filtered_splits)

        effective_seed = seed if seed is not None else 42

        if is_kfold:
            return await self._train_survival_kfold(
                filtered_splits,
                features_dir,
                times_map,
                statuses_map,
                aggregator_name,
                num_classes,
                epochs,
                lr,
                weight_decay,
                logger,
                session_maker,
                model_id,
                model_dir,
                optimizer,
                early_stopping_patience,
                case_level_ctx,
                seed=effective_seed,
            )
        else:
            return await self._train_survival_regular(
                filtered_splits,
                features_dir,
                times_map,
                statuses_map,
                aggregator_name,
                num_classes,
                epochs,
                lr,
                weight_decay,
                logger,
                session_maker,
                model_id,
                model_dir,
                optimizer,
                early_stopping_patience,
                case_level_ctx,
                seed=effective_seed,
            )

    async def _train_survival_regular(
        self,
        splits_map: Dict[str, List[str]],
        features_dir: Path,
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        weight_decay: float,
        logger: Any,
        session_maker: Any,
        model_id: str,
        model_dir: Path,
        optimizer_type: str = "adam",
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
        seed: int = 42,
    ) -> TrainResponse:
        """Train with regular train/val/test splits."""
        from torch.utils.data import DataLoader

        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            training_times = case_level_ctx["case_times"]
            training_statuses = case_level_ctx["case_statuses"]
            working_splits = case_splits
            case_to_wsi = case_level_ctx["case_to_wsi"]
            case_id_map = case_level_ctx["case_id_map"]
        else:
            training_times = times_map
            training_statuses = statuses_map
            working_splits = splits_map

        train_ids = list(
            working_splits.get("train", [])
        )  # Make a copy to avoid modifying original
        val_ids = list(working_splits.get("val", []))
        test_ids = list(working_splits.get("test", []))

        if not train_ids:
            raise ValueError("No training samples in splits_map")

        unit_name = "cases" if is_case_level else "samples"

        n_bins = max(2, num_classes)

        # Auto-create splits using event_status stratification so the trainer's
        # fallback split behavior stays aligned with dataset label export and
        # task creation logic.
        auto_split_created = False
        if not val_ids and not test_ids and len(train_ids) >= 3:
            # No val and no test provided: create full 7:1:2 split
            train_ids, val_ids, test_ids = self._stratified_survival_split(
                train_ids,
                training_statuses,
                train_ratio=0.7,
                val_ratio=0.1,
                test_ratio=0.2,
                seed=seed,
            )
            auto_split_created = True
            split_type = "train/val/test (7:1:2)"
        elif not val_ids and len(train_ids) >= 2:
            # Only val is missing (test exists): create val from train (90:10)
            train_ids, val_ids, _ = self._stratified_survival_split(
                train_ids,
                training_statuses,
                train_ratio=0.9,
                val_ratio=0.1,
                test_ratio=0.0,
                seed=seed,
            )
            auto_split_created = True
            split_type = "val (10% from train)"
        elif not test_ids and len(train_ids) >= 2:
            # Only test is missing (val exists): create test from train (80:20)
            train_ids, _, test_ids = self._stratified_survival_split(
                train_ids,
                training_statuses,
                train_ratio=0.8,
                val_ratio=0.0,
                test_ratio=0.2,
                seed=seed,
            )
            auto_split_created = True
            split_type = "test (20% from train)"

        if auto_split_created:
            # Log event distribution in splits
            train_events = sum(
                1 for sid in train_ids if training_statuses.get(sid, 0) == 1
            )
            val_events = sum(1 for sid in val_ids if training_statuses.get(sid, 0) == 1)
            test_events = sum(
                1 for sid in test_ids if training_statuses.get(sid, 0) == 1
            )
            await logger.info(
                f"Auto-created {split_type} split (stratified by survival bin + censorship)",
                metadata={
                    "train": len(train_ids),
                    "val": len(val_ids),
                    "test": len(test_ids),
                    "train_events": train_events,
                    "val_events": val_events,
                    "test_events": test_events,
                    "auto_split": True,
                    "aggregation_level": "case" if is_case_level else "file",
                },
            )

        await logger.info(
            f"Training survival model with splits: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)} {unit_name}",
            metadata={
                "train": len(train_ids),
                "val": len(val_ids),
                "test": len(test_ids),
                "aggregation_level": "case" if is_case_level else "file",
            },
        )

        # Compute global bin edges once for the full dataset, following MOTCat.
        all_ids = train_ids + val_ids + test_ids
        all_times = [training_times[sample_id] for sample_id in all_ids]
        all_statuses = [training_statuses[sample_id] for sample_id in all_ids]
        bin_edges = self._compute_bin_edges(all_times, all_statuses, n_bins)

        # Discretize all times using dataset-global bin edges
        discretized_labels = self._discretize_times(all_times, bin_edges)

        # Create label tensors indexed by sample_id (wsi_id or case_id)
        y_bins_map = {
            sample_id: discretized_labels[i] for i, sample_id in enumerate(all_ids)
        }
        y_events_map = {sample_id: all_statuses[i] for i, sample_id in enumerate(all_ids)}
        # Create datasets based on data level
        # Pass device for direct GPU loading - avoids CPU->GPU transfer overhead
        if is_case_level:
            # Create CaseFeatureDataset for case-level training
            train_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=train_ids,
                case_to_wsi=case_to_wsi,
                times=training_times,
                statuses=training_statuses,
                task_type="survival",
                device=self.device,
            )
            val_dataset = (
                CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=val_ids,
                    case_to_wsi=case_to_wsi,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                if val_ids
                else None
            )
            test_dataset = (
                CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=test_ids,
                    case_to_wsi=case_to_wsi,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                if test_ids
                else None
            )
        else:
            # Create WSIFeatureDataset for slide-level training
            train_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=train_ids,
                times=training_times,
                statuses=training_statuses,
                task_type="survival",
                device=self.device,
            )
            val_dataset = (
                WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=val_ids,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                if val_ids
                else None
            )
            test_dataset = (
                WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=test_ids,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                if test_ids
                else None
            )

        # Determine feature dimension from dataset (works for both WSI and Case datasets)
        in_dim = train_dataset.get_feature_dim()

        # Build model
        model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=n_bins).to(
            self.device
        )
        criterion = NLLSurvivalLoss(alpha=0.0)

        # Dynamic optimizer selection
        optimizer_type_lower = optimizer_type.lower()
        if optimizer_type_lower == "sgd":
            optimizer = optim.SGD(
                model.parameters(), lr=lr, momentum=0.9, weight_decay=weight_decay
            )
        elif optimizer_type_lower == "adamw":
            optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
        else:  # Default to adam
            optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        # Create DataLoader for training (batch_size=1 for WSI, no collate needed)
        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        train_loader = DataLoader(
            train_dataset,
            batch_size=1,
            shuffle=True,
            num_workers=0,
        )

        history = {
            "train_loss": [],
            "train_c_index": [],
            "val_loss": [],
            "val_c_index": [],
        }
        best_val_loss = float("inf")
        best_val_c_index = 0.0
        best_epoch: Optional[int] = None
        best_state_dict = None
        epochs_without_improvement = 0
        start_epoch = 1

        _resume_path = model_dir / "resume_checkpoint.pth"
        if _resume_path.exists():
            try:
                _ckpt = torch.load(_resume_path, map_location="cpu", weights_only=False)
                model.load_state_dict(_ckpt["model_state_dict"])
                optimizer.load_state_dict(_ckpt["optimizer_state_dict"])
                scheduler.load_state_dict(_ckpt["scheduler_state_dict"])
                history = _ckpt["history"]
                history.setdefault("val_c_index", [])
                best_val_loss = _ckpt["best_val_loss"]
                best_val_c_index = _ckpt["best_val_c_index"]
                best_epoch = _ckpt.get("best_epoch")
                best_state_dict = _ckpt["best_state_dict"]
                epochs_without_improvement = _ckpt["epochs_without_improvement"]
                start_epoch = _ckpt["epoch"] + 1
                await logger.info(
                    f"Resumed survival training from epoch {_ckpt['epoch']}",
                    metadata={"resumed_from_epoch": _ckpt["epoch"]},
                )
            except Exception as _e:
                await logger.info(
                    f"Could not load resume checkpoint ({_e}), starting from epoch 1",
                    metadata={"resume_error": str(_e)},
                )

        model.train()
        for epoch in range(start_epoch, epochs + 1):
            # Check for cancellation or permission revocation at each epoch start
            if is_task_cancelled(self.task_id):
                await logger.info(
                    f"Training cancelled by user/timeout at epoch {epoch}"
                )
                # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                del model, optimizer, criterion
                torch.cuda.empty_cache()  # Release cached GPU memory
                raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")
            if is_permission_revoked(self.task_id):
                await logger.info(
                    f"Training stopped: permission revoked at epoch {epoch}"
                )
                del model, optimizer, criterion
                torch.cuda.empty_cache()  # Release cached GPU memory
                raise PermissionRevokedException(
                    f"Training stopped at epoch {epoch}: permission revoked by admin"
                )

            epoch_start_time = time.time()

            # Run training epoch in thread pool to avoid blocking the event loop.
            # DataLoader iteration triggers torch.load() and GPU ops are blocking.
            (
                running_loss,
                epoch_preds,
                epoch_times,
                epoch_statuses,
                _,
                stop_reason,
            ) = await asyncio.to_thread(
                self._run_one_epoch_survival,
                train_loader,
                model,
                criterion,
                optimizer,
                self.device,
                self.task_id,
                y_bins_map,
                y_events_map,
                is_case_level,
            )

            if stop_reason == "cancelled":
                del model, optimizer, criterion
                torch.cuda.empty_cache()
                raise TrainingCancelledException(
                    f"Training cancelled during epoch {epoch} loop"
                )
            if stop_reason == "permission_revoked":
                del model, optimizer, criterion
                torch.cuda.empty_cache()
                raise PermissionRevokedException(
                    f"Training stopped during epoch {epoch}: permission revoked by admin"
                )

            epoch_loss = running_loss / max(1, len(train_ids))
            train_c_index = calculate_c_index(
                epoch_times, epoch_preds, epoch_statuses
            )
            history["train_loss"].append(epoch_loss)
            history["train_c_index"].append(train_c_index)

            # Validation
            val_loss, val_c_index = None, None
            if val_dataset:
                val_loss, val_c_index = await asyncio.to_thread(
                    self._evaluate_survival,
                    model,
                    val_dataset,
                    training_times,
                    training_statuses,
                    y_bins_map,
                    y_events_map,
                    criterion,
                    is_case_level,
                )
                history["val_loss"].append(val_loss)
                history["val_c_index"].append(val_c_index)

                # Select best model based on C-Index (higher is better)
                # Fallback to loss (lower is better) if C-Index is invalid
                is_improvement = False
                selection_metric_key = "val_c_index"
                selection_metric_label = "Val C-Index"
                selection_metric_value = val_c_index
                if val_c_index is not None and val_c_index > best_val_c_index:
                    best_val_c_index = val_c_index
                    is_improvement = True
                elif val_c_index is None or val_c_index == best_val_c_index:
                    # Tie-breaker: use loss
                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                        is_improvement = True
                        selection_metric_key = "val_loss"
                        selection_metric_label = "Val Loss"
                        selection_metric_value = val_loss

                if is_improvement:
                    # best_val_c_index updated above if applicable
                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                    best_state_dict = {
                        k: v.cpu().clone() for k, v in model.state_dict().items()
                    }
                    best_epoch = epoch
                    epochs_without_improvement = 0
                    best_metadata = {
                        "epoch": epoch,
                        selection_metric_key: selection_metric_value,
                        "val_loss": val_loss,
                        "val_c_index": val_c_index,
                    }
                    await logger.info(
                        f"Best validation model updated at epoch {epoch} | "
                        f"{selection_metric_label}: {selection_metric_value:.4f}",
                        metadata=best_metadata,
                    )
                else:
                    epochs_without_improvement += 1

            # Update learning rate before logging so live LR matches the next-epoch optimizer state.
            scheduler.step()
            current_lr = optimizer.param_groups[0]["lr"]
            epoch_time = time.time() - epoch_start_time

            # Prepare metadata with train_ and val_ prefixes
            metadata = {
                "epoch": epoch,
                "train_loss": epoch_loss,
                "train_c_index": train_c_index,
                "lr": current_lr,
                "epoch_time_sec": epoch_time,
            }
            log_parts = [
                f"Epoch {epoch}/{epochs}",
                f"Train Loss: {epoch_loss:.4f}",
                f"Train C-Index: {train_c_index:.4f}",
            ]
            if val_dataset:
                log_parts.append(f"Val Loss: {val_loss:.4f}")
                log_parts.append(f"Val C-Index: {val_c_index:.4f}")
                metadata.update({"val_loss": val_loss, "val_c_index": val_c_index})
            log_parts.append(f"LR: {current_lr:.2e}")
            log_parts.append(f"Time: {epoch_time:.1f}s")

            await logger.info(" | ".join(log_parts), metadata=metadata)

            # Update progress: training from 66% to 90%, saving from 90% to 100%
            progress = 66 + int(epoch / epochs * 24)
            await _safe_update_progress(
                session_maker, self.task_id, TaskStatus.TRAINING, progress
            )

            await asyncio.to_thread(
                save_resume_checkpoint_sync,
                _resume_path,
                {
                    "epoch": epoch,
                    "model_state_dict": {
                        k: v.cpu() for k, v in model.state_dict().items()
                    },
                    "optimizer_state_dict": optimizer.state_dict(),
                    "scheduler_state_dict": scheduler.state_dict(),
                    "history": history,
                    "best_val_loss": best_val_loss,
                    "best_val_c_index": best_val_c_index,
                    "best_epoch": best_epoch,
                    "best_state_dict": best_state_dict,
                    "epochs_without_improvement": epochs_without_improvement,
                },
            )

            # Early stopping check
            if val_dataset and epochs_without_improvement >= early_stopping_patience:
                await logger.info(
                    f"Early stopping triggered at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                    metadata={"epoch": epoch, "best_val_c_index": best_val_c_index},
                )
                break

        if best_state_dict:
            model.load_state_dict(best_state_dict)

        test_metrics = None
        if test_dataset:
            test_loss, test_c_index = await asyncio.to_thread(
                self._evaluate_survival,
                model,
                test_dataset,
                training_times,
                training_statuses,
                y_bins_map,
                y_events_map,
                criterion,
                is_case_level,
            )
            test_metrics = {"loss": test_loss, "c_index": test_c_index}
            await logger.info(
                f"Final test results using best validation model | "
                f"Test Loss: {test_loss:.4f} | Test C-Index: {test_c_index:.4f}",
                metadata={"test_loss": test_loss, "test_c_index": test_c_index},
            )

        # Save checkpoint
        ckpt_path = model_dir / "aggregator.pth"
        torch.save(
            {
                "state_dict": model.state_dict(),
                "in_dim": in_dim,
                "num_classes": n_bins,
                "bin_edges": bin_edges,
            },
            ckpt_path,
        )

        # Save config
        # Note: aggregation_level uses 'file' instead of 'slide' for clarity
        (model_dir / "config.json").write_text(
            json.dumps(
                {
                    "task_id": self.task_id,
                    "task_type": str(self.task_type),
                    "model": aggregator_name,
                    "in_dim": in_dim,
                    "num_classes": n_bins,
                    "epochs": epochs,
                    "lr": lr,
                    "weight_decay": weight_decay,
                    "bin_edges": bin_edges.tolist(),
                    "split_type": "regular",
                    "aggregation_level": "case" if is_case_level else "file",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        # Save metrics
        metrics_data = {
            "is_kfold": False,
            "history": history,
            "best_epoch": best_epoch,
            "val_metrics": {"c_index": history["val_c_index"][-1]}
            if val_dataset and history["val_c_index"]
            else None,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(
            json.dumps(metrics_data, ensure_ascii=False, indent=2)
        )

        # Create full dataset for saving results
        # Pass device for direct GPU loading
        if is_case_level:
            full_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=all_ids,
                case_to_wsi=case_to_wsi,
                times=training_times,
                statuses=training_statuses,
                task_type="survival",
                device=self.device,
            )
        else:
            full_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=all_ids,
                times=training_times,
                statuses=training_statuses,
                task_type="survival",
                device=self.device,
            )

        # Save survival results
        await self._save_survival_results(
            model=model,
            dataset=full_dataset,
            task_id=self.task_id,
            bin_edges=bin_edges,
            logger=logger,
            session_maker=session_maker,
            aggregator_name=aggregator_name,
            case_level_ctx=case_level_ctx,
            test_sample_ids=test_ids if test_ids else None,
        )

        delete_resume_checkpoint(_resume_path)
        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["train_loss"],
            val_metrics=test_metrics
            or (
                {"c_index": best_val_c_index}
                if val_dataset and best_val_c_index
                else None
            ),
        )

    def _run_one_epoch_survival(
        self,
        train_loader,
        model: nn.Module,
        criterion: nn.Module,
        optimizer,
        device: str,
        task_id: str,
        y_bins_map: Dict[str, int],
        y_events_map: Dict[str, int],
        is_case_level: bool,
    ):
        """
        Run one survival training epoch synchronously.

        Must be called via ``asyncio.to_thread()`` to avoid blocking the
        event loop.  DataLoader iteration triggers ``torch.load()`` in
        ``__getitem__()`` and GPU forward/backward passes are blocking.

        Returns
        -------
        (running_loss, epoch_preds, epoch_times, epoch_statuses, count, stop_reason)
            *stop_reason* is ``None`` when the epoch completes normally,
            ``'cancelled'`` or ``'permission_revoked'`` otherwise.
        """
        running_loss = 0.0
        epoch_preds = []
        epoch_times = []
        epoch_statuses = []
        optimizer.zero_grad()
        count = 0
        batch_count = 0

        for batch in train_loader:
            batch_count += 1

            # Check for cancellation / permission every 50 batches
            if batch_count % 50 == 0:
                interruption = check_training_interruption(task_id)
                if interruption:
                    return None, None, None, interruption

            # Unpack batch based on data level
            if is_case_level:
                (
                    features,
                    sample_time,
                    sample_status,
                    sample_id,
                    slide_wsi_ids,
                    patch_counts,
                ) = batch
                sample_id = sample_id[0]
            else:
                features, sample_time, sample_status, sample_id = batch
                sample_id = sample_id[0]

            H = features.squeeze(0)  # Already on GPU
            logits, _ = model(H)

            target_bin = torch.tensor(
                [y_bins_map[sample_id]], dtype=torch.long, device=device
            )
            target_event = torch.tensor(
                [y_events_map[sample_id]], dtype=torch.float32, device=device
            )

            loss = criterion(logits, target_bin, target_event)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()

            running_loss += float(loss.item())
            hazards = torch.sigmoid(logits).detach()
            survival = compute_survival_from_hazards(hazards)
            risk_score = compute_risk_from_survival(survival)
            epoch_preds.append(float(risk_score.cpu().item()))
            epoch_times.append(float(sample_time))
            epoch_statuses.append(int(sample_status))

            count += 1

        return running_loss, epoch_preds, epoch_times, epoch_statuses, count, None

    def _evaluate_survival(
        self,
        model: nn.Module,
        dataset: Union[WSIFeatureDataset, CaseFeatureDataset],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        y_bins_map: Dict[str, int],
        y_events_map: Dict[str, int],
        criterion: nn.Module,
        is_case_level: bool = False,
    ) -> tuple[Any, ...]:
        """Evaluate survival model on a split using Dataset."""
        from torch.utils.data import DataLoader

        model.eval()
        total_loss = 0.0
        preds = []
        times = []
        statuses = []

        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        eval_loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=0,
        )

        with torch.inference_mode():
            for batch in eval_loader:
                # Unpack batch based on data level
                # Features are already on GPU if Dataset was created with device parameter
                if is_case_level:
                    (
                        features,
                        sample_time,
                        sample_status,
                        sample_id,
                        slide_wsi_ids,
                        patch_counts,
                    ) = batch
                    sample_id = sample_id[0]
                else:
                    features, sample_time, sample_status, sample_id = batch
                    sample_id = sample_id[0]

                H = features.squeeze(0)  # Already on GPU
                logits, _ = model(H)

                target_bin = torch.tensor(
                    [y_bins_map[sample_id]], dtype=torch.long, device=self.device
                )
                target_event = torch.tensor(
                    [y_events_map[sample_id]], dtype=torch.float32, device=self.device
                )

                loss = criterion(logits, target_bin, target_event)
                total_loss += float(loss.item())

                hazards = torch.sigmoid(logits)
                survival = compute_survival_from_hazards(hazards)
                risk_score = compute_risk_from_survival(survival)
                preds.append(float(risk_score.cpu().item()))
                times.append(float(sample_time))
                statuses.append(int(sample_status))

        avg_loss = total_loss / max(1, len(dataset))
        c_index = calculate_c_index(times, preds, statuses)
        model.train()
        # Round to 4 decimal places
        return round(float(avg_loss), 4), round(float(c_index), 4)

    def _calculate_kfold_comprehensive_metrics(
        self,
        task_id: str,
        fold_keys: List[str],
        splits_map: Optional[Dict[str, List[str]]] = None,
    ) -> tuple[Any, ...]:
        """
        Calculate comprehensive metrics for K-Fold survival training by reading saved JSON files.

        This reads the per-WSI result JSON files saved during K-Fold training and
        calculates metrics like c_index and integrated_brier_score for each fold.

        Args:
            task_id: Training task ID
            fold_keys: List of fold keys (e.g., ["fold_0", "fold_1"])
            splits_map: Optional dict mapping fold_key to list of WSI IDs.
                       If provided, directly reads files for known WSI IDs (fast).
                       If None, falls back to scanning directory (slow, for backward compatibility).

        Returns:
            Tuple of:
            - Dict with metric names as keys and {"mean": float, "std": float} as values (aggregated)
            - Dict with fold_key as keys and {"integrated_brier_score": float} as values (per-fold)
        """
        ai_results_root = self.uploads_root / "ai_results"

        # Per-fold metrics
        fold_ibs_scores = []
        per_fold_ibs = {}  # fold_key -> IBS value

        for fold_key in fold_keys:
            # Collect survival data for this fold from saved JSON files
            all_risks = []
            all_times = []
            all_statuses = []
            all_surv_probs = []
            fold_bin_edges = None
            seen_case_ids: set[str] = set()

            def _append_fold_result(data: Dict[str, Any]) -> None:
                nonlocal fold_bin_edges

                risk_score = data.get("risk_score")
                event_time = data.get("event_time")
                event_status = data.get("event_status")
                surv_probs = data.get("surv_probs")
                bin_edges = data.get("bin_edges")

                if (
                    risk_score is None
                    or event_time is None
                    or event_status is None
                ):
                    return

                if data.get("aggregation_level") == "case":
                    case_id = data.get("case_id")
                    if case_id:
                        if case_id in seen_case_ids:
                            return
                        seen_case_ids.add(case_id)

                all_risks.append(risk_score)
                all_times.append(event_time)
                all_statuses.append(event_status)
                if surv_probs is not None:
                    all_surv_probs.append(surv_probs)
                if bin_edges is not None and fold_bin_edges is None:
                    fold_bin_edges = bin_edges

            # Fast path: directly read files for known WSI IDs
            if splits_map and fold_key in splits_map:
                wsi_ids = splits_map[fold_key]
                for wsi_id in wsi_ids:
                    result_file = (
                        ai_results_root
                        / wsi_id
                        / f"train_{task_id}_{fold_key}_result.json"
                    )
                    if result_file.exists():
                        try:
                            with open(result_file, "r") as f:
                                data = json.load(f)
                                _append_fold_result(data)
                        except Exception:
                            continue
            # Slow path: scan directory (fallback for backward compatibility)
            elif ai_results_root.exists():
                for wsi_dir in ai_results_root.iterdir():
                    if wsi_dir.is_dir():
                        result_file = (
                            wsi_dir / f"train_{task_id}_{fold_key}_result.json"
                        )
                        if result_file.exists():
                            try:
                                with open(result_file, "r") as f:
                                    data = json.load(f)
                                    if (
                                        data.get("task_id") == task_id
                                        and data.get("fold_key") == fold_key
                                    ):
                                        _append_fold_result(data)
                            except Exception:
                                continue

            if len(all_risks) >= 2:
                # Calculate IBS if we have survival probabilities and bin edges
                if len(all_surv_probs) >= 2 and fold_bin_edges is not None:
                    ibs = self._calculate_ibs(
                        all_times, all_statuses, all_surv_probs, fold_bin_edges
                    )
                    if ibs is not None and not np.isnan(ibs):
                        fold_ibs_scores.append(ibs)
                        per_fold_ibs[fold_key] = round(float(ibs), 4)

        # Calculate mean and std for metrics
        # Round to 4 decimal places, filter out nan values
        aggregated = {}
        if fold_ibs_scores:
            mean_val = float(np.mean(fold_ibs_scores))
            std_val = float(np.std(fold_ibs_scores))
            if not np.isnan(mean_val) and not np.isnan(std_val):
                aggregated["integrated_brier_score"] = {
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                }

        return aggregated, per_fold_ibs

    def _calculate_ibs(
        self,
        times: List[float],
        events: List[int],
        surv_probs_list: List[List[float]],
        bin_edges: List[float],
    ) -> Optional[float]:
        """
        Calculate Integrated Brier Score (IBS) for survival predictions.

        Args:
            times: List of event times
            events: List of event indicators (1=event, 0=censored)
            surv_probs_list: List of survival probability arrays for each sample
            bin_edges: Bin edges used for discrete-time survival model

        Returns:
            Integrated Brier Score (lower is better), or None if calculation fails
        """
        try:
            from sksurv.metrics import integrated_brier_score

            if not surv_probs_list or len(surv_probs_list) == 0:
                return None

            times_arr = np.array(times, dtype=float)
            events_arr = np.array(events, dtype=bool)
            surv_probs_arr = np.array(surv_probs_list)  # Shape: (n_samples, n_bins)
            bin_edges_arr = np.array(bin_edges)

            # Create structured array for scikit-survival
            y_struct = np.array(
                [(e, t) for e, t in zip(events_arr, times_arr)],
                dtype=[("event", bool), ("time", float)],
            )

            # Use bin edges (excluding first edge which is min time) as evaluation times
            # bin_edges typically has n_bins + 1 values
            eval_times = bin_edges_arr[1:]  # Skip the first edge

            # Filter eval_times to be within observed time range
            min_time = times_arr.min()
            max_time = times_arr.max()
            valid_mask = (eval_times > min_time) & (eval_times < max_time)
            eval_times = eval_times[valid_mask]

            if len(eval_times) == 0:
                return None

            # Filter surv_probs to match eval_times
            # surv_probs has shape (n_samples, n_bins), we need to select columns matching valid eval_times
            surv_probs_filtered = surv_probs_arr[:, valid_mask]

            if surv_probs_filtered.shape[1] != len(eval_times):
                return None

            # Calculate IBS using scikit-survival
            ibs = integrated_brier_score(
                y_struct, y_struct, surv_probs_filtered, eval_times
            )

            # Check for nan
            if np.isnan(ibs):
                return None

            return float(ibs)

        except Exception:
            return None

    async def _train_survival_kfold(
        self,
        splits_map: Dict[str, List[str]],
        features_dir: Path,
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        weight_decay: float,
        logger: Any,
        session_maker: Any,
        model_id: str,
        model_dir: Path,
        optimizer_type: str = "adam",
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
        seed: int = 42,
    ) -> TrainResponse:
        """Train with K-Fold cross-validation using Dataset/DataLoader."""
        from torch.utils.data import DataLoader

        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            case_to_wsi = case_level_ctx["case_to_wsi"]
            training_times = case_level_ctx["case_times"]
            training_statuses = case_level_ctx["case_statuses"]
            working_splits = case_splits
        else:
            training_times = times_map
            training_statuses = statuses_map
            working_splits = splits_map

        num_folds = self._get_num_folds(working_splits)
        fold_keys = sorted([k for k in working_splits.keys() if k.startswith("fold_")])

        unit_name = "cases" if is_case_level else "samples"
        await logger.info(
            f"Starting {num_folds}-fold cross-validation for Survival Analysis ({unit_name})",
            metadata={
                "num_folds": num_folds,
                "epochs_per_fold": epochs,
                "aggregation_level": "case" if is_case_level else "file",
            },
        )

        fold_results = {}
        all_val_c_indices = []
        n_bins = max(2, num_classes)
        all_fold_ids: List[str] = []
        for fold_key in fold_keys:
            all_fold_ids.extend(working_splits.get(fold_key, []))
        all_fold_ids = list(dict.fromkeys(all_fold_ids))
        global_times = [training_times[sample_id] for sample_id in all_fold_ids]
        global_statuses = [training_statuses[sample_id] for sample_id in all_fold_ids]
        global_bin_edges = self._compute_bin_edges(global_times, global_statuses, n_bins)

        _resume_path = model_dir / "resume_checkpoint.pth"
        if _resume_path.exists():
            try:
                _ckpt = torch.load(_resume_path, map_location="cpu", weights_only=False)
                if _ckpt.get("type") == "kfold":
                    fold_results = _ckpt.get("completed_fold_results", {})
                    all_val_c_indices = _ckpt.get("completed_val_c_indices", [])
                    await logger.info(
                        f"Resumed survival kfold: {len(fold_results)} folds already completed",
                        metadata={"completed_folds": list(fold_results.keys())},
                    )
            except Exception as _e:
                await logger.info(
                    f"Could not load kfold resume checkpoint ({_e}), starting from fold 1",
                    metadata={"resume_error": str(_e)},
                )

        for fold_idx, val_fold_key in enumerate(fold_keys):
            if val_fold_key in fold_results:
                await logger.info(
                    f"Fold {fold_idx + 1}/{num_folds}: already completed, skipping",
                    metadata={"fold": fold_idx + 1},
                )
                continue

            val_ids = working_splits[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(working_splits[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)} {unit_name}",
                metadata={"fold": fold_idx + 1},
            )

            # Use dataset-global bin edges for all folds, matching MOTCat.
            bin_edges = global_bin_edges.copy()

            # Discretize all times
            all_ids = train_ids + val_ids
            times = [training_times[sample_id] for sample_id in all_ids]
            discretized_labels = self._discretize_times(times, bin_edges)
            y_bins_map = {
                sample_id: discretized_labels[i] for i, sample_id in enumerate(all_ids)
            }
            y_events_map = {
                sample_id: training_statuses[sample_id] for sample_id in all_ids
            }
            # Create datasets for this fold
            # Pass device for direct GPU loading - avoids CPU->GPU transfer overhead
            if is_case_level:
                train_dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=train_ids,
                    case_to_wsi=case_to_wsi,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                val_dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=val_ids,
                    case_to_wsi=case_to_wsi,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
            else:
                train_dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=train_ids,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )
                val_dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=val_ids,
                    times=training_times,
                    statuses=training_statuses,
                    task_type="survival",
                    device=self.device,
                )

            # Build model - get feature dim from dataset
            in_dim = train_dataset.get_feature_dim()
            model = get_aggregator(
                aggregator_name, in_dim=in_dim, num_classes=n_bins
            ).to(self.device)
            criterion = NLLSurvivalLoss(alpha=0.0)

            # Dynamic optimizer selection
            optimizer_type_lower = optimizer_type.lower()
            if optimizer_type_lower == "sgd":
                optimizer = optim.SGD(
                    model.parameters(), lr=lr, momentum=0.9, weight_decay=weight_decay
                )
            elif optimizer_type_lower == "adamw":
                optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
            else:  # Default to adam
                optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

            # Learning rate scheduler
            scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

            history = {"loss": [], "c_index": [], "val_loss": [], "val_c_index": []}
            best_val_loss = float("inf")
            best_val_c_index = 0.0
            best_epoch: Optional[int] = None
            best_state_dict = None
            epochs_without_improvement = 0
            start_epoch_fold = 1

            if _resume_path.exists():
                try:
                    _fold_ckpt = torch.load(
                        _resume_path, map_location="cpu", weights_only=False
                    )
                    if (
                        _fold_ckpt.get("type") == "kfold"
                        and _fold_ckpt.get("fold_idx") == fold_idx
                    ):
                        model.load_state_dict(_fold_ckpt["model_state_dict"])
                        optimizer.load_state_dict(_fold_ckpt["optimizer_state_dict"])
                        scheduler.load_state_dict(_fold_ckpt["scheduler_state_dict"])
                        history = _fold_ckpt["history"]
                        history.setdefault("val_c_index", [])
                        best_val_loss = _fold_ckpt["best_val_loss"]
                        best_val_c_index = _fold_ckpt.get("best_val_c_index", 0.0)
                        best_epoch = _fold_ckpt.get("best_epoch")
                        best_state_dict = _fold_ckpt["best_state_dict"]
                        epochs_without_improvement = _fold_ckpt[
                            "epochs_without_improvement"
                        ]
                        start_epoch_fold = _fold_ckpt["epoch"] + 1
                        await logger.info(
                            f"[Fold {fold_idx + 1}] Resumed from epoch {_fold_ckpt['epoch']}",
                            metadata={
                                "fold": fold_idx + 1,
                                "resumed_epoch": _fold_ckpt["epoch"],
                            },
                        )
                except Exception as _e:
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Could not restore fold state ({_e}), restarting fold",
                        metadata={"fold": fold_idx + 1, "resume_error": str(_e)},
                    )

            model.train()
            for epoch in range(start_epoch_fold, epochs + 1):
                # Check for cancellation or permission revocation at each epoch start
                if is_task_cancelled(self.task_id):
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Training cancelled by user/timeout at epoch {epoch}"
                    )
                    del model, optimizer, criterion
                    torch.cuda.empty_cache()  # Release cached GPU memory
                    raise TrainingCancelledException(
                        f"Training cancelled at fold {fold_idx + 1}, epoch {epoch}"
                    )
                if is_permission_revoked(self.task_id):
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Training stopped: permission revoked at epoch {epoch}"
                    )
                    del model, optimizer, criterion
                    torch.cuda.empty_cache()  # Release cached GPU memory
                    raise PermissionRevokedException(
                        f"Training stopped at fold {fold_idx + 1}, epoch {epoch}: permission revoked by admin"
                    )

                # Use DataLoader for training
                # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
                train_loader = DataLoader(
                    train_dataset,
                    batch_size=1,
                    shuffle=True,
                    num_workers=0,
                )

                # Run training epoch in thread pool to avoid blocking the event loop.
                (
                    running_loss,
                    epoch_preds,
                    epoch_times,
                    epoch_statuses,
                    _,
                    stop_reason,
                ) = await asyncio.to_thread(
                    self._run_one_epoch_survival,
                    train_loader,
                    model,
                    criterion,
                    optimizer,
                    self.device,
                    self.task_id,
                    y_bins_map,
                    y_events_map,
                    is_case_level,
                )

                if stop_reason == "cancelled":
                    del model, optimizer, criterion
                    torch.cuda.empty_cache()
                    raise TrainingCancelledException(
                        f"Training cancelled during fold {fold_idx + 1}, epoch {epoch} loop"
                    )
                if stop_reason == "permission_revoked":
                    del model, optimizer, criterion
                    torch.cuda.empty_cache()
                    raise PermissionRevokedException(
                        f"Training stopped during fold {fold_idx + 1}, epoch {epoch}: permission revoked by admin"
                    )

                epoch_start_time = time.time()

                epoch_loss = running_loss / max(1, len(train_ids))
                train_c_index = calculate_c_index(
                    epoch_times, epoch_preds, epoch_statuses
                )
                history["loss"].append(epoch_loss)
                history["c_index"].append(train_c_index)

                # Validation - run in thread pool (DataLoader + GPU inference are blocking)
                val_loss, val_c_index = await asyncio.to_thread(
                    self._evaluate_survival,
                    model,
                    val_dataset,
                    training_times,
                    training_statuses,
                    y_bins_map,
                    y_events_map,
                    criterion,
                    is_case_level,
                )
                history["val_loss"].append(val_loss)
                history["val_c_index"].append(val_c_index)

                # Select best model based on C-Index (higher is better)
                # Fallback to loss (lower is better) if C-Index is invalid
                is_improvement = False
                selection_metric_label = "Val C-Index"
                selection_metric_value = val_c_index
                if val_c_index is not None and val_c_index > best_val_c_index:
                    best_val_c_index = val_c_index
                    is_improvement = True
                elif val_c_index is None or val_c_index == best_val_c_index:
                    # Tie-breaker: use loss
                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                        is_improvement = True
                        selection_metric_label = "Val Loss"
                        selection_metric_value = val_loss

                if is_improvement:
                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                    best_state_dict = {
                        k: v.cpu().clone() for k, v in model.state_dict().items()
                    }
                    best_epoch = epoch
                    epochs_without_improvement = 0
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Best validation model updated at epoch {epoch} | "
                        f"{selection_metric_label}: {selection_metric_value:.4f}",
                        metadata={
                            "fold": fold_idx + 1,
                            "epoch": epoch,
                            "val_loss": val_loss,
                            "val_c_index": val_c_index,
                        },
                    )
                else:
                    epochs_without_improvement += 1

                # Update learning rate before logging so live LR matches the next-epoch optimizer state.
                scheduler.step()
                current_lr = optimizer.param_groups[0]["lr"]
                epoch_time = time.time() - epoch_start_time

                # Prepare metadata with train_ and val_ prefixes
                metadata = {
                    "fold": fold_idx + 1,
                    "epoch": epoch,
                    "train_loss": epoch_loss,
                    "train_c_index": train_c_index,
                    "val_loss": val_loss,
                    "val_c_index": val_c_index,
                    "lr": current_lr,
                    "epoch_time_sec": epoch_time,
                }
                log_parts = [
                    f"[Fold {fold_idx + 1}] Epoch {epoch}/{epochs}",
                    f"Train Loss: {epoch_loss:.4f}",
                    f"Train C-Index: {train_c_index:.4f}",
                    f"Val Loss: {val_loss:.4f}",
                    f"Val C-Index: {val_c_index:.4f}",
                    f"LR: {current_lr:.2e}",
                    f"Time: {epoch_time:.1f}s",
                ]

                await logger.info(" | ".join(log_parts), metadata=metadata)

                # Progress (66-100% for all folds including saving)
                # Each fold gets 34/num_folds percent; 70% for training, 30% for saving
                fold_total_range = 34 / num_folds
                fold_progress_base = 66 + int(fold_idx * fold_total_range)
                fold_training_range = int(fold_total_range * 0.7)
                progress = fold_progress_base + int(
                    epoch / epochs * fold_training_range
                )
                await _safe_update_progress(
                    session_maker, self.task_id, TaskStatus.TRAINING, progress
                )

                await asyncio.to_thread(
                    save_resume_checkpoint_sync,
                    _resume_path,
                    {
                        "type": "kfold",
                        "fold_idx": fold_idx,
                        "epoch": epoch,
                        "model_state_dict": {
                            k: v.cpu() for k, v in model.state_dict().items()
                        },
                        "optimizer_state_dict": optimizer.state_dict(),
                        "scheduler_state_dict": scheduler.state_dict(),
                        "history": history,
                        "best_val_loss": best_val_loss,
                        "best_val_c_index": best_val_c_index,
                        "best_epoch": best_epoch,
                        "best_state_dict": best_state_dict,
                        "epochs_without_improvement": epochs_without_improvement,
                        "completed_fold_results": fold_results,
                        "completed_val_c_indices": all_val_c_indices,
                    },
                )

                # Early stopping check
                if epochs_without_improvement >= early_stopping_patience:
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Early stopping at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                        metadata={
                            "fold": fold_idx + 1,
                            "epoch": epoch,
                            "best_val_loss": best_val_loss,
                            "best_val_c_index": best_val_c_index,
                        },
                    )
                    break

            # Restore best and evaluate
            if best_state_dict:
                model.load_state_dict(best_state_dict)
            final_val_loss, final_val_c_index = await asyncio.to_thread(
                self._evaluate_survival,
                model,
                val_dataset,
                training_times,
                training_statuses,
                y_bins_map,
                y_events_map,
                criterion,
                is_case_level,
            )

            fold_results[val_fold_key] = {
                "history": history,
                "best_epoch": best_epoch,
                "val_metrics": {"loss": final_val_loss, "c_index": final_val_c_index},
            }
            all_val_c_indices.append(final_val_c_index)

            # Save fold checkpoint
            fold_dir = model_dir / val_fold_key
            fold_dir.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "in_dim": in_dim,
                    "num_classes": n_bins,
                    "bin_edges": bin_edges,
                },
                fold_dir / "aggregator.pth",
            )

            # Calculate saving progress range for this fold
            fold_total_range = 34 / num_folds
            fold_progress_base = 66 + int(fold_idx * fold_total_range)
            fold_training_range = int(fold_total_range * 0.7)
            fold_saving_base = fold_progress_base + fold_training_range
            fold_saving_range = max(1, int(fold_total_range * 0.3))

            # Save per-WSI inference results for this fold's VALIDATION set only
            await self._save_survival_results(
                model=model,
                dataset=val_dataset,
                task_id=self.task_id,
                bin_edges=bin_edges,
                logger=logger,
                session_maker=session_maker,
                aggregator_name=aggregator_name,
                fold_key=val_fold_key,
                progress_base=fold_saving_base,
                progress_range=fold_saving_range,
                case_level_ctx=case_level_ctx,
            )

            await logger.info(
                f"Fold {fold_idx + 1} validation summary | "
                f"Val Loss: {final_val_loss:.4f} | Val C-Index: {final_val_c_index:.4f}",
                metadata={
                    "fold": fold_idx + 1,
                    "val_loss": round(float(final_val_loss), 4),
                    "val_c_index": round(float(final_val_c_index), 4),
                },
            )

        aggregated = {
            "c_index": {
                "mean": round(float(np.mean(all_val_c_indices)), 4),
                "std": round(float(np.std(all_val_c_indices)), 4),
            },
        }

        comprehensive_metrics, per_fold_ibs = (
            self._calculate_kfold_comprehensive_metrics(
                task_id=self.task_id,
                fold_keys=fold_keys,
                splits_map=splits_map,  # Always use original wsi_id splits for file access
            )
        )
        # Merge comprehensive metrics into aggregated (don't overwrite c_index already calculated)
        for metric_name, metric_stats in comprehensive_metrics.items():
            if metric_name not in aggregated:
                aggregated[metric_name] = metric_stats

        # Add per-fold IBS to fold_results
        for fold_key, ibs_value in per_fold_ibs.items():
            if fold_key in fold_results:
                fold_results[fold_key]["val_metrics"]["integrated_brier_score"] = (
                    ibs_value
                )

        await logger.info(
            f"K-Fold complete: c_index={aggregated['c_index']['mean']:.4f}±{aggregated['c_index']['std']:.4f}",
            metadata={"aggregated": aggregated},
        )

        # Save config
        # Note: aggregation_level uses 'file' instead of 'slide' for clarity
        (model_dir / "config.json").write_text(
            json.dumps(
                {
                    "task_id": self.task_id,
                    "task_type": str(self.task_type),
                    "model": aggregator_name,
                    "in_dim": in_dim,
                    "num_classes": n_bins,
                    "epochs": epochs,
                    "lr": lr,
                    "weight_decay": weight_decay,
                    "split_type": "kfold",
                    "num_folds": num_folds,
                    "aggregation_level": "case" if is_case_level else "file",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        # Save aggregated metrics
        metrics_data = {
            "is_kfold": True,
            "num_folds": num_folds,
            "folds": fold_results,
            "aggregated": aggregated,
        }
        (model_dir / "metrics.json").write_text(
            json.dumps(metrics_data, ensure_ascii=False, indent=2)
        )

        ckpt_path = model_dir / "fold_0" / "aggregator.pth"

        delete_resume_checkpoint(_resume_path)
        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=fold_results["fold_0"]["history"]["loss"],
            val_metrics={
                "c_index": aggregated["c_index"]["mean"],
            },
            kfold_aggregated=aggregated,
        )

    def _split_case_attention_to_slides(
        self,
        attention: Optional[np.ndarray[Any, Any]],
        case_id: str,
        case_wsi_patch_counts: Dict[str, List[int]],
        case_to_wsi: Dict[str, List[str]],
    ) -> Dict[str, Optional[np.ndarray[Any, Any]]]:
        """
        Split case-level attention weights back to individual slides.

        When training with case-level features, the attention is computed over all patches
        from all slides in the case. This method splits the attention back to per-slide
        arrays based on the original patch counts.

        Args:
            attention: Case-level attention array (total_patches,) or (num_classes, total_patches)
            case_id: The case ID to split attention for
            case_wsi_patch_counts: Dict mapping case_id -> list of patch counts per WSI
            case_to_wsi: Dict mapping case_id -> list of wsi_ids

        Returns:
            Dict mapping wsi_id -> attention array for that slide
        """
        if attention is None:
            wsi_ids = case_to_wsi.get(case_id, [])
            return {wsi_id: None for wsi_id in wsi_ids}

        wsi_ids = case_to_wsi.get(case_id, [])
        patch_counts = case_wsi_patch_counts.get(case_id, [])

        if len(wsi_ids) != len(patch_counts):
            # Fallback: return None for all slides
            return {wsi_id: None for wsi_id in wsi_ids}

        slide_attentions: Dict[str, Optional[np.ndarray[Any, Any]]] = {}
        start_idx = 0

        for wsi_id, count in zip(wsi_ids, patch_counts):
            end_idx = start_idx + int(count)
            if attention.ndim == 1:
                # Single attention vector: (total_patches,)
                slide_attentions[wsi_id] = attention[start_idx:end_idx]
            elif attention.ndim == 2:
                # Multi-class attention: (num_classes, total_patches)
                slide_attentions[wsi_id] = attention[:, start_idx:end_idx]
            else:
                slide_attentions[wsi_id] = None
            start_idx = end_idx

        return slide_attentions

    async def _save_survival_results(
        self,
        model,
        dataset: Union[WSIFeatureDataset, CaseFeatureDataset],
        task_id,
        bin_edges,
        logger,
        session_maker,
        aggregator_name: str = None,
        fold_key: Optional[str] = None,
        progress_base: int = 90,
        progress_range: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
        test_sample_ids: Optional[List[str]] = None,
    ):
        """
        Save per-WSI survival inference results after training.

        For case-level training, runs inference on case features and splits
        attention back to per-slide for saving.

        Optimized with:
        - Dynamic progress updates with per-file granularity
        - Parallel file I/O using asyncio
        - Batch database inserts for performance

        Progress allocation within the given range:
        - 0-40%: Inference
        - 40-60%: Per-slide result building
        - 60-85%: File I/O (per-file progress)
        - 85-90%: Database insert
        - 90-100%: Final metrics / completion handoff

        For each WSI, saves:
        - Risk score and risk group
        - Hazards and survival probabilities
        - Attention weights for heatmap visualization

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_attention.npy (if attention available)

        Args:
            dataset: Dataset for loading features on-demand
            fold_key: Optional fold identifier (e.g., "fold_0") for k-fold training.
            progress_base: Starting progress percentage (default 90 for regular training)
            progress_range: Total progress range for saving (default 10 for regular training)
            case_level_ctx: Case-level context dict with case_to_wsi, case_wsi_patch_counts, etc.
        """
        import concurrent.futures
        from functools import partial
        from torch.utils.data import DataLoader

        is_case_level = case_level_ctx is not None
        fold_suffix = f"_{fold_key}" if fold_key else ""
        fold_desc = f" ({fold_key})" if fold_key else ""

        # For case-level, dataset contains case_ids
        # We need to count actual WSI slides for progress
        if is_case_level:
            case_to_wsi = case_level_ctx["case_to_wsi"]
            original_times = case_level_ctx["original_times"]
            original_statuses = case_level_ctx["original_statuses"]
            # Count total slides
            total_slides = sum(
                len(case_to_wsi.get(case_id, [])) for case_id in dataset.case_ids
            )
            total_wsi = total_slides
        else:
            total_wsi = len(dataset)

        # Calculate progress points based on progress_base and progress_range.
        # Keep the last integer slot for the final completed=100 handoff.
        max_saving_progress = progress_base + max(progress_range - 1, 0)
        progress_inference = progress_base
        progress_build_results = max(
            progress_inference,
            min(max_saving_progress, progress_base + int(progress_range * 0.4)),
        )
        progress_file_io_start = max(
            progress_build_results,
            min(max_saving_progress, progress_base + int(progress_range * 0.6)),
        )
        progress_file_io_end = max(
            progress_file_io_start,
            min(max_saving_progress, progress_base + int(progress_range * 0.85)),
        )
        progress_db = max(
            progress_file_io_end,
            min(max_saving_progress, progress_base + int(progress_range * 0.9)),
        )
        progress_metrics = max(
            progress_db,
            min(max_saving_progress, progress_base + int(progress_range * 0.95)),
        )
        file_io_progress_range = progress_file_io_end - progress_file_io_start

        await _safe_update_progress(
            session_maker, self.task_id, TaskStatus.TRAINING, progress_inference
        )
        unit_name = "slides" if is_case_level else "WSI slides"
        await logger.info(
            f"[Saving] Starting to save survival results{fold_desc} for {total_wsi} {unit_name}...",
            {
                "task_id": task_id,
                "num_wsi": total_wsi,
                "fold_key": fold_key,
                "phase": "saving_results",
                "is_case_level": is_case_level,
            },
        )

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        has_raw_attention = hasattr(model, "forward_with_raw_attention")

        file_save_items = []  # For parallel file saving
        db_records = []  # For batch database insert

        # Create DataLoader for inference
        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        inference_loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=0,
        )

        running_loop = asyncio.get_running_loop()
        inference_update_interval = calculate_progress_update_interval(
            total_wsi,
            target_updates=25,
            max_interval=200,
        )

        # Phase 1: Run inference and collect results in thread pool.
        # DataLoader triggers torch.load() in __getitem__(), and GPU inference is blocking.
        def _run_inference():
            """Synchronous inference loop - runs in thread pool to avoid blocking event loop."""
            _all_risks = []
            processed_wsi = 0
            with torch.inference_mode():
                for batch in inference_loader:
                    # Unpack batch based on data level
                    # Features are already on GPU if Dataset was created with device parameter
                    if is_case_level:
                        (
                            features,
                            sample_time,
                            sample_status,
                            sample_id,
                            slide_wsi_ids,
                            patch_counts,
                        ) = batch
                        sample_id = sample_id[0]
                        # Convert from batch format
                        slide_wsi_ids = [wid[0] for wid in slide_wsi_ids]
                        patch_counts = [int(pc) for pc in patch_counts]
                    else:
                        features, sample_time, sample_status, sample_id = batch
                        sample_id = sample_id[0]
                        slide_wsi_ids = None
                        patch_counts = None

                    H = features.squeeze(0)  # Already on GPU

                    if has_raw_attention:
                        logits, attention, raw_attention = (
                            model.forward_with_raw_attention(H)
                        )
                    else:
                        logits, attention = model(H)
                        raw_attention = None

                    # Compute hazards
                    hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                    surv = compute_survival_from_hazards(hazards)
                    risk_score = float(compute_risk_from_survival(surv))
                    _all_risks.append(
                        (
                            sample_id,
                            risk_score,
                            hazards,
                            surv,
                            attention,
                            raw_attention,
                            float(sample_time),
                            int(sample_status),
                            slide_wsi_ids,
                            patch_counts,
                        )
                    )

                    processed_wsi += max(1, len(slide_wsi_ids)) if is_case_level else 1
                    if (
                        processed_wsi % inference_update_interval == 0
                        or processed_wsi >= total_wsi
                    ):
                        inference_progress = interpolate_progress(
                            progress_inference,
                            progress_build_results,
                            processed_wsi,
                            total_wsi,
                        )
                        asyncio.run_coroutine_threadsafe(
                            _safe_update_progress(
                                session_maker,
                                self.task_id,
                                TaskStatus.TRAINING,
                                inference_progress,
                            ),
                            running_loop,
                        )
            return _all_risks

        all_risks = await asyncio.to_thread(_run_inference)

        # Calculate median risk score for risk stratification
        await _safe_update_progress(
            session_maker, self.task_id, TaskStatus.TRAINING, progress_build_results
        )
        median_risk_score = float(np.median([r[1] for r in all_risks]))

        # Phase 2: Build results (split by case if case-level)
        build_update_interval = calculate_progress_update_interval(
            total_wsi,
            target_updates=20,
            max_interval=200,
        )
        built_wsi = 0
        for i, (
            sample_id,
            risk_score,
            hazards,
            surv,
            attention,
            raw_attention,
            sample_time,
            sample_status,
            batch_slide_wsi_ids,
            batch_patch_counts,
        ) in enumerate(all_risks):
            attention_np = attention.cpu().numpy() if attention is not None else None
            raw_attention_np = (
                raw_attention.cpu().numpy() if raw_attention is not None else None
            )
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            if is_case_level:
                # Case-level: split attention back to per-slide and save per WSI
                case_id = sample_id
                slide_wsi_ids_list = (
                    batch_slide_wsi_ids
                    if batch_slide_wsi_ids
                    else case_to_wsi.get(case_id, [])
                )
                # Build case_wsi_patch_counts for this case
                case_wsi_patch_counts = (
                    {case_id: batch_patch_counts} if batch_patch_counts else {}
                )

                slide_attentions = self._split_case_attention_to_slides(
                    attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )
                slide_raw_attentions = (
                    self._split_case_attention_to_slides(
                        raw_attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                    )
                    if raw_attention_np is not None
                    else {wsi_id: None for wsi_id in slide_wsi_ids_list}
                )

                for wsi_id in slide_wsi_ids_list:
                    wsi_result_dir = ai_results_root / wsi_id
                    slide_attn = slide_attentions.get(wsi_id)
                    slide_raw_attn = slide_raw_attentions.get(wsi_id)

                    # Use the slide's own ground truth event_time/status (should be same for case-level survival)
                    wsi_event_time = original_times.get(wsi_id, sample_time)
                    wsi_event_status = original_statuses.get(wsi_id, sample_status)

                    result_data = {
                        "wsi_id": wsi_id,
                        "case_id": case_id,
                        "task_id": task_id,
                        "risk_score": float(risk_score),
                        "risk_group": risk_group,
                        "median_risk_score": median_risk_score,
                        "hazards": hazards.tolist(),
                        "surv_probs": surv.tolist(),
                        "event_time": wsi_event_time,
                        "event_status": wsi_event_status,
                        "bin_edges": bin_edges.tolist(),
                        "aggregator": aggregator_name,
                        "aggregation_level": "case",
                    }
                    if fold_key:
                        result_data["fold_key"] = fold_key

                    file_save_items.append(
                        (
                            wsi_result_dir,
                            result_data,
                            slide_attn,
                            slide_raw_attn,
                            fold_suffix,
                            task_id,
                        )
                    )

                    result_file = (
                        wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
                    )
                    attention_file_path = (
                        str(
                            wsi_result_dir
                            / f"train_{task_id}{fold_suffix}_attention.npy"
                        )
                        if slide_attn is not None
                        else None
                    )
                    db_records.append(
                        {
                            "wsi_id": wsi_id,
                            "task_id": task_id,
                            "pred": risk_group,
                            "probs": None,
                            "extra_metadata": {
                                "task_type": "survival",
                                "case_id": case_id,
                                "risk_score": float(risk_score),
                                "risk_group": risk_group,
                                "median_risk_score": median_risk_score,
                                "hazards": hazards.tolist(),
                                "surv_probs": surv.tolist(),
                                "event_time": wsi_event_time,
                                "event_status": wsi_event_status,
                                "bin_edges": bin_edges.tolist(),
                                "result_file": str(result_file),
                                "attention_file": attention_file_path,
                                "fold_key": fold_key,
                                "aggregation_level": "case",
                            },
                        }
                    )
                built_wsi += max(1, len(slide_wsi_ids_list))
            else:
                # Slide-level: original behavior
                wsi_id = sample_id
                result_dir = ai_results_root / wsi_id

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "risk_score": float(risk_score),
                    "risk_group": risk_group,
                    "median_risk_score": median_risk_score,
                    "hazards": hazards.tolist(),
                    "surv_probs": surv.tolist(),
                    "event_time": sample_time,
                    "event_status": sample_status,
                    "bin_edges": bin_edges.tolist(),
                    "aggregator": aggregator_name,
                }
                if fold_key:
                    result_data["fold_key"] = fold_key

                file_save_items.append(
                    (
                        result_dir,
                        result_data,
                        attention_np,
                        raw_attention_np,
                        fold_suffix,
                        task_id,
                    )
                )

                result_file = result_dir / f"train_{task_id}{fold_suffix}_result.json"
                attention_file_path = (
                    str(result_dir / f"train_{task_id}{fold_suffix}_attention.npy")
                    if attention_np is not None
                    else None
                )
                db_records.append(
                    {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": risk_group,
                        "probs": None,
                        "extra_metadata": {
                            "task_type": "survival",
                            "risk_score": float(risk_score),
                            "risk_group": risk_group,
                            "median_risk_score": median_risk_score,
                            "hazards": hazards.tolist(),
                            "surv_probs": surv.tolist(),
                            "event_time": sample_time,
                            "event_status": sample_status,
                            "bin_edges": bin_edges.tolist(),
                            "result_file": str(result_file),
                            "attention_file": attention_file_path,
                            "fold_key": fold_key,
                        },
                    }
                )
                built_wsi += 1

            if built_wsi % build_update_interval == 0 or built_wsi >= total_wsi:
                build_progress = interpolate_progress(
                    progress_build_results,
                    progress_file_io_start,
                    built_wsi,
                    total_wsi,
                )
                await _safe_update_progress(
                    session_maker, self.task_id, TaskStatus.TRAINING, build_progress
                )

        # Phase 3: Parallel file I/O using thread pool with progress updates
        await _safe_update_progress(
            session_maker, self.task_id, TaskStatus.TRAINING, progress_file_io_start
        )
        await logger.info(
            f"[Saving] Writing {total_wsi} result files to disk...",
            {"phase": "writing_files", "num_files": total_wsi},
        )
        await logger.info(
            "[Saving] Using throttled file I/O to reduce disk pressure",
            {
                "phase": "writing_files",
                "max_workers": SAVE_FILE_IO_MAX_WORKERS,
                "batch_size": SAVE_FILE_IO_BATCH_SIZE,
            },
        )

        completed_count = [0]
        progress_lock = asyncio.Lock()
        # Capture session_maker for use in nested async function
        session_maker_ref = session_maker
        task_id_for_update = self.task_id
        file_update_interval = calculate_progress_update_interval(
            total_wsi,
            target_updates=20,
            max_interval=200,
        )

        def save_single_wsi_files(item):
            """Synchronous function to save files for a single WSI."""
            (
                result_dir,
                result_data,
                attention_np,
                raw_attention_np,
                fold_suffix,
                task_id,
            ) = item
            result_dir.mkdir(parents=True, exist_ok=True)

            result_file = result_dir / f"train_{task_id}{fold_suffix}_result.json"
            with open(result_file, "w") as f:
                json.dump(result_data, f)

            if attention_np is not None:
                attention_file = (
                    result_dir / f"train_{task_id}{fold_suffix}_attention.npy"
                )
                np.save(attention_file, attention_np)
                ensure_recommendation_preview_cache(
                    result_data["wsi_id"], attention_file, Config.get_uploads_dir()
                )

            if raw_attention_np is not None:
                raw_attention_file = (
                    result_dir / f"train_{task_id}{fold_suffix}_attention_raw.npy"
                )
                np.save(raw_attention_file, raw_attention_np)

            return result_data["wsi_id"]

        async def save_with_progress(
            executor, item, total, file_io_start, file_io_range
        ):
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, save_single_wsi_files, item)
            async with progress_lock:
                completed_count[0] += 1
                if (
                    completed_count[0] % file_update_interval == 0
                    or completed_count[0] == total
                ):
                    file_progress = interpolate_progress(
                        file_io_start,
                        file_io_start + file_io_range,
                        completed_count[0],
                        total,
                    )
                    await _safe_update_progress(
                        session_maker_ref,
                        task_id_for_update,
                        TaskStatus.TRAINING,
                        file_progress,
                    )
            return result

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=SAVE_FILE_IO_MAX_WORKERS
        ) as executor:
            for batch_start in range(0, total_wsi, SAVE_FILE_IO_BATCH_SIZE):
                batch_items = file_save_items[
                    batch_start : batch_start + SAVE_FILE_IO_BATCH_SIZE
                ]
                tasks = [
                    save_with_progress(
                        executor,
                        item,
                        total_wsi,
                        progress_file_io_start,
                        file_io_progress_range,
                    )
                    for item in batch_items
                ]
                await asyncio.gather(*tasks)
                await asyncio.sleep(0)

        # Phase 4: Batch database insert
        await _safe_update_progress(
            session_maker, self.task_id, TaskStatus.TRAINING, progress_db
        )
        await logger.info(
            f"[Saving] Inserting {len(db_records)} records to database...",
            {"phase": "database_insert", "num_records": len(db_records)},
        )

        async with scoped_db(session_maker) as db:
            await AIResultRepository.bulk_create(db, db_records, batch_size=100)

        # Phase 5: Calculate and log final metrics
        await _safe_update_progress(
            session_maker, self.task_id, TaskStatus.TRAINING, progress_metrics
        )

        # Extract risk scores from collected data (all_risks is list of tuples)
        # all_risks format: (sample_id, risk_score, hazards, surv, attention, raw_attention, time, status, ...)

        # Filter to test set only if test_sample_ids is provided
        if test_sample_ids is not None and len(test_sample_ids) > 0:
            # Filter all_risks to only test samples
            test_risks = [r for r in all_risks if r[0] in test_sample_ids]

            if len(test_risks) > 0:
                test_risk_scores = [r[1] for r in test_risks]
                test_times = [r[6] for r in test_risks]
                test_statuses = [r[7] for r in test_risks]

                test_c_index = round(
                    float(
                        calculate_c_index(test_times, test_risk_scores, test_statuses)
                    ),
                    4,
                )

                await logger.info(
                    f"[Saving] Complete - Test Set C-Index: {test_c_index:.4f} (n={len(test_risks)})",
                    metadata={"c_index": test_c_index, "test_samples": len(test_risks)},
                )
            else:
                await logger.info(
                    f"[Saving] Complete - No test samples found for metrics calculation",
                    metadata={"task_id": task_id},
                )
        else:
            # No test set specified - log without metrics (for k-fold or when no test set)
            await logger.info(
                f"[Saving] Complete - Inference results saved for {len(all_risks)} samples",
                metadata={"task_id": task_id, "num_samples": len(all_risks)},
            )
