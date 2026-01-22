"""WSI Classification Trainer - integrates feature extraction and ABMIL training."""
from __future__ import annotations

import json
import asyncio
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score, accuracy_score

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
from backend.database.repositories import WSIRepository, TrainingTaskRepository
from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException


class WSIClassificationTrainer(BaseTrainer):
    """
    Trainer for WSI-level classification tasks.

    Pipeline:
    1. Extract features from WSI patches using a feature extractor (e.g., ResNet50)
    2. Train an aggregator model (e.g., ABMIL) on extracted features
    3. Save checkpoint and metrics
    """

    task_type = TaskType.WSI_CLASSIFICATION

    async def extract_features(
        self,
        wsi_ids: List[str],
        extractor_name: str,
        batch_size: int,
        force_recompute: bool,
        logger: Any,
        db: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict] = None,
    ) -> FeatureExtractionResponse:
        """
        Extract features for all WSI slides sequentially (single-GPU optimized).

        Uses global feature cache to avoid redundant extraction:
        - Cache location: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
        - Task directory: uploads/training/{task_id}/features/{wsi_id}.pt (symlink)

        The params_hash ensures features are only reused when preprocessing config matches.
        """
        # VRAM Protection: Check if GPU has enough memory BEFORE loading the model
        # This prevents system crashes from loading models that are too large
        device = torch.device(self.device)
        if device.type == "cuda":
            try:
                check_vram_before_model_load(
                    model_name=extractor_name,
                    device=device,
                    batch_size=batch_size,
                )
            except VRAMInsufficientError as e:
                raise RuntimeError(
                    f"VRAM protection triggered: {e.message}"
                ) from e

        # Build extractor once and reuse
        extractor = get_extractor(extractor_name, pretrained=True, hf_token=hf_token).to(self.device).eval()

        results = []
        total = len(wsi_ids)
        task_features_dir = self.uploads_root / "training" / self.task_id / "features"
        task_features_dir.mkdir(parents=True, exist_ok=True)

        for i, wsi_id in enumerate(wsi_ids, 1):
            task_feat_path = task_features_dir / f"{wsi_id}.pt"
            coords_h5 = self.uploads_root / "coordinates" / f"{wsi_id}_coords.h5"

            # Compute params_hash from coords.h5 to ensure consistency
            # The coords.h5 file contains the actual preprocessing parameters used
            params_hash = read_params_from_coords_h5(coords_h5)
            if not params_hash:
                # Fallback to preprocessing_config if coords.h5 doesn't have params
                preprocessing_config = preprocessing_config or {}
                params_hash = compute_params_hash(
                    patch_size=preprocessing_config.get('tile_size', 512),
                    stride=preprocessing_config.get('stride', 512),
                    level=preprocessing_config.get('level', 0),
                    seg_params={
                        'sthresh': preprocessing_config.get('sthresh', 5),
                        'mthresh': preprocessing_config.get('mthresh', 7),
                        'close': preprocessing_config.get('close', 4),
                        'use_otsu': preprocessing_config.get('use_otsu', False),
                    },
                    filter_params={
                        'a_t': preprocessing_config.get('a_t', 100),
                        'a_h': preprocessing_config.get('a_h', 16),
                        'max_n_holes': preprocessing_config.get('max_n_holes', 8),
                    },
                    contour_fn=preprocessing_config.get('contour_fn', 'four_pt'),
                    use_padding=preprocessing_config.get('use_padding', True),
                )

            # Step 1: Check if task-specific features already exist (file or symlink)
            if task_feat_path.exists() and not force_recompute:
                feats = torch.load(task_feat_path, map_location="cpu")
                shape = tuple(feats.shape)
                await logger.info(
                    f"[{i}/{total}] Features already exist for {wsi_id}, skipping",
                    metadata={"wsi_id": wsi_id, "shape": list(shape), "path": str(task_feat_path)}
                )
                results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                progress = 33 + int(i / total * 33)
                await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
                await db.commit()
                continue

            # Step 2: Check global feature cache
            cached_path = find_cached_features(
                self.uploads_root, extractor_name, params_hash, wsi_id
            )

            if cached_path and not force_recompute:
                # Cache hit: create symlink to cached features
                create_symlink_to_cache(task_features_dir, wsi_id, cached_path)
                feats = torch.load(cached_path, map_location="cpu")
                shape = tuple(feats.shape)
                await logger.info(
                    f"[{i}/{total}] Cache hit for {wsi_id}, created symlink",
                    metadata={"wsi_id": wsi_id, "shape": list(shape), "cached_path": str(cached_path)}
                )
                results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                progress = 33 + int(i / total * 33)
                await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
                await db.commit()
                continue

            # Step 3: Extract features (cache miss)
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise ValueError(f"WSI not found: {wsi_id}")

            wsi_path = wsi.wsi_path

            if not coords_h5.exists():
                raise FileNotFoundError(f"Coordinates not found for {wsi_id}: {coords_h5}")

            await logger.info(
                f"[{i}/{total}] Extracting features for {wsi_id} (cache miss)",
                metadata={"wsi_id": wsi_id, "wsi_index": i, "total_wsi": total}
            )
            await db.commit()

            feats = await self._extract_wsi_features(
                extractor=extractor,
                wsi_path=str(wsi_path),
                coords_h5=str(coords_h5),
                batch_size=batch_size,
            )

            # Save to global cache
            cache_feat_path = get_cache_save_path(
                self.uploads_root, extractor_name, params_hash, wsi_id
            )
            torch.save(feats.contiguous(), cache_feat_path)

            # Create symlink in task directory
            create_symlink_to_cache(task_features_dir, wsi_id, cache_feat_path)
            shape = tuple(feats.shape)

            await logger.info(
                f"[{i}/{total}] Features saved to cache for {wsi_id}",
                metadata={"wsi_id": wsi_id, "shape": list(shape), "cache_path": str(cache_feat_path)}
            )

            progress = 33 + int(i / total * 33)
            await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
            await db.commit()

            results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})

        return self._build_feature_response(results)
    
    async def _extract_wsi_features(
        self,
        extractor: nn.Module,
        wsi_path: str,
        coords_h5: str,
        batch_size: int,
    ) -> torch.Tensor:
        """
        Extract features for a single WSI.

        Uses the extractor's preprocessing transforms to ensure correct
        normalization and image size for the model.

        NOTE: @torch.inference_mode() decorator does NOT work with async functions.
        We must use the context manager inside the function instead.

        VRAM Protection:
        Before batch processing, this method performs a VRAM check by running
        a single sample through the extractor. If the requested batch_size would
        exceed available VRAM (85% threshold), a VRAMExceededError is raised
        with a suggested safe batch_size.
        """
        # VRAM Protection: Check BEFORE creating the large-batch DataLoader
        # to prevent OOM when loading the first batch
        device = torch.device(self.device)
        if device.type == "cuda":
            # Create a small DataLoader with batch_size=1 for VRAM measurement
            probe_loader, probe_dataset = build_dataloader(
                wsi_path=wsi_path,
                coords_h5=coords_h5,
                batch_size=1,  # Use batch_size=1 for safe probing
                num_workers=0,  # No multiprocessing for quick probe
                prefetch_factor=2,  # Ignored when num_workers=0
                pin_memory=False,
                extractor=extractor,
                mode="eval",
            )
            if len(probe_dataset) > 0:
                # Get a single sample for VRAM measurement
                sample_batch, _ = next(iter(probe_loader))
                try:
                    check_vram_before_batch_processing(
                        extractor=extractor,
                        sample_input=sample_batch,
                        requested_batch_size=batch_size,
                        device=device,
                        safety_threshold=0.85,  # Use at most 85% of VRAM
                    )
                except VRAMExceededError as e:
                    # Re-raise with clear message for upstream handling
                    raise RuntimeError(
                        f"VRAM protection triggered: {e.message}. "
                        f"Please reduce batch_size to {e.suggested_batch_size} or lower."
                    ) from e
                # Clean up probe loader
                del probe_loader, probe_dataset
                torch.cuda.empty_cache()

        # Now create the actual DataLoader with user-specified batch_size
        # Note: Disable pin_memory to avoid CUDA errors in multiprocess DataLoader
        # "RuntimeError: Caught RuntimeError in pin memory thread for device 0"
        loader, dataset = build_dataloader(
            wsi_path=wsi_path,
            coords_h5=coords_h5,
            batch_size=batch_size,
            num_workers=4,
            prefetch_factor=2,
            pin_memory=False,  # Disabled to avoid CUDA pin memory errors
            extractor=extractor,
            mode="eval",
        )

        feats_all = []
        # Use context manager for async function (decorator doesn't work with async)
        with torch.inference_mode():
            for imgs, _coords in loader:
                # Check for cancellation at each batch
                if is_task_cancelled(self.task_id):
                    # No need to log here, the caller (extract_features) handles the specific exception or the loop breaks
                    # But we should raise exception to stop immediately
                    raise TrainingCancelledException("Feature extraction cancelled during batch processing")

                # Yield control to event loop to allow cancellation requests to be processed
                await asyncio.sleep(0)

                imgs = imgs.to(self.device, non_blocking=True)
                feats = extractor(imgs)
                feats_all.append(feats.cpu())  # Keep on CPU to save VRAM

        if len(feats_all) == 0:
            return torch.empty(0, extractor.output_dim)

        return torch.cat(feats_all, dim=0)  # (N, D)
    
    def _is_kfold_splits(self, splits_map: Dict[str, List[str]]) -> bool:
        """Check if splits_map represents k-fold configuration."""
        return any(key.startswith("fold_") for key in splits_map.keys())

    def _get_num_folds(self, splits_map: Dict[str, List[str]]) -> int:
        """Get number of folds from k-fold splits_map."""
        fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
        return len(fold_keys)

    def _evaluate_split(
        self,
        model: nn.Module,
        feats: Dict[str, torch.Tensor],
        wsi_ids: List[str],
        labels: Dict[str, int],
        classes: List[str],
    ) -> Dict[str, Any]:
        """Evaluate model on a specific split, return metrics."""
        model.eval()
        all_probs = []
        all_preds = []
        all_labels = []
        total_loss = 0.0
        criterion = nn.CrossEntropyLoss()
        num_classes = len(classes)

        with torch.inference_mode():
            for wsi_id in wsi_ids:
                H = feats[wsi_id].to(self.device)
                logits, _ = model(H)
                y = torch.tensor([labels[wsi_id]], dtype=torch.long, device=self.device)
                loss = criterion(logits, y)
                total_loss += float(loss.item())

                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())

                all_probs.append(probs)
                all_preds.append(pred_idx)
                all_labels.append(labels[wsi_id])

        avg_loss = total_loss / max(1, len(wsi_ids))
        all_probs = np.array(all_probs)
        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)

        accuracy = accuracy_score(all_labels, all_preds)

        # AUC calculation
        try:
            if num_classes == 2:
                auc = roc_auc_score(all_labels, all_probs[:, 1])
            else:
                auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
        except ValueError:
            auc = None

        model.train()
        return {"loss": avg_loss, "accuracy": accuracy, "auc": auc}

    async def _train_single_run(
        self,
        train_ids: List[str],
        val_ids: List[str],
        feats: Dict[str, torch.Tensor],
        labels: Dict[str, int],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        run_name: str = "",
        progress_base: int = 66,
        progress_range: int = 34,
        optimizer_type: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
    ) -> Dict[str, Any]:
        """
        Train a single model run (used for both regular training and k-fold).

        Args:
            optimizer_type: Optimizer type ('adam', 'sgd', 'adamw')
            auto_balance: Whether to apply class weights for imbalanced datasets
            early_stopping_patience: Number of epochs to wait before early stopping

        Returns dict with model, history, and metrics.
        """
        any_tensor = next(iter(feats.values()))
        in_dim = int(any_tensor.shape[1])

        model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=num_classes).to(self.device)

        # Calculate class weights for auto-balancing
        class_weights = None
        if auto_balance:
            class_counts = [0] * num_classes
            for wsi_id in train_ids:
                class_counts[labels[wsi_id]] += 1
            # Formula: weight[i] = n_total / (n_classes * n_samples[i])
            n_total = len(train_ids)
            class_weights = torch.tensor([
                n_total / (num_classes * max(1, count)) for count in class_counts
            ], dtype=torch.float32, device=self.device)
            await logger.info(
                f"Auto-balance enabled: class_weights={[f'{w:.2f}' for w in class_weights.tolist()]}",
                metadata={"class_counts": class_counts, "class_weights": class_weights.tolist()}
            )

        criterion = nn.CrossEntropyLoss(weight=class_weights)

        # Dynamic optimizer selection
        optimizer_type_lower = optimizer_type.lower()
        if optimizer_type_lower == "sgd":
            optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
        elif optimizer_type_lower == "adamw":
            optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
        else:  # Default to adam
            optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=0.0)

        history = {"train_loss": [], "val_loss": [], "val_accuracy": [], "val_auc": []}
        best_val_loss = float('inf')
        best_state_dict = None
        epochs_without_improvement = 0

        model.train()
        for epoch in range(1, epochs + 1):
            # Check for cancellation at each epoch start
            if is_task_cancelled(self.task_id):
                await logger.info(f"{run_name} Training cancelled by user/timeout at epoch {epoch}")
                # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                del model, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")

            running_loss = 0.0
            for wsi_id in train_ids:
                H = feats[wsi_id].to(self.device)
                logits, _ = model(H)
                y = torch.tensor([labels[wsi_id]], dtype=torch.long, device=self.device)
                loss = criterion(logits, y)

                # Check for cancellation within the training loop (per sample/batch)
                if is_task_cancelled(self.task_id):
                    # Clean up CUDA tensors before raising exception
                    del model, optimizer, criterion, H, logits, loss, y
                    if class_weights is not None:
                        del class_weights
                    raise TrainingCancelledException(f"Training cancelled during epoch {epoch} loop")

                # Yield control to event loop to allow cancellation requests to be processed
                await asyncio.sleep(0)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                running_loss += float(loss.item())

            epoch_loss = running_loss / max(1, len(train_ids))
            history["train_loss"].append(epoch_loss)

            # Validation
            val_metrics = {"loss": None, "accuracy": None, "auc": None}
            if val_ids:
                val_metrics = self._evaluate_split(model, feats, val_ids, labels, classes)
                history["val_loss"].append(val_metrics["loss"])
                history["val_accuracy"].append(val_metrics["accuracy"])
                history["val_auc"].append(val_metrics["auc"])

                # Track best model
                if val_metrics["loss"] < best_val_loss:
                    best_val_loss = val_metrics["loss"]
                    best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

            # Log progress
            log_msg = f"{run_name} Epoch {epoch}/{epochs} - train_loss: {epoch_loss:.4f}"
            if val_ids:
                log_msg += f", val_loss: {val_metrics['loss']:.4f}, val_acc: {val_metrics['accuracy']:.4f}"
            await logger.info(log_msg, metadata={"epoch": epoch, "train_loss": epoch_loss, **val_metrics})

            progress = progress_base + int(epoch / epochs * progress_range)
            await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
            await db.commit()

            # Early stopping check
            if val_ids and epochs_without_improvement >= early_stopping_patience:
                await logger.info(
                    f"{run_name} Early stopping triggered at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                    metadata={"epoch": epoch, "best_val_loss": best_val_loss}
                )
                break

        # Restore best model if we have validation
        if best_state_dict is not None:
            model.load_state_dict(best_state_dict)

        return {"model": model, "in_dim": in_dim, "history": history}

    async def train_model(
        self,
        splits_map: Dict[str, List[str]],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
    ) -> TrainResponse:
        """
        Train ABMIL aggregator with proper data splits.

        Supports:
        - Regular splits: {'train': [...], 'val': [...], 'test': [...]}
        - K-Fold CV: {'fold_0': [...], 'fold_1': [...], ...}

        Args:
            optimizer: Optimizer type ('adam', 'sgd', 'adamw')
            auto_balance: Whether to apply class weights for imbalanced datasets
            early_stopping_patience: Number of epochs to wait before early stopping
        """
        # Collect all WSI IDs
        all_wsi_ids = []
        for ids in splits_map.values():
            all_wsi_ids.extend(ids)
        all_wsi_ids = list(set(all_wsi_ids))

        # Load all features
        features_dir = self.uploads_root / "training" / self.task_id / "features"
        feats = self._load_features(features_dir, all_wsi_ids)

        # Get labels from database
        labels = {}
        classes = []
        for wsi_id in all_wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi or not wsi.label:
                raise ValueError(f"WSI {wsi_id} has invalid/missing label")
            if wsi.label not in classes:
                classes.append(wsi.label)

        classes = sorted(classes)
        for wsi_id in all_wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            labels[wsi_id] = classes.index(wsi.label)

        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        is_kfold = self._is_kfold_splits(splits_map)

        if is_kfold:
            return await self._train_kfold(
                splits_map, feats, labels, classes, aggregator_name, num_classes,
                epochs, lr, logger, db, model_id, model_dir,
                optimizer, auto_balance, early_stopping_patience
            )
        else:
            return await self._train_regular(
                splits_map, feats, labels, classes, aggregator_name, num_classes,
                epochs, lr, logger, db, model_id, model_dir,
                optimizer, auto_balance, early_stopping_patience
            )

    async def _train_regular(
        self,
        splits_map: Dict[str, List[str]],
        feats: Dict[str, torch.Tensor],
        labels: Dict[str, int],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        model_id: str,
        model_dir: Path,
        optimizer: str = "adam",
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
                metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "auto_val": True}
            )

        await logger.info(
            f"Training with splits: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)}",
            metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)}
        )

        result = await self._train_single_run(
            train_ids, val_ids, feats, labels, classes, aggregator_name,
            num_classes, epochs, lr, logger, db,
            optimizer_type=optimizer, auto_balance=auto_balance,
            early_stopping_patience=early_stopping_patience
        )

        model = result["model"]
        in_dim = result["in_dim"]
        history = result["history"]

        # Evaluate on test set
        test_metrics = None
        if test_ids:
            test_metrics = self._evaluate_split(model, feats, test_ids, labels, classes)
            await logger.info(
                f"Test metrics: loss={test_metrics['loss']:.4f}, acc={test_metrics['accuracy']:.4f}",
                metadata=test_metrics
            )

        # Save checkpoint
        ckpt_path = model_dir / "aggregator.pth"
        torch.save({
            "state_dict": model.state_dict(),
            "in_dim": in_dim,
            "num_classes": num_classes,
        }, ckpt_path)

        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "split_type": "regular",
        }, ensure_ascii=False, indent=2))

        # Save metrics
        metrics_data = {
            "is_kfold": False,
            "history": history,
            "val_metrics": {
                "accuracy": history["val_accuracy"][-1] if history["val_accuracy"] else None,
                "auc": history["val_auc"][-1] if history["val_auc"] else None,
            } if val_ids else None,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Save per-WSI inference results
        all_wsi_ids = train_ids + val_ids + test_ids
        await self._save_training_inference_results(
            model=model, feats=feats, wsi_ids=all_wsi_ids, classes=classes,
            labels=labels, task_id=self.task_id, logger=logger, db=db,
        )

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["train_loss"],
            val_metrics=test_metrics or (metrics_data.get("val_metrics") if val_ids else None),
        )

    async def _train_kfold(
        self,
        splits_map: Dict[str, List[str]],
        feats: Dict[str, torch.Tensor],
        labels: Dict[str, int],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        model_id: str,
        model_dir: Path,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
    ) -> TrainResponse:
        """Train with K-Fold cross-validation."""
        num_folds = self._get_num_folds(splits_map)
        fold_keys = sorted([k for k in splits_map.keys() if k.startswith("fold_")])

        await logger.info(
            f"Starting {num_folds}-fold cross-validation",
            metadata={"num_folds": num_folds, "epochs_per_fold": epochs}
        )

        fold_results = {}
        all_val_metrics = {"accuracy": [], "auc": [], "loss": []}

        for fold_idx, val_fold_key in enumerate(fold_keys):
            # Current fold is validation, all others are training
            val_ids = splits_map[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(splits_map[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)}",
                metadata={"fold": fold_idx + 1, "train": len(train_ids), "val": len(val_ids)}
            )

            # Calculate progress for this fold
            fold_progress_base = 66 + int(fold_idx / num_folds * 34)
            fold_progress_range = int(34 / num_folds)

            result = await self._train_single_run(
                train_ids, val_ids, feats, labels, classes, aggregator_name,
                num_classes, epochs, lr, logger, db,
                run_name=f"[Fold {fold_idx + 1}/{num_folds}]",
                progress_base=fold_progress_base,
                progress_range=fold_progress_range,
                optimizer_type=optimizer,
                auto_balance=auto_balance,
                early_stopping_patience=early_stopping_patience,
            )

            model = result["model"]
            in_dim = result["in_dim"]
            history = result["history"]

            # Final validation metrics
            val_metrics = self._evaluate_split(model, feats, val_ids, labels, classes)

            fold_results[val_fold_key] = {
                "history": history,
                "val_metrics": val_metrics,
            }

            all_val_metrics["accuracy"].append(val_metrics["accuracy"])
            if val_metrics["auc"] is not None:
                all_val_metrics["auc"].append(val_metrics["auc"])
            all_val_metrics["loss"].append(val_metrics["loss"])

            # Save fold checkpoint
            fold_dir = model_dir / val_fold_key
            fold_dir.mkdir(parents=True, exist_ok=True)
            torch.save({
                "state_dict": model.state_dict(),
                "in_dim": in_dim,
                "num_classes": num_classes,
            }, fold_dir / "aggregator.pth")

            await logger.info(
                f"Fold {fold_idx + 1} complete: acc={val_metrics['accuracy']:.4f}, auc={val_metrics['auc']:.4f if val_metrics['auc'] else 'N/A'}",
                metadata={"fold": fold_idx + 1, **val_metrics}
            )

        # Calculate aggregated statistics
        aggregated = {
            "accuracy": {
                "mean": float(np.mean(all_val_metrics["accuracy"])),
                "std": float(np.std(all_val_metrics["accuracy"])),
            },
            "loss": {
                "mean": float(np.mean(all_val_metrics["loss"])),
                "std": float(np.std(all_val_metrics["loss"])),
            },
        }
        if all_val_metrics["auc"]:
            aggregated["auc"] = {
                "mean": float(np.mean(all_val_metrics["auc"])),
                "std": float(np.std(all_val_metrics["auc"])),
            }

        await logger.info(
            f"K-Fold complete: accuracy={aggregated['accuracy']['mean']:.4f}±{aggregated['accuracy']['std']:.4f}",
            metadata={"aggregated": aggregated}
        )

        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "split_type": "kfold",
            "num_folds": num_folds,
        }, ensure_ascii=False, indent=2))

        # Save aggregated metrics
        metrics_data = {
            "is_kfold": True,
            "num_folds": num_folds,
            "folds": {k: v for k, v in fold_results.items()},
            "aggregated": aggregated,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # For k-fold, use fold_0 as the default checkpoint (or could pick best)
        ckpt_path = model_dir / "fold_0" / "aggregator.pth"

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=fold_results["fold_0"]["history"]["train_loss"],
            val_metrics={
                "accuracy": aggregated["accuracy"]["mean"],
                "auc": aggregated.get("auc", {}).get("mean"),
                "kfold_aggregated": aggregated,
            },
        )

    async def _save_training_inference_results(
        self,
        model: nn.Module,
        feats: Dict[str, torch.Tensor],
        wsi_ids: List[str],
        classes: List[str],
        labels: Dict[str, int],
        task_id: str,
        logger: Any,
        db: Any,
    ) -> None:
        """
        Save per-WSI inference results after training.

        For each WSI, saves:
        - Prediction (pred): predicted class label
        - Probabilities (probs): probability distribution over classes
        - Attention weights (if ABMIL): per-patch attention scores

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_attention.npy (if attention available)
        """
        await logger.info(
            f"Saving inference results for {len(wsi_ids)} WSI slides",
            metadata={"task_id": task_id, "num_wsi": len(wsi_ids)}
        )
        await db.commit()

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"

        # Check if model supports raw attention (ABMIL and similar)
        has_raw_attention = hasattr(model, 'forward_with_raw_attention')

        # Collect predictions for metrics calculation
        all_probs = []  # List of probability arrays
        all_preds = []  # List of predicted class indices
        all_labels = []  # List of ground truth class indices
        num_classes = len(classes)

        with torch.inference_mode():
            for wsi_id in wsi_ids:
                H = feats[wsi_id].to(self.device)

                # Get attention (raw if available)
                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None

                # Compute probabilities
                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())
                pred_label = classes[pred_idx]

                # Collect for metrics
                all_probs.append(probs)
                all_preds.append(pred_idx)
                all_labels.append(labels[wsi_id])

                # Build probability dict
                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}

                # Ground truth
                gt_label = classes[labels[wsi_id]]

                # Create result directory
                wsi_result_dir = ai_results_root / wsi_id
                wsi_result_dir.mkdir(parents=True, exist_ok=True)

                # Save result JSON
                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "ground_truth": gt_label,
                    "correct": pred_label == gt_label,
                    "classes": classes,
                }

                result_file = wsi_result_dir / f"train_{task_id}_result.json"
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                # Save raw attention weights (before softmax) if available
                if raw_attention is not None:
                    raw_attention_np = raw_attention.cpu().numpy()
                    raw_attention_file = wsi_result_dir / f"train_{task_id}_attention_raw.npy"
                    np.save(raw_attention_file, raw_attention_np)

                # Also save normalized attention if available (for backwards compatibility)
                if attention is not None:
                    attention_np = attention.cpu().numpy()
                    attention_file = wsi_result_dir / f"train_{task_id}_attention.npy"
                    np.save(attention_file, attention_np)

        # Calculate metrics
        all_probs = np.array(all_probs)  # (N, num_classes)
        all_preds = np.array(all_preds)  # (N,)
        all_labels = np.array(all_labels)  # (N,)

        # Accuracy
        accuracy = accuracy_score(all_labels, all_preds)

        # AUC calculation
        try:
            if num_classes == 2:
                # Binary classification: use probability of positive class (class 1)
                auc = roc_auc_score(all_labels, all_probs[:, 1])
                auc_display = f"AUC: {auc:.4f}"
            else:
                # Multi-class: use OVR (One-vs-Rest) strategy
                # Need one-hot encoded labels for multi-class AUC
                auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
                auc_display = f"AUC (macro-OVR): {auc:.4f}"
        except ValueError as e:
            # AUC calculation may fail if some classes have no samples
            auc = None
            auc_display = f"AUC: N/A (insufficient samples per class)"

        # Log final metrics
        metrics_metadata = {
            "task_id": task_id,
            "accuracy": accuracy,
            "num_classes": num_classes,
            "classes": classes,
        }
        if auc is not None:
            metrics_metadata["auc"] = auc

        await logger.info(
            f"Training complete - Accuracy: {accuracy:.4f}, {auc_display}",
            metadata=metrics_metadata
        )
        await db.commit()

        model.train()  # Restore training mode

    def _load_features(self, features_dir: Path, wsi_ids: List[str]) -> Dict[str, torch.Tensor]:
        """Load pre-extracted features for all WSI."""
        feats = {}
        for wsi_id in wsi_ids:
            feat_path = features_dir / f"{wsi_id}.pt"
            if not feat_path.exists():
                raise FileNotFoundError(f"Features not found for {wsi_id}: {feat_path}")
            feats[wsi_id] = torch.load(feat_path, map_location="cpu")
        return feats

