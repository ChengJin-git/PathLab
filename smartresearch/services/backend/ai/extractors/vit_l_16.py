"""ViT-L/16 feature extractor (ImageNet pretrained)."""
from __future__ import annotations

import torch
import torch.nn as nn

from .base import BaseExtractor


def _build_vit_l_16(pretrained: bool = True):
    """Build ViT-L/16 with compatibility for both old and new torchvision API."""
    try:
        # Try new torchvision API (>= 0.13)
        from torchvision.models import vit_l_16, ViT_L_16_Weights
        if pretrained:
            return vit_l_16(weights=ViT_L_16_Weights.IMAGENET1K_V1)
        else:
            return vit_l_16(weights=None)
    except ImportError:
        # Fallback to timm if torchvision doesn't have ViT-L/16
        try:
            import timm
            model = timm.create_model('vit_large_patch16_224', pretrained=pretrained)
            return model
        except ImportError:
            raise ImportError(
                "Neither torchvision nor timm is available for ViT-L/16. "
                "Please install: pip install torchvision>=0.13 or pip install timm"
            )


class ViTL16Extractor(BaseExtractor):
    """
    ViT-L/16 (Vision Transformer Large, patch size 16) feature extractor.
    Returns features from the [CLS] token (1024-dim for ViT-L).

    Architecture:
    - Input: 224x224 RGB images
    - Patch size: 16x16
    - Hidden dimension: 1024
    - Number of layers: 24
    - Number of heads: 16
    - Output: 1024-dimensional feature vector

    Preprocessing:
    - Input size: 224x224
    - Normalization: ImageNet mean/std (default)
    """

    def __init__(self, pretrained: bool = True):
        super().__init__()
        self.model = _build_vit_l_16(pretrained=pretrained)

        # Remove classification head if it exists
        if hasattr(self.model, 'head'):
            # torchvision ViT structure
            self._output_dim = self.model.head.in_features
            self.model.head = nn.Identity()
        elif hasattr(self.model, 'heads'):
            # timm ViT structure
            if hasattr(self.model.heads, 'head'):
                self._output_dim = self.model.heads.head.in_features
                self.model.heads.head = nn.Identity()
            else:
                self._output_dim = 1024  # Default for ViT-L
                self.model.heads = nn.Identity()
        else:
            # Fallback
            self._output_dim = 1024

        self.model.eval()

    @property
    def output_dim(self) -> int:
        return self._output_dim

    @property
    def default_image_size(self) -> int:
        return 224
    
    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.
        
        Args:
            x: Input tensor of shape (B, 3, H, W)
               Expected input size is 224x224, but the model can handle other sizes
        
        Returns:
            Feature tensor of shape (B, 1024)
        """
        features = self.model(x)  # (B, 1024)
        return features
    
    @classmethod
    def build(cls, pretrained: bool = True, **kwargs) -> ViTL16Extractor:
        """Build ViT-L/16 extractor."""
        return cls(pretrained=pretrained)

