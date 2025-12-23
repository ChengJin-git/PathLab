"""
Base interfaces for segmentation models (patch or WSI-level via tiling).
A segmentor maps an input image (or tile) to per-pixel class logits.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

import torch
import torch.nn as nn


class BaseSegmentor(ABC, nn.Module):
    """Abstract base class for segmentation networks.

    forward(x) should return logits with shape [B, num_classes, H, W].
    """

    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.num_classes = int(num_classes)

    @abstractmethod
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Compute segmentation logits.

        Parameters
        ----------
        x : torch.Tensor
            Input images [B, 3, H, W]
        Returns
        -------
        torch.Tensor
            Logits [B, num_classes, H, W]
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def build(cls, num_classes: int, **kwargs: Any) -> "BaseSegmentor":
        """Factory method to construct the segmentor instance."""
        raise NotImplementedError

