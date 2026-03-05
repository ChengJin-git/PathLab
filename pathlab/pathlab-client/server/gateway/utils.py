"""
Utility functions for Gateway service
"""
import os
import httpx
from .dependencies import logger, AI_SERVICE_URL

# Optional Aslide import - gateway must stay bootable even when native
# slide libs are unavailable on the current OS/architecture (e.g. macOS).
try:
    from Aslide import Slide
    ASLIDE_AVAILABLE = True
except Exception as e:
    Slide = None
    ASLIDE_AVAILABLE = False
    logger.warning(f"Aslide unavailable ({e}) - WSI property extraction will use defaults")


async def cancel_ai_service_training(task_id: str) -> None:
    """
    Request AI service to cancel a training task and release GPU.

    Uses fire-and-forget pattern: sends the request and returns immediately
    without waiting for response, since AI service may be blocked by GPU training.
    The cancellation flag is set immediately when the request is received.
    """
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.delete(f"{AI_SERVICE_URL}/api/ai/training/{task_id}")
            logger.info(f"Sent cancellation request to AI service for task {task_id}")
    except httpx.TimeoutException:
        logger.info(
            f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)"
        )
    except Exception as e:
        logger.warning(f"Failed to send cancellation to AI service for task {task_id}: {e}")


def extract_wsi_properties(wsi_path: str) -> dict:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification, file_size.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
        "file_size": 0,
    }

    if not wsi_path or not os.path.exists(wsi_path):
        logger.warning(f"WSI file not found: {wsi_path}")
        return default_props

    # Get file size first - this works even if slide reading fails
    try:
        file_size = os.path.getsize(wsi_path)
    except Exception:
        file_size = 0

    # If Aslide is not available, return defaults with file size
    if not ASLIDE_AVAILABLE:
        default_props["file_size"] = file_size
        logger.info(f"Aslide not available, using default props for {os.path.basename(wsi_path)}")
        return default_props

    try:
        with Slide(wsi_path) as slide:
            # Extract properties - start with file_size which is already retrieved
            props = {
                "file_size": file_size,
            }

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
            except Exception:
                props["mpp"] = default_props["mpp"]

            # 2. Vendor
            try:
                vendor = slide.properties.get('openslide.vendor', 'Unknown')
                props["vendor"] = vendor if vendor else "Unknown"
            except Exception:
                props["vendor"] = default_props["vendor"]

            # 3. Width and Height (from level 0 dimensions)
            try:
                width, height = slide.dimensions
                props["width"] = int(width)
                props["height"] = int(height)
            except Exception:
                props["width"] = default_props["width"]
                props["height"] = default_props["height"]

            # 4. Magnification (objective power)
            try:
                mag = slide.properties.get('openslide.objective-power')
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except Exception:
                props["magnification"] = default_props["magnification"]

            logger.info(f"✓ Extracted properties from {os.path.basename(wsi_path)}: "
                       f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                       f"size={props['width']}x{props['height']}, mag={props['magnification']}x, "
                       f"file_size={props['file_size']} bytes")

            return props

    except Exception as e:
        logger.error(f"Failed to read WSI properties from {wsi_path}: {e}")
        # Still return file_size even if slide reading failed
        default_props["file_size"] = file_size
        return default_props
