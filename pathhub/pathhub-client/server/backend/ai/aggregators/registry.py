"""Registry for aggregators."""
from __future__ import annotations

from typing import Dict, Type, List

from .base import BaseAggregator
from .abmil import ABMILAggregator
from .meanmil import MeanMILAggregator
from .maxmil import MaxMILAggregator


# Global registry mapping aggregator names to classes
_AGGREGATOR_REGISTRY: Dict[str, Type[BaseAggregator]] = {
    "abmil": ABMILAggregator,
    "meanmil": MeanMILAggregator,
    "maxmil": MaxMILAggregator,
}


def register_aggregator(name: str, aggregator_class: Type[BaseAggregator]):
    """
    Register a new aggregator.
    
    Args:
        name: Unique identifier for the aggregator (e.g., "abmil", "transmil", "clam")
        aggregator_class: Class inheriting from BaseAggregator
    """
    if name in _AGGREGATOR_REGISTRY:
        raise ValueError(f"Aggregator '{name}' is already registered")
    _AGGREGATOR_REGISTRY[name] = aggregator_class


def get_aggregator(name: str, in_dim: int, num_classes: int, **kwargs) -> BaseAggregator:
    """
    Get an aggregator instance by name.
    
    Args:
        name: Aggregator identifier (e.g., "abmil")
        in_dim: Input feature dimension
        num_classes: Number of output classes
        **kwargs: Additional arguments passed to the aggregator's build() method
    
    Returns:
        Initialized aggregator instance
    
    Raises:
        ValueError: If aggregator name is not registered
    """
    if name not in _AGGREGATOR_REGISTRY:
        raise ValueError(
            f"Unknown aggregator: '{name}'. Available aggregators: {list(_AGGREGATOR_REGISTRY.keys())}"
        )
    aggregator_class = _AGGREGATOR_REGISTRY[name]
    return aggregator_class.build(in_dim=in_dim, num_classes=num_classes, **kwargs)


def list_aggregators() -> List[str]:
    """Return list of all registered aggregator names."""
    return list(_AGGREGATOR_REGISTRY.keys())

