"""Mean pooling MIL aggregator."""
from __future__ import annotations

from typing import Tuple, Optional

import torch
import torch.nn as nn

from .base import BaseAggregator


class MeanMILAggregator(BaseAggregator):
    """
    Mean pooling Multiple Instance Learning aggregator.
    
    Simple baseline that averages all instance features and classifies the mean.
    No attention mechanism - treats all instances equally.
    
    Given instance features H ∈ R^{N×D}, computes:
    1. Mean pooling M = mean(H) ∈ R^D
    2. Bag-level prediction from M
    """
    
    def __init__(
        self,
        in_dim: int,
        num_classes: int,
        dropout: float = 0.25
    ):
        super().__init__(in_dim=in_dim, num_classes=num_classes)
        
        # Simple classifier on top of mean-pooled features
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(in_dim, num_classes)
        )
    
    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Forward pass.
        
        Args:
            H: Instance features of shape (N, D)
        
        Returns:
            logits: Bag-level logits of shape (1, C)
            attention: None (no attention mechanism)
        """
        # Mean pooling across all instances
        M = H.mean(dim=0)  # (D,)
        
        # Classification
        logits = self.classifier(M)  # (C,)
        
        return logits.unsqueeze(0), None  # (1, C), None
    
    @classmethod
    def build(
        cls,
        in_dim: int,
        num_classes: int,
        dropout: float = 0.25,
        **kwargs
    ) -> MeanMILAggregator:
        """Build MeanMIL aggregator."""
        return cls(
            in_dim=in_dim,
            num_classes=num_classes,
            dropout=dropout
        )

