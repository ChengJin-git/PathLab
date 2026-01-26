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

        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        is_kfold = self._is_kfold_splits(filtered_splits)

        if is_kfold:
            return await self._train_survival_kfold(
                filtered_splits, feats, times_map, statuses_map,
                aggregator_name, num_classes, epochs, lr, logger, db, model_id, model_dir,
                optimizer, early_stopping_patience
            )
        else:
            return await self._train_survival_regular(
                filtered_splits, feats, times_map, statuses_map,
                aggregator_name, num_classes, epochs, lr, logger, db, model_id, model_dir,
                optimizer, early_stopping_patience
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
    ) -> TrainResponse:
        """Train with regular train/val/test splits."""
        train_ids = list(splits_map.get("train", []))  # Make a copy to avoid modifying original
        val_ids = list(splits_map.get("val", []))
        test_ids = splits_map.get("test", [])

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

        if auto_val_created:
            await logger.info(
                f"Auto-created val split: moved {len(val_ids)} samples from train to val (10%)",
                metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "auto_val": True}
            )

        await logger.info(
            f"Training survival model with splits: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)}",
            metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)}
        )

        # Get training data
        train_times = [times_map[wsi_id] for wsi_id in train_ids]
        train_statuses = [statuses_map[wsi_id] for wsi_id in train_ids]

        # Compute bin edges from training data only
        n_bins = max(2, num_classes)
        bin_edges = self._compute_bin_edges(train_times, train_statuses, n_bins)

        # Discretize all times using training bin edges
        all_ids = train_ids + val_ids + test_ids
        times = [times_map[wsi_id] for wsi_id in all_ids]
        statuses = [statuses_map[wsi_id] for wsi_id in all_ids]
        discretized_labels = self._discretize_times(times, bin_edges)

        # Create label tensors indexed by wsi_id
        y_bins_map = {wsi_id: discretized_labels[i] for i, wsi_id in enumerate(all_ids)}
        y_events_map = {wsi_id: statuses[i] for i, wsi_id in enumerate(all_ids)}

        # Determine feature dimension
        any_tensor = next(iter(feats.values()))
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

            for i, wsi_id in enumerate(train_ids):
                # Check for cancellation within the training loop
                if is_task_cancelled(self.task_id):
                    # Clean up CUDA tensors before raising exception
                    del model, optimizer, criterion
                    raise TrainingCancelledException(f"Training cancelled during epoch {epoch} loop")

                # Yield control to event loop to allow cancellation requests to be processed
                await asyncio.sleep(0)

                H = feats[wsi_id].to(self.device)
                logits, _ = model(H)

                target_bin = torch.tensor([y_bins_map[wsi_id]], dtype=torch.long, device=self.device)
                target_event = torch.tensor([y_events_map[wsi_id]], dtype=torch.float32, device=self.device)

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
                    model, feats, val_ids, times_map, statuses_map, y_bins_map, y_events_map, criterion
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

            progress = 66 + int(epoch / epochs * 34)
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
                model, feats, test_ids, times_map, statuses_map, y_bins_map, y_events_map, criterion
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
            model=model, feats=feats, wsi_ids=all_ids,
            times=[times_map[wsi_id] for wsi_id in all_ids],
            statuses=[statuses_map[wsi_id] for wsi_id in all_ids],
            task_id=self.task_id, bin_edges=bin_edges, logger=logger, db=db,
            aggregator_name=aggregator_name,
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
        return avg_loss, c_index

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
    ) -> TrainResponse:
        """Train with K-Fold cross-validation."""
        num_folds = self._get_num_folds(splits_map)
        fold_keys = sorted([k for k in splits_map.keys() if k.startswith("fold_")])

        await logger.info(
            f"Starting {num_folds}-fold cross-validation for Survival Analysis",
            metadata={"num_folds": num_folds, "epochs_per_fold": epochs}
        )

        fold_results = {}
        all_val_c_indices = []
        n_bins = max(2, num_classes)

        for fold_idx, val_fold_key in enumerate(fold_keys):
            val_ids = splits_map[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(splits_map[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)}",
                metadata={"fold": fold_idx + 1}
            )

            # Compute bin edges from this fold's training data
            train_times = [times_map[wsi_id] for wsi_id in train_ids]
            train_statuses = [statuses_map[wsi_id] for wsi_id in train_ids]
            bin_edges = self._compute_bin_edges(train_times, train_statuses, n_bins)

            # Discretize all times
            all_ids = train_ids + val_ids
            times = [times_map[wsi_id] for wsi_id in all_ids]
            discretized_labels = self._discretize_times(times, bin_edges)
            y_bins_map = {wsi_id: discretized_labels[i] for i, wsi_id in enumerate(all_ids)}
            y_events_map = {wsi_id: statuses_map[wsi_id] for wsi_id in all_ids}

            # Build model
            any_tensor = next(iter(feats.values()))
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

                for wsi_id in train_ids:
                    # Check for cancellation within the k-fold training loop
                    if is_task_cancelled(self.task_id):
                        # Clean up CUDA tensors before raising exception
                        del model, optimizer, criterion
                        raise TrainingCancelledException(f"Training cancelled during fold {fold_idx+1}, epoch {epoch} loop")

                    # Yield control to event loop to allow cancellation requests to be processed
                    await asyncio.sleep(0)

                    H = feats[wsi_id].to(self.device)
                    logits, _ = model(H)

                    target_bin = torch.tensor([y_bins_map[wsi_id]], dtype=torch.long, device=self.device)
                    target_event = torch.tensor([y_events_map[wsi_id]], dtype=torch.float32, device=self.device)

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
                    model, feats, val_ids, times_map, statuses_map, y_bins_map, y_events_map, criterion
                )
                history["val_loss"].append(val_loss)

                # Select best model based on validation loss (lower is better)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

                # Progress
                fold_progress_base = 66 + int(fold_idx / num_folds * 34)
                fold_progress_range = int(34 / num_folds)
                progress = fold_progress_base + int(epoch / epochs * fold_progress_range)
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
                model, feats, val_ids, times_map, statuses_map, y_bins_map, y_events_map, criterion
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

            # Save per-WSI inference results for this fold's VALIDATION set only
            # In K-Fold, each sample should be predicted by the model that didn't see it during training
            # This ensures the saved predictions are truly out-of-sample predictions
            await self._save_survival_results(
                model=model, feats=feats, wsi_ids=val_ids,
                times=[times_map[wsi_id] for wsi_id in val_ids],
                statuses=[statuses_map[wsi_id] for wsi_id in val_ids],
                task_id=self.task_id, bin_edges=bin_edges, logger=logger, db=db,
                aggregator_name=aggregator_name,
            )

            await logger.info(
                f"Fold {fold_idx + 1} complete: c_index={final_val_c_index:.4f}",
                metadata={"fold": fold_idx + 1, "c_index": final_val_c_index}
            )

        # Calculate aggregated statistics
        aggregated = {
            "c_index": {
                "mean": float(np.mean(all_val_c_indices)),
                "std": float(np.std(all_val_c_indices)),
            },
        }

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
    ):
        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        has_raw_attention = hasattr(model, 'forward_with_raw_attention')

        all_risks = []
        all_results = []  # Store results temporarily for median calculation
        result_files = []  # Store (result_dir, task_id) pairs for updating with median

        with torch.inference_mode():
            for i, wsi_id in enumerate(wsi_ids):
                H = feats[wsi_id].to(self.device)

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                # Compute hazards
                hazards = torch.sigmoid(logits).cpu().numpy().flatten()

                # Compute survival function S(t) = prod(1-h) for discrete bins
                # S_k = S(t > bin_k_end) = Prod_{j=0}^k (1 - h_j)
                surv = np.cumprod(1 - hazards)

                # Risk score (cumulative hazard sum)
                risk_score = np.sum(hazards)
                all_risks.append(risk_score)

                result_dir = ai_results_root / wsi_id
                result_dir.mkdir(parents=True, exist_ok=True)

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "risk_score": float(risk_score),
                    "hazards": hazards.tolist(),
                    "surv_probs": surv.tolist(),
                    "event_time": times[i],
                    "event_status": statuses[i],
                    "bin_edges": bin_edges.tolist(),
                    "aggregator": aggregator_name,
                }

                all_results.append(result_data)
                result_files.append((result_dir, task_id, attention, raw_attention))

        # Calculate median risk score for risk stratification
        median_risk_score = float(np.median(all_risks))

        # Update results with median and risk group, then save
        for result_data, (result_dir, task_id, attention, raw_attention) in zip(all_results, result_files):
            result_data["median_risk_score"] = median_risk_score
            result_data["risk_group"] = "High Risk" if result_data["risk_score"] >= median_risk_score else "Low Risk"

            result_file = result_dir / f"train_{task_id}_result.json"
            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            # Save attention (softmax processed) for heatmap visualization
            attention_file_path = None
            if attention is not None:
                attention_file = result_dir / f"train_{task_id}_attention.npy"
                np.save(attention_file, attention.cpu().numpy())
                attention_file_path = str(attention_file)

            # Save raw attention (before softmax) if available
            if raw_attention is not None:
                raw_attention_file = result_dir / f"train_{task_id}_attention_raw.npy"
                np.save(raw_attention_file, raw_attention.cpu().numpy())

            # Save to ai_results database table
            db_result_data = {
                "wsi_id": result_data["wsi_id"],
                "task_id": task_id,
                "pred": result_data["risk_group"],  # Use risk_group as prediction
                "probs": None,  # No class probabilities for survival
                "extra_metadata": {
                    "task_type": "survival_prediction",
                    "risk_score": result_data["risk_score"],
                    "risk_group": result_data["risk_group"],
                    "median_risk_score": median_risk_score,
                    "hazards": result_data["hazards"],
                    "surv_probs": result_data["surv_probs"],
                    "event_time": result_data["event_time"],
                    "event_status": result_data["event_status"],
                    "bin_edges": result_data["bin_edges"],
                    "result_file": str(result_file),
                    "attention_file": attention_file_path,
                }
            }
            await AIResultRepository.create(db, db_result_data)

        # Commit AI results to database
        await db.commit()

        # Calculate overall C-Index
        overall_c_index = calculate_c_index(times, all_risks, statuses)

        await logger.info(
            f"Survival Training Finished. Final C-Index: {overall_c_index:.4f}",
            metadata={"c_index": overall_c_index}
        )
