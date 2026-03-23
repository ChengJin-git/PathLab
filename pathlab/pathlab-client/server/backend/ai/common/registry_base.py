"""Generic base for model component registries (aggregators, classifiers, etc.)."""

from __future__ import annotations

import logging
from typing import Dict, Generic, List, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseRegistry(Generic[T]):
    """Dict-backed registry with duplicate-safe register and list operations.

    Subclasses provide a pre-populated ``_registry`` class variable (a new dict
    per subclass) and override ``_build_instance`` with their specific signature.

    Example::

        class _AggRegistry(BaseRegistry[BaseAggregator]):
            _registry: Dict[str, Type[BaseAggregator]] = {...}
    """

    _registry: Dict[str, Type[T]] = {}  # Each subclass MUST define its own dict

    @classmethod
    def register(cls, name: str, component_class: Type[T]) -> None:
        if name in cls._registry:
            raise ValueError(f"'{name}' is already registered in {cls.__name__}")
        cls._registry[name] = component_class
        logger.debug("Registered '%s' in %s", name, cls.__name__)

    @classmethod
    def list_names(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def _get_class(cls, name: str) -> Type[T]:
        if name not in cls._registry:
            available = ", ".join(cls.list_names()) or "<empty>"
            raise ValueError(
                f"Unknown component '{name}' in {cls.__name__}. Available: {available}"
            )
        return cls._registry[name]
