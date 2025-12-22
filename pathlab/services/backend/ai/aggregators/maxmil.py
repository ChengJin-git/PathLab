"""Max pooling MIL aggregator."""
from __future__ import annotations

from typing import Tuple, Optional

import torch
import torch.nn as nn

from .base import BaseAggregator


class MaxMILAggregator(BaseAggregator):
    """
    Max pooling Multiple Instance Learning aggregator.
    
    Simple baseline that takes the maximum activation across all instances.
    No attention mechanism - selects the most activated features.
    
    Given instance features H ∈ R^{N×D}, computes:
    1. Max pooling M = max(H) ∈ R^D (element-wise max across instances)
    2. Bag-level prediction from M
    """
    
    def __init__(
        self,
        in_dim: int,
        num_classes: int,
        dropout: float = 0.25
    ):
        super().__init__(in_dim=in_dim, num_classes=num_classes)
        
        # Simple classifier on top of max-pooled features
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
        # Max pooling across all instances (element-wise max)
        M, _ = H.max(dim=0)  # (D,)
        
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
    ) -> MaxMILAggregator:
        """Build MaxMIL aggregator."""
        return cls(
            in_dim=in_dim,
            num_classes=num_classes,
            dropout=dropout
        )

