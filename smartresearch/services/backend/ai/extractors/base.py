"""Base class for feature extractors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple

import torch
import torch.nn as nn


class BaseExtractor(ABC, nn.Module):
    """
    Abstract base class for feature extractors.
    
    All extractors must implement:
    - output_dim: int property (feature dimension)
    - forward(x: Tensor) -> Tensor: extract features from input images
    """
    
    def __init__(self):
        super().__init__()
    
    @property
    @abstractmethod
    def output_dim(self) -> int:
        """Return the output feature dimension."""
        pass
    
    @abstractmethod
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.
        
        Args:
            x: Input tensor of shape (B, C, H, W)
        
        Returns:
            Feature tensor of shape (B, D) where D = output_dim
        """
        pass
    
    @classmethod
    @abstractmethod
    def build(cls, pretrained: bool = True, **kwargs) -> BaseExtractor:
        """
        Factory method to build the extractor.
        
        Args:
            pretrained: Whether to load pretrained weights
            **kwargs: Additional model-specific arguments
        
        Returns:
            Initialized extractor instance
        """
        pass

