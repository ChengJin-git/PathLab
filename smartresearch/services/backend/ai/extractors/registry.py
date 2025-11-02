"""Registry for feature extractors."""
from __future__ import annotations

from typing import Dict, Type, List

from .base import BaseExtractor
from .resnet50 import ResNet50Extractor


# Global registry mapping extractor names to classes
_EXTRACTOR_REGISTRY: Dict[str, Type[BaseExtractor]] = {
    "resnet50": ResNet50Extractor,
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


def list_extractors() -> List[str]:
    """Return list of all registered extractor names."""
    return list(_EXTRACTOR_REGISTRY.keys())

