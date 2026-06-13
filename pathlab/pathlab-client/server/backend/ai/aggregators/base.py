"""Base class for aggregators (WSI-level models)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, Optional

import torch
import torch.nn as nn


class BaseAggregator(ABC, nn.Module):
    """
    Abstract base class for WSI-level aggregators.
    
    Aggregators take instance-level features (patches) and produce bag-level predictions (WSI).
    
    All aggregators must implement:
    - forward(H: Tensor) -> Tuple[Tensor, Optional[Tensor]]: 
        Takes features H of shape (N, D) and returns (logits, attention_weights)
    """
    
    def __init__(self, in_dim: int, num_classes: int):
        super().__init__()
        self.in_dim = in_dim
        self.num_classes = num_classes
        
    def default_criterion(self):
        """
        Default loss function for MIL tasks.
        """
        return nn.CrossEntropyLoss()
    
    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Run a single training step.
        
        Args:
            features: Instance features of shape (N, D)
            labels: Bag-level labels of shape (1,) or (B,)
        
        Returns:
            loss: Computed loss
            logits: Bag-level logits of shape (1, C)
        """
        logits, _ = self.forward(features)
        loss = criterion(logits, labels)
        return loss, logits
    
    @abstractmethod
    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Aggregate instance features to produce bag-level prediction.
        
        Args:
            H: Instance features of shape (N, D) where N = number of patches, D = feature dim
        
        Returns:
            logits: Bag-level logits of shape (1, C) where C = num_classes
            attention: Optional attention weights of shape (N,) or None
        """
        pass
    
    @classmethod
    @abstractmethod
    def build(cls, in_dim: int, num_classes: int, **kwargs) -> BaseAggregator:
        """
        Factory method to build the aggregator.
        
        Args:
            in_dim: Input feature dimension
            num_classes: Number of output classes
            **kwargs: Additional model-specific arguments
        
        Returns:
            Initialized aggregator instance
        """
        pass

