"""
Shared slide loading utilities for PathLab.

Provides centralized color correction configuration and slide loading
to avoid code duplication across preprocessing and AI modules.

Usage:
    from backend.common.slide_utils import configure_color_correction, load_slide
"""
import logging
from typing import Optional

from backend.common.config import Config

logger = logging.getLogger(__name__)


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
        if not hasattr(slide, 'format'):
            return

        # Case-insensitive check against configured formats
        slide_format_lower = slide.format.lower() if slide.format else ''
        if (
            slide_format_lower in Config.COLOR_CORRECTION_FORMATS
            and hasattr(slide, '_osr')
            and hasattr(slide._osr, 'apply_color_correction')
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

