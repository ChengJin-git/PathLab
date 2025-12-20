"""Base class for feature extractors."""
from __future__ import annotations

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

