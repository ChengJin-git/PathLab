"""Registry for feature extractors."""
from __future__ import annotations

from typing import Dict, Type, List, Callable

from .base import BaseExtractor
from .resnet50 import ResNet50Extractor
from .vit_l_16 import ViTL16Extractor
from .transforms import get_default_transforms


# Global registry mapping extractor names to classes
_EXTRACTOR_REGISTRY: Dict[str, Type[BaseExtractor]] = {
    "resnet50": ResNet50Extractor,
    "vit_l_16": ViTL16Extractor,
}


def register_extractor(name: str, extractor_class: Type[BaseExtractor]):
    """
    Register a new feature extractor.

    Args:
        name: Unique identifier for the extractor (e.g., "resnet50", "uni", "conch")
        extractor_class: Class inheriting from BaseExtractor
    """
    if name in _EXTRACTOR_REGISTRY:
        raise ValueError(f"Extractor '{name}' is already registered")
    _EXTRACTOR_REGISTRY[name] = extractor_class


def get_extractor(name: str, pretrained: bool = True, **kwargs) -> BaseExtractor:
    """
    Get an extractor instance by name.

    Args:
        name: Extractor identifier (e.g., "resnet50")
        pretrained: Whether to load pretrained weights
        **kwargs: Additional arguments passed to the extractor's build() method

    Returns:
        Initialized extractor instance

    Raises:
        ValueError: If extractor name is not registered
    """
    if name not in _EXTRACTOR_REGISTRY:
        raise ValueError(
            f"Unknown extractor: '{name}'. Available extractors: {list(_EXTRACTOR_REGISTRY.keys())}"
        )
    extractor_class = _EXTRACTOR_REGISTRY[name]
    return extractor_class.build(pretrained=pretrained, **kwargs)


def get_extractor_transforms(
    name: str,
    mode: str = "eval",
    pretrained: bool = True,
    **kwargs
) -> Callable:
    """
    Get preprocessing transforms for an extractor without loading the full model.

    This is useful when you need the transforms but want to avoid loading
    model weights (e.g., for data preprocessing before training).

    Args:
        name: Extractor identifier (e.g., "resnet50")
        mode: "train" for training with augmentation, "eval" for inference
        pretrained: Whether to use pretrained model configuration
        **kwargs: Additional arguments

    Returns:
        Transform callable for preprocessing images

    Example:
        transform = get_extractor_transforms("resnet50", mode="eval")
        processed_image = transform(pil_image)
    """
    # Build extractor to get its transforms
    # Note: This does load the model, but for most extractors the transforms
    # are defined based on class properties, so this is acceptable.
    # For heavy models, consider caching or using class-level transform methods.
    extractor = get_extractor(name, pretrained=pretrained, **kwargs)
    return extractor.get_transforms(mode=mode)


def list_extractors() -> List[str]:
    """Return list of all registered extractor names."""
    return list(_EXTRACTOR_REGISTRY.keys())

