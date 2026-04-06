"""
PathLab WSI Classification Training Script
============================================

Based on PathLab's WSIClassificationTrainer.
Code Agent can modify ANY part of this script.
Constraints (from skill definition) must be followed:
  - Output /results/metrics.json with test metrics
  - Model forward(H) must return (logits, attention)

Reference: server/backend/ai/tasks/wsi_classification/trainer.py
"""
import json
import time
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from sklearn.metrics import (
    roc_auc_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
)

# ── Logging ─────────────────────────────────────────────────────
logger = logging.getLogger("training")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/results/training.log"),
    ],
)

# ── Reproducibility ─────────────────────────────────────────────
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)


# ============================================================================
# Model — Code Agent can replace this entirely
# ============================================================================

class MILAggregator(nn.Module):
    """
    Gated Attention-Based MIL Aggregator (ABMIL).

    Based on PathLab's ABMILAggregator (server/backend/ai/aggregators/abmil.py).
    Code Agent can: change architecture, add layers, use different attention,
    add regularization, use CLAM/TransMIL/DSMIL, etc.
    """

    def __init__(self, in_dim=1024, num_classes=2, hidden_dim=256, dropout=0.25):
        super().__init__()
        # Gated attention (from PathLab's ABMIL implementation)
        self.attention_V = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.Tanh())
        self.attention_U = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.Sigmoid())
        self.attention_weights = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(in_dim, num_classes)

    def forward(self, H):
        """
        Args:
            H: (N, D) instance features from frozen extractor
        Returns:
            logits:    (1, C) bag-level class logits
            attention: (N,) normalized attention weights
        """
        A_V = self.attention_V(H)
        A_U = self.attention_U(H)
        A_raw = self.attention_weights(self.dropout(A_V * A_U)).squeeze(-1)
        A = torch.softmax(A_raw, dim=0)
        M = torch.sum(A.unsqueeze(-1) * H, dim=0)
        logits = self.classifier(M)
        return logits.unsqueeze(0), A

    def run_one_step(self, H, y, criterion):
        """Single forward step (matches PathLab's BaseAggregator.run_one_step)."""
        logits, _ = self.forward(H)
        loss = criterion(logits, y)
        return loss, logits


# ============================================================================
# Loss — Code Agent can replace this entirely
# ============================================================================

def build_criterion(num_classes, class_weights=None, device="cuda"):
    """
    Build loss function.

    Based on PathLab's loss pattern:
      class_weights = n_total / (n_classes * n_samples_per_class)

    Code Agent can: use focal loss, label smoothing, custom losses, etc.
    """
    if class_weights is not None:
        weights = torch.tensor(class_weights, dtype=torch.float32).to(device)
        return nn.CrossEntropyLoss(weight=weights)
    return nn.CrossEntropyLoss()


# ============================================================================
# Hyperparameters — Code Agent can change any of these
# ============================================================================

LEARNING_RATE = 2e-4
EPOCHS = int(os.getenv("PATHLAB_MAX_EPOCHS", "50"))  # Quick check overrides to 2
OPTIMIZER_TYPE = "adam"         # adam, adamw, sgd
WEIGHT_DECAY = 1e-5
SCHEDULER_TYPE = "cosine"      # cosine, step, none
EARLY_STOPPING_PATIENCE = 10
AUTO_BALANCE = True            # compute class weights from label distribution


# ============================================================================
# Data Loading (mirrors PathLab's WSIFeatureDataset pattern)
# ============================================================================

def load_splits(splits_file="/data/splits.json"):
    """Load train/val/test splits and labels."""
    with open(splits_file) as f:
        data = json.load(f)
    return data


def load_features(wsi_id, features_dir="/data/features", device="cpu"):
    """
    Load pre-extracted features for a WSI.

    Mirrors PathLab's safe_load_features pattern:
    - Handles .pt and .pth extensions
    - Handles dict-wrapped tensors
    - Returns (N_patches, D) tensor
    """
    for ext in (".pt", ".pth"):
        path = Path(features_dir) / f"{wsi_id}{ext}"
        if path.exists():
            tensor = torch.load(path, map_location=device, weights_only=True)
            if isinstance(tensor, dict):
                tensor = tensor.get("features", tensor.get("feats", next(iter(tensor.values()))))
            return tensor
    raise FileNotFoundError(f"No features found for {wsi_id} in {features_dir}")


# ============================================================================
# Evaluation (mirrors PathLab's _evaluate_split)
# ============================================================================

@torch.no_grad()
def evaluate(model, wsi_ids, labels, features_dir, num_classes, criterion, device):
    """
    Evaluate model on a set of WSIs.

    Based on PathLab's WSIClassificationTrainer._evaluate_split().
    Returns: {loss, accuracy, auc, f1, precision, recall}
    """
    model.eval()
    all_probs, all_preds, all_labels = [], [], []
    total_loss = 0.0

    for wsi_id in wsi_ids:
        if wsi_id not in labels:
            continue
        try:
            H = load_features(wsi_id, features_dir, device=device)
        except FileNotFoundError:
            continue

        y = torch.tensor([labels[wsi_id]], device=device)
        loss, logits = model.run_one_step(H, y, criterion)
        total_loss += loss.item()

        probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
        all_probs.append(probs)
        all_preds.append(int(probs.argmax()))
        all_labels.append(labels[wsi_id])

    if not all_labels:
        return {"loss": 0, "accuracy": 0, "auc": None, "f1": 0}

    all_probs = np.array(all_probs)
    all_labels = np.array(all_labels)
    all_preds = np.array(all_preds)

    accuracy = accuracy_score(all_labels, all_preds)

    try:
        if num_classes == 2:
            auc = roc_auc_score(all_labels, all_probs[:, 1])
        else:
            auc = roc_auc_score(all_labels, all_probs, multi_class="ovr", average="macro")
    except ValueError:
        auc = None

    avg = "binary" if num_classes == 2 else "macro"
    f1 = f1_score(all_labels, all_preds, average=avg, zero_division=0)
    precision = precision_score(all_labels, all_preds, average=avg, zero_division=0)
    recall = recall_score(all_labels, all_preds, average=avg, zero_division=0)

    model.train()
    return {
        "loss": round(total_loss / max(1, len(all_labels)), 4),
        "accuracy": round(float(accuracy), 4),
        "auc": round(float(auc), 4) if auc is not None else None,
        "f1": round(float(f1), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
    }


# ============================================================================
# Training Loop (mirrors PathLab's _train_single_run)
# ============================================================================

def train():
    """
    Main training function.

    Based on PathLab's WSIClassificationTrainer._train_single_run().
    Key patterns preserved:
    - batch_size=1 (one WSI per step, MIL standard)
    - model.run_one_step(H, y, criterion) interface
    - CosineAnnealingLR scheduler
    - Early stopping on validation AUC (or loss if AUC unavailable)
    - Class weight auto-balancing
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    features_dir = os.getenv("FEATURES_DIR", "/data/features")

    # Load data
    splits = load_splits()
    labels = {k: int(v) for k, v in splits["labels"].items()}
    train_ids = splits["train"]
    val_ids = splits["val"]
    test_ids = splits["test"]

    logger.info(f"Data: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)}")

    # Determine dimensions
    sample_feat = load_features(train_ids[0], features_dir)
    in_dim = sample_feat.shape[-1]
    num_classes = len(set(labels.values()))
    logger.info(f"Feature dim={in_dim}, num_classes={num_classes}")

    # Build model
    model = MILAggregator(in_dim=in_dim, num_classes=num_classes).to(device)
    params = sum(p.numel() for p in model.parameters())
    logger.info(f"Model: {params:,} parameters")

    # Class weights (PathLab pattern: n_total / (n_classes * count))
    class_weights = None
    if AUTO_BALANCE:
        class_counts = [0] * num_classes
        for wid in train_ids:
            if wid in labels:
                class_counts[labels[wid]] += 1
        n_total = sum(class_counts)
        class_weights = [n_total / (num_classes * max(1, c)) for c in class_counts]
        logger.info(f"Auto-balance: weights={[f'{w:.2f}' for w in class_weights]}")

    criterion = build_criterion(num_classes, class_weights, device)

    # Optimizer (PathLab pattern)
    if OPTIMIZER_TYPE.lower() == "sgd":
        optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE, momentum=0.9, weight_decay=WEIGHT_DECAY)
    elif OPTIMIZER_TYPE.lower() == "adamw":
        optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    else:
        optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    scheduler = None
    if SCHEDULER_TYPE == "cosine":
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    elif SCHEDULER_TYPE == "step":
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)

    # Training loop (matches PathLab's epoch structure)
    best_val_auc = None
    best_val_loss = float("inf")
    best_state_dict = None
    epochs_without_improvement = 0
    history = {"train_loss": [], "val_loss": [], "val_accuracy": [], "val_auc": []}

    for epoch in range(1, EPOCHS + 1):
        model.train()
        running_loss = 0.0
        np.random.shuffle(train_ids)

        # MIL training: one WSI per step (matches PathLab's _run_one_epoch)
        for wsi_id in train_ids:
            if wsi_id not in labels:
                continue
            try:
                H = load_features(wsi_id, features_dir, device=device)
            except FileNotFoundError:
                continue

            y = torch.tensor([labels[wsi_id]], device=device)

            loss, logits = model.run_one_step(H, y, criterion)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

        if scheduler:
            scheduler.step()

        epoch_loss = running_loss / max(1, len(train_ids))
        history["train_loss"].append(epoch_loss)

        # Validation
        val_metrics = evaluate(model, val_ids, labels, features_dir, num_classes, criterion, device)
        history["val_loss"].append(val_metrics["loss"])
        history["val_accuracy"].append(val_metrics["accuracy"])
        history["val_auc"].append(val_metrics["auc"])

        lr = optimizer.param_groups[0]["lr"]
        logger.info(
            f"Epoch {epoch}/{EPOCHS} | loss={epoch_loss:.4f} | "
            f"val_loss={val_metrics['loss']:.4f} | val_acc={val_metrics['accuracy']:.4f} | "
            f"val_auc={val_metrics['auc'] or 'N/A'} | lr={lr:.6f}"
        )

        # Best model tracking (PathLab pattern: prefer AUC, fallback to loss)
        is_improvement = False
        if val_metrics["auc"] is not None:
            if best_val_auc is None or val_metrics["auc"] > best_val_auc:
                best_val_auc = val_metrics["auc"]
                is_improvement = True
        else:
            if val_metrics["loss"] < best_val_loss:
                best_val_loss = val_metrics["loss"]
                is_improvement = True

        if is_improvement:
            best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
            torch.save(best_state_dict, "/results/best_model.pth")
            logger.info(f"  → Best model saved (AUC={best_val_auc}, loss={val_metrics['loss']})")
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= EARLY_STOPPING_PATIENCE:
                logger.info(f"Early stopping at epoch {epoch}")
                break

    # Test evaluation
    if best_state_dict:
        model.load_state_dict(best_state_dict)
    model.to(device)

    test_metrics = evaluate(model, test_ids, labels, features_dir, num_classes, criterion, device)
    logger.info(
        f"Test: auc={test_metrics['auc']} | acc={test_metrics['accuracy']} | f1={test_metrics['f1']}"
    )

    # Save results
    results = {
        "best_val_auc": best_val_auc,
        "best_val_loss": best_val_loss,
        "test": test_metrics,
        "epochs_trained": epoch,
        "hyperparams": {
            "lr": LEARNING_RATE,
            "epochs": EPOCHS,
            "optimizer": OPTIMIZER_TYPE,
            "scheduler": SCHEDULER_TYPE,
            "weight_decay": WEIGHT_DECAY,
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
            "auto_balance": AUTO_BALANCE,
        },
        "model_params": params,
        "feature_dim": in_dim,
        "num_classes": num_classes,
    }

    Path("/results").mkdir(parents=True, exist_ok=True)
    with open("/results/metrics.json", "w") as f:
        json.dump(results, f, indent=2, default=lambda x: float(x) if isinstance(x, (np.floating,)) else None)

    logger.info("Training complete. Results saved to /results/metrics.json")


if __name__ == "__main__":
    train()
