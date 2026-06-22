"""Attention-based MIL (Ilse et al. 2018) aggregator."""
from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn

from .base import BaseAggregator


class ABMILAggregator(BaseAggregator):
    """
    Attention-based Multiple Instance Learning (ABMIL) aggregator.
    
    Reference: Ilse et al. "Attention-based Deep Multiple Instance Learning" (ICML 2018)
    
    Given instance features H ∈ R^{N×D}, computes:
    1. Attention scores A ∈ R^N using gated attention mechanism
    2. Weighted aggregation M = Σ(A_i * H_i)
    3. Bag-level prediction from M
    """
    
    def __init__(
        self,
        in_dim: int,
        num_classes: int,
        hidden_dim: int = 256,
        dropout: float = 0.25
    ):
        super().__init__(in_dim=in_dim, num_classes=num_classes)
        
        # Gated attention mechanism
        self.attention_V = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Tanh(),
        )
        self.attention_U = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Sigmoid(),
        )
        self.attention_weights = nn.Linear(hidden_dim, 1)
        
        # Classifier
        self.classifier = nn.Linear(in_dim, num_classes)
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass.

        Args:
            H: Instance features of shape (N, D)

        Returns:
            logits: Bag-level logits of shape (1, C)
            attention: Normalized attention weights of shape (N,) (after softmax)
        """
        # Compute gated attention
        A_V = self.attention_V(H)  # (N, hidden_dim)
        A_U = self.attention_U(H)  # (N, hidden_dim)
        A_raw = self.attention_weights(self.dropout(A_V * A_U)).squeeze(-1)  # (N,)
        A = torch.softmax(A_raw, dim=0)  # Normalize attention over instances

        # Weighted aggregation
        M = torch.sum(A.unsqueeze(-1) * H, dim=0)  # (D,)

        # Classification
        logits = self.classifier(M)  # (C,)

        return logits.unsqueeze(0), A  # (1, C), (N,)

    def forward_with_raw_attention(
        self, H: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Forward pass that also returns raw attention scores (before softmax).

        Use this method when you need the original attention scores for analysis.

        Args:
            H: Instance features of shape (N, D)

        Returns:
            logits: Bag-level logits of shape (1, C)
            attention: Normalized attention weights of shape (N,) (after softmax)
            raw_attention: Raw attention scores of shape (N,) (before softmax)
        """
        # Compute gated attention
        A_V = self.attention_V(H)  # (N, hidden_dim)
        A_U = self.attention_U(H)  # (N, hidden_dim)
        A_raw = self.attention_weights(self.dropout(A_V * A_U)).squeeze(-1)  # (N,)
        A = torch.softmax(A_raw, dim=0)  # Normalize attention over instances

        # Weighted aggregation
        M = torch.sum(A.unsqueeze(-1) * H, dim=0)  # (D,)

        # Classification
        logits = self.classifier(M)  # (C,)

        return logits.unsqueeze(0), A, A_raw  # (1, C), (N,), (N,)
    
    @classmethod
    def build(
        cls,
        in_dim: int,
        num_classes: int,
        hidden_dim: int = 256,
        dropout: float = 0.25,
        **kwargs
    ) -> ABMILAggregator:
        """Build ABMIL aggregator."""
        return cls(
            in_dim=in_dim,
            num_classes=num_classes,
            hidden_dim=hidden_dim,
            dropout=dropout
        )

