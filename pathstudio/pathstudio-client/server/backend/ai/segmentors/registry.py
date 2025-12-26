"""
Registry for segmentation models.
Use get_segmentor(name, ...) to instantiate a segmentor by name.
"""
from __future__ import annotations
from typing import Dict, Type, List, Any

from .base import BaseSegmentor
from .dinov3 import Dinov3Segmentor


_SEGMENTOR_REGISTRY: Dict[str, Type[BaseSegmentor]] = {
    'vit_large_patch16_dinov3': Dinov3Segmentor,
    'vit_huge_plus_patch16_dinov3': Dinov3Segmentor,
}


def register_segmentor(name: str, cls: Type[BaseSegmentor]) -> None:
    key = name.strip().lower()
    if key in _SEGMENTOR_REGISTRY:
        raise ValueError(f"Segmentor '{name}' already registered")
    _SEGMENTOR_REGISTRY[key] = cls


def get_segmentor(name: str, num_classes: int, **kwargs: Any) -> BaseSegmentor:
    key = name.strip().lower()
    if key not in _SEGMENTOR_REGISTRY:
        available = ", ".join(sorted(_SEGMENTOR_REGISTRY.keys())) or "<empty>"
        raise ValueError(f"Unknown segmentor: '{name}'. Available: {available}")
    cls = _SEGMENTOR_REGISTRY[key]
    return cls.build(num_classes=num_classes, **kwargs)


def list_segmentors() -> List[str]:
    return sorted(_SEGMENTOR_REGISTRY.keys())

