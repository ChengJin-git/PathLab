"""Base class for feature extractors."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Tuple, Callable

import torch
import torch.nn as nn

from .transforms import get_default_transforms, IMAGENET_MEAN, IMAGENET_STD


class BaseExtractor(ABC, nn.Module):
    """
    Abstract base class for feature extractors.

    All extractors must implement:
    - output_dim: int property (feature dimension)
    - forward(x: Tensor) -> Tensor: extract features from input images

    Optional overrides for preprocessing:
    - default_image_size: int property (default: 224)
    - get_transforms(mode): Get preprocessing transforms
    """

    def __init__(self):
        super().__init__()

    @property
    @abstractmethod
    def output_dim(self) -> int:
        """Return the output feature dimension."""
        pass

    @property
    def default_image_size(self) -> int:
        """
        Return the default input image size for this model.

        Override this in subclasses if the model expects a different size.
        Common sizes: 224 (ResNet, ViT), 256 (some EfficientNets), 384 (ViT-L/14)
        """
        return 224

    @property
    def normalization_mean(self) -> Tuple[float, float, float]:
        """
        Return the normalization mean for this model.

        Override this in subclasses for models using non-ImageNet normalization
        (e.g., CLIP-based models use different normalization).
        """
        return IMAGENET_MEAN

    @property
    def normalization_std(self) -> Tuple[float, float, float]:
        """
        Return the normalization std for this model.

        Override this in subclasses for models using non-ImageNet normalization.
        """
        return IMAGENET_STD

    def get_transforms(self, mode: str = "eval") -> Callable:
        """
        Get preprocessing transforms for this extractor.

        This method provides a unified interface for getting model-specific
        preprocessing. Override this in subclasses if the model requires
        special preprocessing (e.g., different normalization, specific augmentations).

        Args:
            mode: "train" for training with data augmentation,
                  "eval" for inference without augmentation

        Returns:
            Callable transform that converts PIL Image to normalized Tensor

        Example override for CLIP-based models:
            def get_transforms(self, mode: str = "eval") -> Callable:
                return get_default_transforms(
                    image_size=self.default_image_size,
                    mode=mode,
                    mean=OPENAI_CLIP_MEAN,
                    std=OPENAI_CLIP_STD,
                )
        """
        return get_default_transforms(
            image_size=self.default_image_size,
            mode=mode,
            mean=self.normalization_mean,
            std=self.normalization_std,
        )

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

    @property
    def supports_spatial(self) -> bool:
        """Whether this extractor supports spatial feature extraction for segmentation.

        Returns True if the extractor can produce unpooled spatial token maps
        via ``forward_spatial()``.  The default implementation checks for a
        ``backbone`` attribute with either timm-style ``forward_features``,
        DINOv2-dict ``forward_features``, or HuggingFace ViT ``embeddings``/
        ``encoder`` attributes.
        """
        if not hasattr(self, "backbone"):
            return False
        bb = self.backbone
        if hasattr(bb, "forward_features"):
            return True
        if hasattr(bb, "embeddings") and hasattr(bb, "encoder"):
            return True
        return False

    def forward_spatial(self, x: torch.Tensor) -> torch.Tensor:
        """Extract spatial feature map for dense prediction (segmentation).

        Returns a feature map of shape ``(B, D, H', W')`` where
        ``H' * W'`` equals the number of spatial patch tokens.

        The default implementation auto-detects three backbone patterns:

        1. **timm ViT** – calls ``backbone.forward_features(x)`` and strips
           prefix tokens (CLS + optional register tokens) using
           ``backbone.num_prefix_tokens``.
        2. **DINOv2 (dict output)** – when ``forward_features`` returns a dict
           with key ``"x_norm_patchtokens"``.
        3. **HuggingFace ViTModel / AutoModel** – calls
           ``backbone(pixel_values=x).last_hidden_state`` and strips the CLS
           token at index 0.

        Override this method in subclasses that do not match any of the above
        patterns (e.g., CONCH v1.5 which wraps a custom ``trunk``).

        Raises:
            NotImplementedError: If the backbone type cannot be auto-detected.
        """
        if not hasattr(self, "backbone"):
            raise NotImplementedError(
                f"{self.__class__.__name__} does not have a 'backbone' attribute. "
                "Override forward_spatial() to enable FM-powered segmentation."
            )

        bb = self.backbone

        # --- Pattern 1 & 2: timm / DINOv2 with forward_features ----------
        if hasattr(bb, "forward_features"):
            out = bb.forward_features(x)

            if isinstance(out, dict):
                # DINOv2-style dict output
                patch_tokens = out["x_norm_patchtokens"]  # (B, N, D)
            else:
                # timm-style tensor output (B, N_total, D)
                num_prefix = getattr(bb, "num_prefix_tokens", 1)
                patch_tokens = out[:, num_prefix:]  # (B, N, D)

            B, N, D = patch_tokens.shape
            H = W = int(math.isqrt(N))
            assert H * W == N, (
                f"Cannot reshape {N} patch tokens into a square grid. "
                f"Got H={H}, W={W} (H*W={H * W})."
            )
            return patch_tokens.permute(0, 2, 1).reshape(B, D, H, W)

        # --- Pattern 3: HuggingFace ViTModel / Dinov2Model ----------------
        if hasattr(bb, "embeddings") and hasattr(bb, "encoder"):
            outputs = bb(pixel_values=x)
            tokens = outputs.last_hidden_state
            patch_tokens = tokens[:, 1:]  # strip CLS token
            B, N, D = patch_tokens.shape
            H = W = int(math.isqrt(N))
            assert H * W == N, (
                f"Cannot reshape {N} patch tokens into a square grid. "
                f"Got H={H}, W={W} (H*W={H * W})."
            )
            return patch_tokens.permute(0, 2, 1).reshape(B, D, H, W)

        raise NotImplementedError(
            f"{self.__class__.__name__} backbone type not auto-detected. "
            "Override forward_spatial() to enable FM-powered segmentation."
        )

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

