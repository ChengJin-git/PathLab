"""Adapters to connect research, training, and other subgraphs."""

from .report_to_training import (
    parse_model_config_from_report,
    model_config_to_training_params,
)

__all__ = [
    "parse_model_config_from_report",
    "model_config_to_training_params",
]
