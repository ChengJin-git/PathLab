"""
Linear Probe Classifier
========================
Single linear layer for feature-based patch classification.
Simplest classifier head: frozen FM features → Linear → logits.
"""
from __future__ import annotations
from typing import Any, Optional
import torch
import torch.nn as nn
from .base import BaseClassifier


class LinearProbeClassifier(BaseClassifier):
    """Linear probe for patch-level classification.

    Expects feature vectors [B, D] and maps them to logits [B, num_classes].
    Optionally applies dropout before the linear layer.
    """

    def __init__(self, num_classes: int, in_dim: Optional[int] = None, **kwargs: Any):
        super().__init__(num_classes=num_classes, in_dim=in_dim)
        if in_dim is None:
            raise ValueError("LinearProbeClassifier requires in_dim (feature dimension)")
        dropout_p = float(kwargs.get("dropout_p", 0.0))
        self.dropout = nn.Dropout(dropout_p) if dropout_p > 0 else nn.Identity()
        self.linear = nn.Linear(in_dim, num_classes)

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        X = self.dropout(X)
        return self.linear(X)

    @classmethod
    def build(
        cls,
        num_classes: int,
        in_dim: Optional[int] = None,
        **kwargs: Any,
    ) -> LinearProbeClassifier:
        return cls(num_classes=num_classes, in_dim=in_dim, **kwargs)

