"""Attention-based MIL aggregator used by WSI tasks."""
from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn

from .base import BaseAggregator


class ABMILAggregator(BaseAggregator):
    """
    Simple attention MIL aggregator aligned with the user's survival baseline.

    Structure:
    1. Project instance features from ``in_dim`` to a fixed hidden size.
    2. Apply configurable activation (default: ReLU).
    3. Compute single-branch attention weights over instances.
    4. Aggregate to a bag embedding and classify with ``Linear(hidden_dim, num_classes)``.
    """

    def __init__(
        self,
        in_dim: int,
        num_classes: int,
        hidden_dim: int = 512,
        attention_dim: int = 128,
        dropout: float = 0.0,
        act: str = "relu",
    ):
        super().__init__(in_dim=in_dim, num_classes=num_classes)

        act_name = act.lower().strip()
        if act_name == "gelu":
            activation: nn.Module = nn.GELU()
        else:
            activation = nn.ReLU()

        feature_layers = [nn.Linear(in_dim, hidden_dim), activation]
        if dropout and dropout > 0:
            feature_layers.append(nn.Dropout(dropout))
        self.feature = nn.Sequential(*feature_layers)

        self.attention = nn.Sequential(
            nn.Linear(hidden_dim, attention_dim),
            nn.Tanh(),
            nn.Linear(attention_dim, 1),
        )
        self.classifier = nn.Linear(hidden_dim, num_classes)

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass.

        Args:
            H: Instance features of shape (N, D)

        Returns:
            logits: Bag-level logits of shape (1, C)
            attention: Normalized attention weights of shape (N,) (after softmax)
        """
        features = self.feature(H)  # (N, hidden_dim)
        attention_raw = self.attention(features).transpose(0, 1)  # (1, N)
        attention = torch.softmax(attention_raw, dim=-1)  # (1, N)
        bag_embedding = torch.mm(attention, features)  # (1, hidden_dim)
        logits = self.classifier(bag_embedding)  # (1, C)

        return logits, attention.squeeze(0)  # (1, C), (N,)

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
        features = self.feature(H)  # (N, hidden_dim)
        attention_raw = self.attention(features).transpose(0, 1)  # (1, N)
        attention = torch.softmax(attention_raw, dim=-1)  # (1, N)
        bag_embedding = torch.mm(attention, features)  # (1, hidden_dim)
        logits = self.classifier(bag_embedding)  # (1, C)

        return logits, attention.squeeze(0), attention_raw.squeeze(0)  # (1, C), (N,), (N,)
    
    @classmethod
    def build(
        cls,
        in_dim: int,
        num_classes: int,
        hidden_dim: int = 512,
        attention_dim: int = 128,
        dropout: float = 0.0,
        act: str = "relu",
        **kwargs
    ) -> ABMILAggregator:
        """Build ABMIL aggregator."""
        _ = kwargs
        return cls(
            in_dim=in_dim,
            num_classes=num_classes,
            hidden_dim=hidden_dim,
            attention_dim=attention_dim,
            dropout=dropout,
            act=act,
        )

