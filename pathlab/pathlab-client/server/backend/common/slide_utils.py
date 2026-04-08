"""
Shared slide loading utilities for PathLab.

Provides centralized color correction configuration and slide loading
to avoid code duplication across preprocessing and AI modules.

Usage:
    from backend.common.slide_utils import (
        configure_color_correction,
        load_slide,
        slide_has_wsi_characteristics,
    )
"""

from importlib import import_module
import logging
from typing import Any

Config = import_module("backend.common.config").Config

logger = logging.getLogger(__name__)


def slide_has_wsi_characteristics(slide: Any) -> bool:
    """Return whether an opened ASlide/OpenSlide-compatible object looks like a WSI."""
    try:
        level_count = getattr(slide, "level_count", None)
        if isinstance(level_count, int) and level_count > 1:
            return True
    except Exception:
        pass

    try:
        level_dimensions = getattr(slide, "level_dimensions", None)
        if level_dimensions is not None and len(level_dimensions) > 1:
            return True
    except Exception:
        pass

    try:
        level_downsamples = getattr(slide, "level_downsamples", None)
        if level_downsamples and any(float(ds) > 1.0 for ds in level_downsamples[1:]):
            return True
    except Exception:
        pass

    try:
        props = getattr(slide, "properties", None)
    except Exception:
        props = None

    if props is not None and hasattr(props, "get"):
        try:
            vendor = str(props.get("openslide.vendor") or "").strip()
            if vendor and vendor.lower() != "unknown":
                return True
        except Exception:
            pass

        for key in ("openslide.objective-power", "openslide.mpp-x", "openslide.mpp-y"):
            try:
                value = str(props.get(key) or "").strip()
                if value:
                    return True
            except Exception:
                pass

    try:
        mpp = getattr(slide, "mpp", None)
        if isinstance(mpp, (int, float)) and mpp > 0:
            return True
        if isinstance(mpp, tuple) and any(float(v) > 0 for v in mpp[:2]):
            return True
    except Exception:
        pass

    try:
        associated_images = getattr(slide, "associated_images", None)
        if associated_images and len(associated_images) > 0:
            return True
    except Exception:
        pass

    return False


def configure_color_correction(slide, apply: bool = True, style: str = "Real") -> None:
    """
    Apply color correction for supported Aslide formats.

    Supported formats are defined in Config.COLOR_CORRECTION_FORMATS.

    Args:
        slide: An Aslide Slide instance
        apply: Whether to apply color correction (default True)
        style: Color correction style (default "Real")
    """
    try:
        if not hasattr(slide, "format"):
            return

        # Case-insensitive check against configured formats
        slide_format_lower = slide.format.lower() if slide.format else ""
        if (
            slide_format_lower in Config.COLOR_CORRECTION_FORMATS
            and hasattr(slide, "_osr")
            and hasattr(slide._osr, "apply_color_correction")
        ):
            slide._osr.apply_color_correction(apply, style)
            logger.info(f"Applied color correction for {slide.format} slide")
    except Exception as e:
        logger.warning(f"Failed to apply color correction: {e}")


def load_slide(file_path: str):
    """
    Load a WSI file using Aslide with color correction applied.

    Args:
        file_path: Path to the WSI file

    Returns:
        An Aslide Slide instance

    Raises:
        Exception: If the slide cannot be opened
    """
    from Aslide.aslide import Slide

    slide = Slide(str(file_path))
    configure_color_correction(slide)
    return slide
