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

TEMPLATE_ROOT = Path(__file__).resolve().parent
if str(TEMPLATE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEMPLATE_ROOT))

try:
    from common.aggregators.registry import get_aggregator
except Exception as exc:
    get_aggregator = None
    _AGGREGATOR_IMPORT_ERROR = exc
else:
    _AGGREGATOR_IMPORT_ERROR = None

# ── Output / logging ─────────────────────────────────────────────
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/results"))

logger = logging.getLogger("training")
logger.setLevel(logging.INFO)
logger.propagate = False
_LOG_FORMATTER = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
if not logger.handlers:
    _stream_handler = logging.StreamHandler(sys.stdout)
    _stream_handler.setFormatter(_LOG_FORMATTER)
    logger.addHandler(_stream_handler)


def ensure_file_logging():
    """Attach the file logger only when train() runs and OUTPUT_DIR is writable."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUTPUT_DIR / "training.log"
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")) == log_path
        for handler in logger.handlers
    ):
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(_LOG_FORMATTER)
        logger.addHandler(file_handler)

# ── Reproducibility ─────────────────────────────────────────────
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)


# ============================================================================
# Model — controlled by the pre-execution model-selection contract
# ============================================================================

class MILAggregator(nn.Module):
    """
    Fallback Gated Attention-Based MIL Aggregator (ABMIL).

    Used only if the copied ``common.aggregators`` registry is unavailable.
    Normal runs build the pre-selected architecture via PATHSCIENTIST_MIL_MODEL.
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


def normalize_mil_model_name(name):
    raw = (name or "abmil").strip().lower().replace("-", "_")
    aliases = {
        "ab_mil": "abmil",
        "attention_mil": "abmil",
        "attention_based_mil": "abmil",
        "clam": "clam_sb",
        "dtfd_mil": "dtfdmil",
        "trans_mil": "transmil",
    }
    return aliases.get(raw, raw)


def build_mil_model(in_dim, num_classes):
    """Build the MIL aggregator fixed by PATHSCIENTIST_MIL_MODEL."""
    mil_model = normalize_mil_model_name(
        os.getenv("PATHSCIENTIST_MIL_MODEL", "abmil")
    )
    if get_aggregator is not None:
        return get_aggregator(mil_model, in_dim=in_dim, num_classes=num_classes)
    if mil_model == "abmil":
        logger.warning(
            "common.aggregators registry unavailable (%s); using fallback ABMIL",
            _AGGREGATOR_IMPORT_ERROR,
        )
        return MILAggregator(in_dim=in_dim, num_classes=num_classes)
    raise RuntimeError(
        "PATHSCIENTIST_MIL_MODEL="
        f"{mil_model!r} requires common.aggregators registry; "
        f"import failed: {_AGGREGATOR_IMPORT_ERROR}"
    )


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
QUICK_CHECK = os.getenv("PATHLAB_QUICK_CHECK", "").lower() in {"1", "true", "yes"}
MAX_TRAIN_SAMPLES = int(os.getenv("PATHLAB_MAX_TRAIN_SAMPLES", "0") or "0")
MAX_VAL_SAMPLES = int(os.getenv("PATHLAB_MAX_VAL_SAMPLES", "0") or "0")
MAX_TEST_SAMPLES = int(os.getenv("PATHLAB_MAX_TEST_SAMPLES", "0") or "0")


# ============================================================================
# Data Loading (mirrors PathLab's WSIFeatureDataset pattern)
# ============================================================================

def load_splits(splits_file="/data/splits.json"):
    """Load train/val/test splits and labels."""
    with open(splits_file) as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return _splits_from_pathlab_manifest(data["items"])
    return data


def _splits_from_pathlab_manifest(items):
    """Convert PathLab DB/training-task export records to splits.json shape."""
    classes = sorted(
        {
            str(item.get("label") or "").strip()
            for item in items
            if str(item.get("label") or "").strip()
        }
    )
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    splits = {"train": [], "val": [], "test": [], "labels": {}}
    for item in items:
        wsi_id = str(item.get("wsi_id") or item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        split = str(item.get("split") or "train").strip().lower()
        if split in {"valid", "validation"}:
            split = "val"
        if not wsi_id or not label or split not in {"train", "val", "test"}:
            continue
        splits[split].append(wsi_id)
        splits["labels"][wsi_id] = class_to_idx[label]
    return splits


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


def feature_path_for(wsi_id, features_dir="/data/features"):
    """Return the existing feature tensor path for ``wsi_id``, if any."""
    feature_root = Path(features_dir)
    for ext in (".pt", ".pth"):
        path = feature_root / f"{wsi_id}{ext}"
        if path.exists():
            return path
    return None


def filter_ids_with_features(wsi_ids, labels, features_dir="/data/features"):
    """Filter one split to slides that have both labels and feature tensors."""
    usable_ids = []
    missing_feature_ids = []
    missing_label_ids = []
    for wsi_id in wsi_ids:
        if wsi_id not in labels:
            missing_label_ids.append(wsi_id)
            continue
        if feature_path_for(wsi_id, features_dir) is None:
            missing_feature_ids.append(wsi_id)
            continue
        usable_ids.append(wsi_id)
    return usable_ids, missing_feature_ids, missing_label_ids


def prepare_feature_splits(splits, features_dir="/data/features"):
    """Filter train/val/test once before training and report coverage.

    This prevents silent per-epoch skips when a slide is present in
    ``splits.json`` but its ``.pt``/``.pth`` tensor was not produced.
    """
    raw_labels = {k: int(v) for k, v in splits["labels"].items()}
    filtered = {}
    stats = {
        "raw_counts": {},
        "usable_counts": {},
        "missing_feature_counts": {},
        "missing_label_counts": {},
        "missing_feature_ids": {},
        "missing_label_ids": {},
    }

    for split_name in ("train", "val", "test"):
        raw_ids = list(splits.get(split_name, []))
        usable_ids, missing_feature_ids, missing_label_ids = filter_ids_with_features(
            raw_ids,
            raw_labels,
            features_dir,
        )
        filtered[split_name] = usable_ids
        stats["raw_counts"][split_name] = len(raw_ids)
        stats["usable_counts"][split_name] = len(usable_ids)
        stats["missing_feature_counts"][split_name] = len(missing_feature_ids)
        stats["missing_label_counts"][split_name] = len(missing_label_ids)
        stats["missing_feature_ids"][split_name] = missing_feature_ids
        stats["missing_label_ids"][split_name] = missing_label_ids

    usable_label_ids = {
        wsi_id
        for split_ids in filtered.values()
        for wsi_id in split_ids
    }
    labels = {wsi_id: raw_labels[wsi_id] for wsi_id in usable_label_ids}
    return filtered, labels, stats


def _sample_limit_for_split(split_name):
    if split_name == "train":
        return MAX_TRAIN_SAMPLES
    if split_name == "val":
        return MAX_VAL_SAMPLES
    if split_name == "test":
        return MAX_TEST_SAMPLES
    return 0


def apply_quick_check_limits(filtered_splits, labels, split_stats):
    """Apply quick-check split caps after feature filtering.

    ``run_experiment(quick_check=True)`` sets PATHLAB_MAX_*_SAMPLES. The MIL
    template must honor those caps before loading tensors, otherwise a quick
    check can still read hundreds of WSI feature bags from NAS.
    """
    if not QUICK_CHECK:
        split_stats.setdefault("quick_check", False)
        return filtered_splits, labels, split_stats

    limited = {}
    limits = {}
    for split_name in ("train", "val", "test"):
        split_ids = list(filtered_splits.get(split_name, []))
        limit = _sample_limit_for_split(split_name)
        limits[split_name] = limit
        if limit > 0:
            split_ids = split_ids[:limit]
        limited[split_name] = split_ids

    limited_label_ids = {
        wsi_id
        for split_ids in limited.values()
        for wsi_id in split_ids
    }
    limited_labels = {wsi_id: labels[wsi_id] for wsi_id in limited_label_ids if wsi_id in labels}
    limited_stats = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in split_stats.items()
    }
    limited_stats["usable_counts_before_quick_check"] = dict(
        split_stats.get("usable_counts", {})
    )
    limited_stats["usable_counts"] = {
        split_name: len(limited.get(split_name, []))
        for split_name in ("train", "val", "test")
    }
    limited_stats["quick_check"] = True
    limited_stats["quick_check_limits"] = limits
    return limited, limited_labels, limited_stats


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
            raise KeyError(f"Missing label for filtered slide {wsi_id}")
        H = load_features(wsi_id, features_dir, device=device)

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
    ensure_file_logging()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    features_dir = os.getenv("FEATURES_DIR", "/data/features")
    # Plan-2026-04-30 data-readiness review P1-4: also honor SPLITS_FILE so
    # workspace-generated splits (under .dataset/readiness/splits.json) can
    # flow through without re-mounting them under /data.
    splits_file = os.getenv("SPLITS_FILE", "/data/splits.json")

    # Load data and filter feature coverage once up front. Do not silently
    # skip missing tensors inside each epoch; that makes metrics ambiguous.
    splits = load_splits(splits_file)
    filtered_splits, labels, split_stats = prepare_feature_splits(
        splits,
        features_dir,
    )
    filtered_splits, labels, split_stats = apply_quick_check_limits(
        filtered_splits,
        labels,
        split_stats,
    )
    train_ids = filtered_splits["train"]
    val_ids = filtered_splits["val"]
    test_ids = filtered_splits["test"]

    raw = split_stats["raw_counts"]
    usable = split_stats["usable_counts"]
    missing_features = split_stats["missing_feature_counts"]
    logger.info(
        "Data raw: train=%d, val=%d, test=%d",
        raw["train"], raw["val"], raw["test"],
    )
    logger.info(
        "Data usable after feature filtering: train=%d, val=%d, test=%d",
        usable["train"], usable["val"], usable["test"],
    )
    if QUICK_CHECK:
        logger.info(
            "Quick check sample caps applied: train=%d, val=%d, test=%d",
            usable["train"], usable["val"], usable["test"],
        )
    if any(missing_features.values()):
        logger.warning(
            "Missing feature tensors skipped before training: train=%d, val=%d, test=%d; examples=%s",
            missing_features["train"],
            missing_features["val"],
            missing_features["test"],
            {
                k: v[:10]
                for k, v in split_stats["missing_feature_ids"].items()
                if v
            },
        )
    if any(split_stats["missing_label_counts"].values()):
        logger.warning(
            "Slides without labels skipped before training: %s",
            split_stats["missing_label_counts"],
        )
    empty_splits = [
        name for name, ids in filtered_splits.items()
        if not ids
    ]
    if empty_splits:
        raise RuntimeError(
            "No usable split after feature filtering: "
            f"{empty_splits}; features_dir={features_dir}"
        )

    # Determine dimensions
    sample_feat = load_features(train_ids[0], features_dir)
    in_dim = sample_feat.shape[-1]
    num_classes = len(set(labels.values()))
    logger.info(f"Feature dim={in_dim}, num_classes={num_classes}")

    # Build model. The orchestrator sets PATHSCIENTIST_MIL_MODEL from
    # literature-grounded model selection and keeps it fixed across iterations.
    mil_model_name = normalize_mil_model_name(
        os.getenv("PATHSCIENTIST_MIL_MODEL", "abmil")
    )
    model = build_mil_model(in_dim=in_dim, num_classes=num_classes).to(device)
    params = sum(p.numel() for p in model.parameters())
    logger.info(f"MIL model={mil_model_name}; params={params:,}")

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
                raise KeyError(f"Missing label for filtered slide {wsi_id}")
            H = load_features(wsi_id, features_dir, device=device)

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
            torch.save(best_state_dict, OUTPUT_DIR / "best_model.pth")
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
        "mil_model": mil_model_name,
        "feature_dim": in_dim,
        "num_classes": num_classes,
        "data_coverage": split_stats,
        "quick_check": QUICK_CHECK,
        "split_counts": {
            "train": len(train_ids),
            "val": len(val_ids),
            "test": len(test_ids),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(results, f, indent=2, default=lambda x: float(x) if isinstance(x, (np.floating,)) else None)

    logger.info("Training complete. Results saved to %s", OUTPUT_DIR / "metrics.json")


if __name__ == "__main__":
    train()
