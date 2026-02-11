"""
Patch/Coordinates Cache Manager

Manages global coordinates caching to avoid redundant patch coordinate computation.
Coordinates are cached by preprocessing parameters (params_hash).
Uses the same params_hash as feature_cache to ensure consistency.

Cache structure:
    uploads/coordinates/{params_hash}/{wsi_id}_coords.h5

The params_hash uniquely identifies the preprocessing configuration
(patch_size, stride, level, seg_params, filter_params, etc.).
Same preprocessing config will produce the same patch coordinates.

This module reuses compute_params_hash from feature_cache to ensure
that coordinates and features use the same cache key.
"""
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List
import numpy as np

logger = logging.getLogger(__name__)

# Re-export compute_params_hash from feature_cache for consistency
from backend.ai.tasks.feature_cache import compute_params_hash


def get_cached_coords_path(
    uploads_root: Path,
    params_hash: str,
    wsi_id: str,
) -> Path:
    """
    Get the path to cached coordinates file.

    Structure: uploads/coordinates/{params_hash}/{wsi_id}_coords.h5
    """
    cache_dir = uploads_root / "coordinates" / params_hash
    coords_path = cache_dir / f"{wsi_id}_coords.h5"
    return coords_path


def find_cached_coords(
    uploads_root: Path,
    params_hash: str,
    wsi_id: str,
) -> Optional[Path]:
    """
    Check if cached coordinates exist for the given params_hash and WSI.

    Returns the path to cached coordinates if found, None otherwise.
    If a .h5.partial file is found, it indicates a previous extraction was
    interrupted — the partial file is deleted and None is returned.
    """
    coords_path = get_cached_coords_path(uploads_root, params_hash, wsi_id)

    # Check for incomplete extraction artifact
    partial_path = coords_path.parent / f"{wsi_id}_coords.h5.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    if coords_path.exists():
        logger.info(f"Found cached coordinates: {coords_path}")
        return coords_path

    return None


def get_coords_cache_save_path(
    uploads_root: Path,
    params_hash: str,
    wsi_id: str,
) -> Path:
    """
    Get the path where coordinates should be saved.

    Creates the cache directory if it doesn't exist.
    Returns coords_path.
    The caller is responsible for saving the actual coordinates.
    """
    cache_dir = uploads_root / "coordinates" / params_hash
    cache_dir.mkdir(parents=True, exist_ok=True)

    coords_path = get_cached_coords_path(uploads_root, params_hash, wsi_id)

    logger.info(f"Coords cache save path: {coords_path}")
    return coords_path


def safe_load_cached_coords(
    coords_path: Path,
    delete_if_corrupted: bool = True,
) -> Tuple[Optional[np.ndarray], Optional[Dict], Optional[str]]:
    """
    Safely load coordinates and attributes from a cached HDF5 file.

    This handles corrupted h5 files that may result from power loss or crashes.

    Args:
        coords_path: Path to the .h5 coordinates file
        delete_if_corrupted: If True, delete corrupted files automatically

    Returns:
        Tuple of (coords_array, attrs_dict, error_message)
        - On success: (coords_array, attrs_dict, None)
        - On failure: (None, None, error_message)
    """
    # Delegate to tiling module's safe_load_h5_coords
    from backend.preprocessing.tiling import safe_load_h5_coords
    return safe_load_h5_coords(coords_path, delete_if_corrupted)


def delete_cached_coords(
    uploads_root: Path,
    params_hash: str,
    wsi_id: str,
) -> Tuple[bool, str]:
    """
    Delete a cached coordinates file.

    Returns (success, description) tuple.
    """
    coords_path = get_cached_coords_path(uploads_root, params_hash, wsi_id)

    if not coords_path.exists():
        return False, "File does not exist"

    try:
        coords_path.unlink()
        logger.info(f"Deleted cached coordinates: {coords_path}")
        return True, "Deleted file"
    except Exception as e:
        logger.error(f"Failed to delete cached coordinates {coords_path}: {e}")
        return False, str(e)


def delete_all_cached_coords_for_wsi(
    uploads_root: Path,
    wsi_id: str,
) -> Dict:
    """
    Delete all cached coordinates for a WSI across all params_hash directories.

    This is useful when deleting a WSI from the system.

    Returns:
        {
            "deleted_files": List[str],
            "failed": List[Tuple[str, str]],
            "total_count": int,
            "total_size": int
        }
    """
    result = {
        "deleted_files": [],
        "failed": [],
        "total_count": 0,
        "total_size": 0
    }

    coords_root = uploads_root / "coordinates"
    if not coords_root.exists():
        return result

    # Search all params_hash directories for this wsi_id
    for params_hash_dir in coords_root.iterdir():
        if params_hash_dir.is_dir():
            # Delete .h5.partial file if exists
            partial_file = params_hash_dir / f"{wsi_id}_coords.h5.partial"
            if partial_file.exists():
                try:
                    size = partial_file.stat().st_size
                    partial_file.unlink()
                    result["deleted_files"].append(str(partial_file))
                    result["total_size"] += size
                    logger.info(f"Deleted partial coordinates file: {partial_file} ({size} bytes)")
                except Exception as e:
                    result["failed"].append((str(partial_file), str(e)))
                    logger.error(f"Failed to delete {partial_file}: {e}")

            # Delete .h5 file if exists
            coords_file = params_hash_dir / f"{wsi_id}_coords.h5"
            if coords_file.exists():
                result["total_count"] += 1
                try:
                    size = coords_file.stat().st_size
                    coords_file.unlink()
                    result["deleted_files"].append(str(coords_file))
                    result["total_size"] += size
                    logger.info(f"Deleted cached coordinates: {coords_file} ({size} bytes)")
                except Exception as e:
                    result["failed"].append((str(coords_file), str(e)))
                    logger.error(f"Failed to delete {coords_file}: {e}")

    return result


def find_any_cached_coords_for_wsi(
    uploads_root: Path,
    wsi_id: str,
) -> Optional[Path]:
    """
    Find any existing cached coordinates file for a given WSI.

    This searches across all params_hash directories and returns the first
    coords file found. Useful for endpoints that need coords but don't care
    about specific preprocessing parameters (e.g., attention heatmap viewing).

    If a .h5.partial file is found, it indicates a previous extraction was
    interrupted — the partial file is deleted and the search continues.

    Args:
        uploads_root: Root uploads directory
        wsi_id: WSI identifier

    Returns:
        Path to coords file if found, None otherwise.
    """
    coords_root = uploads_root / "coordinates"
    if not coords_root.exists():
        return None

    # Search all params_hash directories for this wsi_id
    for params_hash_dir in coords_root.iterdir():
        if params_hash_dir.is_dir():
            # Check for incomplete extraction artifact
            partial_path = params_hash_dir / f"{wsi_id}_coords.h5.partial"
            if partial_path.exists():
                logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
                try:
                    partial_path.unlink()
                except OSError as e:
                    logger.warning(f"Failed to delete partial file {partial_path}: {e}")

            coords_file = params_hash_dir / f"{wsi_id}_coords.h5"
            if coords_file.exists():
                logger.info(f"Found coords file for {wsi_id}: {coords_file}")
                return coords_file

    return None


def list_all_cached_coords_for_wsi(
    uploads_root: Path,
    wsi_id: str,
) -> List[Path]:
    """
    List all cached coordinates files for a given WSI across all params_hash directories.

    Args:
        uploads_root: Root uploads directory
        wsi_id: WSI identifier

    Returns:
        List of paths to all coords files for this WSI.
    """
    result = []
    coords_root = uploads_root / "coordinates"
    if not coords_root.exists():
        return result

    for params_hash_dir in coords_root.iterdir():
        if params_hash_dir.is_dir():
            coords_file = params_hash_dir / f"{wsi_id}_coords.h5"
            if coords_file.exists():
                result.append(coords_file)

    return result

