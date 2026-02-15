"""
Patch Classification Trainer - Feature Extractor + Linear Probe.

Consistent training paradigm with WSI Classification:
1. Use Foundation Model as Feature Extractor (frozen)
2. Train Linear Probe (instead of Aggregator for WSI)
"""
from __future__ import annotations

import json
import asyncio
import logging
import random
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from sklearn.metrics import (
    roc_auc_score, accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix as sklearn_confusion_matrix
)

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.tasks.patch_classification.linear_layer import LinearProbe
from backend.ai.schemas import TaskType, TaskStatus, TrainResponse, FeatureExtractionResponse
from backend.ai.utils.patch_dataset import PatchDatasetFromDB
from backend.ai.utils.cam_utils import get_cam_extractor, get_cam_spatial_size
from backend.database.repositories import TrainingTaskRepository, WSIRepository, AIResultRepository
from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException
from backend.ai.permission_revocation import is_permission_revoked, PermissionRevokedException
from backend.ai.tasks.training_utils import (
    safe_update_progress as _safe_update_progress,
    scoped_db,
    is_kfold_splits,
    get_num_folds,
    calculate_kfold_classification_metrics,
)


logger = logging.getLogger("patch_classification_trainer")


class PatchClassificationTrainer(BaseTrainer):
    """
    Trainer for patch-level classification tasks.

    Pipeline (aligned with WSI Classification):
    1. Use Feature Extractor (e.g., ResNet50, UNI, CONCH) to extract patch features (frozen)
    2. Train Linear Probe for classification (instead of Aggregator for WSI)
    3. Save checkpoint and metrics
    """

    task_type = TaskType.PATCH_CLASSIFICATION

    def __init__(
        self,
        task_id: str,
        uploads_root: str,
        device: str | None = None,
        batch_size: int = 64,
        hf_token: str = "",
        dropout_p: float = 0.0,
    ):
        super().__init__(task_id, uploads_root, device)
        self.batch_size = batch_size
        self.hf_token = hf_token
        self.dropout_p = dropout_p

    async def extract_features(
        self,
        wsi_ids: List[str],
        extractor_name: str,
        batch_size: int,
        force_recompute: bool,
        logger: Any,
        session_maker: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict] = None,
    ) -> FeatureExtractionResponse:
        """
        Patch classification extracts features on-the-fly during training.
        This method is a no-op to satisfy the BaseTrainer interface.
        """
        # Suppress unused parameter warnings (required by BaseTrainer interface)
        del wsi_ids, extractor_name, batch_size, force_recompute, logger, session_maker, hf_token, preprocessing_config
        return self._build_feature_response([])

    def _is_kfold_splits(self, splits_map: Dict[str, List[str]]) -> bool:
        return is_kfold_splits(splits_map)

    def _get_num_folds(self, splits_map: Dict[str, List[str]]) -> int:
        return get_num_folds(splits_map)

    def _calculate_kfold_comprehensive_metrics(
        self,
        task_id: str,
        fold_keys: List[str],
        classes: List[str],
        splits_map: Optional[Dict[str, List[str]]] = None,
    ) -> tuple:
        """Delegate to shared classification metrics calculator."""
        return calculate_kfold_classification_metrics(
            self.uploads_root, task_id, fold_keys, classes, splits_map
        )

    async def train_model(
        self,
        splits_map: Dict[str, List[str]],
        aggregator_name: str,  # For patch classification, this is the extractor name
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
        seed: Optional[int] = 42,
    ) -> TrainResponse:
        """
        Train Linear Probe on frozen Feature Extractor.

        Aligned with WSI Classification's train_model() interface.
        For patch classification:
        - aggregator_name is reused as the feature extractor name
        - splits_map contains data split assignments

        Args:
            optimizer: Optimizer type ('adam', 'sgd', 'adamw')
            auto_balance: Whether to apply class weights for imbalanced datasets
            early_stopping_patience: Number of epochs to wait before early stopping
            seed: Random seed for reproducibility (default: 42)
        """
        # Set global random seeds for reproducibility
        if seed is not None:
            self._set_seed(seed)
            await logger.info(f"Random seed set to {seed} for reproducibility")

        extractor_name = aggregator_name  # Reuse parameter for API compatibility

        # Collect all image IDs
        all_ids = []
        for ids in splits_map.values():
            all_ids.extend(ids)
        all_ids = list(set(all_ids))

        # Get labels from database using batch query (avoid N+1 problem) - short-lived session
        async with scoped_db(session_maker) as db:
            wsi_map = await WSIRepository.get_by_ids(db, all_ids)

        labels = {}
        classes = []
        image_paths = {}
        for wsi_id in all_ids:
            wsi = wsi_map.get(wsi_id)
            if not wsi or not wsi.label:
                raise ValueError(f"Image {wsi_id} has invalid/missing label")
            if wsi.label not in classes:
                classes.append(wsi.label)
            image_paths[wsi_id] = wsi.wsi_path

        classes = sorted(classes)
        for wsi_id in all_ids:
            wsi = wsi_map[wsi_id]
            if not wsi.label or wsi.label not in classes:
                raise ValueError(f"Image {wsi_id} has invalid/missing label")
            labels[wsi_id] = classes.index(wsi.label)

        # Build label mapper
        label_mapper = {label: idx for idx, label in enumerate(classes)}

        is_kfold = self._is_kfold_splits(splits_map)

        if is_kfold:
            return await self._train_kfold(
                splits_map, image_paths, labels, classes, label_mapper,
                extractor_name, num_classes, epochs, lr, logger, session_maker, all_ids,
                optimizer, auto_balance, early_stopping_patience
            )
        else:
            return await self._train_regular(
                splits_map, image_paths, labels, classes, label_mapper,
                extractor_name, num_classes, epochs, lr, logger, session_maker, all_ids,
                optimizer, auto_balance, early_stopping_patience
            )

    @staticmethod
    def _run_one_epoch(
        train_loader: DataLoader,
        extractor: nn.Module,
        linear_probe: nn.Module,
        criterion: nn.Module,
        optimizer,
        device: str,
        task_id: str,
    ):
        """
        Run one training epoch synchronously.

        Must be called via asyncio.to_thread() to avoid blocking the event loop.
        GPU operations (forward/backward pass) and DataLoader iteration are blocking.

        Returns:
            Tuple of (running_loss, num_batches, stop_reason).
            stop_reason is None if completed normally, 'cancelled' or 'permission_revoked' otherwise.
        """
        linear_probe.train()
        running_loss = 0.0
        num_batches = 0
        batch_count = 0

        for batch_img, gt in train_loader:
            batch_count += 1

            # Check for cancellation/permission every 50 batches
            if batch_count % 50 == 0:
                if is_task_cancelled(task_id):
                    return None, 0, "cancelled"
                if is_permission_revoked(task_id):
                    return None, 0, "permission_revoked"

            batch_img = batch_img.to(device)
            gt = gt.to(device).long()

            optimizer.zero_grad()

            with torch.no_grad():
                features = extractor(batch_img)

            logits = linear_probe(features)
            loss = criterion(logits, gt)

            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            num_batches += 1

        return running_loss, num_batches, None

    async def _train_regular(
        self,
        splits_map: Dict[str, List[str]],
        image_paths: Dict[str, str],
        labels: Dict[str, int],
        classes: List[str],
        label_mapper: Dict[str, int],
        extractor_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        all_ids: List[str],
        optimizer_type: str = "adam",
        auto_balance: bool = False,
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
                {"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "auto_val": True}
            )

        # Build path -> label mapping for each split
        train_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in train_ids}
        val_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in val_ids}
        test_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in test_ids}

        await logger.info(
            f"[Data] Train: {len(train_items)}, Val: {len(val_items)}, Test: {len(test_items)}",
            {"train_count": len(train_items), "val_count": len(val_items), "test_count": len(test_items)}
        )

        # Build dataloaders
        train_loader, val_loader, test_loader = self._build_dataloaders(
            train_items=train_items,
            val_items=val_items,
            test_items=test_items,
            label_mapper=label_mapper,
            extractor_name=extractor_name,
        )

        await logger.info(
            f"Starting Patch Classification training with {extractor_name}",
            {"extractor": extractor_name, "num_classes": num_classes, "epochs": epochs, "lr": lr}
        )

        # Build feature extractor (frozen)
        extractor = get_extractor(
            extractor_name, pretrained=True, hf_token=self.hf_token
        ).to(self.device).eval()

        for param in extractor.parameters():
            param.requires_grad = False

        # Build linear probe
        linear_probe = LinearProbe(
            feature_dim=extractor.output_dim,
            num_classes=num_classes,
            dropout_p=self.dropout_p,
        ).to(self.device)

        # Combined model for inference
        model = nn.Sequential(extractor, linear_probe).to(self.device)

        # Calculate class weights for auto-balancing
        class_weights = None
        if auto_balance:
            class_counts = [0] * num_classes
            for wsi_id in train_ids:
                class_counts[labels[wsi_id]] += 1
            n_total = len(train_ids)
            class_weights = torch.tensor([
                n_total / (num_classes * max(1, count)) for count in class_counts
            ], dtype=torch.float32, device=self.device)
            await logger.info(
                f"Auto-balance enabled: class_weights={[f'{w:.2f}' for w in class_weights.tolist()]}",
                {"class_counts": class_counts, "class_weights": class_weights.tolist()}
            )

        # Criterion with optional class weights
        criterion = nn.CrossEntropyLoss(weight=class_weights)

        # Dynamic optimizer selection
        optimizer_type_lower = optimizer_type.lower()
        if optimizer_type_lower == "sgd":
            optimizer = optim.SGD(linear_probe.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
        elif optimizer_type_lower == "adamw":
            optimizer = optim.AdamW(linear_probe.parameters(), lr=lr, weight_decay=0.01)
        else:  # Default to adam
            optimizer = optim.Adam(linear_probe.parameters(), lr=lr, weight_decay=0.0)

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        # Training loop
        history = {"loss": [], "val_loss": [], "val_accuracy": [], "val_auc": []}
        best_val_loss = float('inf')
        best_val_metric = None
        best_epoch = 0
        best_val_metrics = None
        best_test_metrics = None
        epochs_without_improvement = 0

        for epoch in range(1, epochs + 1):
            # Check for cancellation or permission revocation at each epoch start
            if is_task_cancelled(self.task_id):
                await logger.info(f"Training cancelled by user/timeout at epoch {epoch}")
                # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                del model, extractor, linear_probe, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")
            if is_permission_revoked(self.task_id):
                await logger.info(f"Training stopped: permission revoked at epoch {epoch}")
                del model, extractor, linear_probe, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                raise PermissionRevokedException(f"Training stopped at epoch {epoch}: permission revoked by admin")

            # Run training epoch in thread pool to avoid blocking the event loop.
            # GPU operations (forward/backward pass) and DataLoader iteration are blocking.
            running_loss, num_batches, stop_reason = await asyncio.to_thread(
                self._run_one_epoch, train_loader, extractor, linear_probe,
                criterion, optimizer, self.device, self.task_id
            )

            if stop_reason == "cancelled":
                del model, extractor, linear_probe, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                raise TrainingCancelledException(f"Training cancelled during epoch {epoch} loop")
            if stop_reason == "permission_revoked":
                del model, extractor, linear_probe, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                raise PermissionRevokedException(f"Training stopped during epoch {epoch}: permission revoked by admin")

            epoch_loss = running_loss / max(1, num_batches)
            history["loss"].append(epoch_loss)

            # Validation - run in thread pool (DataLoader + GPU inference are blocking)
            if val_loader is not None:
                val_metrics = await asyncio.to_thread(self._evaluate, model, val_loader, criterion)
                val_loss = val_metrics.get("loss", epoch_loss)
                val_acc = val_metrics["accuracy"]
                val_auc = val_metrics.get("auc")
                history["val_loss"].append(val_loss)
                history["val_accuracy"].append(val_acc)
                history["val_auc"].append(val_auc)
            else:
                val_metrics = {"accuracy": 1.0 - epoch_loss, "loss": epoch_loss}
                val_loss = epoch_loss
                val_acc = val_metrics["accuracy"]
                history["val_loss"].append(val_loss)

            # Prepare metadata with train_ prefix for training loss and val_ prefix for validation metrics
            metadata = {"epoch": epoch, "train_loss": epoch_loss}
            if val_loader:
                metadata.update({f"val_{k}": v for k, v in val_metrics.items()})

            await logger.info(
                f"Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f}" +
                (f", val_loss: {val_loss:.4f}, val_acc: {val_acc:.4f}" if val_loader else ""),
                metadata
            )

            # Update progress: training from 66% to 90%, saving from 90% to 100%
            # Use epoch (not epoch-1) to ensure progress updates immediately from first epoch
            progress = 66 + int(epoch / epochs * 24)
            await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress)

            # Update learning rate
            scheduler.step()

            # Save best model based on accuracy/AUC (higher is better)
            # Fallback to loss (lower is better) if Acc/AUC are unavailable
            is_improvement = False
            # Prefer AUC if available, else Accuracy
            check_metric = val_metrics.get("auc") if val_metrics.get("auc") is not None else val_metrics.get("accuracy")

            if check_metric is not None:
                 if best_val_metric is None or check_metric > best_val_metric:
                    best_val_metric = check_metric
                    is_improvement = True
            else:
                 # Fallback to loss for tie-breaking or no metric
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    is_improvement = True

            if is_improvement:
                # Update trackers
                best_epoch = epoch
                best_val_loss = val_loss # Keep this updated for info
                best_val_metrics = val_metrics if val_loader else None
                epochs_without_improvement = 0  # Reset counter

                if test_loader is not None:
                    best_test_metrics = await asyncio.to_thread(self._evaluate, model, test_loader, criterion)
                    await logger.info(
                        f"New best model at epoch {epoch} - val_loss: {val_loss:.4f}, test_acc: {best_test_metrics['accuracy']:.4f}",
                        {"epoch": epoch, **best_test_metrics}
                    )

                self._save_checkpoint(
                    extractor_name=extractor_name,
                    linear_probe=linear_probe,
                    extractor_dim=extractor.output_dim,
                    num_classes=num_classes,
                    epochs=epochs,
                    lr=lr,
                    history=history,
                    val_metrics=best_val_metrics,
                    test_metrics=best_test_metrics,
                    classes=classes,
                )
            else:
                epochs_without_improvement += 1

            # Early stopping check
            if val_loader and epochs_without_improvement >= early_stopping_patience:
                stopped_val = f"{best_val_metric:.4f}" if best_val_metric is not None else f"loss={best_val_loss:.4f}"
                await logger.info(
                    f"Early stopping triggered at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                    {"epoch": epoch, "best_val_metric": stopped_val}
                )
                break

        # Save final metrics with complete history (even if last epoch wasn't best)
        self._save_final_metrics(history, best_val_metrics, best_test_metrics)

        # Save per-image inference results (like WSI classification)
        await self._save_training_inference_results(
            model=model,
            wsi_ids=all_ids,
            image_paths=image_paths,
            classes=classes,
            labels=labels,
            task_id=self.task_id,
            logger=logger,
            session_maker=session_maker,
            extractor_name=extractor_name,
            test_wsi_ids=test_ids if test_ids else None,
        )

        model_id = f"patch_cls_{self.task_id}"
        ckpt_path = self.uploads_root / "models" / model_id / "linear_probe.pth"

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["loss"],
            val_metrics=best_val_metrics,
            test_metrics=best_test_metrics,
            best_epoch=best_epoch,
        )

    async def _train_kfold(
        self,
        splits_map: Dict[str, List[str]],
        image_paths: Dict[str, str],
        labels: Dict[str, int],
        classes: List[str],
        label_mapper: Dict[str, int],
        extractor_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        all_ids: List[str],
        optimizer_type: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
    ) -> TrainResponse:
        """Train with K-Fold cross-validation."""
        num_folds = self._get_num_folds(splits_map)
        fold_keys = sorted([k for k in splits_map.keys() if k.startswith("fold_")])

        await logger.info(
            f"Starting {num_folds}-fold cross-validation for Patch Classification",
            metadata={"num_folds": num_folds, "epochs_per_fold": epochs}
        )

        fold_results = {}
        all_val_metrics = {"accuracy": [], "auc": [], "loss": []}

        # Build extractor once (shared across folds)
        extractor = get_extractor(
            extractor_name, pretrained=True, hf_token=self.hf_token
        ).to(self.device).eval()
        for param in extractor.parameters():
            param.requires_grad = False

        for fold_idx, val_fold_key in enumerate(fold_keys):
            val_ids = splits_map[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(splits_map[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)}",
                metadata={"fold": fold_idx + 1, "train": len(train_ids), "val": len(val_ids)}
            )

            # Build items for this fold
            train_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in train_ids}
            val_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in val_ids}

            train_loader, val_loader, _ = self._build_dataloaders(
                train_items=train_items,
                val_items=val_items,
                test_items={},
                label_mapper=label_mapper,
                extractor_name=extractor_name,
            )

            # New linear probe for each fold
            linear_probe = LinearProbe(
                feature_dim=extractor.output_dim,
                num_classes=num_classes,
                dropout_p=self.dropout_p,
            ).to(self.device)

            model = nn.Sequential(extractor, linear_probe).to(self.device)

            # Calculate class weights for auto-balancing (per fold)
            class_weights = None
            if auto_balance:
                class_counts = [0] * num_classes
                for wsi_id in train_ids:
                    class_counts[labels[wsi_id]] += 1
                n_total = len(train_ids)
                class_weights = torch.tensor([
                    n_total / (num_classes * max(1, count)) for count in class_counts
                ], dtype=torch.float32, device=self.device)

            criterion = nn.CrossEntropyLoss(weight=class_weights)

            # Dynamic optimizer selection
            optimizer_type_lower = optimizer_type.lower()
            if optimizer_type_lower == "sgd":
                optimizer = optim.SGD(linear_probe.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
            elif optimizer_type_lower == "adamw":
                optimizer = optim.AdamW(linear_probe.parameters(), lr=lr, weight_decay=0.01)
            else:  # Default to adam
                optimizer = optim.Adam(linear_probe.parameters(), lr=lr, weight_decay=0.0)

            # Learning rate scheduler
            scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

            history = {"loss": [], "val_loss": [], "val_accuracy": [], "val_auc": []}
            best_val_loss = float('inf')
            best_val_metric = None
            best_state_dict = None
            epochs_without_improvement = 0

            for epoch in range(1, epochs + 1):
                # Check for cancellation or permission revocation at each epoch start
                if is_task_cancelled(self.task_id):
                    await logger.info(f"[Fold {fold_idx + 1}] Training cancelled by user/timeout at epoch {epoch}")
                    # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                    del model, extractor, linear_probe, optimizer, criterion
                    if class_weights is not None:
                        del class_weights
                    raise TrainingCancelledException(f"Training cancelled at fold {fold_idx + 1}, epoch {epoch}")
                if is_permission_revoked(self.task_id):
                    await logger.info(f"[Fold {fold_idx + 1}] Training stopped: permission revoked at epoch {epoch}")
                    del model, extractor, linear_probe, optimizer, criterion
                    if class_weights is not None:
                        del class_weights
                    raise PermissionRevokedException(f"Training stopped at fold {fold_idx + 1}, epoch {epoch}: permission revoked by admin")

                # Run training epoch in thread pool to avoid blocking the event loop.
                # GPU operations (forward/backward pass) and DataLoader iteration are blocking.
                running_loss, num_batches, stop_reason = await asyncio.to_thread(
                    self._run_one_epoch, train_loader, extractor, linear_probe,
                    criterion, optimizer, self.device, self.task_id
                )

                if stop_reason == "cancelled":
                    del model, extractor, linear_probe, optimizer, criterion
                    if class_weights is not None:
                        del class_weights
                    raise TrainingCancelledException(f"Training cancelled during fold {fold_idx+1}, epoch {epoch} loop")
                if stop_reason == "permission_revoked":
                    del model, extractor, linear_probe, optimizer, criterion
                    if class_weights is not None:
                        del class_weights
                    raise PermissionRevokedException(f"Training stopped during fold {fold_idx+1}, epoch {epoch}: permission revoked by admin")

                epoch_loss = running_loss / max(1, num_batches)
                history["loss"].append(epoch_loss)

                # Validation - run in thread pool (DataLoader + GPU inference are blocking)
                val_metrics = await asyncio.to_thread(self._evaluate, model, val_loader, criterion)
                val_loss = val_metrics.get("loss", epoch_loss)
                val_acc = val_metrics.get("accuracy", 0.0)
                history["val_loss"].append(val_loss)
                history["val_accuracy"].append(val_metrics["accuracy"])
                history["val_auc"].append(val_metrics.get("auc"))

                # Select best model based on accuracy/AUC (higher is better)
                is_improvement = False
                check_metric = val_metrics.get("auc") if val_metrics.get("auc") is not None else val_metrics.get("accuracy")

                if check_metric is not None:
                     if best_val_metric is None or check_metric > best_val_metric:
                        best_val_metric = check_metric
                        is_improvement = True
                else:
                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                        is_improvement = True

                if is_improvement:
                    best_val_loss = val_loss # Update for logging
                    best_state_dict = {k: v.cpu().clone() for k, v in linear_probe.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

                # Log epoch progress - format consistent with non-kfold training
                # Prepare metadata with train_ prefix for training loss and val_ prefix for validation metrics
                metadata = {"fold": fold_idx + 1, "epoch": epoch, "train_loss": epoch_loss}
                metadata.update({f"val_{k}": v for k, v in val_metrics.items()})

                await logger.info(
                    f"[Fold {fold_idx + 1}] Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f}, val_loss: {val_loss:.4f}, val_acc: {val_acc:.4f}",
                    metadata
                )

                # Progress update: training uses 66-90% (24% total), saving uses 90-100%
                # Each fold gets equal share of the 24% training range
                # Use epoch (not epoch-1) to ensure progress updates immediately from first epoch
                fold_training_range = 24 / num_folds
                fold_progress_base = 66 + fold_idx * fold_training_range
                progress = int(fold_progress_base + epoch / epochs * fold_training_range)
                await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress)

                # Update learning rate
                scheduler.step()

                # Early stopping check
                if epochs_without_improvement >= early_stopping_patience:
                    stopped_val = f"{best_val_metric:.4f}" if best_val_metric is not None else f"loss={best_val_loss:.4f}"
                    await logger.info(
                        f"[Fold {fold_idx + 1}] Early stopping at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                        metadata={"fold": fold_idx + 1, "epoch": epoch, "best_val_metric": stopped_val}
                    )
                    break

            # Restore best and evaluate
            if best_state_dict:
                linear_probe.load_state_dict(best_state_dict)
            final_val_metrics = await asyncio.to_thread(self._evaluate, model, val_loader)

            fold_results[val_fold_key] = {
                "history": history,
                "val_metrics": final_val_metrics,
            }
            all_val_metrics["accuracy"].append(final_val_metrics["accuracy"])
            if final_val_metrics.get("auc") is not None:
                all_val_metrics["auc"].append(final_val_metrics["auc"])

            # Save fold checkpoint
            model_id = f"patch_cls_{self.task_id}"
            fold_dir = self.uploads_root / "models" / model_id / val_fold_key
            fold_dir.mkdir(parents=True, exist_ok=True)
            torch.save({
                "state_dict": linear_probe.state_dict(),
                "feature_dim": extractor.output_dim,
                "num_classes": num_classes,
            }, fold_dir / "linear_probe.pth")

            # Calculate saving progress range for this fold
            fold_total_range = 34 / num_folds
            fold_progress_base = 66 + int(fold_idx * fold_total_range)
            fold_training_range = int(fold_total_range * 0.7)
            fold_saving_base = fold_progress_base + fold_training_range
            fold_saving_range = max(1, int(fold_total_range * 0.3))

            # Save per-image inference results for this fold's VALIDATION set only
            # In K-Fold, each sample should be predicted by the model that didn't see it during training
            # This ensures the saved predictions are truly out-of-sample predictions
            await self._save_training_inference_results(
                model=model,
                wsi_ids=val_ids,
                image_paths=image_paths,
                classes=classes,
                labels=labels,
                task_id=self.task_id,
                logger=logger,
                session_maker=session_maker,
                extractor_name=extractor_name,
                fold_key=val_fold_key,
                progress_base=fold_saving_base,
                progress_range=fold_saving_range,
            )

            await logger.info(
                f"Fold {fold_idx + 1} complete: acc={final_val_metrics['accuracy']:.4f}",
                metadata={"fold": fold_idx + 1, **final_val_metrics}
            )

        # Calculate aggregated statistics (basic metrics from training, rounded to 4 decimal places)
        aggregated = {
            "accuracy": {
                "mean": round(float(np.mean(all_val_metrics["accuracy"])), 4),
                "std": round(float(np.std(all_val_metrics["accuracy"])), 4),
            },
        }
        if all_val_metrics["auc"]:
            aggregated["auc"] = {
                "mean": round(float(np.mean(all_val_metrics["auc"])), 4),
                "std": round(float(np.std(all_val_metrics["auc"])), 4),
            }

        # Calculate comprehensive metrics by reading saved JSON files
        # This provides precision, sensitivity, specificity, f1, etc. - similar to Analysis
        # Pass splits_map to enable fast direct file access instead of slow directory scanning
        comprehensive_metrics, per_fold_comprehensive = self._calculate_kfold_comprehensive_metrics(
            task_id=self.task_id,
            fold_keys=fold_keys,
            classes=classes,
            splits_map=splits_map,
        )
        # Merge comprehensive metrics into aggregated (don't overwrite accuracy/auc already calculated)
        for metric_name, metric_stats in comprehensive_metrics.items():
            if metric_name not in aggregated:
                aggregated[metric_name] = metric_stats

        # Add per-fold comprehensive metrics to fold_results
        for fold_key, metrics in per_fold_comprehensive.items():
            if fold_key in fold_results:
                fold_results[fold_key]["val_metrics"].update(metrics)

        # Find best fold based on accuracy
        best_fold_idx = int(np.argmax(all_val_metrics["accuracy"]))
        best_fold_key = fold_keys[best_fold_idx]
        best_fold_accuracy = round(float(all_val_metrics["accuracy"][best_fold_idx]), 4)

        await logger.info(
            f"K-Fold complete: accuracy={aggregated['accuracy']['mean']:.4f}±{aggregated['accuracy']['std']:.4f}, "
            f"best={best_fold_key} (acc={best_fold_accuracy:.4f})",
            metadata={"aggregated": aggregated, "best_fold": best_fold_key, "best_fold_accuracy": best_fold_accuracy}
        )

        # Save aggregated metrics
        model_id = f"patch_cls_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "extractor": extractor_name,
            "feature_dim": extractor.output_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "split_type": "kfold",
            "num_folds": num_folds,
            "best_fold": best_fold_key,
        }, ensure_ascii=False, indent=2))

        metrics_data = {
            "is_kfold": True,
            "num_folds": num_folds,
            "best_fold": best_fold_key,
            "folds": fold_results,
            "aggregated": aggregated,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Use best fold's checkpoint as default
        ckpt_path = model_dir / best_fold_key / "linear_probe.pth"

        # Build val_metrics with only float values
        val_metrics_dict: Dict[str, float] = {
            "accuracy": aggregated["accuracy"]["mean"],
        }
        if aggregated.get("auc", {}).get("mean") is not None:
            val_metrics_dict["auc"] = aggregated["auc"]["mean"]

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=fold_results[best_fold_key]["history"]["loss"],
            val_metrics=val_metrics_dict,
            kfold_aggregated=aggregated,
        )

    def _build_dataloaders(
        self,
        train_items: Dict[str, str],
        val_items: Dict[str, str],
        test_items: Dict[str, str],
        label_mapper: Dict[str, int],
        extractor_name: str,
    ) -> Tuple[DataLoader, Optional[DataLoader], Optional[DataLoader]]:
        """Build train/val/test dataloaders."""
        # Get transforms from extractor - train with augmentation, eval without
        extractor = get_extractor(extractor_name, pretrained=True, hf_token=self.hf_token)
        train_transform = extractor.get_transforms(mode="train")
        eval_transform = extractor.get_transforms(mode="eval")
        del extractor  # Free memory

        train_dataset = PatchDatasetFromDB(
            annotations=train_items,
            label_mapper=label_mapper,
            extractor=train_transform,
        )
        val_dataset = PatchDatasetFromDB(
            annotations=val_items,
            label_mapper=label_mapper,
            extractor=eval_transform,
        ) if val_items else None
        test_dataset = PatchDatasetFromDB(
            annotations=test_items,
            label_mapper=label_mapper,
            extractor=eval_transform,
        ) if test_items else None

        train_loader = DataLoader(
            train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=4,
            pin_memory=True,
            persistent_workers=True,
            prefetch_factor=2,
            multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=4,
            pin_memory=True,
            persistent_workers=True,
            prefetch_factor=2,
            multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
        ) if val_dataset else None
        test_loader = DataLoader(
            test_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=4,
            pin_memory=True,
            persistent_workers=True,
            prefetch_factor=2,
            multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
        ) if test_dataset else None

        return train_loader, val_loader, test_loader

    def _evaluate(
        self,
        model: nn.Module,
        dataloader: torch.utils.data.DataLoader,
        criterion: Optional[nn.Module] = None,
    ) -> Dict[str, float]:
        """Evaluate model on dataloader."""
        model.eval()
        all_probs = []
        all_preds = []
        all_labels = []
        total_loss = 0.0
        num_batches = 0
        if criterion is None:
            criterion = nn.CrossEntropyLoss()

        with torch.inference_mode():
            for batch_img, gt in dataloader:
                batch_img = batch_img.to(self.device)
                gt_device = gt.to(self.device).long()
                logits = model(batch_img)

                # Calculate loss
                loss = criterion(logits, gt_device)
                total_loss += loss.item()
                num_batches += 1

                probs = F.softmax(logits, dim=-1).cpu().numpy()
                preds = probs.argmax(axis=1)

                all_probs.append(probs)
                all_preds.extend(preds.tolist())
                all_labels.extend(gt.numpy().tolist())

        all_probs = np.concatenate(all_probs, axis=0)
        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)

        # Calculate metrics
        accuracy = accuracy_score(all_labels, all_preds)
        avg_loss = total_loss / max(1, num_batches)

        # AUC
        try:
            num_classes = all_probs.shape[1]
            if num_classes == 2:
                auc = roc_auc_score(all_labels, all_probs[:, 1])
            else:
                auc = roc_auc_score(
                    all_labels, all_probs, multi_class='ovr', average='macro'
                )
        except ValueError:
            auc = None

        # Round all metrics to 4 decimal places
        metrics = {
            "loss": round(float(avg_loss), 4),
            "accuracy": round(float(accuracy), 4)
        }
        if auc is not None:
            metrics["auc"] = round(float(auc), 4)

        return metrics

    def _save_checkpoint(
        self,
        extractor_name: str,
        linear_probe: nn.Module,
        extractor_dim: int,
        num_classes: int,
        epochs: int,
        lr: float,
        history: Dict,
        val_metrics: Optional[Dict] = None,
        test_metrics: Optional[Dict] = None,
        classes: Optional[List[str]] = None,
    ) -> None:
        """Save model checkpoint and config."""
        model_id = f"patch_cls_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        # Save linear probe weights
        ckpt_path = model_dir / "linear_probe.pth"
        torch.save({
            "state_dict": linear_probe.state_dict(),
            "extractor_name": extractor_name,
            "extractor_dim": extractor_dim,
            "num_classes": num_classes,
        }, ckpt_path)

        # Save config
        config = {
            "task_id": self.task_id,
            "extractor": extractor_name,
            "extractor_dim": extractor_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "classes": classes,
        }
        (model_dir / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2)
        )

        # Save metrics
        metrics = {
            "history": history,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2)
        )

    def _save_final_metrics(
        self,
        history: Dict,
        val_metrics: Optional[Dict] = None,
        test_metrics: Optional[Dict] = None,
    ) -> None:
        """Save final metrics with complete training history after training ends."""
        model_id = f"patch_cls_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        # Save complete history (overwrite partial history saved during best model checkpoint)
        metrics = {
            "history": history,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2)
        )

    async def _save_training_inference_results(
        self,
        model: nn.Module,
        wsi_ids: List[str],
        image_paths: Dict[str, str],
        classes: List[str],
        labels: Dict[str, int],
        task_id: str,
        logger: Any,
        session_maker: Any,
        extractor_name: str,
        fold_key: Optional[str] = None,
        progress_base: int = 90,
        progress_range: int = 10,
        test_wsi_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Save per-image inference results after training.

        Optimized with:
        - Dynamic progress updates with per-file granularity
        - Parallel file I/O using asyncio
        - Batch database inserts for performance

        Progress allocation within the given range:
        - 0-20%: Inference
        - 20-80%: File I/O (per-file progress)
        - 80-90%: Database insert
        - 90-100%: Metrics calculation

        For each image, saves:
        - Prediction (pred): predicted class label
        - Probabilities (probs): probability distribution over classes
        - Ground truth
        - CAM heatmap (attention-like visualization)

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_cam.npy (CAM heatmap)

        Args:
            fold_key: Optional fold identifier (e.g., "fold_0") for k-fold training.
            progress_base: Starting progress percentage (default 90 for regular training)
            progress_range: Total progress range for saving (default 10 for regular training)
        """
        import concurrent.futures
        from functools import partial

        fold_suffix = f"_{fold_key}" if fold_key else ""
        fold_desc = f" ({fold_key})" if fold_key else ""
        total_images = len(wsi_ids)

        # Calculate progress points based on progress_base and progress_range
        # Allocation: 20% inference, 60% file I/O, 10% DB, 10% metrics
        progress_inference = progress_base
        progress_file_io_start = progress_base + int(progress_range * 0.2)
        progress_file_io_end = progress_base + int(progress_range * 0.8)
        progress_db = progress_base + int(progress_range * 0.8)
        progress_metrics = progress_base + int(progress_range * 0.9)
        file_io_progress_range = progress_file_io_end - progress_file_io_start

        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_inference)
        await logger.info(
            f"[Saving] Starting to save inference results{fold_desc} for {total_images} images...",
            {"task_id": task_id, "num_images": total_images, "fold_key": fold_key, "phase": "saving_results"}
        )

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        num_classes = len(classes)

        # Get transforms for inference using actual extractor
        extractor_temp = get_extractor(extractor_name, pretrained=False, hf_token=self.hf_token)
        fm_transform = extractor_temp.get_transforms()
        del extractor_temp

        # Get CAM extractor for heatmap generation
        cam_extractor = get_cam_extractor(extractor_name)
        cam_size = get_cam_spatial_size(extractor_name)

        await logger.info(
            f"[Saving] Using CAM extractor for {extractor_name}, CAM size: {cam_size}",
            {"extractor": extractor_name, "cam_size": cam_size}
        )

        # Need to enable gradients for Grad-CAM (ResNet)
        from backend.ai.utils.cam_utils import is_cnn_extractor
        use_gradients = is_cnn_extractor(extractor_name)

        # Phase 1: Run inference and collect results in thread pool.
        # GPU inference and image loading are blocking - run in thread to avoid blocking event loop.
        from PIL import Image

        def _run_inference():
            """Synchronous inference loop - runs in thread pool to avoid blocking event loop."""
            _all_probs = []
            _all_preds = []
            _all_labels_list = []
            _file_save_items = []
            _db_records = []

            with torch.set_grad_enabled(use_gradients):
                for idx, wsi_id in enumerate(wsi_ids):
                    # Load and transform image
                    img_path = image_paths[wsi_id]
                    img = Image.open(img_path).convert("RGB")
                    img_tensor = fm_transform(img).unsqueeze(0).to(self.device)

                    # Forward pass for prediction
                    with torch.inference_mode():
                        logits = model(img_tensor)
                        probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                        pred_idx = int(probs.argmax())
                        pred_label = classes[pred_idx]

                    # Extract CAM heatmap
                    try:
                        cam_map = cam_extractor.extract_cam(
                            model=model,
                            input_tensor=img_tensor,
                            target_class=pred_idx,
                        )
                        cam_map = cam_map.squeeze(0)
                    except Exception as e:
                        import traceback
                        error_details = traceback.format_exc()
                        logger.warning(f"CAM extraction failed for {wsi_id}: {e}\n{error_details}")
                        cam_map = np.ones(cam_size, dtype=np.float32) / (cam_size[0] * cam_size[1])

                    # Collect for metrics
                    _all_probs.append(probs)
                    _all_preds.append(pred_idx)
                    _all_labels_list.append(labels[wsi_id])

                    probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                    gt_label = classes[labels[wsi_id]]

                    wsi_result_dir = ai_results_root / wsi_id
                    cam_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_cam.npy"
                    result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"

                    result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "cam_file": str(cam_file),
                        "cam_size": list(cam_size),
                    }
                    if fold_key:
                        result_data["fold_key"] = fold_key

                    _file_save_items.append((wsi_result_dir, result_data, cam_map, fold_suffix, task_id))

                    # Prepare database record
                    _db_records.append({
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "extra_metadata": {
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label,
                            "classes": classes,
                            "task_type": "patch_classification",
                            "cam_file": str(cam_file),
                            "cam_size": list(cam_size),
                            "fold_key": fold_key,
                            "result_file": str(result_file),
                        }
                    })

            return _all_probs, _all_preds, _all_labels_list, _file_save_items, _db_records

        all_probs, all_preds, all_labels_list, file_save_items, db_records = await asyncio.to_thread(_run_inference)

        # Phase 2: Parallel file I/O using thread pool with progress updates
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_file_io_start)
        await logger.info(
            f"[Saving] Writing {total_images} result files to disk...",
            {"phase": "writing_files", "num_files": total_images}
        )

        # Track completed files for progress updates
        completed_count = [0]
        progress_lock = asyncio.Lock()

        def save_single_image_files(item):
            """Synchronous function to save files for a single image."""
            wsi_result_dir, result_data, cam_map, fold_suffix, task_id = item
            wsi_result_dir.mkdir(parents=True, exist_ok=True)

            # Save CAM heatmap
            cam_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_cam.npy"
            np.save(cam_file, cam_map)

            # Save result JSON
            result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False)

            return result_data["wsi_id"]

        # Capture session_maker reference for use in nested function
        session_maker_ref = session_maker
        task_id_for_update = self.task_id

        async def save_with_progress(executor, item, total,
                                      file_io_start, file_io_range):
            """Save files and update progress."""
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, save_single_image_files, item)
            async with progress_lock:
                completed_count[0] += 1
                # Update progress every 10% of files or at least every 500 files (reduced frequency for performance)
                update_interval = max(1, min(total // 10, 500))
                if completed_count[0] % update_interval == 0 or completed_count[0] == total:
                    file_progress = file_io_start + int(completed_count[0] / total * file_io_range)
                    await _safe_update_progress(session_maker_ref, task_id_for_update, TaskStatus.TRAINING, file_progress)
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            tasks = [
                save_with_progress(executor, item, total_images,
                                   progress_file_io_start, file_io_progress_range)
                for item in file_save_items
            ]
            await asyncio.gather(*tasks)

        # Phase 3: Batch database insert
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_db)
        await logger.info(
            f"[Saving] Inserting {len(db_records)} records to database...",
            {"phase": "database_insert", "num_records": len(db_records)}
        )

        async with scoped_db(session_maker) as db:
            await AIResultRepository.bulk_create(db, db_records, batch_size=100)

        # Phase 4: Calculate and log final metrics
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_metrics)

        all_probs = np.array(all_probs)
        all_preds = np.array(all_preds)
        all_labels_arr = np.array(all_labels_list)

        # Filter to test set only if test_wsi_ids is provided
        if test_wsi_ids is not None and len(test_wsi_ids) > 0:
            # Create mask for test samples
            test_mask = np.array([wid in test_wsi_ids for wid in wsi_ids])
            test_probs = all_probs[test_mask]
            test_preds = all_preds[test_mask]
            test_labels = all_labels_arr[test_mask]

            if len(test_labels) > 0:
                accuracy = round(float(accuracy_score(test_labels, test_preds)), 4)

                try:
                    if num_classes == 2:
                        auc = round(float(roc_auc_score(test_labels, test_probs[:, 1])), 4)
                        auc_display = f"AUC: {auc:.4f}"
                    else:
                        auc = round(float(roc_auc_score(test_labels, test_probs, multi_class='ovr', average='macro')), 4)
                        auc_display = f"AUC (macro-OVR): {auc:.4f}"
                except ValueError:
                    auc = None
                    auc_display = "AUC: N/A (insufficient samples per class)"

                metrics_metadata = {
                    "task_id": task_id,
                    "accuracy": accuracy,
                    "num_classes": num_classes,
                    "classes": classes,
                    "test_samples": len(test_labels),
                }
                if auc is not None:
                    metrics_metadata["auc"] = auc

                await logger.info(
                    f"[Saving] Complete - Test Set Accuracy: {accuracy:.4f}, {auc_display} (n={len(test_labels)})",
                    metadata=metrics_metadata
                )
            else:
                await logger.info(
                    f"[Saving] Complete - No test samples found for metrics calculation",
                    metadata={"task_id": task_id}
                )
        else:
            # No test set specified - log without metrics (for k-fold or when no test set)
            await logger.info(
                f"[Saving] Complete - Inference results saved for {len(wsi_ids)} images",
                metadata={"task_id": task_id, "num_images": len(wsi_ids)}
            )

        model.train()

