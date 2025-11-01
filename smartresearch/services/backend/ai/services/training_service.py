"""
Training Service

Handles model training workflow.
Coordinates feature extraction and aggregator training.
"""

import os
import json
import time
import torch
import torch.nn as nn
import torch.optim as optim
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .feature_service import FeatureService
from .model_service import ModelService

# Get uploads directory (same as AI service main.py)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
UPLOADS_DIR = os.path.join(ROOT, "uploads")


class TrainingService:
    """Service for model training"""

    @staticmethod
    async def train_model(
        task_id: str,
        wsi_features: Dict[str, str],  # {wsi_id: feature_path}
        wsi_labels: Dict[str, str],    # {wsi_id: label}
        classes: List[str],
        config: Dict
    ) -> Dict:
        """
        Train a model
        
        Args:
            task_id: Training task ID
            wsi_features: Mapping of wsi_id to feature file path
            wsi_labels: Mapping of wsi_id to label
            classes: List of class names
            config: Training configuration
                {
                    "feature_extractor": str,
                    "aggregator": str,
                    "epochs": int,
                    "learning_rate": float,
                    "batch_size": int,
                    "device": str,
                    "train_split": List[str],  # wsi_ids for training
                    "val_split": List[str],    # wsi_ids for validation
                }
        
        Returns:
            Training result
                {
                    "model_path": str,
                    "config_path": str,
                    "train_metrics": Dict,
                    "val_metrics": Dict,
                    "training_history": Dict
                }
        """
        # Extract config
        feature_extractor = config.get("feature_extractor", "resnet50")
        aggregator = config.get("aggregator", "abmil")
        epochs = config.get("epochs", 10)
        learning_rate = config.get("learning_rate", 1e-4)
        device = config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        train_split = config.get("train_split", [])
        val_split = config.get("val_split", [])

        # Create model directory
        model_id = f"model-{task_id}-{int(time.time())}"
        model_dir = os.path.join(UPLOADS_DIR, "models", model_id)
        os.makedirs(model_dir, exist_ok=True)
        
        # Load features and labels
        train_data = await TrainingService._load_dataset(
            wsi_features, wsi_labels, train_split, classes
        )
        val_data = await TrainingService._load_dataset(
            wsi_features, wsi_labels, val_split, classes
        )
        
        # Create model
        feature_dim = FeatureService.get_feature_dim(feature_extractor)
        num_classes = len(classes)
        model = TrainingService._create_model(aggregator, feature_dim, num_classes)
        model = model.to(device)
        
        # Training setup
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=learning_rate)
        
        # Training loop
        history = {
            "train_loss": [],
            "train_acc": [],
            "val_loss": [],
            "val_acc": []
        }
        
        best_val_acc = 0.0
        best_checkpoint = None
        
        for epoch in range(epochs):
            # Train
            train_loss, train_acc = await TrainingService._train_epoch(
                model, train_data, criterion, optimizer, device
            )
            
            # Validate
            val_loss, val_acc = await TrainingService._validate_epoch(
                model, val_data, criterion, device
            )
            
            # Record history
            history["train_loss"].append(train_loss)
            history["train_acc"].append(train_acc)
            history["val_loss"].append(val_loss)
            history["val_acc"].append(val_acc)
            
            print(f"Epoch {epoch+1}/{epochs}: "
                  f"train_loss={train_loss:.4f}, train_acc={train_acc:.4f}, "
                  f"val_loss={val_loss:.4f}, val_acc={val_acc:.4f}")
            
            # Save best checkpoint
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_checkpoint = {
                    "epoch": epoch,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "val_acc": val_acc,
                }
        
        # Save final model
        model_path = os.path.join(model_dir, "checkpoint.pth")
        torch.save(best_checkpoint, model_path)
        
        # Save config
        config_data = {
            "model_id": model_id,
            "task_id": task_id,
            "classes": classes,
            "feature_extractor": feature_extractor,
            "aggregator": aggregator,
            "feature_dim": feature_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "learning_rate": learning_rate,
        }
        config_path = os.path.join(model_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        # Save training history
        history_path = os.path.join(model_dir, "training_history.json")
        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)
        
        # Prepare result
        result = {
            "model_id": model_id,
            "model_path": f"models/{model_id}/checkpoint.pth",
            "config_path": f"models/{model_id}/config.json",
            "train_metrics": {
                "loss": history["train_loss"][-1],
                "accuracy": history["train_acc"][-1],
            },
            "val_metrics": {
                "loss": history["val_loss"][-1],
                "accuracy": history["val_acc"][-1],
                "best_accuracy": best_val_acc,
            },
            "training_history": history
        }
        
        return result

    @staticmethod
    async def _load_dataset(
        wsi_features: Dict[str, str],
        wsi_labels: Dict[str, str],
        wsi_ids: List[str],
        classes: List[str]
    ) -> List[Tuple[torch.Tensor, int]]:
        """Load dataset from feature files"""
        dataset = []
        class_to_idx = {cls: idx for idx, cls in enumerate(classes)}
        
        for wsi_id in wsi_ids:
            if wsi_id not in wsi_features or wsi_id not in wsi_labels:
                continue
            
            # Load features
            feature_path = wsi_features[wsi_id]
            features = await FeatureService.load_features(feature_path)
            
            # Get label
            label = wsi_labels[wsi_id]
            label_idx = class_to_idx.get(label)
            if label_idx is None:
                continue
            
            dataset.append((features, label_idx))
        
        return dataset

    @staticmethod
    def _create_model(aggregator: str, feature_dim: int, num_classes: int) -> nn.Module:
        """Create aggregator model using built-in model library"""
        from smartresearch.services.backend.ai.models.lib import create_aggregator

        # Create aggregator using built-in library
        model = create_aggregator(
            name=aggregator,
            feature_dim=feature_dim,
            num_classes=num_classes,
            device="cpu"  # Will be moved to device later
        )

        return model

    @staticmethod
    async def _train_epoch(
        model: nn.Module,
        dataset: List[Tuple[torch.Tensor, int]],
        criterion: nn.Module,
        optimizer: optim.Optimizer,
        device: str
    ) -> Tuple[float, float]:
        """Train for one epoch"""
        model.train()
        total_loss = 0.0
        correct = 0
        total = 0

        for features, label in dataset:
            features = features.to(device)
            label_tensor = torch.tensor([label], dtype=torch.long, device=device)

            optimizer.zero_grad()

            # Forward pass - aggregator may return (logits, attention) or just logits
            output = model(features)
            if isinstance(output, tuple):
                logits, _ = output  # Ignore attention weights during training
            else:
                logits = output

            loss = criterion(logits.unsqueeze(0), label_tensor)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            pred = torch.argmax(logits)
            correct += (pred == label).item()
            total += 1

        avg_loss = total_loss / max(total, 1)
        accuracy = correct / max(total, 1)
        return avg_loss, accuracy

    @staticmethod
    async def _validate_epoch(
        model: nn.Module,
        dataset: List[Tuple[torch.Tensor, int]],
        criterion: nn.Module,
        device: str
    ) -> Tuple[float, float]:
        """Validate for one epoch"""
        model.eval()
        total_loss = 0.0
        correct = 0
        total = 0

        with torch.no_grad():
            for features, label in dataset:
                features = features.to(device)
                label_tensor = torch.tensor([label], dtype=torch.long, device=device)

                # Forward pass - aggregator may return (logits, attention) or just logits
                output = model(features)
                if isinstance(output, tuple):
                    logits, _ = output  # Ignore attention weights during validation
                else:
                    logits = output

                loss = criterion(logits.unsqueeze(0), label_tensor)

                total_loss += loss.item()
                pred = torch.argmax(logits)
                correct += (pred == label).item()
                total += 1

        avg_loss = total_loss / max(total, 1)
        accuracy = correct / max(total, 1)
        return avg_loss, accuracy

