"""PathLab aggregators — standalone copy for training sandbox."""
from .registry import get_aggregator, list_aggregators
from .abmil import ABMILAggregator
from .clam import CLAM_SB, CLAM_MB
from .transmil import TransMILAggregator
from .dsmil import DSMILAggregator
from .dtfdmil import DTFDAggregator
from .maxmil import MaxMILAggregator
from .meanmil import MeanMILAggregator
