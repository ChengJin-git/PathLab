"""
Feature Cache Manager

Manages global feature caching to avoid redundant feature extraction.
Features are cached by extractor name and preprocessing parameters.
Uses symlinks in task directories to avoid duplication.

Cache structure:
    uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt

The params_hash uniquely identifies the preprocessing configuration
(patch_size, stride, level, seg_params, filter_params, etc.).
Same preprocessing config will produce the same patches, thus same features.

Concurrency:
    Uses file locking (fcntl.flock) to prevent race conditions when
    multiple tasks try to extract features for the same WSI simultaneously.
"""
import fcntl
import hashlib
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Lock file timeout in seconds
LOCK_TIMEOUT = 300  # 5 minutes - feature extraction can take a while


@contextmanager
def file_lock(lock_path: Path, timeout: float = LOCK_TIMEOUT):
    """
    Context manager for file-based locking using fcntl.flock.

    This provides exclusive access to a resource identified by lock_path.
    Uses non-blocking lock with retry to implement timeout.

    Args:
        lock_path: Path to the lock file (will be created if not exists)
        timeout: Maximum time to wait for lock in seconds

    Raises:
        TimeoutError: If lock cannot be acquired within timeout
    """
    import time

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, 'w')

    start_time = time.time()
    acquired = False

    try:
        while time.time() - start_time < timeout:
            try:
                # Try to acquire exclusive lock (non-blocking)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                # Lock is held by another process, wait and retry
                time.sleep(0.5)

        if not acquired:
            raise TimeoutError(f"Could not acquire lock on {lock_path} within {timeout} seconds")

        yield lock_file

    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def get_lock_path(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> Path:
    """
    Get the path to the lock file for a specific feature cache entry.

    Lock files are stored in: uploads/features/.locks/{extractor_name}/{params_hash}/{wsi_id}.lock
    """
    lock_dir = uploads_root / "features" / ".locks" / extractor_name / params_hash
    return lock_dir / f"{wsi_id}.lock"


def compute_params_hash(
    patch_size: int,
    stride: int,
    level: int,
    seg_params: Optional[Dict] = None,
    filter_params: Optional[Dict] = None,
    contour_fn: str = 'four_pt',
    use_padding: bool = True
) -> str:
    """
    Compute a hash of preprocessing parameters for cache key.

    Returns a short hash string (8 characters) that uniquely identifies
    the preprocessing configuration.
    """
    params = {
        'patch_size': patch_size,
        'stride': stride,
        'level': level,
        'contour_fn': contour_fn,
        'use_padding': use_padding,
    }

    if seg_params:
        params['sthresh'] = seg_params.get('sthresh', 5)
        params['mthresh'] = seg_params.get('mthresh', 7)
        params['close'] = seg_params.get('close', 4)
        params['use_otsu'] = seg_params.get('use_otsu', False)

    if filter_params:
        params['a_t'] = filter_params.get('a_t', 100)
        params['a_h'] = filter_params.get('a_h', 16)
        params['max_n_holes'] = filter_params.get('max_n_holes', 8)

    # Create deterministic JSON string and hash it
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:8]


def get_cached_features_path(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> Path:
    """
    Get the path to cached features file.

    Structure: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
    """
    cache_dir = uploads_root / "features" / extractor_name / params_hash
    features_path = cache_dir / f"{wsi_id}.pt"
    return features_path


def find_cached_features(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> Optional[Path]:
    """
    Check if cached features exist for the given extractor, params_hash, and WSI.

    Returns the path to cached features if found, None otherwise.
    """
    features_path = get_cached_features_path(
        uploads_root, extractor_name, params_hash, wsi_id
    )

    if features_path.exists():
        logger.info(f"Found cached features: {features_path}")
        return features_path

    return None


def get_cache_save_path(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> Path:
    """
    Get the path where features should be saved.

    Returns features_path.
    The caller is responsible for saving the actual features tensor.
    """
    cache_dir = uploads_root / "features" / extractor_name / params_hash
    cache_dir.mkdir(parents=True, exist_ok=True)

    features_path = get_cached_features_path(
        uploads_root, extractor_name, params_hash, wsi_id
    )

    logger.info(f"Cache save path: {features_path}")
    return features_path


def read_params_from_coords_h5(coords_h5_path: Path) -> Optional[str]:
    """
    Read preprocessing parameters from a coordinates H5 file and compute params_hash.

    This is useful for inference when we don't have the original preprocessing config
    but need to find cached features that match the coordinates.

    Returns params_hash if successful, None if file doesn't exist or lacks required attrs.
    """
    import h5py

    if not coords_h5_path.exists():
        return None

    try:
        with h5py.File(coords_h5_path, 'r') as f:
            # Attributes are stored on the 'coords' dataset, not on the file level
            if 'coords' not in f:
                logger.warning(f"No 'coords' dataset in {coords_h5_path}")
                return None
            attrs = dict(f['coords'].attrs)

            # Required parameters
            patch_size = int(attrs.get('patch_size', 512))
            stride = int(attrs.get('stride', 512))
            level = int(attrs.get('patch_level', 0))
            contour_fn = attrs.get('contour_fn', 'four_pt')
            use_padding = bool(attrs.get('use_padding', True))

            # Handle bytes vs string for contour_fn
            if isinstance(contour_fn, bytes):
                contour_fn = contour_fn.decode('utf-8')

            # Segmentation parameters
            seg_params = {
                'sthresh': int(attrs.get('sthresh', 5)),
                'mthresh': int(attrs.get('mthresh', 7)),
                'close': int(attrs.get('close', 4)),
                'use_otsu': bool(attrs.get('use_otsu', False)),
            }

            # Filter parameters
            filter_params = {
                'a_t': int(attrs.get('a_t', 100)),
                'a_h': int(attrs.get('a_h', 16)),
                'max_n_holes': int(attrs.get('max_n_holes', 8)),
            }

            return compute_params_hash(
                patch_size=patch_size,
                stride=stride,
                level=level,
                seg_params=seg_params,
                filter_params=filter_params,
                contour_fn=contour_fn,
                use_padding=use_padding,
            )
    except Exception as e:
        logger.warning(f"Failed to read params from {coords_h5_path}: {e}")
        return None


def create_symlink_to_cache(
    task_features_dir: Path,
    wsi_id: str,
    cached_features_path: Path
) -> Path:
    """
    Create a symbolic link in the task features directory pointing to cached features.

    Returns the path to the symlink.
    """
    task_features_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = task_features_dir / f"{wsi_id}.pt"

    # Remove existing file or symlink if present
    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()

    # Create relative symlink for portability
    try:
        rel_path = os.path.relpath(cached_features_path, task_features_dir)
        symlink_path.symlink_to(rel_path)
        logger.info(f"Created symlink: {symlink_path} -> {rel_path}")
    except OSError as e:
        # Fallback to absolute path if relative fails
        symlink_path.symlink_to(cached_features_path)
        logger.warning(f"Created absolute symlink (relative failed): {symlink_path} -> {cached_features_path}")

    return symlink_path


def is_symlink(path: Path) -> bool:
    """Check if a path is a symbolic link."""
    return path.is_symlink()


def safe_delete_feature_file(path: Path) -> Tuple[bool, str]:
    """
    Safely delete a feature file, distinguishing between symlinks and real files.

    Returns (success, description) tuple.
    - For symlinks: only removes the symlink, not the target
    - For real files: removes the file
    """
    if not path.exists() and not path.is_symlink():
        return False, "File does not exist"

    try:
        if path.is_symlink():
            # Just remove the symlink, not the target
            path.unlink()
            return True, "Removed symlink (cached file preserved)"
        else:
            # Remove the actual file
            path.unlink()
            return True, "Removed file"
    except Exception as e:
        return False, str(e)


def get_cache_reference_count(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> int:
    """
    Count how many task directories have symlinks pointing to this cached feature.

    This helps determine if a cached feature can be safely deleted.
    """
    cached_features_path = get_cached_features_path(
        uploads_root, extractor_name, params_hash, wsi_id
    )

    if not cached_features_path.exists():
        return 0

    count = 0
    training_dir = uploads_root / "training"

    if training_dir.exists():
        for task_dir in training_dir.iterdir():
            if task_dir.is_dir():
                features_dir = task_dir / "features"
                if features_dir.exists():
                    for feat_file in features_dir.iterdir():
                        if feat_file.is_symlink():
                            try:
                                target = feat_file.resolve()
                                if target == cached_features_path.resolve():
                                    count += 1
                            except Exception:
                                pass

    return count


def find_symlinks_to_cache(
    uploads_root: Path,
    cached_features_path: Path
) -> List[Path]:
    """
    Find all symlinks in training directories that point to a specific cached feature file.

    Returns a list of symlink paths.
    """
    symlinks = []
    training_dir = uploads_root / "training"

    if not training_dir.exists():
        return symlinks

    try:
        resolved_cache_path = cached_features_path.resolve()
    except Exception:
        return symlinks

    for task_dir in training_dir.iterdir():
        if task_dir.is_dir():
            features_dir = task_dir / "features"
            if features_dir.exists():
                for feat_file in features_dir.iterdir():
                    if feat_file.is_symlink():
                        try:
                            target = feat_file.resolve()
                            if target == resolved_cache_path:
                                symlinks.append(feat_file)
                        except Exception:
                            pass

    return symlinks


def delete_cached_features_with_symlinks(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
) -> Dict:
    """
    Delete a cached feature file and all symlinks pointing to it.

    This should be called when deleting the original cached features to prevent
    dangling symlinks.

    Returns:
        {
            "deleted_cache_file": str or None,
            "deleted_symlinks": List[str],
            "failed": List[Tuple[str, str]],  # (path, error)
            "success": bool
        }
    """
    result = {
        "deleted_cache_file": None,
        "deleted_symlinks": [],
        "failed": [],
        "success": True
    }

    cached_features_path = get_cached_features_path(
        uploads_root, extractor_name, params_hash, wsi_id
    )

    # First, find and delete all symlinks pointing to this cache file
    symlinks = find_symlinks_to_cache(uploads_root, cached_features_path)
    for symlink in symlinks:
        try:
            symlink.unlink()
            result["deleted_symlinks"].append(str(symlink))
            logger.info(f"Deleted symlink: {symlink}")
        except Exception as e:
            result["failed"].append((str(symlink), str(e)))
            logger.error(f"Failed to delete symlink {symlink}: {e}")

    # Then delete the cache file itself
    if cached_features_path.exists():
        try:
            cached_features_path.unlink()
            result["deleted_cache_file"] = str(cached_features_path)
            logger.info(f"Deleted cached features: {cached_features_path}")
        except Exception as e:
            result["failed"].append((str(cached_features_path), str(e)))
            result["success"] = False
            logger.error(f"Failed to delete cached features {cached_features_path}: {e}")

    return result


def cleanup_dangling_symlinks(uploads_root: Path) -> Dict:
    """
    Find and remove all dangling symlinks in training directories.

    A dangling symlink is one whose target no longer exists.
    This can happen if cached features were deleted without using
    delete_cached_features_with_symlinks().

    Returns:
        {
            "deleted_symlinks": List[str],
            "failed": List[Tuple[str, str]],
            "total_checked": int
        }
    """
    result = {
        "deleted_symlinks": [],
        "failed": [],
        "total_checked": 0
    }

    training_dir = uploads_root / "training"
    if not training_dir.exists():
        return result

    for task_dir in training_dir.iterdir():
        if task_dir.is_dir():
            features_dir = task_dir / "features"
            if features_dir.exists():
                for feat_file in features_dir.iterdir():
                    if feat_file.is_symlink():
                        result["total_checked"] += 1
                        # Check if target exists
                        try:
                            target = feat_file.resolve()
                            if not target.exists():
                                # Dangling symlink - delete it
                                feat_file.unlink()
                                result["deleted_symlinks"].append(str(feat_file))
                                logger.info(f"Deleted dangling symlink: {feat_file}")
                        except Exception as e:
                            # If we can't resolve, it's probably dangling
                            try:
                                feat_file.unlink()
                                result["deleted_symlinks"].append(str(feat_file))
                                logger.info(f"Deleted unresolvable symlink: {feat_file}")
                            except Exception as e2:
                                result["failed"].append((str(feat_file), str(e2)))
                                logger.error(f"Failed to delete symlink {feat_file}: {e2}")

    return result


def acquire_feature_lock(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
    timeout: float = LOCK_TIMEOUT,
):
    """
    Acquire a lock for feature extraction/saving for a specific WSI.

    This should be used as a context manager to prevent race conditions
    when multiple tasks try to extract features for the same WSI.

    Usage:
        with acquire_feature_lock(uploads_root, extractor_name, params_hash, wsi_id):
            # Check cache again (another process may have just finished)
            cached = find_cached_features(...)
            if cached:
                return cached
            # Extract and save features
            features = extract_features(...)
            save_features(...)

    Args:
        uploads_root: Root directory for uploads
        extractor_name: Name of the feature extractor
        params_hash: Hash of preprocessing parameters
        wsi_id: WSI identifier
        timeout: Maximum time to wait for lock in seconds

    Returns:
        Context manager that holds the lock
    """
    lock_path = get_lock_path(uploads_root, extractor_name, params_hash, wsi_id)
    return file_lock(lock_path, timeout)


def cleanup_lock_files(uploads_root: Path) -> Dict:
    """
    Clean up stale lock files.

    Lock files are normally cleaned up when the lock is released,
    but may be left behind if a process crashes.

    Returns:
        {
            "deleted_locks": List[str],
            "failed": List[Tuple[str, str]],
            "total_checked": int
        }
    """
    result = {
        "deleted_locks": [],
        "failed": [],
        "total_checked": 0
    }

    locks_dir = uploads_root / "features" / ".locks"
    if not locks_dir.exists():
        return result

    for lock_file in locks_dir.rglob("*.lock"):
        result["total_checked"] += 1
        try:
            # Try to acquire lock - if successful, the lock is stale
            with open(lock_file, 'w') as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Lock acquired - file is stale, delete it
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    lock_file.unlink()
                    result["deleted_locks"].append(str(lock_file))
                    logger.info(f"Deleted stale lock file: {lock_file}")
                except BlockingIOError:
                    # Lock is held by another process - skip
                    pass
        except Exception as e:
            result["failed"].append((str(lock_file), str(e)))
            logger.error(f"Failed to check/delete lock file {lock_file}: {e}")

    return result
