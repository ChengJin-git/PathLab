"""
Utility functions for Gateway service
"""
import os
from Aslide import Slide
from .dependencies import logger


def extract_wsi_properties(wsi_path: str) -> dict:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
    }

    if not wsi_path or not os.path.exists(wsi_path):
        logger.warning(f"WSI file not found: {wsi_path}")
        return default_props

    try:
        with Slide(wsi_path) as slide:
            # Extract properties
            props = {}

            # 1. MPP (microns per pixel)
            try:
                mpp_value = slide.mpp
                if isinstance(mpp_value, (int, float)):
                    props["mpp"] = float(mpp_value)
                elif isinstance(mpp_value, tuple) and len(mpp_value) >= 2:
                    # If mpp is a tuple (mpp_x, mpp_y), take average
                    props["mpp"] = (float(mpp_value[0]) + float(mpp_value[1])) / 2
                else:
                    props["mpp"] = default_props["mpp"]
            except:
                props["mpp"] = default_props["mpp"]

            # 2. Vendor
            try:
                vendor = slide.properties.get('openslide.vendor', 'Unknown')
                props["vendor"] = vendor if vendor else "Unknown"
            except:
                props["vendor"] = default_props["vendor"]

            # 3. Width and Height (from level 0 dimensions)
            try:
                width, height = slide.dimensions
                props["width"] = int(width)
                props["height"] = int(height)
            except:
                props["width"] = default_props["width"]
                props["height"] = default_props["height"]

            # 4. Magnification (objective power)
            try:
                mag = slide.properties.get('openslide.objective-power')
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except:
                props["magnification"] = default_props["magnification"]

            logger.info(f"✓ Extracted properties from {os.path.basename(wsi_path)}: "
                       f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                       f"size={props['width']}x{props['height']}, mag={props['magnification']}x")

            return props

    except Exception as e:
        logger.error(f"Failed to read WSI properties from {wsi_path}: {e}")
        return default_props

