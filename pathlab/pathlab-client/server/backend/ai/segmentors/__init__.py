"""Segmentation models package (patch- or WSI-level via tiling).

Add new segmentors by implementing BaseSegmentor and registering in registry.py.
"""
from .registry import get_segmentor, list_segmentors, register_segmentor

__all__ = [
    "get_segmentor",
    "list_segmentors",
    "register_segmentor",
]

