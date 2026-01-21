"""
Patch Classification Trainer - Feature Extractor + Linear Probe.

Consistent training paradigm with WSI Classification:
1. Use Foundation Model as Feature Extractor (frozen)
2. Train Linear Probe (instead of Aggregator for WSI)
"""
from __future__ import annotations

import json
import logging
import random
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from sklearn.metrics import roc_auc_score, accuracy_score

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.tasks.patch_classification.linear_layer import LinearProbe
from backend.ai.schemas import TaskType, TrainResponse, FeatureExtractionResponse
from backend.ai.utils.patch_dataset import PatchDatasetFromDB
from backend.ai.utils.cam_utils import get_cam_extractor, get_cam_spatial_size
from backend.database.repositories import TrainingTaskRepository, WSIRepository, AIResultRepository


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
        db: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict] = None,
    ) -> FeatureExtractionResponse:
        """
        Patch classification extracts features on-the-fly during training.
        This method is a no-op to satisfy the BaseTrainer interface.
        """
        # Suppress unused parameter warnings (required by BaseTrainer interface)
        del wsi_ids, extractor_name, batch_size, force_recompute, logger, db, hf_token, preprocessing_config
        return self._build_feature_response([])

    async def train_model(
        self,
        wsi_ids: List[str],
        aggregator_name: str,  # For patch classification, this is the extractor name
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
    ) -> TrainResponse:
        """
        Train Linear Probe on frozen Feature Extractor.

        Aligned with WSI Classification's train_model() interface.
        For patch classification:
        - aggregator_name is reused as the feature extractor name
        - wsi_ids are used to get patch images and labels from database
        """
        extractor_name = aggregator_name  # Reuse parameter for API compatibility

        # Get labels from database (same as WSI classification)
        labels = {}
        classes = []
        image_paths = {}
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi or not wsi.label:
                raise ValueError(f"Image {wsi_id} has invalid/missing label")
            if wsi.label not in classes:
                classes.append(wsi.label)
            image_paths[wsi_id] = wsi.wsi_path

        classes = sorted(classes)
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi or not wsi.label or wsi.label not in classes:
                raise ValueError(f"Image {wsi_id} has invalid/missing label")
            labels[wsi_id] = classes.index(wsi.label)

        # Build label mapper
        label_mapper = {label: idx for idx, label in enumerate(classes)}

        # Build path -> label mapping for dataset
        # All images go to train initially, then auto-split
        all_items = {image_paths[wsi_id]: classes[labels[wsi_id]] for wsi_id in wsi_ids}

        # Auto-split: 70% train, 20% val, 10% test
        all_paths = list(all_items.keys())
        random.shuffle(all_paths)

        n_total = len(all_paths)
        n_train = max(1, int(n_total * 0.7))
        n_val = int(n_total * 0.2)

        train_paths = all_paths[:n_train]
        val_paths = all_paths[n_train:n_train + n_val]
        test_paths = all_paths[n_train + n_val:]

        train_items = {p: all_items[p] for p in train_paths}
        val_items = {p: all_items[p] for p in val_paths}
        test_items = {p: all_items[p] for p in test_paths}

        await logger.info(
            f"[Data] Train: {len(train_items)}, Val: {len(val_items)}, Test: {len(test_items)}",
            {"train_count": len(train_items), "val_count": len(val_items), "test_count": len(test_items)}
        )
        await db.commit()

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
        await db.commit()

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

        # Optimizer only for linear probe
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

                with torch.no_grad():
                    features = extractor(batch_img)

                logits = linear_probe(features)
                loss = criterion(logits, gt)

                loss.backward()
                optimizer.step()

                running_loss += loss.item()
                num_batches += 1

            epoch_loss = running_loss / max(1, num_batches)
            history["loss"].append(epoch_loss)

            # Validation
            if val_loader is not None:
                val_metrics = self._evaluate(model, val_loader)
                val_acc = val_metrics["accuracy"]
            else:
                val_metrics = {"accuracy": 1.0 - epoch_loss}
                val_acc = val_metrics["accuracy"]

            await logger.info(
                f"Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f}" +
                (f", val_acc: {val_acc:.4f}" if val_loader else ""),
                {"epoch": epoch, "loss": epoch_loss, **val_metrics}
            )

            # Update progress: training from 66% to 100%
            progress = 66 + int(epoch / epochs * 34)
            await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
            await db.commit()

            # Save best model
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_epoch = epoch
                best_val_metrics = val_metrics if val_loader else None

                if test_loader is not None:
                    best_test_metrics = self._evaluate(model, test_loader)
                    await logger.info(
                        f"New best model at epoch {epoch} - test_acc: {best_test_metrics['accuracy']:.4f}",
                        {"epoch": epoch, **best_test_metrics}
                    )
                    await db.commit()

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

        # Save final metrics with complete history (even if last epoch wasn't best)
        self._save_final_metrics(history, best_val_metrics, best_test_metrics)

        # Save per-image inference results (like WSI classification)
        await self._save_training_inference_results(
            model=model,
            wsi_ids=wsi_ids,
            image_paths=image_paths,
            classes=classes,
            labels=labels,
            task_id=self.task_id,
            logger=logger,
            db=db,
            extractor_name=extractor_name,
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

    def _build_dataloaders(
        self,
        train_items: Dict[str, str],
        val_items: Dict[str, str],
        test_items: Dict[str, str],
        label_mapper: Dict[str, int],
        extractor_name: str,
    ) -> Tuple[DataLoader, Optional[DataLoader], Optional[DataLoader]]:
        """Build train/val/test dataloaders."""
        # Get transforms from extractor
        extractor = get_extractor(extractor_name, pretrained=True, hf_token=self.hf_token)
        fm_transform = extractor.get_transforms()
        del extractor  # Free memory

        train_dataset = PatchDatasetFromDB(
            annotations=train_items,
            label_mapper=label_mapper,
            mode='train',
            fm_transform=fm_transform,
        )
        val_dataset = PatchDatasetFromDB(
            annotations=val_items,
            label_mapper=label_mapper,
            mode='val',
            fm_transform=fm_transform,
        ) if val_items else None
        test_dataset = PatchDatasetFromDB(
            annotations=test_items,
            label_mapper=label_mapper,
            mode='test',
            fm_transform=fm_transform,
        ) if test_items else None

        train_loader = DataLoader(train_dataset, batch_size=self.batch_size, shuffle=True, num_workers=4)
        val_loader = DataLoader(val_dataset, batch_size=self.batch_size, shuffle=False, num_workers=4) if val_dataset else None
        test_loader = DataLoader(test_dataset, batch_size=self.batch_size, shuffle=False, num_workers=4) if test_dataset else None

        return train_loader, val_loader, test_loader

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
        db: Any,
        extractor_name: str,
    ) -> None:
        """
        Save per-image inference results after training.

        For each image, saves:
        - Prediction (pred): predicted class label
        - Probabilities (probs): probability distribution over classes
        - Ground truth
        - CAM heatmap (attention-like visualization)

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_cam.npy (CAM heatmap)
        """
        await logger.info(
            f"Saving inference results for {len(wsi_ids)} images",
            {"task_id": task_id, "num_images": len(wsi_ids)}
        )
        await db.commit()

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"

        # Collect predictions for metrics calculation
        all_probs = []
        all_preds = []
        all_labels = []
        num_classes = len(classes)

        # Get transforms for inference using actual extractor
        extractor_temp = get_extractor(extractor_name, pretrained=False, hf_token=self.hf_token)
        fm_transform = extractor_temp.get_transforms()
        del extractor_temp

        # Get CAM extractor for heatmap generation
        cam_extractor = get_cam_extractor(extractor_name)
        cam_size = get_cam_spatial_size(extractor_name)

        await logger.info(
            f"Using CAM extractor for {extractor_name}, CAM size: {cam_size}",
            {"extractor": extractor_name, "cam_size": cam_size}
        )
        await db.commit()

        # Need to enable gradients for Grad-CAM (ResNet)
        # For ViT attention-based CAM, inference_mode is fine
        from backend.ai.utils.cam_utils import is_cnn_extractor
        use_gradients = is_cnn_extractor(extractor_name)

        with torch.set_grad_enabled(use_gradients):
            for wsi_id in wsi_ids:
                # Load and transform image
                from PIL import Image
                img_path = image_paths[wsi_id]
                img = Image.open(img_path).convert("RGB")
                img_tensor = fm_transform(img).unsqueeze(0).to(self.device)

                # Forward pass for prediction
                with torch.inference_mode():
                    logits = model(img_tensor)
                    probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                    pred_idx = int(probs.argmax())
                    pred_label = classes[pred_idx]

                # Extract CAM heatmap (requires gradients for ResNet Grad-CAM)
                try:
                    cam_map = cam_extractor.extract_cam(
                        model=model,
                        input_tensor=img_tensor,
                        target_class=pred_idx,
                    )
                    # cam_map shape: (1, H, W) -> squeeze to (H, W)
                    cam_map = cam_map.squeeze(0)
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    await logger.warning(f"CAM extraction failed for {wsi_id}: {e}\n{error_details}")
                    # Fallback to uniform CAM
                    cam_map = np.ones(cam_size, dtype=np.float32) / (cam_size[0] * cam_size[1])

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

                # Save CAM heatmap (like WSI attention)
                cam_file = wsi_result_dir / f"train_{task_id}_cam.npy"
                np.save(cam_file, cam_map)

                # Save result JSON
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

                result_file = wsi_result_dir / f"train_{task_id}_result.json"
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                # Save to ai_results database table
                db_result_data = {
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
                    }
                }
                await AIResultRepository.create(db, db_result_data)

        # Calculate metrics
        all_probs = np.array(all_probs)
        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)

        # Accuracy
        accuracy = accuracy_score(all_labels, all_preds)

        # AUC calculation
        try:
            if num_classes == 2:
                auc = roc_auc_score(all_labels, all_probs[:, 1])
                auc_display = f"AUC: {auc:.4f}"
            else:
                auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
                auc_display = f"AUC (macro-OVR): {auc:.4f}"
        except ValueError:
            auc = None
            auc_display = "AUC: N/A (insufficient samples per class)"

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

