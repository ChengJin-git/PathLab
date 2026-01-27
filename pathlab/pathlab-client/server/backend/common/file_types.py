"""
File type classification constants for PathLab.

This module provides centralized constants for determining whether a file
is a WSI (Whole Slide Image) or a Patch (simple image file).

Usage:
    from backend.common.file_types import (
        WSI_EXTENSIONS,
        PATCH_EXTENSIONS,
        TIF_EXTENSIONS,
        SIZE_THRESHOLD,
        is_wsi_file,
        is_patch_file,
    )
"""
from typing import FrozenSet

# File size threshold for determining WSI vs Patch for .tif/.tiff files (100 MB)
SIZE_THRESHOLD: int = 100 * 1024 * 1024

# WSI file extensions (excluding .tif/.tiff which need size check)
# These are always treated as WSI files regardless of size
WSI_EXTENSIONS: FrozenSet[str] = frozenset({
    '.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif',
    '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap',
    '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax',
    '.dyj', '.dyqx', '.ibl', '.zyp',  # Additional WSI formats
})

# Patch/image file extensions (excluding .tif/.tiff which need size check)
# These are always treated as patch files regardless of size
PATCH_EXTENSIONS: FrozenSet[str] = frozenset({
    '.jpg', '.jpeg', '.png', '.bmp',
})

# TIFF extensions that require size-based classification
TIF_EXTENSIONS: FrozenSet[str] = frozenset({
    '.tif', '.tiff',
})


def is_wsi_file(file_path: str, file_size: int = 0) -> bool:
    """
    Determine if a file is a WSI (Whole Slide Image).

    Classification rules:
    - Files with WSI_EXTENSIONS are always WSI
    - .tif/.tiff files >= SIZE_THRESHOLD (100MB) are WSI
    - Everything else is not WSI

    Args:
        file_path: Path to the file (only extension is used)
        file_size: File size in bytes (only needed for .tif/.tiff files)

    Returns:
        True if the file is a WSI, False otherwise
    """
    path_lower = file_path.lower()

    # Check explicit WSI extensions
    for ext in WSI_EXTENSIONS:
        if path_lower.endswith(ext):
            return True

    # Check .tif/.tiff with size threshold
    for ext in TIF_EXTENSIONS:
        if path_lower.endswith(ext):
            return file_size >= SIZE_THRESHOLD

    return False


def is_patch_file(file_path: str, file_size: int = 0) -> bool:
    """
    Determine if a file is a patch (simple image file).

    Classification rules:
    - Files with PATCH_EXTENSIONS are always patches
    - .tif/.tiff files < SIZE_THRESHOLD (100MB) are patches
    - Everything else is not a patch

    Args:
        file_path: Path to the file (only extension is used)
        file_size: File size in bytes (only needed for .tif/.tiff files)

    Returns:
        True if the file is a patch, False otherwise
    """
    path_lower = file_path.lower()

    # Check explicit patch extensions
    for ext in PATCH_EXTENSIONS:
        if path_lower.endswith(ext):
            return True

    # Check .tif/.tiff with size threshold
    for ext in TIF_EXTENSIONS:
        if path_lower.endswith(ext):
            return file_size < SIZE_THRESHOLD

    return False

