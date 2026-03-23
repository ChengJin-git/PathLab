"""Registry for aggregators."""

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
from backend.ai.common.registry_base import BaseRegistry


class _AggregatorRegistry(BaseRegistry[BaseAggregator]):
    _registry: Dict[str, Type[BaseAggregator]] = {
        "abmil": ABMILAggregator,
        "meanmil": MeanMILAggregator,
        "maxmil": MaxMILAggregator,
        "dsmil": DSMILAggregator,
        "dtfdmil": DTFDAggregator,
        "clam_sb": CLAM_SB,
        "clam_mb": CLAM_MB,
        "transmil": TransMILAggregator,
    }


def register_aggregator(name: str, aggregator_class: Type[BaseAggregator]) -> None:
    _AggregatorRegistry.register(name, aggregator_class)


def get_aggregator(
    name: str, in_dim: int, num_classes: int, **kwargs
) -> BaseAggregator:
    cls = _AggregatorRegistry._get_class(name)
    return cls.build(in_dim=in_dim, num_classes=num_classes, **kwargs)


def list_aggregators() -> List[str]:
    return _AggregatorRegistry.list_names()
