"""Deterministic empirical figure generators for the paper agent."""

from __future__ import annotations

from .registry import generate_figure, supported_generators
from .types import FigureOutput

__all__ = ["FigureOutput", "generate_figure", "supported_generators"]
