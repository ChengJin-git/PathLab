"""
Storage Stats Mixin

Handles storage statistics calculation, caching, and utility methods.
Extracted from StorageManager for code organization.
"""

import os
import json
import time
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import logging

from backend.common.config import Config

logger = logging.getLogger(__name__)

# Persistent cache filename
STORAGE_STATS_CACHE_FILE = ".storage_stats_cache.json"


class StorageStatsMixin:
    """Mixin providing storage statistics and caching functionality."""

    # ==================== Stats Cache Methods ====================

    def _get_cache_file_path(self) -> Path:
        """Get the path to the persistent cache file."""
        return self.uploads_dir / STORAGE_STATS_CACHE_FILE

    def _load_persistent_cache(self) -> None:
        """Load storage stats from persistent cache file if available."""
        cache_file = self._get_cache_file_path()
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                cache_time = data.get("cache_time", 0)
                stats = data.get("stats", {})
                # Load directory mtime cache for incremental updates
                self._dir_mtime_cache = data.get("dir_mtimes", {})
                if stats:
                    self._stats_cache = (cache_time, stats)
                    # Mark that this cache was loaded from persistent storage
                    # This allows us to use mtime-based validation instead of TTL
                    self._stats_cache_from_persistent = True
                    logger.info(f"Loaded persistent storage stats cache from {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to load persistent cache: {e}")
                self._stats_cache = None
                self._stats_cache_from_persistent = False
                self._dir_mtime_cache = {}

    def _save_persistent_cache(self, cache_time: float, stats: Dict) -> None:
        """Save storage stats to persistent cache file."""
        cache_file = self._get_cache_file_path()
        try:
            # Ensure uploads directory exists
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "cache_time": cache_time,
                "stats": stats,
                "dir_mtimes": getattr(self, '_dir_mtime_cache', {})
            }
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved persistent storage stats cache to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to save persistent cache: {e}")

    def _get_directory_mtime(self, directory: Path) -> float:
        """
        Get the maximum mtime of a directory and its contents.

        For incremental updates, we need to detect if any file in the directory
        has changed. We use the directory's own mtime plus check subdirectories.

        Uses os.scandir() for efficiency - avoids extra stat calls per entry
        since DirEntry caches file type info from the OS readdir result.
        """
        dir_str = str(directory)
        if not os.path.exists(dir_str):
            return 0.0
        try:
            # Get directory's own mtime
            max_mtime = os.stat(dir_str).st_mtime
            # Also check immediate subdirectories (for nested structures)
            with os.scandir(dir_str) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            item_mtime = entry.stat().st_mtime
                            if item_mtime > max_mtime:
                                max_mtime = item_mtime
                        except (OSError, IOError):
                            pass
            return max_mtime
        except (OSError, IOError):
            return 0.0

    def _is_cache_still_valid_by_mtime(self) -> bool:
        """
        Check if cached stats are still valid by comparing directory mtimes.

        This is used for persistent caches loaded after restart to avoid
        full recalculation when directories haven't changed.

        Returns:
            True if all monitored directories have the same mtime as cached.
        """
        if not self._dir_mtime_cache:
            return False

        directories = [
            ("coordinates", self.coords_dir),
            ("masks", self.masks_dir),
            ("ai_results", self.ai_results_dir),
            ("features_cache", self.uploads_dir / "features"),
            ("training", self.training_dir),
            ("models", self.models_dir),
            ("logs", self.logs_dir),
            ("wsi_files", self.wsi_files_dir),
        ]

        for category, directory in directories:
            current_mtime = self._get_directory_mtime(directory)
            cached_mtime = self._dir_mtime_cache.get(category, 0.0)
            if current_mtime != cached_mtime:
                logger.debug(f"Directory {category} mtime changed: {cached_mtime} -> {current_mtime}")
                return False

        return True

    def invalidate_stats_cache(self) -> None:
        """Invalidate the storage stats cache. Call after file operations."""
        self._stats_cache = None
        # Also remove persistent cache file
        cache_file = self._get_cache_file_path()
        try:
            if cache_file.exists():
                cache_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove persistent cache file: {e}")

    # ==================== Stats Calculation Methods ====================

    def _calculate_storage_stats(self) -> Dict:
        """
        Calculate storage statistics with incremental updates.

        Uses directory mtime to detect changes. Only re-scans directories
        whose mtime has changed since the last scan.
        """
        stats = {
            "uploads_dir": str(self.uploads_dir),
            "total_size": 0,
            "breakdown": {},
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
            "cached": False
        }

        # Get cached stats for comparison (if available)
        cached_breakdown = {}
        if self._stats_cache is not None:
            _, cached_stats = self._stats_cache
            cached_breakdown = cached_stats.get("breakdown", {})

        # Track new directory mtimes
        new_dir_mtimes: Dict[str, float] = {}
        skipped_dirs = []
        rescanned_dirs = []

        # Define directories to scan: (category_name, directory_path)
        directories = [
            ("coordinates", self.coords_dir),
            ("masks", self.masks_dir),
            ("ai_results", self.ai_results_dir),
            ("features_cache", self.uploads_dir / "features"),
            ("training", self.training_dir),
            ("models", self.models_dir),
            ("logs", self.logs_dir),
        ]

        for category, directory in directories:
            current_mtime = self._get_directory_mtime(directory)
            cached_mtime = self._dir_mtime_cache.get(category, 0.0)

            # Check if directory has changed
            if current_mtime == cached_mtime and cached_mtime > 0 and category in cached_breakdown:
                # Directory unchanged - use cached stats
                category_stats = cached_breakdown[category]
                skipped_dirs.append(category)
            else:
                # Directory changed or no cache - rescan
                category_stats = self._get_directory_stats(directory)
                rescanned_dirs.append(category)

            stats["breakdown"][category] = category_stats
            stats["total_size"] += category_stats["size"]
            new_dir_mtimes[category] = current_mtime

        # WSI files - special handling (flat directory, no subdirs)
        wsi_mtime = self._get_directory_mtime(self.wsi_files_dir)
        cached_wsi_mtime = self._dir_mtime_cache.get("wsi_files", 0.0)

        if wsi_mtime == cached_wsi_mtime and cached_wsi_mtime > 0 and "wsi_files" in cached_breakdown:
            # WSI directory unchanged - use cached stats
            wsi_stats = cached_breakdown["wsi_files"]
            skipped_dirs.append("wsi_files")
        else:
            # WSI directory changed - rescan
            wsi_files_size = 0
            wsi_files_count = 0
            if self.wsi_files_dir.exists():
                for item in self.wsi_files_dir.iterdir():
                    if item.is_file():
                        wsi_files_size += item.stat().st_size
                        wsi_files_count += 1
            wsi_stats = {"size": wsi_files_size, "file_count": wsi_files_count}
            rescanned_dirs.append("wsi_files")

        stats["breakdown"]["wsi_files"] = wsi_stats
        stats["total_size"] += wsi_stats["size"]
        new_dir_mtimes["wsi_files"] = wsi_mtime

        # Update mtime cache
        self._dir_mtime_cache = new_dir_mtimes

        # Log incremental update info
        if skipped_dirs:
            logger.info(f"Incremental update: skipped {len(skipped_dirs)} unchanged dirs: {skipped_dirs}")
        if rescanned_dirs:
            logger.info(f"Incremental update: rescanned {len(rescanned_dirs)} changed dirs: {rescanned_dirs}")

        return stats

    def _refresh_stats_background(self) -> None:
        """Background thread function to refresh storage stats."""
        try:
            logger.info("Starting background storage stats refresh...")
            start_time = time.time()
            stats = self._calculate_storage_stats()
            current_time = time.time()

            # Update memory cache
            self._stats_cache = (current_time, stats.copy())

            # Save to persistent cache
            self._save_persistent_cache(current_time, stats)

            elapsed = current_time - start_time
            logger.info(f"Background storage stats refresh completed in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Background storage stats refresh failed: {e}")
        finally:
            with self._stats_refresh_lock:
                self._stats_refresh_in_progress = False

    def _trigger_background_refresh(self) -> None:
        """Trigger a background refresh if not already in progress."""
        with self._stats_refresh_lock:
            if self._stats_refresh_in_progress:
                return
            self._stats_refresh_in_progress = True

        # Start background thread
        thread = threading.Thread(target=self._refresh_stats_background, daemon=True)
        thread.start()

    def get_total_storage_stats(self, force_refresh: bool = False) -> Dict:
        """
        Get overall storage statistics with stale-while-revalidate caching.

        Uses a multi-tier caching strategy:
        1. Fresh cache (< STORAGE_STATS_CACHE_TTL): Return immediately
        2. Stale cache (< STORAGE_STATS_STALE_TTL): Return stale data, trigger background refresh
        3. No cache or expired: Calculate synchronously (first load only)

        Cache is persisted to disk for fast startup after service restart.

        Args:
            force_refresh: If True, bypass cache and recalculate stats synchronously

        Returns:
            Dictionary with storage statistics
        """
        current_time = time.time()

        # Check cache validity
        if not force_refresh and self._stats_cache is not None:
            cache_time, cached_stats = self._stats_cache
            cache_age = current_time - cache_time

            if cache_age < Config.STORAGE_STATS_CACHE_TTL:
                # Fresh cache - return immediately
                result = cached_stats.copy()
                result["cached"] = True
                result["stale"] = False
                return result
            elif cache_age < Config.STORAGE_STATS_STALE_TTL:
                # Stale cache - return stale data but trigger background refresh
                result = cached_stats.copy()
                result["cached"] = True
                result["stale"] = True
                # Trigger background refresh
                self._trigger_background_refresh()
                return result
            elif self._stats_cache_from_persistent:
                # Cache was loaded from persistent storage after restart
                # Check if directories have actually changed using mtime
                if self._is_cache_still_valid_by_mtime():
                    logger.info("Persistent cache valid (no directory changes detected), using cached stats")
                    result = cached_stats.copy()
                    result["cached"] = True
                    result["stale"] = True
                    # Update cache_time to current time so subsequent calls are fast
                    self._stats_cache = (current_time, cached_stats)
                    self._stats_cache_from_persistent = False
                    # Save with updated timestamp
                    self._save_persistent_cache(current_time, cached_stats)
                    return result
                else:
                    logger.info("Persistent cache invalid (directory changes detected), will recalculate")

        # No cache or cache too old - calculate synchronously
        # But first check if another scan is already in progress
        if self._scan_in_progress:
            logger.info("Another scan is in progress, returning stale cache if available...")
            if self._stats_cache is not None:
                _, cached_stats = self._stats_cache
                result = cached_stats.copy()
                result["cached"] = True
                result["stale"] = True
                return result

        # Acquire global scan lock to prevent concurrent heavy I/O
        acquired = self._global_scan_lock.acquire(timeout=1)
        if not acquired:
            logger.info("Could not acquire scan lock, returning stale cache...")
            if self._stats_cache is not None:
                _, cached_stats = self._stats_cache
                result = cached_stats.copy()
                result["cached"] = True
                result["stale"] = True
                return result
            # No cache at all - must wait
            self._global_scan_lock.acquire()

        try:
            self._scan_in_progress = True
            logger.info("No valid cache available, calculating storage stats synchronously...")
            start_time = time.time()
            stats = self._calculate_storage_stats()
            current_time = time.time()

            # Update memory cache
            self._stats_cache = (current_time, stats.copy())
            self._stats_cache_from_persistent = False

            # Save to persistent cache
            self._save_persistent_cache(current_time, stats)

            elapsed = current_time - start_time
            logger.info(f"Storage stats calculation completed in {elapsed:.2f}s")

            stats["stale"] = False
            return stats
        finally:
            self._scan_in_progress = False
            self._global_scan_lock.release()


    # ==================== Utility Methods ====================

    def _get_dir_size(self, directory: Path) -> int:
        """
        Get total size of a directory in bytes.

        For symlinks, only counts the symlink size (not the target file size).
        This ensures accurate size reporting when features are symlinked to cache.
        """
        total = 0
        try:
            for item in directory.rglob('*'):
                if item.is_symlink():
                    # For symlinks, use lstat to get symlink size, not target size
                    total += item.lstat().st_size
                elif item.is_file():
                    total += item.stat().st_size
        except Exception as e:
            logger.warning(f"Error calculating directory size for {directory}: {e}")
        return total

    def _get_file_info(self, file_path: Path) -> Dict:
        """Get file information."""
        if file_path.exists() and file_path.is_file():
            return {
                "path": str(file_path),
                "size": file_path.stat().st_size,
                "exists": True
            }
        else:
            return {
                "path": str(file_path),
                "size": 0,
                "exists": False
            }

    def _get_directory_stats(self, directory: Path) -> Dict:
        """
        Get directory statistics (size and file count) in a single traversal.

        Optimized to avoid double traversal - calculates both size and count together.
        """
        if directory.exists() and directory.is_dir():
            total_size = 0
            file_count = 0
            try:
                for item in directory.rglob('*'):
                    if item.is_symlink():
                        # For symlinks, use lstat to get symlink size, not target size
                        total_size += item.lstat().st_size
                        file_count += 1
                    elif item.is_file():
                        total_size += item.stat().st_size
                        file_count += 1
            except Exception as e:
                logger.warning(f"Error calculating directory stats for {directory}: {e}")
            return {
                "size": total_size,
                "file_count": file_count
            }
        else:
            return {
                "size": 0,
                "file_count": 0
            }