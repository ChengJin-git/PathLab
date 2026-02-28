"""
Storage Orphan Mixin

Handles orphaned file detection, cleanup, and empty directory management.
Extracted from StorageManager for code organization.
"""

import os
import shutil
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import logging

from backend.common.file_types import WSI_EXTENSIONS, PATCH_EXTENSIONS, TIF_EXTENSIONS
from backend.common.config import Config

logger = logging.getLogger(__name__)

# All supported image extensions for orphan detection
# Combines WSI, Patch, and TIF extensions
ALL_IMAGE_EXTENSIONS: frozenset = WSI_EXTENSIONS | PATCH_EXTENSIONS | TIF_EXTENSIONS

# Orphan cache filename
ORPHAN_CACHE_FILE = ".orphan_cache.json"


class StorageOrphanMixin:
    """Mixin providing orphaned file detection and cleanup functionality."""

    # ==================== Orphan Cache Methods ====================

    def _get_orphan_cache_file_path(self) -> Path:
        """Get the path to the orphan detection persistent cache file."""
        return self.uploads_dir / ORPHAN_CACHE_FILE

    def _load_orphan_persistent_cache(self) -> None:
        """Load orphan detection cache from persistent file if available."""
        cache_file = self._get_orphan_cache_file_path()
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                cache_time = data.get("cache_time", 0)
                orphan_result = data.get("orphan_result", {})
                wsi_ids_hash = data.get("wsi_ids_hash", "")
                task_ids_hash = data.get("task_ids_hash", "")
                model_ids_hash = data.get("model_ids_hash", "")
                self._orphan_dir_mtime_cache = data.get("dir_mtimes", {})
                if orphan_result:
                    self._orphan_cache = (cache_time, orphan_result, wsi_ids_hash, task_ids_hash, model_ids_hash)
                    logger.info(f"Loaded persistent orphan cache from {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to load orphan persistent cache: {e}")
                self._orphan_cache = None
                self._orphan_dir_mtime_cache = {}

    def _save_orphan_persistent_cache(self, cache_time: float, orphan_result: Dict,
                                       wsi_ids_hash: str, task_ids_hash: str, model_ids_hash: str) -> None:
        """Save orphan detection result to persistent cache file."""
        cache_file = self._get_orphan_cache_file_path()
        try:
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "cache_time": cache_time,
                "orphan_result": orphan_result,
                "wsi_ids_hash": wsi_ids_hash,
                "task_ids_hash": task_ids_hash,
                "model_ids_hash": model_ids_hash,
                "dir_mtimes": getattr(self, '_orphan_dir_mtime_cache', {})
            }
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved persistent orphan cache to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to save orphan persistent cache: {e}")

    def _compute_ids_hash(self, ids: List[str]) -> str:
        """Compute a hash of a list of IDs for cache invalidation."""
        import hashlib
        sorted_ids = sorted(ids)
        return hashlib.md5(",".join(sorted_ids).encode()).hexdigest()

    def invalidate_orphan_cache(self) -> None:
        """Invalidate the orphan detection cache."""
        self._orphan_cache = None
        cache_file = self._get_orphan_cache_file_path()
        try:
            if cache_file.exists():
                cache_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove orphan cache file: {e}")

    # ==================== Empty Directory Cleanup ====================

    def _cleanup_empty_directories(self, deleted_file_paths: List[str]) -> List[str]:
        """
        Clean up empty parent directories after file deletion.

        Recursively removes empty directories up to (but not including)
        root-level upload directories.

        Args:
            deleted_file_paths: List of file paths that were deleted

        Returns:
            List of empty directory paths that were deleted
        """
        # Collect unique parent directories from deleted files
        parent_dirs_to_check = set()
        for file_path in deleted_file_paths:
            parent_dirs_to_check.add(Path(file_path).parent)

        # Root directories that should never be deleted
        root_dirs = {
            self.coords_dir, self.masks_dir, self.features_dir,
            self.ai_results_dir, self.training_dir, self.models_dir,
            self.logs_dir, self.wsi_files_dir, self.metadata_dir,
            self.uploads_dir
        }

        deleted_empty_dirs = []

        # Keep checking until no more directories can be deleted
        # This handles recursive empty directory chains
        while parent_dirs_to_check:
            # Sort by depth (deepest first) to clean up nested directories properly
            sorted_parents = sorted(
                parent_dirs_to_check,
                key=lambda p: len(p.parts),
                reverse=True
            )

            parent_dirs_to_check = set()  # Reset for next iteration

            for parent_dir in sorted_parents:
                try:
                    # Check if directory exists and is empty
                    if parent_dir.exists() and parent_dir.is_dir():
                        # Check if directory is empty (no files, no subdirectories)
                        if not any(parent_dir.iterdir()):
                            # Don't delete root-level upload directories
                            if parent_dir not in root_dirs:
                                parent_dir.rmdir()
                                deleted_empty_dirs.append(str(parent_dir))
                                logger.info(f"Deleted empty directory: {parent_dir}")
                                # Add grandparent to check in next iteration
                                grandparent = parent_dir.parent
                                if grandparent not in root_dirs:
                                    parent_dirs_to_check.add(grandparent)
                except Exception as e:
                    # Ignore errors when cleaning up empty directories
                    logger.debug(f"Could not remove directory {parent_dir}: {e}")

        return deleted_empty_dirs

    # ==================== Orphan Detection ====================

    def _calculate_orphaned_files(self, existing_wsi_ids: List[str], existing_task_ids: List[str],
                                    existing_model_ids: List[str]) -> Dict[str, Any]:
        """
        Calculate orphaned files by scanning directories.
        This is the expensive operation that should be cached.
        Supports incremental updates based on directory mtime.
        """
        result = {
            "orphaned_wsi_files": [],
            "orphaned_coordinates": [],
            "orphaned_masks": [],
            "orphaned_features_cache": [],
            "orphaned_ai_results": [],
            "orphaned_training_dirs": [],
            "orphaned_models": [],
            "orphaned_logs": [],
            "total_orphaned_size": 0,
            "total_orphaned_count": 0,
            "total_orphaned_file_count": 0,
            "total_orphaned_dir_count": 0
        }

        existing_wsi_set = set(existing_wsi_ids)
        existing_task_set = set(existing_task_ids)
        existing_model_set = set(existing_model_ids)

        # Get cached result for incremental updates
        cached_orphan_result = {}
        if self._orphan_cache is not None:
            _, cached_orphan_result, _, _, _ = self._orphan_cache

        new_dir_mtimes: Dict[str, float] = {}
        skipped_categories = []
        rescanned_categories = []

        def _should_use_cache(category: str, result_key: str, directory: Path) -> bool:
            """Check if we can use cached result for this category."""
            if result_key not in cached_orphan_result:
                return False
            current_mtime = self._get_directory_mtime(directory)
            cached_mtime = self._orphan_dir_mtime_cache.get(category, 0.0)
            return current_mtime == cached_mtime and cached_mtime > 0

        def _use_cached_category(category: str, result_key: str, directory: Path):
            """Use cached result for a category."""
            new_dir_mtimes[category] = self._get_directory_mtime(directory)
            cached_items = cached_orphan_result.get(result_key, [])
            result[result_key] = cached_items
            for item in cached_items:
                result["total_orphaned_size"] += item.get("size", 0)
                result["total_orphaned_count"] += 1
                # Check if item is a directory or file based on type field or path
                item_type = item.get("type", "")
                item_path = Path(item.get("path", ""))
                if item_type == "wsi_directory" or item_type in ("training", "analysis") or (item_path.exists() and item_path.is_dir()):
                    result["total_orphaned_dir_count"] += 1
                else:
                    result["total_orphaned_file_count"] += 1
            skipped_categories.append(category)

        # Check WSI/image files (uses ALL_IMAGE_EXTENSIONS from file_types.py)
        if _should_use_cache("wsi_files", "orphaned_wsi_files", self.wsi_files_dir):
            _use_cached_category("wsi_files", "orphaned_wsi_files", self.wsi_files_dir)
        else:
            rescanned_categories.append("wsi_files")
            new_dir_mtimes["wsi_files"] = self._get_directory_mtime(self.wsi_files_dir)
            if self.wsi_files_dir.exists():
                for item in self.wsi_files_dir.iterdir():
                    if item.is_file() and item.suffix.lower() in ALL_IMAGE_EXTENSIONS:
                        wsi_id = item.stem
                        if wsi_id not in existing_wsi_set:
                            size = item.stat().st_size
                            result["orphaned_wsi_files"].append({
                                "path": str(item),
                                "size": size,
                                "wsi_id": wsi_id
                            })
                            result["total_orphaned_size"] += size
                            result["total_orphaned_count"] += 1
                            result["total_orphaned_file_count"] += 1

        # Check coordinates (new structure: coordinates/{params_hash}/{wsi_id}_coords.h5)
        coords_dir = self.uploads_dir / "coordinates"
        if _should_use_cache("coordinates", "orphaned_coordinates", coords_dir):
            _use_cached_category("coordinates", "orphaned_coordinates", coords_dir)
        else:
            rescanned_categories.append("coordinates")
            new_dir_mtimes["coordinates"] = self._get_directory_mtime(coords_dir)
            if coords_dir.exists():
                # Scan all params_hash subdirectories
                for params_hash_dir in coords_dir.iterdir():
                    if params_hash_dir.is_dir():
                        for item in params_hash_dir.glob("*_coords.h5"):
                            wsi_id = item.stem.replace("_coords", "")
                            if wsi_id not in existing_wsi_set:
                                size = item.stat().st_size
                                result["orphaned_coordinates"].append({
                                    "path": str(item),
                                    "size": size,
                                    "wsi_id": wsi_id,
                                    "params_hash": params_hash_dir.name
                                })
                                result["total_orphaned_size"] += size
                                result["total_orphaned_count"] += 1
                                result["total_orphaned_file_count"] += 1

        # Check masks
        masks_dir = self.uploads_dir / "masks"
        if _should_use_cache("masks", "orphaned_masks", masks_dir):
            _use_cached_category("masks", "orphaned_masks", masks_dir)
        else:
            rescanned_categories.append("masks")
            new_dir_mtimes["masks"] = self._get_directory_mtime(masks_dir)
            if masks_dir.exists():
                for item in masks_dir.glob("*_mask.png"):
                    wsi_id = item.stem.replace("_mask", "")
                    if wsi_id not in existing_wsi_set:
                        size = item.stat().st_size
                        result["orphaned_masks"].append({
                            "path": str(item),
                            "size": size,
                            "wsi_id": wsi_id
                        })
                        result["total_orphaned_size"] += size
                        result["total_orphaned_count"] += 1
                        result["total_orphaned_file_count"] += 1


        # Check features cache (structure: features/{extractor}/{params_hash}/{wsi_id}.pt)
        features_cache_dir = self.uploads_dir / "features"
        if _should_use_cache("features_cache", "orphaned_features_cache", features_cache_dir):
            _use_cached_category("features_cache", "orphaned_features_cache", features_cache_dir)
        else:
            rescanned_categories.append("features_cache")
            new_dir_mtimes["features_cache"] = self._get_directory_mtime(features_cache_dir)
            if features_cache_dir.exists():
                for extractor_dir in features_cache_dir.iterdir():
                    if extractor_dir.is_dir():
                        for params_hash_dir in extractor_dir.iterdir():
                            if params_hash_dir.is_dir():
                                for item in params_hash_dir.glob("*.pt"):
                                    # Extract wsi_id from filename: {wsi_id}.pt
                                    wsi_id = item.stem
                                    if wsi_id not in existing_wsi_set:
                                        size = item.stat().st_size
                                        result["orphaned_features_cache"].append({
                                            "path": str(item),
                                            "size": size,
                                            "wsi_id": wsi_id,
                                            "extractor": extractor_dir.name,
                                            "params_hash": params_hash_dir.name
                                        })
                                        result["total_orphaned_size"] += size
                                        result["total_orphaned_count"] += 1
                                        result["total_orphaned_file_count"] += 1

        # Check AI results
        ai_results_dir = self.uploads_dir / "ai_results"
        if _should_use_cache("ai_results", "orphaned_ai_results", ai_results_dir):
            _use_cached_category("ai_results", "orphaned_ai_results", ai_results_dir)
        else:
            rescanned_categories.append("ai_results")
            new_dir_mtimes["ai_results"] = self._get_directory_mtime(ai_results_dir)
            if ai_results_dir.exists():
                for wsi_dir in ai_results_dir.iterdir():
                    if wsi_dir.is_dir():
                        wsi_id = wsi_dir.name
                        if wsi_id not in existing_wsi_set:
                            size = self._get_dir_size(wsi_dir)
                            result["orphaned_ai_results"].append({
                                "path": str(wsi_dir),
                                "size": size,
                                "wsi_id": wsi_id,
                                "type": "wsi_directory"
                            })
                            result["total_orphaned_size"] += size
                            result["total_orphaned_count"] += 1
                            result["total_orphaned_dir_count"] += 1
                        else:
                            for file_item in wsi_dir.iterdir():
                                if file_item.is_file():
                                    filename = file_item.stem
                                    task_id = None
                                    for suffix in ["_result", "_attention_raw", "_attention", "_cam"]:
                                        if filename.endswith(suffix):
                                            name_without_suffix = filename[:-len(suffix)]
                                            if name_without_suffix.startswith("train_"):
                                                task_id = name_without_suffix[6:]
                                            else:
                                                task_id = name_without_suffix
                                            break
                                    if task_id is None:
                                        continue
                                    if task_id not in existing_task_set:
                                        size = file_item.stat().st_size
                                        result["orphaned_ai_results"].append({
                                            "path": str(file_item),
                                            "size": size,
                                            "wsi_id": wsi_id,
                                            "task_id": task_id,
                                            "type": "task_file"
                                        })
                                        result["total_orphaned_size"] += size
                                        result["total_orphaned_count"] += 1
                                        result["total_orphaned_file_count"] += 1

        # Check training directories
        training_dir = self.uploads_dir / "training"
        if _should_use_cache("training", "orphaned_training_dirs", training_dir):
            _use_cached_category("training", "orphaned_training_dirs", training_dir)
        else:
            rescanned_categories.append("training")
            new_dir_mtimes["training"] = self._get_directory_mtime(training_dir)
            if training_dir.exists():
                for task_dir in training_dir.iterdir():
                    if task_dir.is_dir():
                        task_id = task_dir.name
                        if task_id not in existing_task_set:
                            size = self._get_dir_size(task_dir)
                            result["orphaned_training_dirs"].append({
                                "path": str(task_dir),
                                "size": size,
                                "task_id": task_id
                            })
                            result["total_orphaned_size"] += size
                            result["total_orphaned_count"] += 1
                            result["total_orphaned_dir_count"] += 1

        # Check models
        models_dir = self.uploads_dir / "models"
        if _should_use_cache("models", "orphaned_models", models_dir):
            _use_cached_category("models", "orphaned_models", models_dir)
        else:
            rescanned_categories.append("models")
            new_dir_mtimes["models"] = self._get_directory_mtime(models_dir)
            if models_dir.exists():
                for model_dir in models_dir.iterdir():
                    if model_dir.is_dir():
                        model_id = model_dir.name
                        if model_id not in existing_model_set:
                            size = self._get_dir_size(model_dir)
                            result["orphaned_models"].append({
                                "path": str(model_dir),
                                "size": size,
                                "model_id": model_id
                            })
                            result["total_orphaned_size"] += size
                            result["total_orphaned_count"] += 1
                            result["total_orphaned_dir_count"] += 1

        # Check logs
        logs_dir = self.uploads_dir / "logs"
        if _should_use_cache("logs", "orphaned_logs", logs_dir):
            _use_cached_category("logs", "orphaned_logs", logs_dir)
        else:
            rescanned_categories.append("logs")
            new_dir_mtimes["logs"] = self._get_directory_mtime(logs_dir)
            if logs_dir.exists():
                training_logs_dir = logs_dir / "training"
                if training_logs_dir.exists():
                    for task_dir in training_logs_dir.iterdir():
                        if task_dir.is_dir():
                            task_id = task_dir.name
                            if task_id not in existing_task_set:
                                size = self._get_dir_size(task_dir)
                                result["orphaned_logs"].append({
                                    "path": str(task_dir),
                                    "size": size,
                                    "task_id": task_id,
                                    "log_type": "training"
                                })
                                result["total_orphaned_size"] += size
                                result["total_orphaned_count"] += 1
                                result["total_orphaned_dir_count"] += 1

                analysis_logs_dir = logs_dir / "analysis"
                if analysis_logs_dir.exists():
                    for task_dir in analysis_logs_dir.iterdir():
                        if task_dir.is_dir():
                            task_id = task_dir.name
                            if task_id not in existing_task_set:
                                size = self._get_dir_size(task_dir)
                                result["orphaned_logs"].append({
                                    "path": str(task_dir),
                                    "size": size,
                                    "task_id": task_id,
                                    "log_type": "analysis"
                                })
                                result["total_orphaned_size"] += size
                                result["total_orphaned_count"] += 1
                                result["total_orphaned_dir_count"] += 1

                for item in logs_dir.glob("*.log"):
                    task_id = item.stem
                    if task_id not in existing_task_set:
                        size = item.stat().st_size
                        result["orphaned_logs"].append({
                            "path": str(item),
                            "size": size,
                            "task_id": task_id,
                            "log_type": "legacy"
                        })
                        result["total_orphaned_size"] += size
                        result["total_orphaned_count"] += 1
                        result["total_orphaned_file_count"] += 1

        # Update mtime cache
        self._orphan_dir_mtime_cache = new_dir_mtimes

        # Log incremental update info
        if skipped_categories:
            logger.info(f"Orphan detection: skipped {len(skipped_categories)} unchanged dirs: {skipped_categories}")
        if rescanned_categories:
            logger.info(f"Orphan detection: rescanned {len(rescanned_categories)} changed dirs: {rescanned_categories}")

        return result

    def _refresh_orphan_background(self, existing_wsi_ids: List[str], existing_task_ids: List[str],
                                    existing_model_ids: List[str], wsi_hash: str, task_hash: str, model_hash: str) -> None:
        """Background thread function to refresh orphan detection."""
        try:
            logger.info("Starting background orphan detection refresh...")
            start_time = time.time()
            result = self._calculate_orphaned_files(existing_wsi_ids, existing_task_ids, existing_model_ids)
            current_time = time.time()

            # Update memory cache
            self._orphan_cache = (current_time, result.copy(), wsi_hash, task_hash, model_hash)

            # Save to persistent cache
            self._save_orphan_persistent_cache(current_time, result, wsi_hash, task_hash, model_hash)

            elapsed = current_time - start_time
            logger.info(f"Background orphan detection completed in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Background orphan detection failed: {e}")
        finally:
            with self._orphan_refresh_lock:
                self._orphan_refresh_in_progress = False

    def _trigger_orphan_background_refresh(self, existing_wsi_ids: List[str], existing_task_ids: List[str],
                                            existing_model_ids: List[str], wsi_hash: str, task_hash: str, model_hash: str) -> None:
        """Trigger a background orphan refresh if not already in progress."""
        with self._orphan_refresh_lock:
            if self._orphan_refresh_in_progress:
                return
            self._orphan_refresh_in_progress = True

        thread = threading.Thread(
            target=self._refresh_orphan_background,
            args=(existing_wsi_ids, existing_task_ids, existing_model_ids, wsi_hash, task_hash, model_hash),
            daemon=True
        )
        thread.start()

    def find_orphaned_files(self, existing_wsi_ids: List[str], existing_task_ids: List[str],
                            existing_model_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Find files that exist in the file system but not in the database.

        Uses stale-while-revalidate caching for performance:
        1. Fresh cache (< ORPHAN_CACHE_TTL): Return immediately
        2. Stale cache (< ORPHAN_STALE_TTL): Return stale data, trigger background refresh
        3. No cache or expired: Calculate synchronously

        Args:
            existing_wsi_ids: List of WSI IDs that exist in the database
            existing_task_ids: List of training task IDs that exist in the database
            existing_model_ids: List of model IDs that exist in the database

        Returns:
            Dictionary with orphaned file information per category
        """
        if existing_model_ids is None:
            existing_model_ids = []

        current_time = time.time()

        # Compute hashes for cache invalidation
        wsi_hash = self._compute_ids_hash(existing_wsi_ids)
        task_hash = self._compute_ids_hash(existing_task_ids)
        model_hash = self._compute_ids_hash(existing_model_ids)

        # Check cache validity
        if self._orphan_cache is not None:
            cache_time, cached_result, cached_wsi_hash, cached_task_hash, cached_model_hash = self._orphan_cache
            cache_age = current_time - cache_time

            # Check if database IDs have changed
            ids_changed = (wsi_hash != cached_wsi_hash or task_hash != cached_task_hash or model_hash != cached_model_hash)

            if not ids_changed and cache_age < Config.ORPHAN_CACHE_TTL:
                # Fresh cache - return immediately
                result = cached_result.copy()
                result["cached"] = True
                result["stale"] = False
                return result
            elif not ids_changed and cache_age < Config.ORPHAN_STALE_TTL:
                # Stale cache - return stale data but trigger background refresh
                result = cached_result.copy()
                result["cached"] = True
                result["stale"] = True
                self._trigger_orphan_background_refresh(existing_wsi_ids, existing_task_ids, existing_model_ids,
                                                        wsi_hash, task_hash, model_hash)
                return result

        # No cache, cache too old, or IDs changed - calculate synchronously
        # But first check if another scan is already in progress
        if self._scan_in_progress:
            logger.info("Another scan is in progress, returning stale orphan cache if available...")
            if self._orphan_cache is not None:
                _, cached_result, _, _, _ = self._orphan_cache
                result = cached_result.copy()
                result["cached"] = True
                result["stale"] = True
                return result

        # Acquire global scan lock to prevent concurrent heavy I/O
        acquired = self._global_scan_lock.acquire(timeout=1)
        if not acquired:
            logger.info("Could not acquire scan lock for orphan detection, returning stale cache...")
            if self._orphan_cache is not None:
                _, cached_result, _, _, _ = self._orphan_cache
                result = cached_result.copy()
                result["cached"] = True
                result["stale"] = True
                return result
            # No cache at all - must wait
            self._global_scan_lock.acquire()

        try:
            self._scan_in_progress = True
            logger.info("No valid orphan cache available, calculating synchronously...")
            start_time = time.time()
            result = self._calculate_orphaned_files(existing_wsi_ids, existing_task_ids, existing_model_ids)
            current_time = time.time()

            # Update memory cache
            self._orphan_cache = (current_time, result.copy(), wsi_hash, task_hash, model_hash)

            # Save to persistent cache
            self._save_orphan_persistent_cache(current_time, result, wsi_hash, task_hash, model_hash)

            elapsed = current_time - start_time
            logger.info(f"Orphan detection completed in {elapsed:.2f}s")

            result["cached"] = False
            result["stale"] = False
            return result
        finally:
            self._scan_in_progress = False
            self._global_scan_lock.release()

    def cleanup_orphaned_files(self, orphaned_files: Dict[str, Any], categories: List[str] = None) -> Dict[str, Any]:
        """
        Clean up orphaned files.

        Args:
            orphaned_files: Result from find_orphaned_files()
            categories: List of categories to clean up. If None, clean up all.
                       Options: ["wsi_files", "coordinates", "masks",
                                "ai_results", "training_dirs", "logs"]

        Returns:
            Dictionary with deletion results and summary
        """
        if categories is None:
            categories = ["wsi_files", "coordinates", "masks", "features_cache",
                         "ai_results", "training_dirs", "models", "logs"]

        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        category_map = {
            "wsi_files": "orphaned_wsi_files",
            "coordinates": "orphaned_coordinates",
            "masks": "orphaned_masks",
            "features_cache": "orphaned_features_cache",
            "ai_results": "orphaned_ai_results",
            "training_dirs": "orphaned_training_dirs",
            "models": "orphaned_models",
            "logs": "orphaned_logs"
        }

        for category in categories:
            orphaned_key = category_map.get(category)
            if not orphaned_key or orphaned_key not in orphaned_files:
                continue

            for item in orphaned_files[orphaned_key]:
                path = Path(item["path"])
                size = item["size"]

                try:
                    if path.is_file():
                        path.unlink()
                        deleted_files.append(str(path))
                        total_size += size
                        logger.info(f"Deleted orphaned file: {path}")
                    elif path.is_dir():
                        shutil.rmtree(path)
                        deleted_dirs.append(str(path))
                        total_size += size
                        logger.info(f"Deleted orphaned directory: {path}")
                except Exception as e:
                    failed.append((str(path), str(e)))
                    logger.error(f"Failed to delete {path}: {e}")

        # Clean up empty parent directories after file deletion
        # This recursively removes empty parent directories up to root upload directories
        deleted_empty_dirs = self._cleanup_empty_directories(deleted_files)
        # Add empty dirs to deleted_dirs for comprehensive tracking
        deleted_dirs.extend(deleted_empty_dirs)

        summary = (
            f"Orphaned files cleanup: {len(deleted_files)} files, "
            f"{len(deleted_dirs)} directories deleted ({len(deleted_empty_dirs)} empty), "
            f"{len(failed)} failed, {total_size / (1024**2):.2f} MB freed"
        )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "deleted_empty_dirs": deleted_empty_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary
        }