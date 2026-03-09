"""
Patch Segmentation Trainer.

Uses segmentation_models_pytorch (SMP) for training segmentation models.
Supports end-to-end training with various backbones.

Key Features for High-Performance Training:
- Mixed precision training (AMP) for faster computation
- Gradient accumulation for effective larger batch sizes
- Cosine annealing with warm restarts learning rate schedule
- Early stopping with patience
- Best model checkpointing
- Comprehensive metrics tracking (IoU, Dice, Accuracy, F1)
"""

from __future__ import annotations

import json
import asyncio
import gc
import logging
import random
import copy
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable, Union

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torch.cuda.amp import GradScaler, autocast
from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts, ReduceLROnPlateau, OneCycleLR
import segmentation_models_pytorch as smp
from sklearn.metrics import confusion_matrix

from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException
from backend.ai.schemas.base import TaskStatus
from backend.ai.tasks.training_utils import safe_update_progress as _safe_update_progress
from backend.ai.utils.segmentation_dataset import SegmentationDataset, get_transforms
from backend.ai.segmentors import Segmentor
from backend.database.utils.training_logger import TrainingLogger

logger = logging.getLogger("patch_segmentation_trainer")

SegmentationMetricValue = Union[float, List[float]]


__default_config__ = {
    "architecture": "unet",  # Model architecture
    "backbone": "resnet50",  # Encoder backbone for segmentation model
    "loss": {
        "names": ["DiceLoss", "JaccardLoss"],
        "weights": [0.5, 0.5],
    },  # Loss functions and weights
    
    "dataset": {
        "classes": 1,  # Number of segmentation classes
        "channels": 3,  # Number of input image channels
        "train": {
            "image_dir": "",
            "annotations_path": "",
        },
        "val": {
            "image_dir": "",
            "annotations_path": "",
        },
        "test": {
            "image_dir": "",
            "annotations_path": "",
        },
    }, # Dataset paths
    
    # Training hyperparameters
    "training": {
        "epochs": 100,
        "lr": 1e-4,
        "min_lr": 1e-7,
        "weight_decay": 1e-4,
        "optimizer": "adamw",  # adam, adamw, sgd
        "scheduler": "cosine_warm_restarts",  # cosine_warm_restarts, reduce_on_plateau, one_cycle
        "warmup_epochs": 5,
        "early_stopping_patience": 15,
        "gradient_clip": 1.0,
        "gradient_accumulation_steps": 1,
        "use_amp": True,  # Mixed precision training
        "t_0": 10,  # Initial restart interval for cosine annealing
        "t_mult": 2,  # Multiplier for restart interval
    },
    
    "metrics": ['iou', 'miou', 'dice', 'accuracy', 'f1', 'precision', 'recall'],  # Metrics to track
    "monitor_metric": 'iou',  # Metric to monitor for saving best model (auto-promotes to miou for multi-class)
    "save_dir": "./checkpoints",  # Directory to save checkpoints
}


class SegmentationTrainer:
    """
    Trainer for patch-level segmentation tasks using segmentation_models_pytorch.
    
    Features for high-performance training:
    - Mixed precision training (AMP) for faster computation and lower memory usage
    - Gradient accumulation for effective larger batch sizes
    - Multiple learning rate schedulers (cosine annealing, plateau, one-cycle)
    - Early stopping with patience to prevent overfitting
    - Best model checkpointing based on validation metrics
    - Comprehensive metrics: IoU, Dice, Accuracy, F1, Precision, Recall
    - Gradient clipping for training stability
    """
    
    def __init__(
        self,
        task_id: str,
        uploads_root: Path,
        device: str | None = None,
        batch_size: int = 8,
        config: Dict[str, Any] = None,
        task_logger: Optional[TrainingLogger] = None,
    ):
        self.task_id = task_id
        self.uploads_root = Path(uploads_root)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.batch_size = batch_size
        self.config = self.update_config(config)
        self.task_logger = task_logger
        self._owns_task_logger = task_logger is None
        segmentor = Segmentor(
            architecture=self.config["architecture"],
            encoder_name=self.config["backbone"],
            in_channels=self.config["dataset"]["channels"],
            classes=self.config["dataset"]["classes"]
            )
        
        self.is_fm = segmentor.is_fm
        self.model = segmentor.build_model().to(self.device)
        self.loss_fn = segmentor.build_losses(
            loss_names=self.config["loss"]["names"],
            loss_weights=self.config["loss"]["weights"],
            mode=smp.losses.MULTILABEL_MODE
        )
        # build dataset and dataloaders
        normalization_mean, normalization_std = segmentor.get_normalization_params()
        self.train_dataset = SegmentationDataset(
            img_dir=self.config["dataset"]["train"]["image_dir"],
            annotations_path=self.config["dataset"]["train"]["annotations_path"],
            transform=get_transforms("train", normalization_mean=normalization_mean, normalization_std=normalization_std)
        )
        self.val_dataset = SegmentationDataset(
            img_dir=self.config["dataset"]["val"]["image_dir"],
            annotations_path=self.config["dataset"]["val"]["annotations_path"],
            transform=get_transforms("val", normalization_mean=normalization_mean, normalization_std=normalization_std)
        )
        if self.config["dataset"].get("test") is not None:
            self.test_dataset = SegmentationDataset(
                img_dir=self.config["dataset"]["test"]["image_dir"],
                annotations_path=self.config["dataset"]["test"]["annotations_path"],
                transform=get_transforms("test", normalization_mean=normalization_mean, normalization_std=normalization_std)
            )
        else:
            self.test_dataset = None

    def update_config(self, config: Dict[str, Any]):
        """
        Update trainer configuration with deep merge support.
        """
        if config is None:
            config = {}
            
        def deep_update(base_dict, update_dict):
            for key, value in update_dict.items():
                if (
                    key in base_dict 
                    and isinstance(base_dict[key], dict) 
                    and isinstance(value, dict)
                ):
                    deep_update(base_dict[key], value)
                else:
                    base_dict[key] = value
            return base_dict

        # Merge with default config using deep copy to avoid modifying the original default
        merged_config = copy.deepcopy(__default_config__)
        deep_update(merged_config, config)
        return merged_config

    def release_resources(self) -> None:
        """
        Release trainer-held references so route-level cleanup can actually free GPU memory.

        Patch segmentation keeps the model and datasets on ``self``. If the route-level
        ``finally`` runs while those references are still alive, ``torch.cuda.empty_cache()``
        cannot fully reclaim memory. This method is safe to call multiple times.
        """
        for attr_name in ("model", "loss_fn", "train_dataset", "val_dataset", "test_dataset"):
            if hasattr(self, attr_name):
                setattr(self, attr_name, None)

        gc.collect()
        gc.collect()

        if torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            except Exception as exc:
                logger.debug(f"Failed to fully release CUDA memory during segmentation cleanup: {exc}")

    def _get_task_logger(self) -> TrainingLogger:
        """Lazily initialize the task logger used by the live log stream."""
        if self.task_logger is None:
            self.task_logger = TrainingLogger(self.task_id)
            self._owns_task_logger = True
        return self.task_logger

    def _log_info(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Write a training log entry to the task log stream, with fallback to std logging."""
        try:
            asyncio.run(self._get_task_logger().info(message, metadata))
        except Exception as exc:
            logger.debug(f"Failed to write segmentation task log to stream: {exc}")
            logger.info(message)

    def _close_task_logger(self) -> None:
        """Flush and close the per-task logger when training exits."""
        if self.task_logger is None or not self._owns_task_logger:
            return
        try:
            asyncio.run(self.task_logger.close())
        except Exception as exc:
            logger.debug(f"Failed to close segmentation task logger cleanly: {exc}")
        finally:
            self.task_logger = None

    def _update_training_progress(self, progress: int) -> None:
        """Write segmentation training progress to the shared progress store."""
        asyncio.run(
            _safe_update_progress(
                None,
                self.task_id,
                TaskStatus.TRAINING,
                max(0, min(progress, 100)),
            )
        )

    def _get_num_classes(self) -> int:
        dataset_cfg = self.config.get("dataset", {})
        try:
            return max(1, int(dataset_cfg.get("classes", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def _get_primary_iou_metric_key(self) -> str:
        return "miou" if self._get_num_classes() > 1 else "iou"

    def _get_primary_iou_metric_label(self) -> str:
        return "mIoU" if self._get_num_classes() > 1 else "IoU"

    def _get_monitor_metric(self) -> str:
        configured_metric = self.config.get("monitor_metric")
        if configured_metric == "iou" and self._get_num_classes() > 1:
            return "miou"
        return configured_metric or self._get_primary_iou_metric_key()

    
    def build_loaders(self) -> Tuple[DataLoader, DataLoader, Optional[DataLoader]]:
        """
        Build DataLoaders for training, validation, and testing datasets.
        """
        train_loader = DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=4,
            pin_memory=True,
            multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
        )
        val_loader = DataLoader(
            self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=4,
            pin_memory=True,
            multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
        )
        test_loader = None
        if self.test_dataset is not None:
            test_loader = DataLoader(
                self.test_dataset,
                batch_size=self.batch_size,
                shuffle=False,
                num_workers=4,
                pin_memory=True,
                multiprocessing_context='spawn',  # Avoid fork deadlock in multithreaded env
            )
        return train_loader, val_loader, test_loader
    
    def evaluate_model(self, data_loader: DataLoader) -> Dict[str, SegmentationMetricValue]:
        """
        Evaluate the model on the given DataLoader and return metrics.
        """
        self.model.eval()
        total_loss = 0.0
        total_samples = 0
        accumulated_stats = None
        
        with torch.no_grad():
            for images, masks in data_loader:
                images = images.to(self.device)
                masks = masks.to(self.device)
                
                outputs = self.model(images)
                loss = self.loss_fn(outputs, masks)
                
                total_loss += loss.item() * images.size(0)
                total_samples += images.size(0)
                accumulated_stats = self._accumulate_metric_stats(
                    accumulated_stats,
                    self._get_batch_metric_stats(outputs, masks),
                )
        
        avg_loss = total_loss / total_samples
        metrics = {"loss": avg_loss}
        if accumulated_stats is not None:
            all_metrics = self._compute_metrics_from_stats(
                *self._finalize_metric_stats(accumulated_stats)
            )
            for metric_name in self.config.get("metrics", []):
                if metric_name in all_metrics:
                    metrics[metric_name] = all_metrics[metric_name]
        
        return metrics
    
    def _get_batch_metric_stats(
        self,
        preds: torch.Tensor,
        targets: torch.Tensor,
        threshold: float = 0.5,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute per-sample/per-class confusion stats for a single batch."""
        preds_binary = (torch.sigmoid(preds.detach()) > threshold).long()
        targets_long = targets.detach().long()

        tp, fp, fn, tn = smp.metrics.get_stats(
            preds_binary, targets_long, mode='multilabel', threshold=None
        )
        return tuple(stat.cpu() for stat in (tp, fp, fn, tn))

    def _accumulate_metric_stats(
        self,
        accumulated: Optional[Tuple[List[torch.Tensor], List[torch.Tensor], List[torch.Tensor], List[torch.Tensor]]],
        batch_stats: Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
    ) -> Tuple[List[torch.Tensor], List[torch.Tensor], List[torch.Tensor], List[torch.Tensor]]:
        """Accumulate compact per-sample confusion stats across batches."""
        if accumulated is None:
            return tuple([stat] for stat in batch_stats)
        for current, update in zip(accumulated, batch_stats):
            current.append(update)
        return accumulated

    def _finalize_metric_stats(
        self,
        accumulated: Tuple[List[torch.Tensor], List[torch.Tensor], List[torch.Tensor], List[torch.Tensor]],
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Concatenate accumulated per-sample stats across all batches."""
        return tuple(torch.cat(stats, dim=0) for stats in accumulated)

    def _compute_metrics(
        self, 
        preds: torch.Tensor, 
        targets: torch.Tensor,
        threshold: float = 0.5
    ) -> Dict[str, SegmentationMetricValue]:
        """
        Compute comprehensive segmentation metrics.
        
        Args:
            preds: Model predictions (logits or probabilities)
            targets: Ground truth masks
            threshold: Threshold for converting probabilities to binary predictions
            
        Returns:
            Dictionary of metric values
        """
        stats = self._get_batch_metric_stats(preds, targets, threshold=threshold)
        return self._compute_metrics_from_stats(*stats)

    def _compute_metrics_from_stats(
        self,
        tp: torch.Tensor,
        fp: torch.Tensor,
        fn: torch.Tensor,
        tn: torch.Tensor,
    ) -> Dict[str, SegmentationMetricValue]:
        """Compute segmentation metrics from accumulated confusion stats."""
        metrics = {}

        # get_stats(mode='multilabel') returns per-sample/per-class confusion
        # counts with shape (N, C). For dataset-level reporting we aggregate over
        # the sample dimension first so per-class outputs become 1-D lists of
        # length C instead of nested [sample, class] arrays.
        if tp.dim() > 1:
            tp = tp.sum(dim=0)
            fp = fp.sum(dim=0)
            fn = fn.sum(dim=0)
            tn = tn.sum(dim=0)

        # Per-class IoU, then average
        iou_per_class = smp.metrics.iou_score(tp, fp, fn, tn, reduction='none')
        primary_iou_key = self._get_primary_iou_metric_key()
        metrics[primary_iou_key] = iou_per_class.mean().item()
        metrics['iou_per_class'] = iou_per_class.tolist() if iou_per_class.dim() > 0 else [iou_per_class.item()]
        
        # Dice Score (F1 for segmentation)
        dice_per_class = smp.metrics.f1_score(tp, fp, fn, tn, reduction='none')
        metrics['dice'] = dice_per_class.mean().item()
        metrics['dice_per_class'] = dice_per_class.tolist() if dice_per_class.dim() > 0 else [dice_per_class.item()]
        
        # Accuracy
        accuracy = smp.metrics.accuracy(tp, fp, fn, tn, reduction='micro')
        metrics['accuracy'] = accuracy.item()
        
        # Precision
        precision = smp.metrics.precision(tp, fp, fn, tn, reduction='micro')
        metrics['precision'] = precision.item()
        precision_per_class = smp.metrics.precision(tp, fp, fn, tn, reduction='none')
        metrics['precision_per_class'] = precision_per_class.tolist() if precision_per_class.dim() > 0 else [precision_per_class.item()]
        
        # Recall / Sensitivity
        recall = smp.metrics.recall(tp, fp, fn, tn, reduction='micro')
        metrics['recall'] = recall.item()
        recall_per_class = smp.metrics.recall(tp, fp, fn, tn, reduction='none')
        metrics['recall_per_class'] = recall_per_class.tolist() if recall_per_class.dim() > 0 else [recall_per_class.item()]
        
        # F1 Score (harmonic mean of precision and recall)
        if precision.item() + recall.item() > 0:
            f1 = 2 * (precision.item() * recall.item()) / (precision.item() + recall.item())
        else:
            f1 = 0.0
        metrics['f1'] = f1
        metrics['f1_per_class'] = dice_per_class.tolist() if dice_per_class.dim() > 0 else [dice_per_class.item()]
        
        return metrics

    def _build_optimizer(self, model: nn.Module) -> optim.Optimizer:
        """
        Build optimizer based on configuration.
        
        Args:
            model: The model to optimize
            
        Returns:
            Configured optimizer
        """
        training_cfg = self.config.get("training", {})
        lr = training_cfg.get("lr", 1e-4)
        weight_decay = training_cfg.get("weight_decay", 1e-4)
        optimizer_type = training_cfg.get("optimizer", "adamw").lower()
        
        # Separate parameters for encoder and decoder (different learning rates)
        encoder_params = []
        decoder_params = []
        
        for name, param in model.named_parameters():
            if not param.requires_grad:
                continue
            if "encoder" in name:
                encoder_params.append(param)
            else:
                decoder_params.append(param)
        
        # Use lower learning rate for pretrained encoder
        param_groups = [
            {"params": encoder_params, "lr": lr * 0.1},  # Lower LR for encoder
            {"params": decoder_params, "lr": lr},  # Full LR for decoder
        ]
        
        if optimizer_type == "sgd":
            optimizer = optim.SGD(
                param_groups, 
                momentum=0.9, 
                weight_decay=weight_decay,
                nesterov=True
            )
        elif optimizer_type == "adamw":
            optimizer = optim.AdamW(
                param_groups, 
                weight_decay=weight_decay,
                betas=(0.9, 0.999)
            )
        else:  # Default to Adam
            optimizer = optim.Adam(
                param_groups, 
                weight_decay=weight_decay,
                betas=(0.9, 0.999)
            )
        
        return optimizer
    
    def _build_scheduler(
        self, 
        optimizer: optim.Optimizer, 
        train_loader: DataLoader
    ) -> Optional[Any]:
        """
        Build learning rate scheduler based on configuration.
        
        Args:
            optimizer: The optimizer to schedule
            train_loader: Training data loader (needed for OneCycleLR)
            
        Returns:
            Configured scheduler or None
        """
        training_cfg = self.config.get("training", {})
        scheduler_type = training_cfg.get("scheduler", "cosine_warm_restarts").lower()
        epochs = training_cfg.get("epochs", 100)
        lr = training_cfg.get("lr", 1e-4)
        min_lr = training_cfg.get("min_lr", 1e-7)
        t_0 = training_cfg.get("t_0", 10)
        t_mult = training_cfg.get("t_mult", 2)
        
        if scheduler_type == "cosine_warm_restarts":
            scheduler = CosineAnnealingWarmRestarts(
                optimizer,
                T_0=t_0,
                T_mult=t_mult,
                eta_min=min_lr
            )
        elif scheduler_type == "reduce_on_plateau":
            scheduler = ReduceLROnPlateau(
                optimizer,
                mode='max',  # Maximize IoU
                factor=0.5,
                patience=5,
                min_lr=min_lr,
                verbose=True
            )
        elif scheduler_type == "one_cycle":
            steps_per_epoch = len(train_loader)
            scheduler = OneCycleLR(
                optimizer,
                max_lr=lr,
                epochs=epochs,
                steps_per_epoch=steps_per_epoch,
                pct_start=0.1,  # 10% warmup
                anneal_strategy='cos',
                div_factor=25.0,
                final_div_factor=1000.0
            )
        else:
            scheduler = None
            
        return scheduler
    
    def _train_one_epoch(
        self,
        model: nn.Module,
        train_loader: DataLoader,
        optimizer: optim.Optimizer,
        scheduler: Optional[Any],
        scaler: Optional[GradScaler],
        epoch: int,
    ) -> Tuple[float, Dict[str, SegmentationMetricValue]]:
        """
        Train for one epoch with mixed precision and gradient accumulation.
        
        Args:
            model: The model to train
            train_loader: Training data loader
            optimizer: Optimizer
            scheduler: Learning rate scheduler
            scaler: Gradient scaler for AMP
            epoch: Current epoch number
            
        Returns:
            Tuple of (average loss, metrics dict)
        """
        model.train()
        training_cfg = self.config.get("training", {})
        use_amp = training_cfg.get("use_amp", True) and self.device != "cpu"
        gradient_clip = training_cfg.get("gradient_clip", 1.0)
        accumulation_steps = training_cfg.get("gradient_accumulation_steps", 1)
        scheduler_type = training_cfg.get("scheduler", "cosine_warm_restarts").lower()
        
        total_loss = 0.0
        accumulated_stats = None
        
        optimizer.zero_grad()
        
        for batch_idx, (images, masks) in enumerate(train_loader):
            if is_task_cancelled(self.task_id):
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                raise TrainingCancelledException("Training cancelled during segmentation batch loop")

            images = images.to(self.device)
            masks = masks.to(self.device)
            
            # Mixed precision forward pass
            if use_amp:
                with autocast():
                    outputs = model(images)
                    loss = self.loss_fn(outputs, masks)
                    loss = loss / accumulation_steps  # Scale loss for accumulation
                
                # Scaled backward pass
                scaler.scale(loss).backward()
                
                # Gradient accumulation
                if (batch_idx + 1) % accumulation_steps == 0 or (batch_idx + 1) == len(train_loader):
                    # Gradient clipping
                    if gradient_clip > 0:
                        scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
                    
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad()
                    
                    # Step scheduler for OneCycleLR (step per batch)
                    if scheduler is not None and scheduler_type == "one_cycle":
                        scheduler.step()
            else:
                outputs = model(images)
                loss = self.loss_fn(outputs, masks)
                loss = loss / accumulation_steps
                
                loss.backward()
                
                if (batch_idx + 1) % accumulation_steps == 0 or (batch_idx + 1) == len(train_loader):
                    if gradient_clip > 0:
                        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
                    
                    optimizer.step()
                    optimizer.zero_grad()
                    
                    if scheduler is not None and scheduler_type == "one_cycle":
                        scheduler.step()
            
            total_loss += loss.item() * accumulation_steps * images.size(0)
            
            # Accumulate compact metrics state instead of caching full predictions
            with torch.no_grad():
                accumulated_stats = self._accumulate_metric_stats(
                    accumulated_stats,
                    self._get_batch_metric_stats(outputs, masks),
                )
        
        # Step scheduler for epoch-based schedulers
        if scheduler is not None and scheduler_type == "cosine_warm_restarts":
            scheduler.step()
        
        avg_loss = total_loss / len(train_loader.dataset)
        
        # Compute training metrics
        train_metrics = self._compute_metrics_from_stats(
            *self._finalize_metric_stats(accumulated_stats)
        )
        train_metrics['loss'] = avg_loss
        
        return avg_loss, train_metrics
    
    def _validate(
        self,
        model: nn.Module,
        val_loader: DataLoader,
    ) -> Tuple[float, Dict[str, SegmentationMetricValue]]:
        """
        Validate the model.
        
        Args:
            model: The model to validate
            val_loader: Validation data loader
            
        Returns:
            Tuple of (average loss, metrics dict)
        """
        model.eval()
        training_cfg = self.config.get("training", {})
        use_amp = training_cfg.get("use_amp", True) and self.device != "cpu"
        
        total_loss = 0.0
        accumulated_stats = None
        
        with torch.no_grad():
            for images, masks in val_loader:
                if is_task_cancelled(self.task_id):
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    raise TrainingCancelledException("Training cancelled during segmentation validation")

                images = images.to(self.device)
                masks = masks.to(self.device)
                
                if use_amp:
                    with autocast():
                        outputs = model(images)
                        loss = self.loss_fn(outputs, masks)
                else:
                    outputs = model(images)
                    loss = self.loss_fn(outputs, masks)
                
                total_loss += loss.item() * images.size(0)
                accumulated_stats = self._accumulate_metric_stats(
                    accumulated_stats,
                    self._get_batch_metric_stats(outputs, masks),
                )
        
        avg_loss = total_loss / len(val_loader.dataset)
        
        # Compute validation metrics
        val_metrics = self._compute_metrics_from_stats(
            *self._finalize_metric_stats(accumulated_stats)
        )
        val_metrics['loss'] = avg_loss
        
        return avg_loss, val_metrics
    
    def _save_checkpoint(
        self,
        model: nn.Module,
        optimizer: optim.Optimizer,
        scheduler: Optional[Any],
        epoch: int,
        metrics: Dict[str, float],
        is_best: bool = False,
        filename: str = "checkpoint.pth"
    ) -> Path:
        """
        Save model checkpoint.
        
        Args:
            model: The model to save
            optimizer: Optimizer state
            scheduler: Scheduler state
            epoch: Current epoch
            metrics: Current metrics
            is_best: Whether this is the best model
            filename: Checkpoint filename
            
        Returns:
            Path to saved checkpoint
        """
        save_dir = Path(self.config.get("save_dir", "./checkpoints"))
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # For FM-based models, save only the lightweight decoder + head weights
        # (the frozen backbone is reconstructed from the local FM checkpoint).
        from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel
        if isinstance(model, FMSegmentationModel):
            model_weights = model.decoder_state_dict()
        else:
            model_weights = model.state_dict()

        checkpoint = {
            "epoch": epoch,
            "model_state_dict": model_weights,
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
            "metrics": metrics,
            "config": self.config,
            "is_fm": self.is_fm,
        }
        
        checkpoint_path = save_dir / filename
        torch.save(checkpoint, checkpoint_path)
        
        if is_best:
            best_path = save_dir / "best_model.pth"
            torch.save(checkpoint, best_path)
            monitor_metric = self._get_monitor_metric()
            self._log_info(
                f"Saved best model with {monitor_metric}: {metrics.get(monitor_metric, 0):.4f}",
                {"epoch": epoch, monitor_metric: metrics.get(monitor_metric, 0)},
            )
        
        return checkpoint_path
        
    def train_model(
        self,
        epochs: Optional[int] = None,
        lr: Optional[float] = None,
        early_stopping_patience: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Train the segmentation model with high-performance training techniques.
        
        This method implements a comprehensive training pipeline with:
        - Mixed precision training (AMP) for faster computation
        - Gradient accumulation for effective larger batch sizes
        - Learning rate scheduling (cosine annealing with warm restarts)
        - Early stopping based on validation metrics
        - Best model checkpointing
        - Comprehensive metrics tracking
        
        Args:
            epochs: Number of training epochs (overrides config)
            lr: Learning rate (overrides config)
            early_stopping_patience: Early stopping patience (overrides config)
            
        Returns:
            Dictionary containing training history and results
        """
        try:
            # Override config with provided parameters
            training_cfg = self.config.get("training", {})
            epochs = epochs or training_cfg.get("epochs", 100)
            patience = early_stopping_patience or training_cfg.get("early_stopping_patience", 15)
            use_amp = training_cfg.get("use_amp", True) and self.device != "cpu"
            monitor_metric = self._get_monitor_metric()
            primary_iou_metric = self._get_primary_iou_metric_key()
            primary_iou_label = self._get_primary_iou_metric_label()

            if lr is not None:
                training_cfg["lr"] = lr
                self.config["training"] = training_cfg

            # Build data loaders
            train_loader, val_loader, test_loader = self.build_loaders()
            test_count = len(test_loader.dataset) if test_loader is not None else 0

            self._log_info(
                f"Training on {len(train_loader.dataset)} samples, validating on {len(val_loader.dataset)} samples",
                {
                    "train_count": len(train_loader.dataset),
                    "val_count": len(val_loader.dataset),
                    "test_count": test_count,
                },
            )
            self._log_info(
                f"Using device: {self.device}, AMP: {use_amp}",
                {"device": self.device, "use_amp": use_amp},
            )
            self._log_info(
                f"Architecture: {self.config['architecture']}, Backbone: {self.config['backbone']}",
                {"architecture": self.config["architecture"], "backbone": self.config["backbone"], "epochs": epochs},
            )
            self._update_training_progress(0)

            # Build optimizer and scheduler
            optimizer = self._build_optimizer(self.model)
            scheduler = self._build_scheduler(optimizer, train_loader)

            # Mixed precision scaler
            scaler = GradScaler() if use_amp else None

            # Training history
            history = {
                "train_loss": [],
                "val_loss": [],
                "train_metrics": [],
                "val_metrics": [],
                "learning_rates": [],
            }

            # Early stopping variables
            best_metric = 0.0
            best_epoch = 0
            best_state_dict = None
            epochs_without_improvement = 0

            # Training loop
            start_time = time.time()

            for epoch in range(1, epochs + 1):
                if is_task_cancelled(self.task_id):
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")

                epoch_start_time = time.time()

                # Train for one epoch
                train_loss, train_metrics = self._train_one_epoch(
                    self.model, train_loader, optimizer, scheduler, scaler, epoch
                )

                # Validate
                val_loss, val_metrics = self._validate(self.model, val_loader)

                # Update scheduler (for ReduceLROnPlateau)
                scheduler_type = training_cfg.get("scheduler", "cosine_warm_restarts").lower()
                if scheduler is not None and scheduler_type == "reduce_on_plateau":
                    scheduler.step(val_metrics.get(monitor_metric, val_loss))

                # Get current learning rate
                current_lr = optimizer.param_groups[0]['lr']

                # Record history
                history["train_loss"].append(train_loss)
                history["val_loss"].append(val_loss)
                history["train_metrics"].append(train_metrics)
                history["val_metrics"].append(val_metrics)
                history["learning_rates"].append(current_lr)

                # Check for improvement
                current_metric = val_metrics.get(monitor_metric, 0.0)
                is_best = current_metric > best_metric

                if is_best:
                    best_metric = current_metric
                    best_epoch = epoch
                    # For FM models, only keep decoder+head weights in memory
                    from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel
                    if isinstance(self.model, FMSegmentationModel):
                        best_state_dict = copy.deepcopy(self.model.decoder_state_dict())
                    else:
                        best_state_dict = copy.deepcopy(self.model.state_dict())
                    epochs_without_improvement = 0

                    # Save best checkpoint
                    self._save_checkpoint(
                        self.model, optimizer, scheduler, epoch, val_metrics,
                        is_best=True, filename=f"checkpoint_epoch_{epoch}.pth"
                    )
                else:
                    epochs_without_improvement += 1

                epoch_time = time.time() - epoch_start_time
                epoch_metadata = {
                    "epoch": epoch,
                    "train_loss": train_loss,
                    "val_loss": val_loss,
                    f"val_{primary_iou_metric}": val_metrics.get(primary_iou_metric, 0),
                    "val_dice": val_metrics.get('dice', 0),
                    "lr": current_lr,
                    "epoch_time_sec": epoch_time,
                }

                self._log_info(
                    f"Epoch {epoch}/{epochs} | "
                    f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
                    f"Val {primary_iou_label}: {val_metrics.get(primary_iou_metric, 0):.4f} | "
                    f"Val Dice: {val_metrics.get('dice', 0):.4f} | "
                    f"LR: {current_lr:.2e} | "
                    f"Time: {epoch_time:.1f}s",
                    epoch_metadata,
                )
                self._update_training_progress(min(90, max(1, int(epoch / epochs * 90))))

                # Early stopping check
                if epochs_without_improvement >= patience:
                    self._log_info(
                        f"Early stopping triggered at epoch {epoch}. "
                        f"No improvement for {patience} epochs. "
                        f"Best {monitor_metric}: {best_metric:.4f} at epoch {best_epoch}",
                        {
                            "epoch": epoch,
                            "best_epoch": best_epoch,
                            f"best_{monitor_metric}": best_metric,
                            "patience": patience,
                        },
                    )
                    break

            # Restore best model
            if best_state_dict is not None:
                from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel
                if isinstance(self.model, FMSegmentationModel):
                    self.model.load_decoder_state_dict(best_state_dict)
                else:
                    self.model.load_state_dict(best_state_dict)
                self._log_info(
                    f"Restored best model from epoch {best_epoch}",
                    {"best_epoch": best_epoch, f"best_{monitor_metric}": best_metric},
                )

            # Final evaluation on test set if available
            test_metrics = None
            if test_loader is not None:
                test_loss, test_metrics = self._validate(self.model, test_loader)
                self._log_info(
                    f"Test Results | Loss: {test_loss:.4f} | "
                    f"{primary_iou_label}: {test_metrics.get(primary_iou_metric, 0):.4f} | "
                    f"Dice: {test_metrics.get('dice', 0):.4f} | "
                    f"Accuracy: {test_metrics.get('accuracy', 0):.4f}",
                    {
                        "test_loss": test_loss,
                        f"test_{primary_iou_metric}": test_metrics.get(primary_iou_metric, 0),
                        "test_dice": test_metrics.get('dice', 0),
                        "test_accuracy": test_metrics.get('accuracy', 0),
                    },
                )

            total_time = time.time() - start_time

            # Compile results
            results = {
                "history": history,
                "best_epoch": best_epoch,
                "best_metric": best_metric,
                "best_val_metrics": history["val_metrics"][best_epoch - 1] if best_epoch > 0 else {},
                "test_metrics": test_metrics,
                "total_training_time": total_time,
                "config": self.config,
            }

            self._log_info(
                f"Training completed in {total_time/60:.1f} minutes. "
                f"Best {monitor_metric}: {best_metric:.4f} at epoch {best_epoch}",
                {
                    "training_time_sec": total_time,
                    "best_epoch": best_epoch,
                    f"best_{monitor_metric}": best_metric,
                },
            )
            self._update_training_progress(90)

            return results
        finally:
            self._close_task_logger()
        