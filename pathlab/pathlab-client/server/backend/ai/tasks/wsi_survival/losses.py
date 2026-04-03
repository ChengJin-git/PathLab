"""
Survival analysis loss functions and metrics utilities.

Extracted from wsi_survival/trainer.py to reduce file size.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


def compute_survival_from_hazards(hazards):
    """Compute cumulative survival probabilities from discrete hazards."""
    if isinstance(hazards, torch.Tensor):
        return torch.cumprod(1 - hazards, dim=-1)
    return np.cumprod(1 - np.asarray(hazards), axis=-1)


def compute_risk_from_survival(survival):
    """Compute scalar risk score with higher values indicating higher risk."""
    if isinstance(survival, torch.Tensor):
        return -torch.sum(survival, dim=-1)
    return -np.sum(np.asarray(survival), axis=-1)


# -----------------------------------------------------------------------------
# Discrete Survival Loss
# -----------------------------------------------------------------------------
class NLLSurvivalLoss(nn.Module):
    """
    Negative Log Likelihood Loss for Discrete-Time Survival Analysis.

    Model outputs: Logits for K bins (hazards).
    """
    def __init__(self, alpha=0.0, eps=1e-7):
        super().__init__()
        self.alpha = alpha
        self.eps = eps

    def forward(self, logits, y_bin, event, alpha=None):
        """
        logits: (batch, num_bins) - raw output from model
        y_bin: (batch,) - bin index where event/censoring occurred
        event: (batch,) - 1 if event occurred, 0 if censored
        """
        batch_size = len(y_bin)
        y_bin = y_bin.view(batch_size, 1).long()
        censored = (1.0 - event.view(batch_size, 1).float()).to(logits.device)

        alpha = self.alpha if alpha is None else alpha

        hazards = torch.sigmoid(logits)
        survival = compute_survival_from_hazards(hazards)
        survival_padded = torch.cat([torch.ones_like(censored), survival], dim=1)

        uncensored_loss = -(1 - censored) * (
            torch.log(torch.gather(survival_padded, 1, y_bin).clamp(min=self.eps))
            + torch.log(torch.gather(hazards, 1, y_bin).clamp(min=self.eps))
        )
        censored_loss = -censored * torch.log(
            torch.gather(survival_padded, 1, y_bin + 1).clamp(min=self.eps)
        )

        neg_likelihood = censored_loss + uncensored_loss
        loss = (1 - alpha) * neg_likelihood + alpha * uncensored_loss
        return loss.mean()


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

