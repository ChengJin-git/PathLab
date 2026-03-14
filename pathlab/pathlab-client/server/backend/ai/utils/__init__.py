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
from .patch_resize import (
    DEFAULT_NON_FM_PATCH_RESIZE,
    resolve_patch_resize_size,
    build_patch_classification_transform,
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
    "DEFAULT_NON_FM_PATCH_RESIZE",
    "resolve_patch_resize_size",
    "build_patch_classification_transform",
    # Scoped session utilities for preventing DB connection hogging
    "ScopedSession",
    "ScopedTrainingLogger",
]
