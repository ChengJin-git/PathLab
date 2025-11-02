"""ResNet50 feature extractor (ImageNet pretrained)."""
from __future__ import annotations

import torch
import torch.nn as nn

from .base import BaseExtractor


def _build_resnet50(pretrained: bool = True):
    """Build ResNet50 with compatibility for both old and new torchvision API."""
    try:
        from torchvision.models import resnet50, ResNet50_Weights
        return resnet50(weights=ResNet50_Weights.IMAGENET1K_V2 if pretrained else None)
    except Exception:
        from torchvision.models import resnet50 as r50_old
        return r50_old(pretrained=pretrained)


class ResNet50Extractor(BaseExtractor):
    """
    ResNet50 feature extractor.
    Returns penultimate layer features (2048-dim) before the classification head.
    """
    
    def __init__(self, pretrained: bool = True):
        super().__init__()
        backbone = _build_resnet50(pretrained=pretrained)
        # Remove final FC layer, keep up to avgpool
        modules = list(backbone.children())[:-1]
        self.feature_extractor = nn.Sequential(*modules)
        self._output_dim = 2048
    
    @property
    def output_dim(self) -> int:
        return self._output_dim
    
    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.
        
        Args:
            x: Input tensor of shape (B, 3, H, W)
        
        Returns:
            Feature tensor of shape (B, 2048)
        """
        feats = self.feature_extractor(x)  # (B, 2048, 1, 1)
        feats = torch.flatten(feats, 1)    # (B, 2048)
        return feats
    
    @classmethod
    def build(cls, pretrained: bool = True, **kwargs) -> ResNet50Extractor:
        """Build ResNet50 extractor."""
        return cls(pretrained=pretrained)

