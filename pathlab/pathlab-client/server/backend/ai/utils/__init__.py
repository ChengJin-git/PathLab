"""Utility modules for AI service."""

from .cam_utils import (
    PatchCAMResult,
    BaseCAMExtractor,
    ResNetCAMExtractor,
    TransformerCAMExtractor,
    TimmViTCAMExtractor,
    get_cam_extractor,
    is_cnn_extractor,
    is_vit_extractor,
    get_cam_spatial_size,
)

from .scoped_session import (
    ScopedSession,
    ScopedTrainingLogger,
)

__all__ = [
    "PatchCAMResult",
    "BaseCAMExtractor",
    "ResNetCAMExtractor",
    "TransformerCAMExtractor",
    "TimmViTCAMExtractor",
    "get_cam_extractor",
    "is_cnn_extractor",
    "is_vit_extractor",
    "get_cam_spatial_size",
    # Scoped session utilities for preventing DB connection hogging
    "ScopedSession",
    "ScopedTrainingLogger",
]
