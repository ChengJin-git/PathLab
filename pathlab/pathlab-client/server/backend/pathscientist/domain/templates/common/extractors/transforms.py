"""
Preprocessing transforms for feature extractors.

This module provides:
1. Default ImageNet-style transforms (used by ResNet, ViT, etc.)
2. Train/eval mode support for data augmentation
3. A unified interface for extractor-specific preprocessing

Usage:
    from .transforms import get_default_transforms, IMAGENET_MEAN, IMAGENET_STD
    
    # Get default transforms
    transform = get_default_transforms(image_size=224, mode="eval")
    
    # In custom extractor, override get_transforms() to use model-specific preprocessing
"""
from __future__ import annotations

from typing import Callable, List, Tuple, Optional, Any

# Lazy import to avoid overhead
_T = None

def _get_T():
    """Lazy import torchvision.transforms."""
    global _T
    if _T is None:
        import torchvision.transforms as T
        _T = T
    return _T


# Standard ImageNet normalization parameters
IMAGENET_MEAN: Tuple[float, float, float] = (0.485, 0.456, 0.406)
IMAGENET_STD: Tuple[float, float, float] = (0.229, 0.224, 0.225)


def get_default_transforms(
    image_size: int = 224,
    mode: str = "eval",
    mean: Tuple[float, float, float] = IMAGENET_MEAN,
    std: Tuple[float, float, float] = IMAGENET_STD,
) -> Callable[..., Any]:
    """
    Get default preprocessing transforms.
    
    Args:
        image_size: Target image size (height and width)
        mode: "train" for training with augmentation, "eval" for inference
        mean: Normalization mean (default: ImageNet)
        std: Normalization std (default: ImageNet)
    
    Returns:
        Composed transform callable
    """
    T = _get_T()
    
    if mode == "train":
        # Training transforms with data augmentation
        return T.Compose([
            T.RandomHorizontalFlip(p=0.5),
            T.RandomVerticalFlip(p=0.5),
            T.RandomApply([T.RandomRotation(degrees=90)], p=0.5),
            T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1),
            T.Resize((image_size, image_size)),
            T.ToTensor(),
            T.Normalize(mean=list(mean), std=list(std)),
        ])
    else:
        # Eval/inference transforms (no augmentation)
        return T.Compose([
            T.Resize((image_size, image_size)),
            T.ToTensor(),
            T.Normalize(mean=list(mean), std=list(std)),
        ])


def get_pathology_transforms(
    image_size: int = 224,
    mode: str = "eval",
    mean: Tuple[float, float, float] = IMAGENET_MEAN,
    std: Tuple[float, float, float] = IMAGENET_STD,
) -> Callable[..., Any]:
    """
    Get transforms optimized for pathology images.
    
    Includes stronger augmentations suitable for H&E stained images.
    
    Args:
        image_size: Target image size
        mode: "train" or "eval"
        mean: Normalization mean
        std: Normalization std
    
    Returns:
        Composed transform callable
    """
    T = _get_T()
    
    if mode == "train":
        return T.Compose([
            T.RandomHorizontalFlip(p=0.5),
            T.RandomVerticalFlip(p=0.5),
            T.RandomApply([
                T.RandomChoice([
                    T.RandomRotation(degrees=[90, 90]),
                    T.RandomRotation(degrees=[180, 180]),
                    T.RandomRotation(degrees=[270, 270]),
                ])
            ], p=0.75),
            T.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.05),
            T.RandomApply([T.GaussianBlur(kernel_size=3)], p=0.1),
            T.Resize((image_size, image_size)),
            T.ToTensor(),
            T.Normalize(mean=list(mean), std=list(std)),
        ])
    else:
        return T.Compose([
            T.Resize((image_size, image_size)),
            T.ToTensor(),
            T.Normalize(mean=list(mean), std=list(std)),
        ])


# Commonly used normalization parameters for different models
OPENAI_CLIP_MEAN: Tuple[float, float, float] = (0.48145466, 0.4578275, 0.40821073)
OPENAI_CLIP_STD: Tuple[float, float, float] = (0.26862954, 0.26130258, 0.27577711)

# UNI uses ImageNet normalization
UNI_MEAN: Tuple[float, float, float] = IMAGENET_MEAN
UNI_STD: Tuple[float, float, float] = IMAGENET_STD

# CONCH uses CLIP normalization
CONCH_MEAN: Tuple[float, float, float] = OPENAI_CLIP_MEAN
CONCH_STD: Tuple[float, float, float] = OPENAI_CLIP_STD
