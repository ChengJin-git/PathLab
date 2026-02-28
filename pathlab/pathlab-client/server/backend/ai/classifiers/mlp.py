"""
MLP Classifier
==============
Multi-layer perceptron head for feature-based patch classification.
Frozen FM features → MLP (hidden layers + ReLU + Dropout) → logits.
"""
from __future__ import annotations
from typing import Any, Optional, List
import torch
import torch.nn as nn
from .base import BaseClassifier


class MLPClassifier(BaseClassifier):
    """MLP head for patch-level classification.

    Expects feature vectors [B, D] and maps them to logits [B, num_classes]
    through one or more hidden layers with ReLU activation and dropout.
    """

    def __init__(self, num_classes: int, in_dim: Optional[int] = None, **kwargs: Any):
        super().__init__(num_classes=num_classes, in_dim=in_dim)
        if in_dim is None:
            raise ValueError("MLPClassifier requires in_dim (feature dimension)")

        hidden_dims: List[int] = kwargs.get("hidden_dims", [512])
        if isinstance(hidden_dims, int):
            hidden_dims = [hidden_dims]
        dropout_p = float(kwargs.get("dropout_p", 0.25))

        layers: list[nn.Module] = []
        prev_dim = in_dim
        for h_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, h_dim),
                nn.ReLU(inplace=True),
                nn.Dropout(dropout_p),
            ])
            prev_dim = h_dim
        layers.append(nn.Linear(prev_dim, num_classes))

        self.net = nn.Sequential(*layers)

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        return self.net(X)

    @classmethod
    def build(
        cls,
        num_classes: int,
        in_dim: Optional[int] = None,
        **kwargs: Any,
    ) -> MLPClassifier:
        return cls(num_classes=num_classes, in_dim=in_dim, **kwargs)

