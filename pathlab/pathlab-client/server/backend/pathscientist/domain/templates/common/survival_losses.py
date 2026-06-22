"""
Survival analysis loss functions and metrics utilities.

Extracted from wsi_survival/trainer.py to reduce file size.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


# -----------------------------------------------------------------------------
# Discrete Survival Loss
# -----------------------------------------------------------------------------
class NLLSurvivalLoss(nn.Module):
    """
    Negative Log Likelihood Loss for Discrete-Time Survival Analysis.

    Model outputs: Logits for K bins (hazards).
    """
    def __init__(self, eps=1e-7):
        super().__init__()
        self.eps = eps

    def forward(self, logits, y_bin, event):
        """
        logits: (batch, num_bins) - raw output from model
        y_bin: (batch,) - bin index where event/censoring occurred
        event: (batch,) - 1 if event occurred, 0 if censored
        """
        # Sigmoid to get hazard probabilities h(t|T>=t)
        hazards = torch.sigmoid(logits)

        # Survival term: log(1 - h)
        # We want to sum log(1-h) for all bins BEFORE y_bin
        # Create a mask for bins < y_bin
        batch_size, num_bins = logits.shape

        # Mask of shape (batch, num_bins) where mask[i, j] = 1 if j < y_bin[i]
        # This represents all the bins the patient SURVIVED through
        # range_tensor: [0, 1, ..., num_bins-1]
        range_tensor = torch.arange(num_bins, device=logits.device).unsqueeze(0)
        y_bin = y_bin.unsqueeze(1)

        survived_mask = (range_tensor < y_bin).float()

        # Event mask: mask[i, j] = 1 if j == y_bin[i] AND event[i] == 1
        event_mask = (range_tensor == y_bin).float() * event.unsqueeze(1)

        # Loss calculation
        # 1. Uncensored: log(h_bin) + Sum_{j<bin} log(1 - h_j)
        # 2. Censored: Sum_{j<bin} log(1 - h_j)  (assuming censored at start of bin)

        # Survival loss term (for all samples)
        # log(1 - h)
        surv_loss = survived_mask * torch.log(1 - hazards + self.eps)

        # Event loss term (only for uncensored samples)
        # log(h)
        event_loss = event_mask * torch.log(hazards + self.eps)

        # Total log likelihood
        log_likelihood = surv_loss + event_loss

        # Minimize negative log likelihood
        loss = -torch.sum(log_likelihood) / batch_size
        return loss


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

