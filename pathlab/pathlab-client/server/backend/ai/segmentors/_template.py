"""
Segmentor Template
==================

This is a template for creating new segmentation models (patch-level or WSI via tiling).
Copy this file and rename it to your segmentor name (e.g., unet.py, deeplabv3.py).

Steps to add a new segmentor:
1. Copy this file (e.g., to unet.py)
2. Rename the class (e.g., UNetSegmentor)
3. Implement __init__/forward returning logits [B, num_classes, H, W]
4. Implement build class method
5. Register in registry.py
"""
from __future__ import annotations
from typing import Any
import torch
import torch.nn as nn
from .base import BaseSegmentor


class TemplateSegmentor(BaseSegmentor):
    """Template segmentation network.

    Replace this with your network architecture description.
    Expected output logits shape: [B, num_classes, H, W].
    """

    def __init__(self, num_classes: int, **kwargs: Any):
        super().__init__(num_classes=num_classes)

        # TODO: Build your encoder/decoder here
        # Example: simple UNet-like skeleton
        # self.encoder = ...
        # self.decoder = ...
        # self.head = nn.Conv2d(decoder_out_channels, num_classes, kernel_size=1)

        self.net = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, num_classes, 1),
        )  # Minimal stub; replace with real network

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: input images [B, 3, H, W]
        Returns:
            logits: [B, num_classes, H, W]
        """
        return self.net(x)

    @classmethod
    def build(cls, num_classes: int, **kwargs: Any) -> TemplateSegmentor:
        return cls(num_classes=num_classes, **kwargs)


# ==============================================================================
# CHECKLIST BEFORE REGISTERING
# ==============================================================================
# [ ] Renamed class from TemplateSegmentor to YourSegmentor
# [ ] Implemented __init__ & forward()
# [ ] Verified logits shape is [B, num_classes, H, W]
# [ ] Implemented build() class method
# [ ] Registered in registry.py
# [ ] Tested with dummy data
#       x = torch.randn(2, 3, 256, 256); model(x)

# ==============================================================================
# COMMON PITFALLS
# ==============================================================================
# 1) Returning probabilities instead of logits; keep logits for loss functions like CrossEntropyLoss
# 2) Mismatch between decoder output channels and num_classes
# 3) Not handling variable input sizes; prefer padding='same' or adaptive pooling
# 4) Forgetting to switch to eval() mode during inference

