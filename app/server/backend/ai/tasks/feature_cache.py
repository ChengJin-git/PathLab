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

import asyncio
from backend.common import file_lock as fcntl
import json
import logging
import os
import pickle
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import torch

from backend.common.config import Config
from backend.common.coords_cache import compute_params_hash

logger = logging.getLogger(__name__)


# Interval for logging wait status (seconds)
LOCK_WAIT_LOG_INTERVAL = 30


class FeatureLockTimeoutError(TimeoutError):
    """
    Raised when feature lock cannot be acquired within timeout.

    Contains additional context for graceful handling.
    """

    def __init__(self, lock_path: Path, timeout: float, wsi_id: str = None):
        self.lock_path = lock_path
        self.timeout = timeout
        self.wsi_id = wsi_id
        message = f"Could not acquire lock on {lock_path} within {timeout} seconds"
        if wsi_id:
            message = f"Feature extraction lock timeout for WSI {wsi_id}: {message}"
        super().__init__(message)


class LockBusyError(Exception):
    """
    Raised by try_file_lock_nowait when the lock is currently held by another process.

    Unlike FeatureLockTimeoutError (which implies a long wait that expired),
    LockBusyError is raised immediately without any waiting.
    Callers should handle this by deferring the WSI to a later pass.
    """

    def __init__(self, wsi_id: Optional[str] = None, lock_path: Optional[Path] = None):
        self.wsi_id = wsi_id
        self.lock_path = lock_path
        who = wsi_id or str(lock_path) or "unknown"
        super().__init__(f"Feature lock busy (held by another task) for {who}")


@asynccontextmanager
async def file_lock(
    lock_path: Path,
    timeout: float = None,
    cancellation_check: callable = None,
    wait_callback: callable = None,
    wsi_id: str = None,
):
    """
    Async context manager for file-based locking using fcntl.flock.

    This provides exclusive access to a resource identified by lock_path.
    Uses non-blocking lock with retry to implement timeout.

    Uses asyncio.sleep() instead of time.sleep() to avoid blocking the event loop
    while waiting for the lock, allowing other coroutines to run.

    Supports cancellation checking and progress callbacks for better user experience
    when multiple tasks are waiting for the same WSI feature extraction.

    Args:
        lock_path: Path to the lock file (will be created if not exists)
        timeout: Maximum time to wait for lock in seconds
        cancellation_check: Optional callable that returns True if task should be cancelled.
                           Called periodically during lock wait.
        wait_callback: Optional callable(wait_seconds) called periodically while waiting.
                      Can be used to log progress or update UI.
        wsi_id: Optional WSI ID for better error messages

    Raises:
        FeatureLockTimeoutError: If lock cannot be acquired within timeout
        TrainingCancelledException: If cancellation_check returns True (if provided)
    """
    import time
    from backend.ai.cancellation import TrainingCancelledException

    # Use default timeout from Config if not specified
    if timeout is None:
        timeout = Config.FEATURE_LOCK_TIMEOUT

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")

    start_time = time.time()
    last_log_time = start_time
    acquired = False

    try:
        while time.time() - start_time < timeout:
            try:
                # Try to acquire exclusive lock (non-blocking)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                # Lock is held by another process
                elapsed = time.time() - start_time

                # Check for cancellation
                if cancellation_check and cancellation_check():
                    lock_file.close()
                    raise TrainingCancelledException(
                        f"Task cancelled while waiting for feature lock on {wsi_id or lock_path}"
                    )

                # Periodic callback for progress reporting
                if (
                    wait_callback
                    and (time.time() - last_log_time) >= LOCK_WAIT_LOG_INTERVAL
                ):
                    wait_callback(elapsed)
                    last_log_time = time.time()

                # Wait and retry - use asyncio.sleep to release event loop
                await asyncio.sleep(0.5)

        if not acquired:
            raise FeatureLockTimeoutError(lock_path, timeout, wsi_id)

        yield lock_file

    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


@asynccontextmanager
async def try_file_lock_nowait(lock_path: Path, wsi_id: Optional[str] = None):
    """
    Async context manager: acquire file lock non-blocking.
    Raises LockBusyError immediately if the lock is held. Never waits.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            lock_file.close()
            raise LockBusyError(wsi_id=wsi_id, lock_path=lock_path)
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
    If a .pt.partial file is found, it indicates a previous extraction was
    interrupted — the partial file is deleted and None is returned.
    """
    features_path = get_cached_features_path(
        uploads_root, extractor_name, params_hash, wsi_id
    )

    # Check for incomplete extraction artifact
    partial_path = features_path.parent / f"{wsi_id}.pt.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete feature file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    if features_path.exists():
        logger.info(f"Found cached features: {features_path}")
        return features_path

    return None


def save_features(feature_path: Path, features: torch.Tensor, contract: dict | None = None) -> bool:
    """
    Save features to PyTorch .pt file using atomic write pattern.

    Writes to a .pt.partial temporary file first, then renames to .pt.
    This ensures that if the process is interrupted during saving,
    the incomplete file is clearly identifiable and won't be mistaken
    for a valid cache entry.

    Refuses to save empty tensors (shape[0] == 0) to prevent polluting the
    cache with features from WSIs where tissue segmentation failed.

    Args:
        feature_path: Path to save the .pt file
        features: Feature tensor of shape (num_patches, feature_dim)

    Returns:
        True if saved successfully, False if refused (empty tensor).
    """
    # Guard: refuse to cache empty feature tensors.
    # These result from WSIs with 0 valid patches (segmentation failure)
    # and would crash the training aggregator downstream.
    if features.ndim >= 1 and features.shape[0] == 0:
        logger.warning(
            f"[Fallback] Refusing to save empty feature tensor {tuple(features.shape)} "
            f"to {feature_path}. The source WSI likely has no detectable tissue."
        )
        return False

    feature_path = Path(feature_path)
    feature_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to .partial file first, then atomically rename
    partial_path = feature_path.parent / f"{feature_path.stem}.pt.partial"
    torch.save(features.cpu(), partial_path)
    partial_path.rename(feature_path)
    from backend.services.viewer_features import record_feature_contract
    record_feature_contract(feature_path,contract)
    return True


def safe_load_features(
    feature_path: Path,
    delete_if_corrupted: bool = True,
    device: Optional[str] = None,
):
    """
    Safely load features from PyTorch .pt file, handling corrupted files gracefully.

    This is important for system recovery after power loss or crashes,
    where .pt files may be incomplete/corrupted if they were being written
    when the system went down.

    Args:
        feature_path: Path to the .pt feature file
        delete_if_corrupted: If True, delete corrupted files automatically
        device: Target device for loading (e.g., 'cuda:0'). If specified,
                features are loaded directly to this device, avoiding
                CPU -> GPU transfer overhead.

    Returns:
        Tuple of (tensor, None) if successful,
        or (None, error_message) if file is corrupted/unreadable

    The caller should handle the None case by re-extracting features.
    """
    try:
        # Direct GPU loading when device is specified - avoids CPU->GPU transfer overhead
        if device is not None:
            feats = torch.load(feature_path, map_location=device, weights_only=True)
        else:
            feats = torch.load(feature_path, map_location="cpu", weights_only=True)
        return feats, None
    except (RuntimeError, pickle.UnpicklingError, EOFError) as e:
        error_msg = str(e)
        logger.warning(
            f"Detected corrupted feature file (likely from power loss): {feature_path}. "
            f"Error: {error_msg}"
        )
        if delete_if_corrupted:
            try:
                # Resolve symlink if needed to delete the actual corrupted file
                actual_path = (
                    feature_path.resolve()
                    if feature_path.is_symlink()
                    else feature_path
                )

                # Delete the corrupted file
                actual_path.unlink()
                logger.info(f"Deleted corrupted feature file: {actual_path}")

                # Also delete the symlink if it was a symlink
                if feature_path.is_symlink() and feature_path.exists():
                    feature_path.unlink()
                    logger.info(f"Deleted symlink to corrupted file: {feature_path}")

            except Exception as del_e:
                logger.error(f"Failed to delete corrupted file {feature_path}: {del_e}")

        return None, f"Corrupted file (will re-extract): {error_msg}"
    except Exception as e:
        # Other errors (file not found, permission, etc.)
        logger.error(f"Failed to load feature file {feature_path}: {e}")
        return None, str(e)


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


# Required attributes that must exist in coords.h5 for valid cache
# Note: patch_size and stride are NOT required for hash - they're auto-determined by MPP
REQUIRED_COORDS_ATTRS = [
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
]


def read_params_from_coords_h5(coords_h5_path: Path) -> Optional[str]:
    """
    Read preprocessing parameters from a coordinates H5 file and compute params_hash.

    This is useful for inference when we don't have the original preprocessing config
    but need to find cached features that match the coordinates.

    Returns params_hash if successful, None if file doesn't exist or lacks required attrs.

    PrePATH-style: patch_size and stride are NOT used for hash calculation
    because they are automatically determined by each WSI's magnification/MPP.

    NOTE: All required attributes must exist in the h5 file. Old cache files without
    complete attributes will return None, forcing recomputation.
    """
    from backend.preprocessing.coords_utils import safe_load_h5_coords

    if not coords_h5_path.exists():
        return None

    # Use safe loading to handle corrupted files (e.g., from power loss)
    _, attrs, load_error = safe_load_h5_coords(
        coords_h5_path, delete_if_corrupted=False
    )

    if attrs is None:
        logger.warning(f"Failed to load coords H5 for params: {load_error}")
        return None

    try:
        # Check all required attributes exist
        missing_attrs = [attr for attr in REQUIRED_COORDS_ATTRS if attr not in attrs]
        if missing_attrs:
            logger.warning(
                f"Missing required attributes in {coords_h5_path}: {missing_attrs}. "
                "This is likely an old cache file that needs recomputation."
            )
            return None

        # Required parameters (NOT patch_size/stride - they're auto-determined)
        level = int(attrs["patch_level"])
        contour_fn = attrs["contour_fn"]
        use_padding = bool(attrs["use_padding"])
        seg_level = int(attrs["seg_level"])

        # Handle bytes vs string for contour_fn
        if isinstance(contour_fn, bytes):
            contour_fn = contour_fn.decode("utf-8")

        # Segmentation parameters
        seg_params = {
            "sthresh": int(attrs["sthresh"]),
            "mthresh": int(attrs["mthresh"]),
            "close": int(attrs["close"]),
            "use_otsu": bool(attrs["use_otsu"]),
        }

        # Filter parameters
        filter_params = {
            "a_t": int(attrs["a_t"]),
            "a_h": int(attrs["a_h"]),
            "max_n_holes": int(attrs["max_n_holes"]),
        }

        return compute_params_hash(
            level=level,
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=contour_fn,
            use_padding=use_padding,
            seg_level=seg_level,
        )
    except Exception as e:
        logger.warning(f"Failed to read params from {coords_h5_path}: {e}")
        return None


def create_symlink_to_cache(
    task_features_dir: Path, wsi_id: str, cached_features_path: Path
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
        if os.name == 'nt':
            # Standard Windows users cannot create symlinks without Developer
            # Mode. Hard links retain independent directory entries; cross-volume
            # storage falls back to a copy, preserving the selected cache data.
            try:
                os.link(cached_features_path, symlink_path)
            except OSError:
                import shutil
                shutil.copy2(cached_features_path, symlink_path)
        else:
            symlink_path.symlink_to(cached_features_path)
        logger.info('Created feature-cache fallback link/copy: %s', symlink_path)

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
    uploads_root: Path, cached_features_path: Path
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
) -> Dict[str, Any]:
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
        "success": True,
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
            logger.error(
                f"Failed to delete cached features {cached_features_path}: {e}"
            )

    return result


def cleanup_dangling_symlinks(uploads_root: Path) -> Dict[str, Any]:
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
    result = {"deleted_symlinks": [], "failed": [], "total_checked": 0}

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
                                logger.info(
                                    f"Deleted unresolvable symlink: {feat_file}"
                                )
                            except Exception as e2:
                                result["failed"].append((str(feat_file), str(e2)))
                                logger.error(
                                    f"Failed to delete symlink {feat_file}: {e2}"
                                )

    return result


def acquire_feature_lock(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
    timeout: float = None,
    cancellation_check: callable = None,
    wait_callback: callable = None,
):
    """
    Acquire a lock for feature extraction/saving for a specific WSI.

    This should be used as an async context manager to prevent race conditions
    when multiple tasks try to extract features for the same WSI.

    When multiple users submit tasks for the same dataset simultaneously,
    only one task will extract features while others wait. The waiting tasks
    will use the cached result once extraction completes.

    Usage:
        def check_cancelled():
            return is_task_cancelled(task_id)

        def on_wait(seconds):
            logger.info(f"Waiting {seconds:.0f}s for another task to finish extracting {wsi_id}")

        async with acquire_feature_lock(
            uploads_root, extractor_name, params_hash, wsi_id,
            cancellation_check=check_cancelled,
            wait_callback=on_wait
        ):
            # Check cache again (another process may have just finished)
            cached = find_cached_features(...)
            if cached:
                return cached
            # Extract and save features
            features = await asyncio.to_thread(extract_features, ...)
            await asyncio.to_thread(save_features, ...)

    Args:
        uploads_root: Root directory for uploads
        extractor_name: Name of the feature extractor
        params_hash: Hash of preprocessing parameters
        wsi_id: WSI identifier
        timeout: Maximum time to wait for lock in seconds
        cancellation_check: Optional callable that returns True if task should be cancelled
        wait_callback: Optional callable(wait_seconds) for progress reporting

    Returns:
        Async context manager that holds the lock

    Raises:
        FeatureLockTimeoutError: If lock cannot be acquired within timeout
        TrainingCancelledException: If cancellation_check returns True
    """
    lock_path = get_lock_path(uploads_root, extractor_name, params_hash, wsi_id)
    return file_lock(
        lock_path,
        timeout,
        cancellation_check=cancellation_check,
        wait_callback=wait_callback,
        wsi_id=wsi_id,
    )


def try_acquire_feature_lock_nowait(
    uploads_root: Path,
    extractor_name: str,
    params_hash: str,
    wsi_id: str,
):
    """Non-blocking variant of acquire_feature_lock. Raises LockBusyError immediately if held."""
    lock_path = get_lock_path(uploads_root, extractor_name, params_hash, wsi_id)
    return try_file_lock_nowait(lock_path, wsi_id=wsi_id)


def cleanup_lock_files(uploads_root: Path) -> Dict[str, Any]:
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
    result = {"deleted_locks": [], "failed": [], "total_checked": 0}

    locks_dir = uploads_root / "features" / ".locks"
    if not locks_dir.exists():
        return result

    for lock_file in locks_dir.rglob("*.lock"):
        result["total_checked"] += 1
        try:
            # Try to acquire lock - if successful, the lock is stale
            with open(lock_file, "w") as f:
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
