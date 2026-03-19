"""
Coordinate cache validation, orchestration, visualization, and safe H5 loading utilities.

Extracted from tiling.py to keep tiling.py focused on the core TissueSegmenter
and WSITiler classes.
"""

import json
import numpy as np
import cv2
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image
import logging

logger = logging.getLogger(__name__)


# Required attributes that must exist in coords.h5 for valid cache
# Note: patch_size and stride are recorded but NOT used for cache validation
# because they are auto-determined by each WSI's magnification/MPP (PrePATH-style)
REQUIRED_COORDS_ATTRS = [
    "patch_size",
    "stride",
    "patch_level",
    "contour_fn",
    "use_padding",
    "seg_level",
    "sthresh",
    "mthresh",
    "close",
    "use_otsu",
    "a_t",
    "a_h",
    "max_n_holes",
    "native_mpp",
    "read_size",
    "step_size",
]


def _delete_corrupted_h5(h5_path: Path) -> None:
    """Delete a corrupted H5 file and log the action."""
    try:
        h5_path.unlink()
        logger.info(f"Deleted corrupted H5 file: {h5_path}")
    except Exception as del_e:
        logger.error(f"Failed to delete corrupted H5 file {h5_path}: {del_e}")


def safe_load_h5_coords(
    h5_path: Path,
    delete_if_corrupted: bool = True,
) -> Tuple[Optional[np.ndarray[Any, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """
    Safely load coordinates and attributes from an HDF5 file.

    This handles corrupted h5 files that may result from power loss or crashes
    during file writing.

    Args:
        h5_path: Path to the .h5 coordinates file
        delete_if_corrupted: If True, delete corrupted files automatically

    Returns:
        Tuple of (coords_array, attrs_dict, error_message)
        - On success: (coords_array, attrs_dict, None)
        - On failure: (None, None, error_message)

    The caller should handle the None case by recomputing coordinates.
    """
    import h5py

    if not h5_path.exists():
        return None, None, f"File does not exist: {h5_path}"

    try:
        with h5py.File(h5_path, "r") as f:
            if "coords" not in f:
                error_msg = f"No 'coords' dataset in {h5_path}"
                logger.warning(error_msg)
                if delete_if_corrupted:
                    _delete_corrupted_h5(h5_path)
                return None, None, error_msg

            coords_array = f["coords"][:]
            attrs = dict(f["coords"].attrs)
            return coords_array, attrs, None

    except OSError as e:
        # OSError covers HDF5 file corruption errors like:
        # - "Unable to open file" (truncated file)
        # - "file signature not found" (incomplete write)
        # - "Unable to read data" (corrupted data)
        error_msg = str(e)
        logger.warning(
            f"Detected corrupted H5 file (likely from power loss): {h5_path}. "
            f"Error: {error_msg}"
        )
        if delete_if_corrupted:
            _delete_corrupted_h5(h5_path)
        return None, None, f"Corrupted file (will recompute): {error_msg}"


def safe_load_h5_coords_attrs(
    h5_path: Path,
    delete_if_corrupted: bool = True,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Safely load only coords.h5 dataset attributes without reading the full coords array.

    This is useful for lightweight metadata lookups such as patch_size, where loading
    the full coordinates array would be unnecessarily expensive.
    """
    import h5py

    if not h5_path.exists():
        return None, f"File does not exist: {h5_path}"

    try:
        with h5py.File(h5_path, "r") as f:
            if "coords" not in f:
                error_msg = f"No 'coords' dataset in {h5_path}"
                logger.warning(error_msg)
                if delete_if_corrupted:
                    _delete_corrupted_h5(h5_path)
                return None, error_msg

            return dict(f["coords"].attrs), None

    except OSError as e:
        error_msg = str(e)
        logger.warning(
            f"Detected corrupted H5 file (likely from power loss): {h5_path}. "
            f"Error: {error_msg}"
        )
        if delete_if_corrupted:
            _delete_corrupted_h5(h5_path)
        return None, f"Corrupted file (will recompute): {error_msg}"

    except Exception as e:
        # Other unexpected errors
        error_msg = str(e)
        logger.error(f"Failed to load H5 file {h5_path}: {error_msg}")
        return None, None, error_msg


def _check_coords_params_match(
    attrs: Dict[str, Any],
    level: int,
    seg_params: Optional[Dict[str, Any]],
    filter_params: Optional[Dict[str, Any]],
    contour_fn: str,
    use_padding: bool,
    seg_level: int = -1,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> bool:
    """
    Check if cached coordinates parameters match the requested parameters.

    Returns True if all parameters match, False otherwise.

    PrePATH-style: patch_size and stride are NOT validated because they are
    automatically determined by each WSI's magnification/MPP.

    NOTE: All required attributes must exist in the cached file. Old cache files
    without complete attributes will return False, forcing recomputation.
    """
    # Check all required attributes exist first
    missing_attrs = [attr for attr in REQUIRED_COORDS_ATTRS if attr not in attrs]
    if missing_attrs:
        logger.warning(
            f"Missing required attributes in cache: {missing_attrs}. "
            "This is likely an old cache file that needs recomputation."
        )
        return False

    # Use defaults for seg_params and filter_params if None
    seg_params = seg_params or {}
    filter_params = filter_params or {}

    # Check basic tiling parameters (NOT patch_size/stride - they're auto-determined by MPP)
    if attrs["patch_level"] != level:
        logger.warning(
            f"patch_level mismatch: cached={attrs['patch_level']}, requested={level}"
        )
        return False

    # Handle bytes vs string for contour_fn
    cached_contour_fn = attrs["contour_fn"]
    if isinstance(cached_contour_fn, bytes):
        cached_contour_fn = cached_contour_fn.decode("utf-8")

    if cached_contour_fn != contour_fn:
        logger.warning(
            f"contour_fn mismatch: cached={cached_contour_fn}, requested={contour_fn}"
        )
        return False
    if attrs["use_padding"] != use_padding:
        logger.warning(
            f"use_padding mismatch: cached={attrs['use_padding']}, requested={use_padding}"
        )
        return False

    # Check seg_level
    if attrs["seg_level"] != seg_level:
        logger.warning(
            f"seg_level mismatch: cached={attrs['seg_level']}, requested={seg_level}"
        )
        return False

    # Check segmentation parameters (always check, use defaults if not provided)
    requested_sthresh = seg_params.get("sthresh", 5)
    if attrs["sthresh"] != requested_sthresh:
        logger.warning(
            f"sthresh mismatch: cached={attrs['sthresh']}, requested={requested_sthresh}"
        )
        return False

    requested_mthresh = seg_params.get("mthresh", 7)
    if attrs["mthresh"] != requested_mthresh:
        logger.warning(
            f"mthresh mismatch: cached={attrs['mthresh']}, requested={requested_mthresh}"
        )
        return False

    requested_close = seg_params.get("close", 4)
    if attrs["close"] != requested_close:
        logger.warning(
            f"close mismatch: cached={attrs['close']}, requested={requested_close}"
        )
        return False

    requested_use_otsu = seg_params.get("use_otsu", False)
    if attrs["use_otsu"] != requested_use_otsu:
        logger.warning(
            f"use_otsu mismatch: cached={attrs['use_otsu']}, requested={requested_use_otsu}"
        )
        return False

    # Check filter parameters (always check, use defaults if not provided)
    requested_a_t = filter_params.get("a_t", 100)
    if attrs["a_t"] != requested_a_t:
        logger.warning(
            f"a_t mismatch: cached={attrs['a_t']}, requested={requested_a_t}"
        )
        return False

    requested_a_h = filter_params.get("a_h", 16)
    if attrs["a_h"] != requested_a_h:
        logger.warning(
            f"a_h mismatch: cached={attrs['a_h']}, requested={requested_a_h}"
        )
        return False

    requested_max_n_holes = filter_params.get("max_n_holes", 8)
    if attrs["max_n_holes"] != requested_max_n_holes:
        logger.warning(
            f"max_n_holes mismatch: cached={attrs['max_n_holes']}, requested={requested_max_n_holes}"
        )
        return False

    # NOTE: native_mpp is NOT validated - same slide always has same MPP
    # patch_size and stride are also NOT validated - they're auto-determined by MPP

    return True


def check_coords_cache_valid(
    wsi_id: str,
    coords_dir: Path,
    level: int = 0,
    seg_params: Optional[Dict[str, Any]] = None,
    filter_params: Optional[Dict[str, Any]] = None,
    contour_fn: str = "four_pt",
    use_padding: bool = True,
    seg_level: int = -1,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> Optional[Tuple[List[Tuple[int, int]], Path]]:
    """
    Check if valid cached coordinates exist for the given parameters.

    Uses params_hash-based directory structure:
        coords_dir/{params_hash}/{wsi_id}_coords.h5
    """
    from backend.ai.tasks.feature_cache import compute_params_hash

    # Compute params_hash
    params_hash = compute_params_hash(
        level=level,
        seg_params=seg_params,
        filter_params=filter_params,
        contour_fn=contour_fn,
        use_padding=use_padding,
        seg_level=seg_level,
    )

    coords_file = coords_dir / params_hash / f"{wsi_id}_coords.h5"

    # Check for incomplete extraction artifact
    partial_path = coords_file.parent / f"{wsi_id}_coords.h5.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    if not coords_file.exists():
        return None

    # Use safe loading to handle corrupted files
    coords_array, attrs, load_error = safe_load_h5_coords(
        coords_file, delete_if_corrupted=True
    )

    if coords_array is None:
        logger.warning(f"Failed to load cached coordinates: {load_error}")
        return None

    # With params_hash directory structure, we trust the hash matches
    # But still validate to catch any edge cases (e.g., hash collision)
    if _check_coords_params_match(
        attrs,
        level,
        seg_params,
        filter_params,
        contour_fn,
        use_padding,
        seg_level=seg_level,
    ):
        if len(coords_array) > 0:
            logger.info(
                f"[Coords cache hit] {len(coords_array)} coordinates from {coords_file}"
            )
            return [tuple(coord) for coord in coords_array], coords_file
        else:
            # Cached file has 0 coordinates - treat as cache miss so adaptive fallback can try
            logger.warning(
                f"[Coords cache] Cached file has 0 coordinates for {wsi_id}, "
                f"treating as cache miss for adaptive seg_level fallback"
            )
            return None

    logger.info("Cached coordinates have different parameters (hash collision?)")
    return None


def get_or_compute_coordinates(
    wsi_id: str,
    slide,
    coords_dir: Path,
    level: int = 0,
    force_recompute: bool = False,
    seg_params: Optional[Dict[str, Any]] = None,
    filter_params: Optional[Dict[str, Any]] = None,
    contour_fn: str = "four_pt",
    use_padding: bool = True,
    seg_level: int = -1,
    tissue_contours: Optional[List[Any]] = None,
    hole_contours: Optional[List[Any]] = None,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> Tuple[List[Tuple[int, int]], Path]:
    """
    Get patch coordinates from cache or compute if not exists.

    Uses params_hash-based directory structure for caching:
        coords_dir/{params_hash}/{wsi_id}_coords.h5

    PrePATH-style tiling: patch_size and stride are automatically determined
    by each WSI's magnification/MPP, NOT passed as parameters.

    Cache validation checks parameters including:
    - level (pyramid level)
    - contour_fn, use_padding (tiling options)
    - seg_level: pyramid level for tissue segmentation
    - seg_params: sthresh, mthresh, close, use_otsu (segmentation params)
    - filter_params: a_t, a_h, max_n_holes (contour filter params)

    native_mpp is automatically extracted from the slide object.

    Args:
        wsi_id: WSI identifier
        slide: ASlide Slide object
        coords_dir: Root directory to store coordinates (e.g., uploads/coordinates)
        level: Pyramid level (always 0 for PrePATH-style)
        force_recompute: Force recomputation even if cache exists
        seg_params: Segmentation parameters (optional)
        filter_params: Contour filtering parameters (optional)
        contour_fn: Contour checking function
        use_padding: Allow patches at tissue boundary
        seg_level: Pyramid level for tissue segmentation (-1 = auto)

    Returns:
        Tuple of (coordinates, coords_file_path):
        - coordinates: List of (x, y) coordinates at level 0
        - coords_file_path: Path to the saved/cached coords h5 file
    """
    # Lazy imports to avoid circular dependency with tiling.py
    from .tiling import TissueSegmenter, WSITiler, get_native_mpp
    from backend.ai.tasks.feature_cache import compute_params_hash

    # Compute params_hash for cache directory (PrePATH-style: no patch_size/stride)
    params_hash = compute_params_hash(
        level=level,
        seg_params=seg_params,
        filter_params=filter_params,
        contour_fn=contour_fn,
        use_padding=use_padding,
        seg_level=seg_level,
    )

    # Create cache directory with params_hash
    cache_dir = coords_dir / params_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    coords_file = cache_dir / f"{wsi_id}_coords.h5"

    # Check for incomplete extraction artifact
    partial_path = coords_file.parent / f"{wsi_id}_coords.h5.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    # Get native MPP from slide for MPP-aware tiling
    native_mpp = get_native_mpp(slide)
    logger.info(f"Slide native MPP: {native_mpp}, params_hash: {params_hash}")

    # Load from cache if exists
    if coords_file.exists() and not force_recompute:
        logger.info(f"Checking cached coordinates: {coords_file}")

        # Use safe loading to handle corrupted files
        coords_array, attrs, load_error = safe_load_h5_coords(
            coords_file, delete_if_corrupted=True
        )

        if coords_array is not None:
            # With params_hash directory, we trust the hash matches
            # But still validate to catch edge cases
            if _check_coords_params_match(
                attrs,
                level,
                seg_params,
                filter_params,
                contour_fn,
                use_padding,
                seg_level=seg_level,
            ):
                if len(coords_array) > 0:
                    logger.info(
                        f"[Coords cache hit] {len(coords_array)} coordinates from {coords_file}"
                    )
                    return [tuple(coord) for coord in coords_array], coords_file
                else:
                    # Cached file has 0 coordinates - recompute with adaptive fallback
                    logger.warning(
                        f"[Coords cache hit] Cached file has 0 coordinates for {wsi_id}, "
                        f"recomputing with adaptive seg_level fallback"
                    )
            else:
                logger.warning(
                    "Cached coordinates have different parameters (hash collision?), recomputing"
                )
        else:
            logger.warning(
                f"Failed to load cached coordinates: {load_error}, recomputing"
            )

    # Compute new coordinates
    logger.info(f"Computing new coordinates for {wsi_id}")

    # Merge seg_level into seg_params for TissueSegmenter
    effective_seg_params = dict(seg_params or {})
    effective_seg_params["seg_level"] = seg_level

    # Create segmenter with custom parameters
    segmenter = TissueSegmenter(**effective_seg_params, filter_params=filter_params)

    # Resolve the actual segmentation level (auto-selection resolves -1 to a concrete level)
    initial_seg_level = segmenter._get_seg_level(slide)

    # Get level downsample factor for MPP calculation
    level_downsample = (
        slide.level_downsamples[level] if level < len(slide.level_downsamples) else 1.0
    )

    # Create tiler with PrePATH-style settings (patch_size/stride auto-determined by MPP)
    tiler = WSITiler(
        level=level,
        segmenter=segmenter,
        contour_fn=contour_fn,
        use_padding=use_padding,
        native_mpp=native_mpp,
        level_downsample=level_downsample,
    )

    # Don't save yet - may need adaptive fallback to lower seg_levels
    coordinates = tiler.compute_coordinates(
        slide,
        save_path=None,
        tissue_contours=tissue_contours,
        hole_contours=hole_contours,
        seg_params=seg_params,
        filter_params=filter_params,
    )

    # Get default sthresh value for adaptive fallback
    default_sthresh = seg_params.get("sthresh", 8) if seg_params else 8

    # Adaptive sthresh fallback: if no coordinates found, try lower sthresh values first
    # This is cheaper than falling back to lower seg_levels
    STHREAD_FALLBACK_VALUES = [5, 3, 1]

    if len(coordinates) == 0 and default_sthresh > 1:
        for fallback_sthresh in STHREAD_FALLBACK_VALUES:
            if fallback_sthresh >= default_sthresh:
                continue

            logger.info(
                f"[Adaptive sthresh fallback] Trying sthresh={fallback_sthresh} (default={default_sthresh}) for {wsi_id}"
            )

            fallback_seg_params = dict(seg_params or {})
            fallback_seg_params["sthresh"] = fallback_sthresh

            fallback_segmenter = TissueSegmenter(
                **fallback_seg_params, filter_params=filter_params
            )

            fallback_tiler = WSITiler(
                level=level,
                segmenter=fallback_segmenter,
                contour_fn=contour_fn,
                use_padding=use_padding,
                native_mpp=native_mpp,
                level_downsample=level_downsample,
            )

            coordinates = fallback_tiler.compute_coordinates(
                slide,
                save_path=None,
                seg_params=fallback_seg_params,
                filter_params=filter_params,
            )

            if len(coordinates) > 0:
                logger.info(
                    f"[Adaptive sthresh fallback] Found {len(coordinates)} coordinates at "
                    f"sthresh={fallback_sthresh} for {wsi_id} "
                    f"(original sthresh={default_sthresh}, seg_level={initial_seg_level})"
                )
                # Update seg_params for final save
                seg_params = fallback_seg_params
                break

    # Adaptive seg_level fallback: if no coordinates found after sthresh fallback, try lower seg_levels
    # Lower levels have higher resolution, making it easier to detect small tissue regions.
    #
    # SAFETY: Only try levels whose image dimensions do not exceed _SEG_MAX_DIM on either axis.
    # segment_tissue() calls slide.read_region((0,0), level, level_dims), so attempting a level
    # with e.g. 100k×80k pixels loads the entire image into RAM, causing OOM or an indefinite hang
    # on large blank slides — which in turn triggers a 504 from the Gateway (600 s timeout).
    # 8192 px is ample for tissue detection: tissue blobs are large low-frequency structures
    # visible at any sufficiently downsampled resolution.
    _SEG_MAX_DIM = 8192
    safe_fallback_levels = [
        lvl
        for lvl in range(initial_seg_level - 1, -1, -1)
        if max(slide.level_dimensions[lvl]) <= _SEG_MAX_DIM
    ]
    skipped_oversized_levels = [
        lvl
        for lvl in range(initial_seg_level - 1, -1, -1)
        if max(slide.level_dimensions[lvl]) > _SEG_MAX_DIM
    ]
    if skipped_oversized_levels:
        logger.warning(
            f"[Adaptive fallback] Skipping seg_levels {skipped_oversized_levels} for {wsi_id} "
            f"— their dimensions exceed {_SEG_MAX_DIM}px and would cause OOM/hang."
        )
    if len(coordinates) == 0 and safe_fallback_levels:
        logger.warning(
            f"No coordinates found at seg_level={initial_seg_level} (sthresh fallback exhausted) for {wsi_id}, "
            f"trying lower seg_levels {safe_fallback_levels} (max_dim<={_SEG_MAX_DIM}px) with adaptive sthresh..."
        )
        for fallback_level in safe_fallback_levels:
            logger.info(
                f"[Adaptive fallback] Trying seg_level={fallback_level} for {wsi_id}"
            )

            # For each seg_level, also try adaptive sthresh values
            for sthresh_val in [default_sthresh] + STHREAD_FALLBACK_VALUES:
                if sthresh_val >= default_sthresh:
                    sthresh_val = default_sthresh

                fallback_seg_params = dict(seg_params or {})
                fallback_seg_params["seg_level"] = fallback_level
                fallback_seg_params["sthresh"] = sthresh_val

                fallback_segmenter = TissueSegmenter(
                    **fallback_seg_params, filter_params=filter_params
                )

                fallback_tiler = WSITiler(
                    level=level,
                    segmenter=fallback_segmenter,
                    contour_fn=contour_fn,
                    use_padding=use_padding,
                    native_mpp=native_mpp,
                    level_downsample=level_downsample,
                )

                coordinates = fallback_tiler.compute_coordinates(
                    slide,
                    save_path=None,
                    seg_params=fallback_seg_params,
                    filter_params=filter_params,
                )

                if len(coordinates) > 0:
                    logger.info(
                        f"[Adaptive fallback] Found {len(coordinates)} coordinates at "
                        f"seg_level={fallback_level}, sthresh={sthresh_val} for {wsi_id} "
                        f"(original: seg_level={initial_seg_level}, sthresh={default_sthresh})"
                    )
                    # Update seg_params for final save
                    seg_params = fallback_seg_params
                    break

            if len(coordinates) > 0:
                break

        if len(coordinates) == 0:
            logger.error(
                f"No tissue coordinates found for {wsi_id} after exhausting all safe seg_levels "
                f"(tried: {safe_fallback_levels}; skipped oversized: {skipped_oversized_levels}). "
                f"The slide may not contain detectable tissue."
            )

    # Only save coordinates if we actually found tissue patches.
    # Saving 0-coordinate files pollutes the cache and causes downstream
    # feature extraction to produce empty [0, feat_dim] tensors that crash training.
    if len(coordinates) > 0:
        tiler._save_coordinates(
            coordinates, coords_file, seg_params=seg_params, filter_params=filter_params
        )
    else:
        logger.warning(
            f"[Fallback] Skipping coordinate save for {wsi_id} — 0 patches found "
            f"after exhausting all seg_levels. The slide may not contain detectable tissue."
        )

    return coordinates, coords_file


def visualize_segmentation(
    slide,
    tissue_contours: List[Any],
    hole_contours: List[Any],
    vis_level: int = -1,
    line_thickness: int = 5,
    color: Tuple[int, int, int] = (0, 255, 0),
    hole_color: Tuple[int, int, int] = (0, 0, 255),
) -> Image.Image:
    """
    Visualize tissue segmentation results

    Args:
        slide: ASlide Slide object
        tissue_contours: List of tissue contours (at level 0)
        hole_contours: List of hole contours (at level 0)
        vis_level: Visualization level (-1 = auto select ~64x)
        line_thickness: Line thickness for drawing contours
        color: Color for tissue contours (RGB)
        hole_color: Color for hole contours (RGB)

    Returns:
        PIL Image with segmentation overlay
    """
    # Auto-select visualization level
    if vis_level < 0:
        target_downsample = 64
        level_downsamples = slide.level_downsamples
        vis_level = 0
        min_diff = abs(level_downsamples[0] - target_downsample)
        for i, ds in enumerate(level_downsamples):
            diff = abs(ds - target_downsample)
            if diff < min_diff:
                min_diff = diff
                vis_level = i

    # Read slide at visualization level
    level_dims = slide.level_dimensions[vis_level]
    img = slide.read_region((0, 0), vis_level, level_dims)
    img_np = np.array(img.convert("RGB"))
    del img  # Release PIL image immediately

    # Scale contours to visualization level
    downsample = slide.level_downsamples[vis_level]
    scale = (1.0 / downsample, 1.0 / downsample)

    scaled_tissue = [np.array(cont * scale, dtype="int32") for cont in tissue_contours]
    scaled_holes = [
        [np.array(h * scale, dtype="int32") for h in holes] for holes in hole_contours
    ]

    # Draw tissue contours
    cv2.drawContours(
        img_np, scaled_tissue, -1, color, line_thickness, lineType=cv2.LINE_8
    )
    del scaled_tissue  # Release scaled contour copies

    # Draw holes
    for holes in scaled_holes:
        cv2.drawContours(
            img_np, holes, -1, hole_color, line_thickness, lineType=cv2.LINE_8
        )
    del scaled_holes  # Release scaled hole copies

    # Convert to PIL and release numpy array
    result = Image.fromarray(img_np)
    del img_np
    return result
