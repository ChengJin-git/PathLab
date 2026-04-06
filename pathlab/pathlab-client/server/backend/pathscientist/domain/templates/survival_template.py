"""
PathLab Survival Analysis Training Template
=============================================

AI Agent can modify the code between ### MODIFIABLE ### markers.
FIXED zones (data loading, evaluation, result saving) must NOT be changed.

Forward signature: model(H) -> (hazards, attention)
  H:         (N_patches, D) — instance features
  hazards:   (1, K)         — predicted hazard logits for K time bins
  attention: (N,)           — normalized attention weights
"""

# === FIXED: Imports & Data Loading ==========================================
from common.data_loader import load_survival_data
from common.metrics import compute_survival_metrics
from common.utils import save_checkpoint, save_results, set_seed, setup_logging

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

logger = setup_logging()
set_seed(42)


### MODIFIABLE START: model ###
class SurvivalAggregator(nn.Module):
    """
    Attention-Based MIL for Survival Analysis.
    Outputs hazard logits for discrete time bins.

    Agent can: change architecture, attention mechanism, add layers, etc.
    Must keep forward(H) -> (hazards, attention).
    """

    def __init__(self, in_dim=1024, num_bins=4, hidden_dim=256, dropout=0.25):
        super().__init__()
        # Gated attention
        self.attention_V = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Tanh(),
        )
        self.attention_U = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Sigmoid(),
        )
        self.attention_weights = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)

        # Survival head
        self.fc = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_bins),
        )

    def forward(self, H):
        """
        Args:
            H: (N, D) instance features
        Returns:
            hazards:   (1, K) hazard logits for K time bins
            attention: (N,)   normalized attention weights
        """
        A_V = self.attention_V(H)
        A_U = self.attention_U(H)
        A_raw = self.attention_weights(
            self.dropout(A_V * A_U)
        ).squeeze(-1)
        A = torch.softmax(A_raw, dim=0)

        M = torch.sum(A.unsqueeze(-1) * H, dim=0)

        hazards = self.fc(M)
        return hazards.unsqueeze(0), A
### MODIFIABLE END: model ###


### MODIFIABLE START: loss ###
class NLLSurvivalLoss(nn.Module):
    """
    Negative log-likelihood loss for discrete-time survival analysis.
    Reference: Zadeh & Schmid (2020) — "Deep Survival"

    Agent can: use Cox partial likelihood, ranking loss, etc.
    """

    def __init__(self, alpha=0.0):
        super().__init__()
        self.alpha = alpha  # Regularization weight for uncensored samples

    def forward(self, hazards, survival_time_bin, event_status):
        """
        Args:
            hazards: (1, K) raw logits
            survival_time_bin: int, which bin the event/censor falls in
            event_status: int, 1=event occurred, 0=censored
        """
        sigmoid_hazards = torch.sigmoid(hazards.squeeze(0))  # (K,)
        survival = torch.cumprod(1 - sigmoid_hazards, dim=0)  # (K,)

        bin_idx = min(survival_time_bin, len(sigmoid_hazards) - 1)

        if event_status == 1:
            # Event: P(T=t) = S(t-1) * h(t)
            if bin_idx == 0:
                loss = -torch.log(sigmoid_hazards[0] + 1e-7)
            else:
                loss = -torch.log(survival[bin_idx - 1] + 1e-7) - torch.log(
                    sigmoid_hazards[bin_idx] + 1e-7
                )
        else:
            # Censored: P(T>t) = S(t)
            loss = -torch.log(survival[bin_idx] + 1e-7)

        return loss


def get_criterion(num_bins, alpha=0.0):
    return NLLSurvivalLoss(alpha=alpha)
### MODIFIABLE END: loss ###


### MODIFIABLE START: hyperparams ###
LEARNING_RATE = 0.0002
EPOCHS = int(os.getenv("PATHLAB_MAX_EPOCHS", "30"))  # Quick check overrides to 2
OPTIMIZER = "adam"
NUM_BINS = 4
EARLY_STOPPING_PATIENCE = 7
SCHEDULER = "cosine"
WEIGHT_DECAY = 1e-4
### MODIFIABLE END: hyperparams ###


# === FIXED: Training Loop ===================================================
def _assign_time_bins(times: dict, num_bins: int) -> dict:
    """Assign survival times to discrete bins using quantiles."""
    all_times = sorted(times.values())
    if not all_times:
        return {}

    quantiles = np.quantile(all_times, np.linspace(0, 1, num_bins + 1)[1:])
    bins = {}
    for wsi_id, t in times.items():
        bin_idx = int(np.searchsorted(quantiles, t))
        bins[wsi_id] = min(bin_idx, num_bins - 1)
    return bins


def train():
    # 1. Load data
    features, times, events, splits = load_survival_data()
    logger.info(
        f"Data loaded: {len(features)} WSIs, "
        f"train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])}"
    )

    # 2. Assign time bins
    time_bins = _assign_time_bins(times, NUM_BINS)

    # 3. Determine dimensions
    sample_id = next(iter(features))
    in_dim = features[sample_id].shape[-1]
    logger.info(f"Feature dim={in_dim}, num_bins={NUM_BINS}")

    # 4. Create model
    model = SurvivalAggregator(in_dim=in_dim, num_bins=NUM_BINS).cuda()
    logger.info(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # 5. Create optimizer & scheduler
    criterion = get_criterion(NUM_BINS)

    if OPTIMIZER == "adamw":
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
        )
    elif OPTIMIZER == "sgd":
        optimizer = torch.optim.SGD(
            model.parameters(), lr=LEARNING_RATE, momentum=0.9, weight_decay=WEIGHT_DECAY
        )
    else:
        optimizer = torch.optim.Adam(
            model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
        )

    scheduler = None
    if SCHEDULER == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    elif SCHEDULER == "step":
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.5)

    # 6. Training loop
    best_val_metric = 0.0
    patience_counter = 0
    train_ids = splits["train"]

    for epoch in range(1, EPOCHS + 1):
        model.train()
        train_loss = 0.0
        n_train = 0
        np.random.shuffle(train_ids)

        for wsi_id in train_ids:
            if wsi_id not in features or wsi_id not in time_bins or wsi_id not in events:
                continue

            H = features[wsi_id].cuda()
            optimizer.zero_grad()
            hazards, _ = model(H)
            loss = criterion(hazards, time_bins[wsi_id], events[wsi_id])
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            n_train += 1

        if scheduler:
            scheduler.step()

        avg_loss = train_loss / max(n_train, 1)

        # 7. Validation
        val_metrics = compute_survival_metrics(
            model, features, times, events, splits["val"]
        )
        logger.info(
            f"Epoch {epoch}/{EPOCHS} | loss={avg_loss:.4f} | "
            f"val_c_index={val_metrics['c_index']:.4f}"
        )

        # 8. Early stopping
        if val_metrics["c_index"] > best_val_metric:
            best_val_metric = val_metrics["c_index"]
            patience_counter = 0
            save_checkpoint(model, "/results/best_model.pth")
        else:
            patience_counter += 1
            if patience_counter >= EARLY_STOPPING_PATIENCE:
                logger.info(f"Early stopping at epoch {epoch}")
                break

    # 9. Test evaluation
    model.load_state_dict(
        torch.load("/results/best_model.pth", map_location="cuda", weights_only=True)
    )
    test_metrics = compute_survival_metrics(
        model, features, times, events, splits["test"]
    )
    logger.info(f"Test results: c_index={test_metrics['c_index']:.4f}")

    # 10. Save results
    save_results("/results/metrics.json", {
        "best_val_c_index": best_val_metric,
        "test": test_metrics,
        "epochs_trained": epoch,
        "hyperparams": {
            "lr": LEARNING_RATE,
            "epochs": EPOCHS,
            "optimizer": OPTIMIZER,
            "scheduler": SCHEDULER,
            "num_bins": NUM_BINS,
            "weight_decay": WEIGHT_DECAY,
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        },
    })
    logger.info("Training complete. Results saved to /results/metrics.json")


if __name__ == "__main__":
    train()
