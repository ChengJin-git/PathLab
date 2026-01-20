"""
Patch Classification Trainer - Feature Extractor + Linear Probe.

Consistent training paradigm with WSI Classification:
1. Use Foundation Model as Feature Extractor (frozen)
2. Train Linear Probe
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Any, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score, accuracy_score

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.tasks.patch_classification.linear_layer import LinearProbe
from backend.ai.schemas import TaskType, TrainResponse, FeatureExtractionResponse
from backend.database.repositories import TrainingTaskRepository


logger = logging.getLogger("patch_classification_trainer")


class PatchClassificationTrainer(BaseTrainer):
    """
    Trainer for patch-level classification tasks.

    Pipeline (与 WSI Classification 一致):
    1. 使用 Feature Extractor (e.g., ResNet50, UNI, CONCH) 提取 patch 特征 (frozen)
    2. 训练 Linear Probe 进行分类
    3. 保存 checkpoint 和 metrics
    """

    task_type = TaskType.PATCH_CLASSIFICATION

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
        Patch classification does not require feature extraction.
        This method is a placeholder to satisfy the BaseTrainer interface.
        """
        # Suppress unused parameter warnings (required by BaseTrainer interface)
        del wsi_ids, extractor_name, batch_size, force_recompute, logger, db, hf_token, preprocessing_config
        return self._build_feature_response([])

    async def train_model(
        self,
        wsi_ids: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
    ) -> TrainResponse:
        """
        Train Linear Probe on frozen Feature Extractor.

        Note: For patch classification, this method is not used.
        Use train_with_dataset() instead.
        """
        # Suppress unused parameter warnings (required by BaseTrainer interface)
        del wsi_ids, aggregator_name, num_classes, epochs, lr, logger, db
        raise NotImplementedError(
            "Use train_with_dataset() for patch classification training. "
            "This method is only for BaseTrainer interface compatibility."
        )

    async def train_with_dataset(
        self,
        train_loader: torch.utils.data.DataLoader,
        val_loader: Optional[torch.utils.data.DataLoader],
        test_loader: Optional[torch.utils.data.DataLoader],
        extractor_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
        hf_token: str = "",
        dropout_p: float = 0.0,
        classes: Optional[List[str]] = None,
    ) -> TrainResponse:
        """
        Train Linear Probe with provided DataLoaders.

        Args:
            train_loader: Training data loader
            val_loader: Validation data loader
            test_loader: Test data loader (optional)
            extractor_name: Name of feature extractor (e.g., "resnet50", "uni")
            num_classes: Number of output classes
            epochs: Number of training epochs
            lr: Learning rate
            logger: TrainingLogger instance
            db: Database session
            hf_token: HuggingFace token for gated models
            dropout_p: Dropout probability for linear probe
            classes: List of class names for result saving
        """
        await logger.info(
            f"Starting Patch Classification training with {extractor_name}",
            metadata={
                "extractor": extractor_name,
                "num_classes": num_classes,
                "epochs": epochs,
                "lr": lr,
            }
        )
        await db.commit()

        # Build feature extractor (frozen)
        extractor = get_extractor(
            extractor_name, pretrained=True, hf_token=hf_token
        ).to(self.device).eval()

        # Freeze extractor
        for param in extractor.parameters():
            param.requires_grad = False

        # Build linear probe
        linear_probe = LinearProbe(
            feature_dim=extractor.output_dim,
            num_classes=num_classes,
            dropout_p=dropout_p,
        ).to(self.device)

        # Build combined model for inference
        model = nn.Sequential(extractor, linear_probe).to(self.device)

        # Optimizer only for linear probe parameters
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(linear_probe.parameters(), lr=lr, weight_decay=0.0)

        # Training loop
        history = {"loss": []}
        best_val_acc = 0.0
        best_epoch = 0
        best_val_metrics = None
        best_test_metrics = None

        for epoch in range(1, epochs + 1):
            # Training
            linear_probe.train()
            running_loss = 0.0
            num_batches = 0

            for batch_img, gt in train_loader:
                batch_img = batch_img.to(self.device)
                gt = gt.to(self.device).long()

                optimizer.zero_grad()

                # Extract features (no grad)
                with torch.no_grad():
                    features = extractor(batch_img)

                # Forward through linear probe
                logits = linear_probe(features)
                loss = criterion(logits, gt)

                loss.backward()
                optimizer.step()

                running_loss += loss.item()
                num_batches += 1

            epoch_loss = running_loss / max(1, num_batches)
            history["loss"].append(epoch_loss)

            # Validation (if val_loader is available)
            if val_loader is not None:
                val_metrics = self._evaluate(model, val_loader)
                val_acc = val_metrics["accuracy"]
            else:
                # Use training loss as proxy for model selection
                val_metrics = {"accuracy": 1.0 - epoch_loss}  # Lower loss = higher "accuracy"
                val_acc = val_metrics["accuracy"]

            await logger.info(
                f"Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f}" +
                (f", val_acc: {val_acc:.4f}" if val_loader else ""),
                metadata={"epoch": epoch, "loss": epoch_loss, **val_metrics}
            )

            # Update progress
            progress = 66 + int(epoch / epochs * 34)
            await TrainingTaskRepository.update_status(
                db, self.task_id, "training", progress=progress
            )
            await db.commit()

            # Save best model
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_epoch = epoch
                best_val_metrics = val_metrics if val_loader else None

                # Test on test set if available
                if test_loader is not None:
                    best_test_metrics = self._evaluate(model, test_loader)
                    await logger.info(
                        f"New best model at epoch {epoch} - test_acc: {best_test_metrics['accuracy']:.4f}",
                        metadata={"epoch": epoch, **best_test_metrics}
                    )
                    await db.commit()

                # Save checkpoint
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

        # Return unified response
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

    def _evaluate(
        self,
        model: nn.Module,
        dataloader: torch.utils.data.DataLoader,
    ) -> Dict[str, float]:
        """Evaluate model on dataloader."""
        model.eval()
        all_probs = []
        all_preds = []
        all_labels = []

        with torch.inference_mode():
            for batch_img, gt in dataloader:
                batch_img = batch_img.to(self.device)
                logits = model(batch_img)
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

        metrics = {"accuracy": accuracy}
        if auc is not None:
            metrics["auc"] = auc

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

