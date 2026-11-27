"""
Attention Classifier
====================
Self-attention based head for feature-based patch classification.
Frozen FM features → Self-Attention → MLP → logits.

Uses a lightweight single-head self-attention to let the classifier
attend to different parts of the feature vector before classification.
"""
from __future__ import annotations
from typing import Any, Optional
import torch
import torch.nn as nn
from .base import BaseClassifier


class AttentionClassifier(BaseClassifier):
    """Attention-based head for patch-level classification.

    Expects feature vectors [B, D]. Applies a self-attention mechanism
    that splits the feature into pseudo-tokens, applies attention,
    then classifies with a linear head.
    """

    def __init__(self, num_classes: int, in_dim: Optional[int] = None, **kwargs: Any):
        super().__init__(num_classes=num_classes, in_dim=in_dim)
        if in_dim is None:
            raise ValueError("AttentionClassifier requires in_dim (feature dimension)")

        hidden_dim = int(kwargs.get("hidden_dim", 256))
        num_heads = int(kwargs.get("num_heads", 4))
        dropout_p = float(kwargs.get("dropout_p", 0.25))

        # Project to hidden_dim
        self.input_proj = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
        )

        # Self-attention (treat each sample's hidden_dim as a single token sequence)
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_dim,
            num_heads=num_heads,
            dropout=dropout_p,
            batch_first=True,
        )
        self.norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout_p)

        # Classification head
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout_p),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        # X: [B, D] -> project to [B, hidden_dim]
        h = self.input_proj(X)

        # Add sequence dimension: [B, hidden_dim] -> [B, 1, hidden_dim]
        h = h.unsqueeze(1)

        # Self-attention (single token attends to itself - acts as gated projection)
        attn_out, _ = self.attention(h, h, h)
        h = self.norm(h + attn_out)
        h = self.dropout(h)

        # Remove sequence dim and classify
        h = h.squeeze(1)  # [B, hidden_dim]
        return self.classifier(h)

    @classmethod
    def build(
        cls,
        num_classes: int,
        in_dim: Optional[int] = None,
        **kwargs: Any,
    ) -> AttentionClassifier:
        return cls(num_classes=num_classes, in_dim=in_dim, **kwargs)

