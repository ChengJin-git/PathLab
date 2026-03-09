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
        is_patch_file,
    )
"""
import logging
from typing import FrozenSet


logger = logging.getLogger(__name__)

# File size threshold for determining WSI vs Patch for .tif/.tiff files (32 MB)
SIZE_THRESHOLD: int = 32 * 1024 * 1024

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

# TIFF extensions that require slide inspection first, size fallback second
TIF_EXTENSIONS: FrozenSet[str] = frozenset({
    '.tif', '.tiff',
})


def _inspect_tiff_with_slide(file_path: str):
    """Return TIFF classification from slide inspection.

    Returns:
        False if TIFF looks like a WSI,
        True if TIFF looks like a patch,
        None if slide inspection failed and caller should use fallback heuristics.
    """
    try:
        from backend.common.slide_utils import load_slide, slide_has_wsi_characteristics

        slide = load_slide(file_path)
    except Exception as exc:
        logger.debug("TIFF slide inspection failed for %s, using size fallback: %s", file_path, exc)
        return None

    try:
        return not slide_has_wsi_characteristics(slide)
    except Exception as exc:
        logger.debug("TIFF feature inspection failed for %s, using size fallback: %s", file_path, exc)
        return None
    finally:
        try:
            slide.close()
        except Exception:
            pass


def is_patch_file(file_path: str, file_size: int = 0) -> bool:
    """
    Determine if a file is a patch (simple image file).

    Classification rules:
    - Files with PATCH_EXTENSIONS are always patches
    - .tif/.tiff files are inspected with ASlide/OpenSlide-compatible metadata first
    - If inspection is unavailable, .tif/.tiff files < SIZE_THRESHOLD (32MB) are patches
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

    # Check .tif/.tiff via slide inspection, then size fallback
    for ext in TIF_EXTENSIONS:
        if path_lower.endswith(ext):
            inspected = _inspect_tiff_with_slide(file_path)
            if inspected is not None:
                return inspected
            return file_size < SIZE_THRESHOLD

    return False

