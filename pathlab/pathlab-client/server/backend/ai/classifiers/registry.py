"""Registry for patch-level classifiers."""

from __future__ import annotations

from typing import Dict, Type, List, Optional, Any

from .base import BaseClassifier
from .linear import LinearProbeClassifier
from .mlp import MLPClassifier
from .attention import AttentionClassifier
from backend.ai.common.registry_base import BaseRegistry


class _ClassifierRegistry(BaseRegistry[BaseClassifier]):
    _registry: Dict[str, Type[BaseClassifier]] = {
        "linear": LinearProbeClassifier,
        "mlp": MLPClassifier,
        "attention": AttentionClassifier,
    }


def register_classifier(name: str, cls: Type[BaseClassifier]) -> None:
    key = name.strip().lower()
    _ClassifierRegistry.register(key, cls)


def get_classifier(
    name: str,
    num_classes: int,
    in_dim: Optional[int] = None,
    **kwargs: Any,
) -> BaseClassifier:
    key = name.strip().lower()
    classifier_cls = _ClassifierRegistry._get_class(key)
    return classifier_cls.build(num_classes=num_classes, in_dim=in_dim, **kwargs)


def list_classifiers() -> List[str]:
    return sorted(_ClassifierRegistry.list_names())
