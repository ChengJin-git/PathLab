"""
Base interfaces for patch-level classifiers.
A classifier maps an input (image or features) to patch-level class logits.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Any

import torch
import torch.nn as nn


class BaseClassifier(ABC, nn.Module):
    """Abstract base class for patch-level classifiers.

    Notes
    -----
    - Input can be either raw images [B, 3, H, W] or precomputed features [B, D].
    - Implementations should clearly document their expected input format.
    - The forward() must return logits of shape [B, num_classes].
    """

    def __init__(self, num_classes: int, in_dim: Optional[int] = None) -> None:
        super().__init__()
        self.num_classes = int(num_classes)
        self.in_dim = int(in_dim) if in_dim is not None else None

    @abstractmethod
    def forward(self, X: torch.Tensor) -> torch.Tensor:
        """Compute logits for a batch of patches.

        Parameters
        ----------
        X : torch.Tensor
            Either images [B, 3, H, W] or features [B, D].
        Returns
        -------
        torch.Tensor
            Logits tensor of shape [B, num_classes].
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def build(
        cls,
        num_classes: int,
        in_dim: Optional[int] = None,
        **kwargs: Any,
    ) -> "BaseClassifier":
        """Factory method to construct the classifier instance.

        This is used by the registry to create models by name.
        """
        raise NotImplementedError

