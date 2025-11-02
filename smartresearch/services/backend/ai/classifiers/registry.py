"""
Registry for patch-level classifiers.
Use get_classifier(name, ...) to instantiate a classifier by name.
"""
from __future__ import annotations
from typing import Dict, Type, List, Optional, Any

from .base import BaseClassifier


_CLASSIFIER_REGISTRY: Dict[str, Type[BaseClassifier]] = {}


def register_classifier(name: str, cls: Type[BaseClassifier]) -> None:
    key = name.strip().lower()
    if key in _CLASSIFIER_REGISTRY:
        raise ValueError(f"Classifier '{name}' already registered")
    _CLASSIFIER_REGISTRY[key] = cls


def get_classifier(
    name: str,
    num_classes: int,
    in_dim: Optional[int] = None,
    **kwargs: Any,
) -> BaseClassifier:
    key = name.strip().lower()
    if key not in _CLASSIFIER_REGISTRY:
        available = ", ".join(sorted(_CLASSIFIER_REGISTRY.keys())) or "<empty>"
        raise ValueError(f"Unknown classifier: '{name}'. Available: {available}")
    cls = _CLASSIFIER_REGISTRY[key]
    return cls.build(num_classes=num_classes, in_dim=in_dim, **kwargs)


def list_classifiers() -> List[str]:
    return sorted(_CLASSIFIER_REGISTRY.keys())

