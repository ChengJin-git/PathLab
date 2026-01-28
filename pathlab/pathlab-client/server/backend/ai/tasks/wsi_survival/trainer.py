"""WSI Survival Analysis Trainer - Discrete Time Survival."""
from __future__ import annotations

import json
import asyncio
import numpy as np
import math
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.utils.dataset import build_dataloader
from backend.ai.utils.vram_guard import (
    check_vram_before_model_load,
    check_vram_before_batch_processing,
    VRAMInsufficientError,
    VRAMExceededError,
)
from backend.ai.schemas import TaskType, TrainResponse, FeatureExtractionResponse
from backend.ai.tasks.feature_cache import (
    compute_params_hash,
    find_cached_features,
    get_cache_save_path,
    create_symlink_to_cache,
    read_params_from_coords_h5,
)
from backend.ai.tasks.wsi_classification.trainer import WSIClassificationTrainer
from backend.database.repositories import WSIRepository, TrainingTaskRepository, AIResultRepository
from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException

# -----------------------------------------------------------------------------
# Discrete Survival Loss
# -----------------------------------------------------------------------------
class NLLSurvivalLoss(nn.Module):
    """
    Negative Log Likelihood Loss for Discrete-Time Survival Analysis.
    
    Model outputs: Logits for K bins (hazards).
    """
    def __init__(self, eps=1e-7):
        super().__init__()
        self.eps = eps

    def forward(self, logits, y_bin, event):
        """
        logits: (batch, num_bins) - raw output from model
        y_bin: (batch,) - bin index where event/censoring occurred
        event: (batch,) - 1 if event occurred, 0 if censored
        """
        # Sigmoid to get hazard probabilities h(t|T>=t)
        hazards = torch.sigmoid(logits)
        
        # Survival term: log(1 - h)
        # We want to sum log(1-h) for all bins BEFORE y_bin
        # Create a mask for bins < y_bin
        batch_size, num_bins = logits.shape
        
        # Mask of shape (batch, num_bins) where mask[i, j] = 1 if j < y_bin[i]
        # This represents all the bins the patient SURVIVED through
        # range_tensor: [0, 1, ..., num_bins-1]
        range_tensor = torch.arange(num_bins, device=logits.device).unsqueeze(0)
        y_bin = y_bin.unsqueeze(1)
        
        survived_mask = (range_tensor < y_bin).float()
        
        # Event mask: mask[i, j] = 1 if j == y_bin[i] AND event[i] == 1
        event_mask = (range_tensor == y_bin).float() * event.unsqueeze(1)
        
        # Loss calculation
        # 1. Uncensored: log(h_bin) + Sum_{j<bin} log(1 - h_j)
        # 2. Censored: Sum_{j<bin} log(1 - h_j)  (assuming censored at start of bin)
        
        # Survival loss term (for all samples)
        # log(1 - h)
        surv_loss = survived_mask * torch.log(1 - hazards + self.eps)
        
        # Event loss term (only for uncensored samples)
        # log(h)
        event_loss = event_mask * torch.log(hazards + self.eps)
        
        # Total log likelihood
        log_likelihood = surv_loss + event_loss
        
        # Minimize negative log likelihood
        loss = -torch.sum(log_likelihood) / batch_size
        return loss

# -----------------------------------------------------------------------------
# Metrics Utils
# -----------------------------------------------------------------------------
def calculate_c_index(y_true, y_pred, event):
    """
    Calculate Harrell's C-Index using scikit-survival.

    y_true: True times (array-like)
    y_pred: Predicted risk scores (higher = higher risk = shorter survival)
    event: Event status (1=event, 0=censored)

    Returns: C-Index (float between 0 and 1)
    """
    from sksurv.metrics import concordance_index_censored

    n = len(y_true)
    if n < 2:
        return 0.5

    # Convert to numpy arrays
    times = np.asarray(y_true)
    risks = np.asarray(y_pred)
    events = np.asarray(event, dtype=bool)  # scikit-survival expects boolean

    try:
        # concordance_index_censored expects:
        # - event_indicator: boolean array (True = event occurred)
        # - event_time: float array of times
        # - estimate: float array of risk scores (higher = higher risk)
        c_index, concordant, discordant, tied_risk, tied_time = concordance_index_censored(
            events, times, risks
        )
        return c_index
    except Exception:
        # Fallback if calculation fails (e.g., no comparable pairs)
        return 0.5


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
        db: Any,
        logger: Any,
    ) -> tuple:
        """Load survival data (times, statuses) for given WSI IDs."""
        times = []
        statuses = []
        valid_ids = []

        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if wsi and wsi.event_time is not None and wsi.event_status is not None:
                times.append(float(wsi.event_time))
                statuses.append(int(wsi.event_status))
                valid_ids.append(wsi_id)
            else:
                await logger.warning(f"Skipping WSI {wsi_id} - missing survival data")

        return times, statuses, valid_ids

    def _compute_bin_edges(self, times: List[float], statuses: List[int], n_bins: int) -> np.ndarray:
        """Compute bin edges from uncensored data quantiles."""
        uncensored_times = [t for t, s in zip(times, statuses) if s == 1]

        if not uncensored_times:
            uncensored_times = times

        quantiles = np.linspace(0, 100, n_bins + 1)
        bin_edges = np.percentile(uncensored_times, quantiles)
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < n_bins + 1:
            bin_edges = np.linspace(min(times), max(times), n_bins + 1)

        return bin_edges

    def _discretize_times(self, times: List[float], bin_edges: np.ndarray) -> List[int]:
        """Discretize continuous times into bin indices."""
        class_bounds = bin_edges[1:]
        discretized_labels = []
        for t in times:
            bin_idx = 0
            for i, bound in enumerate(class_bounds):
                if t <= bound:
                    bin_idx = i
                    break
            else:
                bin_idx = len(class_bounds) - 1
            discretized_labels.append(bin_idx)
        return discretized_labels

    def _prepare_case_level_survival_data(
        self,
        feats: Dict[str, torch.Tensor],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        case_id_map: Dict[str, str],
    ) -> tuple:
        """
        Prepare case-level survival data by grouping slides and concatenating features.

        For survival tasks, all slides in a case should have the same event_time/event_status
        (this is validated at CSV upload time for case-level + survival datasets).

        Returns:
            Tuple of:
            - case_feats: Dict[case_id, concatenated features tensor]
            - case_times: Dict[case_id, event_time]
            - case_statuses: Dict[case_id, event_status]
            - case_to_wsi: Dict[case_id, list of wsi_ids in that case]
            - case_wsi_patch_counts: Dict[case_id, list of patch counts per WSI (for splitting attention)]
        """
        # Group wsi_ids by case_id
        case_to_wsi: Dict[str, List[str]] = {}
        for wsi_id, case_id in case_id_map.items():
            if case_id not in case_to_wsi:
                case_to_wsi[case_id] = []
            case_to_wsi[case_id].append(wsi_id)

        case_feats: Dict[str, torch.Tensor] = {}
        case_times: Dict[str, float] = {}
        case_statuses: Dict[str, int] = {}
        case_wsi_patch_counts: Dict[str, List[int]] = {}

        for case_id, wsi_ids in case_to_wsi.items():
            # Collect features for all slides in this case
            slide_feats = []
            patch_counts: List[int] = []
            for wsi_id in wsi_ids:
                if wsi_id in feats:
                    slide_feat = feats[wsi_id]
                    slide_feats.append(slide_feat)
                    patch_counts.append(slide_feat.shape[0])

            if slide_feats:
                # Concatenate all slide features
                case_feats[case_id] = torch.cat(slide_feats, dim=0)
                case_wsi_patch_counts[case_id] = patch_counts

                # Use the first slide's survival data (all slides in case should have same values)
                first_wsi = wsi_ids[0]
                if first_wsi in times_map:
                    case_times[case_id] = times_map[first_wsi]
                if first_wsi in statuses_map:
                    case_statuses[case_id] = statuses_map[first_wsi]

        return case_feats, case_times, case_statuses, case_to_wsi, case_wsi_patch_counts

    async def train_model(
        self,
        splits_map: Dict[str, List[str]],
        aggregator_name: str,
        num_classes: int,  # n_bins
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        optimizer: str = "adam",
        early_stopping_patience: int = 10,
    ) -> TrainResponse:
        """
        Train survival model with proper data splits.

        Args:
            num_classes: Number of discrete time bins (default: 4)
            optimizer: Optimizer type ('adam', 'sgd', 'adamw')
            early_stopping_patience: Number of epochs to wait before early stopping
        """
        # Collect all WSI IDs
        all_wsi_ids = []
        for ids in splits_map.values():
            all_wsi_ids.extend(ids)
        all_wsi_ids = list(set(all_wsi_ids))

        # Load features
        features_dir = self.uploads_root / "training" / self.task_id / "features"
        feats = self._load_features(features_dir, all_wsi_ids)

        # Load survival data
        times_map = {}
        statuses_map = {}
        valid_ids = []

        for wsi_id in all_wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
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
            filtered_splits[split_name] = [wsi_id for wsi_id in ids if wsi_id in valid_ids]

        # Check if this is a case-level dataset
        data_level = await TrainingTaskRepository.get_dataset_data_level(db, self.task_id)
        is_case_level = (data_level == "case")

        # Build case_level_ctx if case-level
        case_level_ctx = None
        if is_case_level:
            case_id_map = await TrainingTaskRepository.get_wsi_case_ids(db, self.task_id)
            # Filter to only include valid_ids
            case_id_map = {k: v for k, v in case_id_map.items() if k in valid_ids}

            # Prepare case-level survival data
            case_feats, case_times, case_statuses, case_to_wsi, case_wsi_patch_counts = \
                self._prepare_case_level_survival_data(feats, times_map, statuses_map, case_id_map)

            # Convert splits to case-level
            case_splits = self._convert_splits_to_case_level(filtered_splits, case_id_map)

            case_level_ctx = {
                "case_feats": case_feats,
                "case_times": case_times,
                "case_statuses": case_statuses,
                "case_splits": case_splits,
                "case_to_wsi": case_to_wsi,
                "case_wsi_patch_counts": case_wsi_patch_counts,
                "original_times": times_map,
                "original_statuses": statuses_map,
            }

            await logger.info(
                f"Case-level survival training: {len(case_feats)} cases from {len(valid_ids)} slides",
                metadata={"data_level": "case", "num_cases": len(case_feats), "num_slides": len(valid_ids)}
            )

        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        is_kfold = self._is_kfold_splits(filtered_splits)

        if is_kfold:
            return await self._train_survival_kfold(
                filtered_splits, feats, times_map, statuses_map,
                aggregator_name, num_classes, epochs, lr, logger, db, model_id, model_dir,
                optimizer, early_stopping_patience, case_level_ctx,
            )
        else:
            return await self._train_survival_regular(
                filtered_splits, feats, times_map, statuses_map,
                aggregator_name, num_classes, epochs, lr, logger, db, model_id, model_dir,
                optimizer, early_stopping_patience, case_level_ctx,
            )

    async def _train_survival_regular(
        self,
        splits_map: Dict[str, List[str]],
        feats: Dict[str, torch.Tensor],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        model_id: str,
        model_dir: Path,
        optimizer_type: str = "adam",
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
    ) -> TrainResponse:
        """Train with regular train/val/test splits."""
        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            training_feats = case_level_ctx["case_feats"]
            training_times = case_level_ctx["case_times"]
            training_statuses = case_level_ctx["case_statuses"]
            working_splits = case_splits
        else:
            training_feats = feats
            training_times = times_map
            training_statuses = statuses_map
            working_splits = splits_map

        train_ids = list(working_splits.get("train", []))  # Make a copy to avoid modifying original
        val_ids = list(working_splits.get("val", []))
        test_ids = working_splits.get("test", [])

        if not train_ids:
            raise ValueError("No training samples in splits_map")

        # Auto-create val split from train if val is empty (10% of train)
        auto_val_created = False
        if not val_ids and len(train_ids) > 1:
            import random
            n_val = max(1, int(len(train_ids) * 0.1))
            random.shuffle(train_ids)
            val_ids = train_ids[:n_val]
            train_ids = train_ids[n_val:]
            auto_val_created = True

        unit_name = "cases" if is_case_level else "samples"
        if auto_val_created:
            await logger.info(
                f"Auto-created val split: moved {len(val_ids)} {unit_name} from train to val (10%)",
                metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "auto_val": True, "data_level": "case" if is_case_level else "slide"}
            )

        await logger.info(
            f"Training survival model with splits: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)} {unit_name}",
            metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "data_level": "case" if is_case_level else "slide"}
        )

        # Get training data
        train_times = [training_times[sample_id] for sample_id in train_ids]
        train_statuses = [training_statuses[sample_id] for sample_id in train_ids]

        # Compute bin edges from training data only
        n_bins = max(2, num_classes)
        bin_edges = self._compute_bin_edges(train_times, train_statuses, n_bins)

        # Discretize all times using training bin edges
        all_ids = train_ids + val_ids + test_ids
        times = [training_times[sample_id] for sample_id in all_ids]
        statuses = [training_statuses[sample_id] for sample_id in all_ids]
        discretized_labels = self._discretize_times(times, bin_edges)

        # Create label tensors indexed by sample_id (wsi_id or case_id)
        y_bins_map = {sample_id: discretized_labels[i] for i, sample_id in enumerate(all_ids)}
        y_events_map = {sample_id: statuses[i] for i, sample_id in enumerate(all_ids)}

        # Determine feature dimension
        any_tensor = next(iter(training_feats.values()))
        in_dim = int(any_tensor.shape[1])

        # Build model
        model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=n_bins).to(self.device)
        criterion = NLLSurvivalLoss()

        # Dynamic optimizer selection
        optimizer_type_lower = optimizer_type.lower()
        if optimizer_type_lower == "sgd":
            optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
        elif optimizer_type_lower == "adamw":
            optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
        else:  # Default to adam
            optimizer = optim.Adam(model.parameters(), lr=lr)

        history = {"train_loss": [], "train_c_index": [], "val_loss": [], "val_c_index": []}
        best_val_loss = float('inf')
        best_val_c_index = None
        best_state_dict = None
        epochs_without_improvement = 0

        model.train()
        for epoch in range(1, epochs + 1):
            # Check for cancellation at each epoch start
            if is_task_cancelled(self.task_id):
                await logger.info(f"Training cancelled by user/timeout at epoch {epoch}")
                # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                del model, optimizer, criterion
                raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")

            # Training
            running_loss = 0.0
            epoch_preds = []
            optimizer.zero_grad()
            batch_accum = 32
            count = 0

            for i, sample_id in enumerate(train_ids):
                # Check for cancellation within the training loop
                if is_task_cancelled(self.task_id):
                    # Clean up CUDA tensors before raising exception
                    del model, optimizer, criterion
                    raise TrainingCancelledException(f"Training cancelled during epoch {epoch} loop")

                # Yield control to event loop to allow cancellation requests to be processed
                await asyncio.sleep(0)

                H = training_feats[sample_id].to(self.device)
                logits, _ = model(H)

                target_bin = torch.tensor([y_bins_map[sample_id]], dtype=torch.long, device=self.device)
                target_event = torch.tensor([y_events_map[sample_id]], dtype=torch.float32, device=self.device)

                loss = criterion(logits, target_bin, target_event)
                loss.backward()

                running_loss += float(loss.item())
                hazards = torch.sigmoid(logits).detach().cpu().numpy()
                epoch_preds.append(np.sum(hazards))

                count += 1
                if count % batch_accum == 0:
                    optimizer.step()
                    optimizer.zero_grad()

            if count % batch_accum != 0:
                optimizer.step()
                optimizer.zero_grad()

            epoch_loss = running_loss / max(1, len(train_ids))
            train_c_index = calculate_c_index(train_times, epoch_preds, train_statuses)
            history["train_loss"].append(epoch_loss)
            history["train_c_index"].append(train_c_index)

            # Validation
            val_loss, val_c_index = None, None
            if val_ids:
                val_loss, val_c_index = self._evaluate_survival(
                    model, training_feats, val_ids, training_times, training_statuses, y_bins_map, y_events_map, criterion
                )
                history["val_loss"].append(val_loss)
                history["val_c_index"].append(val_c_index)

                # Select best model based on validation loss (lower is better)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_val_c_index = val_c_index
                    best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

            log_msg = f"Epoch {epoch}/{epochs} - train_loss: {epoch_loss:.4f}, train_c_index: {train_c_index:.4f}"
            if val_ids:
                log_msg += f", val_loss: {val_loss:.4f}, val_c_index: {val_c_index:.4f}"
            await logger.info(log_msg, metadata={"epoch": epoch, "train_loss": epoch_loss, "train_c_index": train_c_index})

            # Update progress: training from 66% to 95%, saving from 95% to 100%
            progress = 66 + int(epoch / epochs * 29)
            await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
            await db.commit()

            # Early stopping check
            if val_ids and epochs_without_improvement >= early_stopping_patience:
                await logger.info(
                    f"Early stopping triggered at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                    metadata={"epoch": epoch, "best_val_loss": best_val_loss}
                )
                break

        # Restore best model
        if best_state_dict:
            model.load_state_dict(best_state_dict)

        # Test evaluation
        test_metrics = None
        if test_ids:
            test_loss, test_c_index = self._evaluate_survival(
                model, training_feats, test_ids, training_times, training_statuses, y_bins_map, y_events_map, criterion
            )
            test_metrics = {"loss": test_loss, "c_index": test_c_index}
            await logger.info(f"Test metrics: loss={test_loss:.4f}, c_index={test_c_index:.4f}", metadata=test_metrics)

        # Save checkpoint
        ckpt_path = model_dir / "aggregator.pth"
        torch.save({
            "state_dict": model.state_dict(),
            "in_dim": in_dim,
            "num_classes": n_bins,
            "bin_edges": bin_edges,
        }, ckpt_path)

        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "task_type": str(self.task_type),
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": n_bins,
            "epochs": epochs,
            "lr": lr,
            "bin_edges": bin_edges.tolist(),
            "split_type": "regular",
            "data_level": "case" if is_case_level else "slide",
        }, ensure_ascii=False, indent=2))

        # Save metrics
        metrics_data = {
            "is_kfold": False,
            "history": history,
            "val_metrics": {"c_index": history["val_c_index"][-1]} if val_ids and history["val_c_index"] else None,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Save survival results
        all_ids = train_ids + val_ids + test_ids
        await self._save_survival_results(
            model=model, feats=training_feats, wsi_ids=all_ids,
            times=[training_times[sample_id] for sample_id in all_ids],
            statuses=[training_statuses[sample_id] for sample_id in all_ids],
            task_id=self.task_id, bin_edges=bin_edges, logger=logger, db=db,
            aggregator_name=aggregator_name,
            case_level_ctx=case_level_ctx,
        )

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["train_loss"],
            val_metrics=test_metrics or ({"c_index": best_val_c_index} if val_ids and best_val_c_index else None),
        )

    def _evaluate_survival(
        self,
        model: nn.Module,
        feats: Dict[str, torch.Tensor],
        wsi_ids: List[str],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        y_bins_map: Dict[str, int],
        y_events_map: Dict[str, int],
        criterion: nn.Module,
    ) -> tuple:
        """Evaluate survival model on a split."""
        model.eval()
        total_loss = 0.0
        preds = []
        times = []
        statuses = []

        with torch.inference_mode():
            for wsi_id in wsi_ids:
                H = feats[wsi_id].to(self.device)
                logits, _ = model(H)

                target_bin = torch.tensor([y_bins_map[wsi_id]], dtype=torch.long, device=self.device)
                target_event = torch.tensor([y_events_map[wsi_id]], dtype=torch.float32, device=self.device)

                loss = criterion(logits, target_bin, target_event)
                total_loss += float(loss.item())

                hazards = torch.sigmoid(logits).cpu().numpy()
                preds.append(np.sum(hazards))
                times.append(times_map[wsi_id])
                statuses.append(statuses_map[wsi_id])

        avg_loss = total_loss / max(1, len(wsi_ids))
        c_index = calculate_c_index(times, preds, statuses)
        model.train()
        # Round to 4 decimal places
        return round(float(avg_loss), 4), round(float(c_index), 4)

    def _calculate_kfold_comprehensive_metrics(
        self,
        task_id: str,
        fold_keys: List[str],
        splits_map: Optional[Dict[str, List[str]]] = None,
    ) -> tuple:
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
        fold_c_indices = []
        fold_ibs_scores = []
        per_fold_ibs = {}  # fold_key -> IBS value

        for fold_key in fold_keys:
            # Collect survival data for this fold from saved JSON files
            all_risks = []
            all_times = []
            all_statuses = []
            all_surv_probs = []
            fold_bin_edges = None

            # Fast path: directly read files for known WSI IDs
            if splits_map and fold_key in splits_map:
                wsi_ids = splits_map[fold_key]
                for wsi_id in wsi_ids:
                    result_file = ai_results_root / wsi_id / f"train_{task_id}_{fold_key}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                risk_score = data.get("risk_score")
                                event_time = data.get("event_time")
                                event_status = data.get("event_status")
                                surv_probs = data.get("surv_probs")
                                bin_edges = data.get("bin_edges")

                                if risk_score is not None and event_time is not None and event_status is not None:
                                    all_risks.append(risk_score)
                                    all_times.append(event_time)
                                    all_statuses.append(event_status)
                                    if surv_probs is not None:
                                        all_surv_probs.append(surv_probs)
                                    if bin_edges is not None and fold_bin_edges is None:
                                        fold_bin_edges = bin_edges
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
                                        risk_score = data.get("risk_score")
                                        event_time = data.get("event_time")
                                        event_status = data.get("event_status")
                                        surv_probs = data.get("surv_probs")
                                        bin_edges = data.get("bin_edges")

                                        if risk_score is not None and event_time is not None and event_status is not None:
                                            all_risks.append(risk_score)
                                            all_times.append(event_time)
                                            all_statuses.append(event_status)
                                            if surv_probs is not None:
                                                all_surv_probs.append(surv_probs)
                                            if bin_edges is not None and fold_bin_edges is None:
                                                fold_bin_edges = bin_edges
                            except Exception:
                                continue

            if len(all_risks) >= 2:
                # Calculate c_index using the existing function
                c_index = calculate_c_index(all_times, all_risks, all_statuses)
                if c_index is not None and not np.isnan(c_index):
                    fold_c_indices.append(c_index)

                # Calculate IBS if we have survival probabilities and bin edges
                if len(all_surv_probs) >= 2 and fold_bin_edges is not None:
                    ibs = self._calculate_ibs(all_times, all_statuses, all_surv_probs, fold_bin_edges)
                    if ibs is not None and not np.isnan(ibs):
                        fold_ibs_scores.append(ibs)
                        per_fold_ibs[fold_key] = round(float(ibs), 4)

        # Calculate mean and std for metrics
        # Round to 4 decimal places, filter out nan values
        aggregated = {}
        if fold_c_indices:
            mean_val = float(np.mean(fold_c_indices))
            std_val = float(np.std(fold_c_indices))
            if not np.isnan(mean_val) and not np.isnan(std_val):
                aggregated["c_index"] = {
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                }
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
                dtype=[('event', bool), ('time', float)]
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
            ibs = integrated_brier_score(y_struct, y_struct, surv_probs_filtered, eval_times)

            # Check for nan
            if np.isnan(ibs):
                return None

            return float(ibs)

        except Exception:
            return None

    async def _train_survival_kfold(
        self,
        splits_map: Dict[str, List[str]],
        feats: Dict[str, torch.Tensor],
        times_map: Dict[str, float],
        statuses_map: Dict[str, int],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        model_id: str,
        model_dir: Path,
        optimizer_type: str = "adam",
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
    ) -> TrainResponse:
        """Train with K-Fold cross-validation."""
        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            training_feats = case_level_ctx["case_feats"]
            training_times = case_level_ctx["case_times"]
            training_statuses = case_level_ctx["case_statuses"]
            working_splits = case_splits
        else:
            training_feats = feats
            training_times = times_map
            training_statuses = statuses_map
            working_splits = splits_map

        num_folds = self._get_num_folds(working_splits)
        fold_keys = sorted([k for k in working_splits.keys() if k.startswith("fold_")])

        unit_name = "cases" if is_case_level else "samples"
        await logger.info(
            f"Starting {num_folds}-fold cross-validation for Survival Analysis ({unit_name})",
            metadata={"num_folds": num_folds, "epochs_per_fold": epochs, "data_level": "case" if is_case_level else "slide"}
        )

        fold_results = {}
        all_val_c_indices = []
        n_bins = max(2, num_classes)

        for fold_idx, val_fold_key in enumerate(fold_keys):
            val_ids = working_splits[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(working_splits[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)} {unit_name}",
                metadata={"fold": fold_idx + 1}
            )

            # Compute bin edges from this fold's training data
            train_times = [training_times[sample_id] for sample_id in train_ids]
            train_statuses = [training_statuses[sample_id] for sample_id in train_ids]
            bin_edges = self._compute_bin_edges(train_times, train_statuses, n_bins)

            # Discretize all times
            all_ids = train_ids + val_ids
            times = [training_times[sample_id] for sample_id in all_ids]
            discretized_labels = self._discretize_times(times, bin_edges)
            y_bins_map = {sample_id: discretized_labels[i] for i, sample_id in enumerate(all_ids)}
            y_events_map = {sample_id: training_statuses[sample_id] for sample_id in all_ids}

            # Build model
            any_tensor = next(iter(training_feats.values()))
            in_dim = int(any_tensor.shape[1])
            model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=n_bins).to(self.device)
            criterion = NLLSurvivalLoss()

            # Dynamic optimizer selection
            optimizer_type_lower = optimizer_type.lower()
            if optimizer_type_lower == "sgd":
                optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
            elif optimizer_type_lower == "adamw":
                optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
            else:  # Default to adam
                optimizer = optim.Adam(model.parameters(), lr=lr)

            history = {"loss": [], "c_index": [], "val_loss": []}
            best_val_loss = float('inf')
            best_state_dict = None
            epochs_without_improvement = 0

            model.train()
            for epoch in range(1, epochs + 1):
                running_loss = 0.0
                epoch_preds = []
                optimizer.zero_grad()
                batch_accum = 32
                count = 0

                for sample_id in train_ids:
                    # Check for cancellation within the k-fold training loop
                    if is_task_cancelled(self.task_id):
                        # Clean up CUDA tensors before raising exception
                        del model, optimizer, criterion
                        raise TrainingCancelledException(f"Training cancelled during fold {fold_idx+1}, epoch {epoch} loop")

                    # Yield control to event loop to allow cancellation requests to be processed
                    await asyncio.sleep(0)

                    H = training_feats[sample_id].to(self.device)
                    logits, _ = model(H)

                    target_bin = torch.tensor([y_bins_map[sample_id]], dtype=torch.long, device=self.device)
                    target_event = torch.tensor([y_events_map[sample_id]], dtype=torch.float32, device=self.device)

                    loss = criterion(logits, target_bin, target_event)
                    loss.backward()

                    running_loss += float(loss.item())
                    hazards = torch.sigmoid(logits).detach().cpu().numpy()
                    epoch_preds.append(np.sum(hazards))

                    count += 1
                    if count % batch_accum == 0:
                        optimizer.step()
                        optimizer.zero_grad()

                if count % batch_accum != 0:
                    optimizer.step()
                    optimizer.zero_grad()

                epoch_loss = running_loss / max(1, len(train_ids))
                train_c_index = calculate_c_index(train_times, epoch_preds, train_statuses)
                history["loss"].append(epoch_loss)
                history["c_index"].append(train_c_index)

                # Validation
                val_loss, val_c_index = self._evaluate_survival(
                    model, training_feats, val_ids, training_times, training_statuses, y_bins_map, y_events_map, criterion
                )
                history["val_loss"].append(val_loss)

                # Select best model based on validation loss (lower is better)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

                # Progress (66-100% for all folds including saving)
                # Each fold gets 34/num_folds percent; 70% for training, 30% for saving
                fold_total_range = 34 / num_folds
                fold_progress_base = 66 + int(fold_idx * fold_total_range)
                fold_training_range = int(fold_total_range * 0.7)
                progress = fold_progress_base + int(epoch / epochs * fold_training_range)
                await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
                await db.commit()

                # Early stopping check
                if epochs_without_improvement >= early_stopping_patience:
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Early stopping at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                        metadata={"fold": fold_idx + 1, "epoch": epoch, "best_val_loss": best_val_loss}
                    )
                    break

            # Restore best and evaluate
            if best_state_dict:
                model.load_state_dict(best_state_dict)
            final_val_loss, final_val_c_index = self._evaluate_survival(
                model, training_feats, val_ids, training_times, training_statuses, y_bins_map, y_events_map, criterion
            )

            fold_results[val_fold_key] = {
                "history": history,
                "val_metrics": {"loss": final_val_loss, "c_index": final_val_c_index},
            }
            all_val_c_indices.append(final_val_c_index)

            # Save fold checkpoint
            fold_dir = model_dir / val_fold_key
            fold_dir.mkdir(parents=True, exist_ok=True)
            torch.save({
                "state_dict": model.state_dict(),
                "in_dim": in_dim,
                "num_classes": n_bins,
                "bin_edges": bin_edges,
            }, fold_dir / "aggregator.pth")

            # Calculate saving progress range for this fold
            fold_total_range = 34 / num_folds
            fold_progress_base = 66 + int(fold_idx * fold_total_range)
            fold_training_range = int(fold_total_range * 0.7)
            fold_saving_base = fold_progress_base + fold_training_range
            fold_saving_range = max(1, int(fold_total_range * 0.3))

            # Save per-WSI inference results for this fold's VALIDATION set only
            await self._save_survival_results(
                model=model, feats=training_feats, wsi_ids=val_ids,
                times=[training_times[sample_id] for sample_id in val_ids],
                statuses=[training_statuses[sample_id] for sample_id in val_ids],
                task_id=self.task_id, bin_edges=bin_edges, logger=logger, db=db,
                aggregator_name=aggregator_name, fold_key=val_fold_key,
                progress_base=fold_saving_base,
                progress_range=fold_saving_range,
                case_level_ctx=case_level_ctx,
            )

            await logger.info(
                f"Fold {fold_idx + 1} complete: c_index={final_val_c_index:.4f}",
                metadata={"fold": fold_idx + 1, "c_index": round(float(final_val_c_index), 4)}
            )

        # Calculate aggregated statistics (basic metrics from training, rounded to 4 decimal places)
        aggregated = {
            "c_index": {
                "mean": round(float(np.mean(all_val_c_indices)), 4),
                "std": round(float(np.std(all_val_c_indices)), 4),
            },
        }

        # Calculate comprehensive metrics by reading saved JSON files
        # This recalculates c_index from saved risk scores and calculates IBS
        # Pass splits_map to enable fast direct file access instead of slow directory scanning
        # For case-level, we need to use the original splits_map (with wsi_ids) for file access
        comprehensive_metrics, per_fold_ibs = self._calculate_kfold_comprehensive_metrics(
            task_id=self.task_id,
            fold_keys=fold_keys,
            splits_map=splits_map,  # Always use original wsi_id splits for file access
        )
        # Merge comprehensive metrics into aggregated (don't overwrite c_index already calculated)
        for metric_name, metric_stats in comprehensive_metrics.items():
            if metric_name not in aggregated:
                aggregated[metric_name] = metric_stats

        # Add per-fold IBS to fold_results
        for fold_key, ibs_value in per_fold_ibs.items():
            if fold_key in fold_results:
                fold_results[fold_key]["val_metrics"]["integrated_brier_score"] = ibs_value

        await logger.info(
            f"K-Fold complete: c_index={aggregated['c_index']['mean']:.4f}±{aggregated['c_index']['std']:.4f}",
            metadata={"aggregated": aggregated}
        )

        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "task_type": str(self.task_type),
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": n_bins,
            "epochs": epochs,
            "lr": lr,
            "split_type": "kfold",
            "num_folds": num_folds,
            "data_level": "case" if is_case_level else "slide",
        }, ensure_ascii=False, indent=2))

        # Save aggregated metrics
        metrics_data = {
            "is_kfold": True,
            "num_folds": num_folds,
            "folds": fold_results,
            "aggregated": aggregated,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        ckpt_path = model_dir / "fold_0" / "aggregator.pth"

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
        attention: Optional[np.ndarray],
        case_id: str,
        case_wsi_patch_counts: Dict[str, List[int]],
        case_to_wsi: Dict[str, List[str]],
    ) -> Dict[str, Optional[np.ndarray]]:
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

        slide_attentions: Dict[str, Optional[np.ndarray]] = {}
        start_idx = 0

        for wsi_id, count in zip(wsi_ids, patch_counts):
            end_idx = start_idx + count
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
        feats,
        wsi_ids,
        times,
        statuses,
        task_id,
        bin_edges,
        logger,
        db,
        aggregator_name: str = None,
        fold_key: Optional[str] = None,
        progress_base: int = 90,
        progress_range: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
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
        - 0-20%: Inference
        - 20-80%: File I/O (per-file progress)
        - 80-90%: Database insert
        - 90-100%: Metrics calculation

        For each WSI, saves:
        - Risk score and risk group
        - Hazards and survival probabilities
        - Attention weights for heatmap visualization

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_attention.npy (if attention available)

        Args:
            fold_key: Optional fold identifier (e.g., "fold_0") for k-fold training.
            progress_base: Starting progress percentage (default 90 for regular training)
            progress_range: Total progress range for saving (default 10 for regular training)
            case_level_ctx: Case-level context dict with case_to_wsi, case_wsi_patch_counts, etc.
        """
        import concurrent.futures
        from functools import partial

        is_case_level = case_level_ctx is not None
        fold_suffix = f"_{fold_key}" if fold_key else ""
        fold_desc = f" ({fold_key})" if fold_key else ""

        # For case-level, wsi_ids are actually case_ids
        # We need to count actual WSI slides for progress
        if is_case_level:
            case_to_wsi = case_level_ctx["case_to_wsi"]
            case_wsi_patch_counts = case_level_ctx["case_wsi_patch_counts"]
            original_times = case_level_ctx["original_times"]
            original_statuses = case_level_ctx["original_statuses"]
            # Count total slides
            total_slides = sum(len(case_to_wsi.get(case_id, [])) for case_id in wsi_ids)
            total_wsi = total_slides
        else:
            total_wsi = len(wsi_ids)

        # Calculate progress points based on progress_base and progress_range
        progress_inference = progress_base
        progress_file_io_start = progress_base + int(progress_range * 0.2)
        progress_file_io_end = progress_base + int(progress_range * 0.8)
        progress_db = progress_base + int(progress_range * 0.8)
        progress_metrics = progress_base + int(progress_range * 0.9)
        file_io_progress_range = progress_file_io_end - progress_file_io_start

        await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress_inference)
        unit_name = "slides" if is_case_level else "WSI slides"
        await logger.info(
            f"[Saving] Starting to save survival results{fold_desc} for {total_wsi} {unit_name}...",
            {"task_id": task_id, "num_wsi": total_wsi, "fold_key": fold_key, "phase": "saving_results", "is_case_level": is_case_level}
        )
        await db.commit()

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        has_raw_attention = hasattr(model, 'forward_with_raw_attention')

        all_risks = []
        file_save_items = []  # For parallel file saving
        db_records = []  # For batch database insert

        # Phase 1: Run inference and collect results (GPU-bound, sequential)
        with torch.inference_mode():
            for i, sample_id in enumerate(wsi_ids):
                H = feats[sample_id].to(self.device)

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                # Compute hazards
                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                surv = np.cumprod(1 - hazards)
                risk_score = np.sum(hazards)
                all_risks.append((sample_id, risk_score, hazards, surv, attention, raw_attention))

        # Calculate median risk score for risk stratification
        median_risk_score = float(np.median([r[1] for r in all_risks]))

        # Phase 2: Build results (split by case if case-level)
        for i, (sample_id, risk_score, hazards, surv, attention, raw_attention) in enumerate(all_risks):
            attention_np = attention.cpu().numpy() if attention is not None else None
            raw_attention_np = raw_attention.cpu().numpy() if raw_attention is not None else None
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            if is_case_level:
                # Case-level: split attention back to per-slide and save per WSI
                case_id = sample_id
                slide_wsi_ids = case_to_wsi.get(case_id, [])
                slide_attentions = self._split_case_attention_to_slides(
                    attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )
                slide_raw_attentions = self._split_case_attention_to_slides(
                    raw_attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                ) if raw_attention_np is not None else {wsi_id: None for wsi_id in slide_wsi_ids}

                for wsi_id in slide_wsi_ids:
                    wsi_result_dir = ai_results_root / wsi_id
                    slide_attn = slide_attentions.get(wsi_id)
                    slide_raw_attn = slide_raw_attentions.get(wsi_id)

                    # Use the slide's own ground truth event_time/status (should be same for case-level survival)
                    wsi_event_time = original_times.get(wsi_id, times[i])
                    wsi_event_status = original_statuses.get(wsi_id, statuses[i])

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
                        "data_level": "case",
                    }
                    if fold_key:
                        result_data["fold_key"] = fold_key

                    file_save_items.append((wsi_result_dir, result_data, slide_attn, slide_raw_attn, fold_suffix, task_id))

                    result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
                    attention_file_path = str(wsi_result_dir / f"train_{task_id}{fold_suffix}_attention.npy") if slide_attn is not None else None
                    db_records.append({
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": risk_group,
                        "probs": None,
                        "extra_metadata": {
                            "task_type": "survival_prediction",
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
                            "data_level": "case",
                        }
                    })
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
                    "event_time": times[i],
                    "event_status": statuses[i],
                    "bin_edges": bin_edges.tolist(),
                    "aggregator": aggregator_name,
                }
                if fold_key:
                    result_data["fold_key"] = fold_key

                file_save_items.append((result_dir, result_data, attention_np, raw_attention_np, fold_suffix, task_id))

                result_file = result_dir / f"train_{task_id}{fold_suffix}_result.json"
                attention_file_path = str(result_dir / f"train_{task_id}{fold_suffix}_attention.npy") if attention_np is not None else None
                db_records.append({
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": risk_group,
                    "probs": None,
                    "extra_metadata": {
                        "task_type": "survival_prediction",
                        "risk_score": float(risk_score),
                        "risk_group": risk_group,
                        "median_risk_score": median_risk_score,
                        "hazards": hazards.tolist(),
                        "surv_probs": surv.tolist(),
                        "event_time": times[i],
                        "event_status": statuses[i],
                        "bin_edges": bin_edges.tolist(),
                        "result_file": str(result_file),
                        "attention_file": attention_file_path,
                        "fold_key": fold_key,
                    }
                })

        # Phase 2: Parallel file I/O using thread pool with progress updates
        await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress_file_io_start)
        await logger.info(
            f"[Saving] Writing {total_wsi} result files to disk...",
            {"phase": "writing_files", "num_files": total_wsi}
        )
        await db.commit()

        completed_count = [0]
        progress_lock = asyncio.Lock()

        def save_single_wsi_files(item):
            """Synchronous function to save files for a single WSI."""
            result_dir, result_data, attention_np, raw_attention_np, fold_suffix, task_id = item
            result_dir.mkdir(parents=True, exist_ok=True)

            result_file = result_dir / f"train_{task_id}{fold_suffix}_result.json"
            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            if attention_np is not None:
                attention_file = result_dir / f"train_{task_id}{fold_suffix}_attention.npy"
                np.save(attention_file, attention_np)

            if raw_attention_np is not None:
                raw_attention_file = result_dir / f"train_{task_id}{fold_suffix}_attention_raw.npy"
                np.save(raw_attention_file, raw_attention_np)

            return result_data["wsi_id"]

        async def save_with_progress(executor, item, total, db, task_id_for_update,
                                      file_io_start, file_io_range):
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, save_single_wsi_files, item)
            async with progress_lock:
                completed_count[0] += 1
                update_interval = max(1, min(total // 10, 50))
                if completed_count[0] % update_interval == 0 or completed_count[0] == total:
                    file_progress = file_io_start + int(completed_count[0] / total * file_io_range)
                    await TrainingTaskRepository.update_status(db, task_id_for_update, "training", progress=file_progress)
                    await db.commit()
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            tasks = [
                save_with_progress(executor, item, total_wsi, db, self.task_id,
                                   progress_file_io_start, file_io_progress_range)
                for item in file_save_items
            ]
            await asyncio.gather(*tasks)

        # Phase 3: Batch database insert
        await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress_db)
        await logger.info(
            f"[Saving] Inserting {len(db_records)} records to database...",
            {"phase": "database_insert", "num_records": len(db_records)}
        )
        await db.commit()

        await AIResultRepository.bulk_create(db, db_records, batch_size=100)

        # Phase 4: Calculate and log final metrics
        await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress_metrics)

        # Extract risk scores from collected data (all_risks is list of tuples)
        risk_scores_for_c_index = [r[1] for r in all_risks]
        overall_c_index = round(float(calculate_c_index(times, risk_scores_for_c_index, statuses)), 4)

        await logger.info(
            f"[Saving] Complete - Final C-Index: {overall_c_index:.4f}",
            metadata={"c_index": overall_c_index}
        )
        await db.commit()
