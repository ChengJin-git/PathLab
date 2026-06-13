"""Registry for aggregators — standalone version for training sandbox."""
from __future__ import annotations

from typing import Dict, Type, List

from .base import BaseAggregator
from .abmil import ABMILAggregator
from .meanmil import MeanMILAggregator
from .maxmil import MaxMILAggregator
from .dsmil import DSMILAggregator
from .dtfdmil import DTFDAggregator
from .clam import CLAM_SB, CLAM_MB
from .transmil import TransMILAggregator


_REGISTRY: Dict[str, Type[BaseAggregator]] = {
    "abmil": ABMILAggregator,
    "meanmil": MeanMILAggregator,
    "maxmil": MaxMILAggregator,
    "dsmil": DSMILAggregator,
    "dtfdmil": DTFDAggregator,
    "clam_sb": CLAM_SB,
    "clam_mb": CLAM_MB,
    "transmil": TransMILAggregator,
}


def get_aggregator(name: str, in_dim: int, num_classes: int, **kwargs) -> BaseAggregator:
    """Build an aggregator by name."""
    name_lower = name.lower().replace("-", "_")
    if name_lower not in _REGISTRY:
        raise KeyError(f"Unknown aggregator: {name!r}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name_lower].build(in_dim=in_dim, num_classes=num_classes, **kwargs)


def list_aggregators() -> List[str]:
    """List all available aggregator names."""
    return list(_REGISTRY.keys())
