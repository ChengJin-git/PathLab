"""
Storage Manager

Centralized storage management for all file resources.
Handles file deletion, storage statistics, and orphaned file cleanup.

Statistics and orphan detection are implemented as mixins:
- StorageStatsMixin: Storage stats with stale-while-revalidate caching
- StorageOrphanMixin: Orphaned file detection and cleanup
"""

import os
import shutil
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Callable
from datetime import datetime, timezone
import logging

from backend.ai.tasks.feature_cache import cleanup_dangling_symlinks
from backend.ai.tasks.patch_cache import (
    delete_all_cached_coords_for_wsi,
    list_all_cached_coords_for_wsi,
)

from .stats_mixin import StorageStatsMixin
from .orphan_mixin import StorageOrphanMixin

logger = logging.getLogger(__name__)


class StorageManager(StorageStatsMixin, StorageOrphanMixin):
    """
    Centralized storage manager for all file resources.

    Manages file lifecycle for:
    - WSI files and their derivatives (coordinates, features, AI results)
    - Training tasks (features, logs, models)
    - AI tasks and results
    """

    def __init__(self, uploads_dir: str):
        """
        Initialize storage manager.

        Args:
            uploads_dir: Root uploads directory path
        """
        self.set_uploads_dir(uploads_dir)
        # Cache for storage stats: (timestamp, stats_dict)
        self._stats_cache: Optional[Tuple[float, Dict[str, Any]]] = None
        # Flag to indicate if cache was loaded from persistent storage (survives restart)
        self._stats_cache_from_persistent: bool = False
        # Lock for background refresh to prevent multiple concurrent refreshes
        self._stats_refresh_lock = threading.Lock()
        self._stats_refresh_in_progress = False
        # Directory mtime cache for incremental updates: {category: mtime}
        self._dir_mtime_cache: Dict[str, float] = {}

        # Orphan detection cache: (timestamp, orphan_result, wsi_ids_hash, task_ids_hash, model_ids_hash)
        self._orphan_cache: Optional[Tuple[float, Dict[str, Any], str, str, str]] = None
        self._orphan_cache_from_persistent: bool = False
        self._orphan_refresh_lock = threading.Lock()
        self._orphan_refresh_in_progress = False
        # Directory mtime cache for orphan incremental updates
        self._orphan_dir_mtime_cache: Dict[str, float] = {}

        # Global scan lock: prevents concurrent heavy I/O scans
        # When one scan is in progress, others return cached results immediately
        self._global_scan_lock = threading.Lock()
        self._scan_in_progress = False

        # Load persistent cache on initialization
        self._load_persistent_cache()
        self._load_orphan_persistent_cache()

    def set_uploads_dir(self, uploads_dir: str) -> None:
        """Update uploads directory and derived subpaths."""
        self.uploads_dir = Path(uploads_dir)
        self.coords_dir = self.uploads_dir / "coordinates"
        self.masks_dir = self.uploads_dir / "masks"
        self.features_dir = self.uploads_dir / "features"
        self.ai_results_dir = self.uploads_dir / "ai_results"
        self.training_dir = self.uploads_dir / "training"
        self.models_dir = self.uploads_dir / "models"
        self.logs_dir = self.uploads_dir / "logs"
        self.wsi_files_dir = self.uploads_dir / "wsi_files"
        self.metadata_dir = self.uploads_dir / "metadata"

    # Stats cache and orphan cache methods are provided by
    # StorageStatsMixin and StorageOrphanMixin via inheritance.
    # See stats_mixin.py and orphan_mixin.py for details.

    def _get_task_ai_result_patterns(self, task_id: str) -> List[str]:
        """Get filename patterns for task-scoped AI result artifacts."""
        return [
            f"{task_id}_*",
            f"train_{task_id}_*",
            f"extval_{task_id}_*",
        ]

    def _iter_task_ai_result_files(self, task_id: str):
        """Yield task-scoped AI result files across all WSI result directories."""
        if not self.ai_results_dir.exists() or not self.ai_results_dir.is_dir():
            return

        seen_paths = set()
        patterns = self._get_task_ai_result_patterns(task_id)

        for wsi_result_dir in self.ai_results_dir.iterdir():
            if not wsi_result_dir.is_dir():
                continue

            for pattern in patterns:
                for file_path in wsi_result_dir.glob(pattern):
                    if file_path.is_file() and file_path not in seen_paths:
                        seen_paths.add(file_path)
                        yield file_path

    def delete_wsi_files(
        self, wsi_id: str, wsi_path: Optional[str] = None, mode: str = "standard"
    ) -> Dict[str, Any]:
        """
        Delete files associated with a WSI.

        Deletion modes:
        - "standard" (recommended): Delete WSI file and direct derivatives (coords, mask)
                                   Keep training-related files (features in training tasks)
        - "complete": Delete all associated files including training features

        Files deleted in standard mode:
        - WSI file itself (if wsi_path provided and in uploads directory)
        - Coordinates: uploads/coordinates/{wsi_id}_coords.h5
        - Masks: uploads/masks/{wsi_id}_mask.png
        - AI results: uploads/ai_results/{wsi_id}/ (entire directory)

        Additional files deleted in complete mode:
        - Features: uploads/training/*/features/{wsi_id}.pt (all training tasks, may be symlinks)
        - Global feature cache: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt

        Args:
            wsi_id: WSI identifier
            wsi_path: Path to WSI file (optional)
            mode: Deletion mode ("standard" or "complete")

        Returns:
            Dictionary with deletion results:
            {
                "deleted_files": List[str],
                "deleted_dirs": List[str],
                "failed": List[Tuple[str, str]],  # (path, error)
                "total_size": int,  # bytes freed
                "summary": str,
                "mode": str
            }
        """
        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        # 1. Delete WSI file itself
        if wsi_path and os.path.exists(wsi_path):
            if wsi_path.startswith(str(self.uploads_dir)):
                try:
                    size = os.path.getsize(wsi_path)
                    os.remove(wsi_path)
                    deleted_files.append(wsi_path)
                    total_size += size
                    logger.info(f"Deleted WSI file: {wsi_path}")
                except Exception as e:
                    failed.append((wsi_path, str(e)))
                    logger.error(f"Failed to delete WSI file {wsi_path}: {e}")

        # 1.5 Delete associated files for special formats (MRXS, TMAP)
        if wsi_path:
            wsi_path_obj = Path(wsi_path)
            file_extension = wsi_path_obj.suffix.lower()
            wsi_parent_dir = wsi_path_obj.parent

            if file_extension == ".mrxs":
                # MRXS: data folder has the same stem as the .mrxs file
                # (uploaded: stem == wsi_id; external: stem == original filename)
                mrxs_data_folder = wsi_parent_dir / wsi_path_obj.stem
                if mrxs_data_folder.exists() and mrxs_data_folder.is_dir():
                    try:
                        size = self._get_dir_size(mrxs_data_folder)
                        shutil.rmtree(mrxs_data_folder)
                        deleted_dirs.append(str(mrxs_data_folder))
                        total_size += size
                        logger.info(f"Deleted MRXS data folder: {mrxs_data_folder}")
                    except Exception as e:
                        failed.append((str(mrxs_data_folder), str(e)))
                        logger.error(
                            f"Failed to delete MRXS data folder {mrxs_data_folder}: {e}"
                        )

            elif file_extension == ".tmap":
                # TMAP: .DT<n> siblings share the same stem as the .tmap file
                # (uploaded: stem == wsi_id; external: stem == original filename)
                try:
                    for dt_file in wsi_parent_dir.glob(f"{wsi_path_obj.stem}.DT*"):
                        if dt_file.is_file():
                            try:
                                size = dt_file.stat().st_size
                                dt_file.unlink()
                                deleted_files.append(str(dt_file))
                                total_size += size
                                logger.info(f"Deleted TMAP DT file: {dt_file}")
                            except Exception as e:
                                failed.append((str(dt_file), str(e)))
                                logger.error(
                                    f"Failed to delete TMAP DT file {dt_file}: {e}"
                                )
                except Exception as e:
                    logger.error(f"Failed to scan for TMAP DT files: {e}")

        # 2. Delete coordinates files (from all params_hash directories)
        # Structure: uploads/coordinates/{params_hash}/{wsi_id}_coords.h5
        coords_result = delete_all_cached_coords_for_wsi(self.uploads_dir, wsi_id)
        deleted_files.extend(coords_result["deleted_files"])
        total_size += coords_result["total_size"]
        failed.extend(coords_result["failed"])
        if coords_result["deleted_files"]:
            logger.info(
                f"Deleted {len(coords_result['deleted_files'])} coordinates files for {wsi_id}"
            )

        # 3. Delete mask file
        mask_file = self.masks_dir / f"{wsi_id}_mask.png"
        if mask_file.exists():
            try:
                size = mask_file.stat().st_size
                mask_file.unlink()
                deleted_files.append(str(mask_file))
                total_size += size
                logger.info(f"Deleted mask: {mask_file}")
            except Exception as e:
                failed.append((str(mask_file), str(e)))
                logger.error(f"Failed to delete mask {mask_file}: {e}")

        # 4. Delete AI results directory
        ai_results_wsi_dir = self.ai_results_dir / wsi_id
        if ai_results_wsi_dir.exists() and ai_results_wsi_dir.is_dir():
            try:
                size = self._get_dir_size(ai_results_wsi_dir)
                shutil.rmtree(ai_results_wsi_dir)
                deleted_dirs.append(str(ai_results_wsi_dir))
                total_size += size
                logger.info(f"Deleted AI results directory: {ai_results_wsi_dir}")
            except Exception as e:
                failed.append((str(ai_results_wsi_dir), str(e)))
                logger.error(
                    f"Failed to delete AI results directory {ai_results_wsi_dir}: {e}"
                )

        # 4.5 Delete metadata file (always deleted in both standard and complete mode)
        metadata_file = self.metadata_dir / f"{wsi_id}.json"
        if metadata_file.exists():
            try:
                size = metadata_file.stat().st_size
                metadata_file.unlink()
                deleted_files.append(str(metadata_file))
                total_size += size
                logger.info(f"Deleted metadata file: {metadata_file}")
            except Exception as e:
                failed.append((str(metadata_file), str(e)))
                logger.error(f"Failed to delete metadata file {metadata_file}: {e}")

        # 5. Delete feature files from training tasks (only in complete mode)
        # Features may be symlinks pointing to global cache, or actual files
        if mode == "complete" and self.training_dir.exists():
            for task_dir in self.training_dir.iterdir():
                if task_dir.is_dir():
                    features_dir = task_dir / "features"
                    if features_dir.exists():
                        feature_file = features_dir / f"{wsi_id}.pt"
                        if feature_file.exists() or feature_file.is_symlink():
                            try:
                                if feature_file.is_symlink():
                                    # Just remove symlink
                                    feature_file.unlink()
                                    deleted_files.append(str(feature_file))
                                    logger.info(
                                        f"Deleted feature symlink: {feature_file}"
                                    )
                                else:
                                    size = feature_file.stat().st_size
                                    feature_file.unlink()
                                    deleted_files.append(str(feature_file))
                                    total_size += size
                                    logger.info(f"Deleted feature file: {feature_file}")
                            except Exception as e:
                                failed.append((str(feature_file), str(e)))
                                logger.error(
                                    f"Failed to delete feature file {feature_file}: {e}"
                                )

        # 6. Delete cached features from global cache (only in complete mode)
        # Structure: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
        if mode == "complete":
            if self.features_dir.exists():
                for extractor_dir in self.features_dir.iterdir():
                    if extractor_dir.is_dir():
                        # Iterate through params_hash subdirectories
                        for params_hash_dir in extractor_dir.iterdir():
                            if params_hash_dir.is_dir():
                                feature_file = params_hash_dir / f"{wsi_id}.pt"
                                if feature_file.exists():
                                    try:
                                        size = feature_file.stat().st_size
                                        feature_file.unlink()
                                        deleted_files.append(str(feature_file))
                                        total_size += size
                                        logger.info(
                                            f"Deleted cached features: {feature_file}"
                                        )
                                        # Clean up empty params_hash directory
                                        if not any(params_hash_dir.iterdir()):
                                            params_hash_dir.rmdir()
                                            logger.info(
                                                f"Removed empty params_hash dir: {params_hash_dir}"
                                            )
                                    except Exception as e:
                                        failed.append((str(feature_file), str(e)))
                                        logger.error(
                                            f"Failed to delete cached features {feature_file}: {e}"
                                        )

        summary = (
            f"WSI {wsi_id} storage cleanup ({mode} mode): "
            f"{len(deleted_files)} files, {len(deleted_dirs)} directories deleted, "
            f"{len(failed)} failed, {total_size / (1024**2):.2f} MB freed"
        )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary,
            "mode": mode,
        }

    def delete_wsi_ai_results(
        self, wsi_id: str, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Delete AI results for a specific WSI.

        If task_id is provided, only delete results for that specific task.
        Otherwise, delete all AI results for the WSI.

        Files deleted:
        - If task_id specified: uploads/ai_results/{wsi_id}/train_{task_id}_*.* (result.json, attention.npy, etc.)
        - If task_id not specified: uploads/ai_results/{wsi_id}/ (entire directory)

        Args:
            wsi_id: WSI identifier
            task_id: Optional task ID to delete results for a specific task only

        Returns:
            Dictionary with deletion results:
            {
                "deleted_files": List[str],
                "deleted_dirs": List[str],
                "failed": List[Tuple[str, str]],
                "total_size": int,
                "summary": str
            }
        """
        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        ai_results_wsi_dir = self.ai_results_dir / wsi_id

        if not ai_results_wsi_dir.exists():
            return {
                "deleted_files": [],
                "deleted_dirs": [],
                "failed": [],
                "total_size": 0,
                "summary": f"No AI results found for WSI {wsi_id}",
            }

        if task_id:
            # Delete only files for the specific task
            patterns = self._get_task_ai_result_patterns(task_id)
            for pattern in patterns:
                for file_path in ai_results_wsi_dir.glob(pattern):
                    if file_path.is_file():
                        try:
                            size = file_path.stat().st_size
                            file_path.unlink()
                            deleted_files.append(str(file_path))
                            total_size += size
                            logger.info(f"Deleted AI result file: {file_path}")
                        except Exception as e:
                            failed.append((str(file_path), str(e)))
                            logger.error(
                                f"Failed to delete AI result file {file_path}: {e}"
                            )

            # Clean up empty directory
            if ai_results_wsi_dir.exists() and not any(ai_results_wsi_dir.iterdir()):
                try:
                    ai_results_wsi_dir.rmdir()
                    deleted_dirs.append(str(ai_results_wsi_dir))
                    logger.info(
                        f"Removed empty AI results directory: {ai_results_wsi_dir}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not remove AI results directory {ai_results_wsi_dir}: {e}"
                    )

            summary = (
                f"WSI {wsi_id} AI results cleanup (task {task_id}): "
                f"{len(deleted_files)} files deleted, {len(failed)} failed, "
                f"{total_size / (1024**2):.2f} MB freed"
            )
        else:
            # Delete entire directory
            try:
                total_size = self._get_dir_size(ai_results_wsi_dir)
                shutil.rmtree(ai_results_wsi_dir)
                deleted_dirs.append(str(ai_results_wsi_dir))
                logger.info(f"Deleted AI results directory: {ai_results_wsi_dir}")
            except Exception as e:
                failed.append((str(ai_results_wsi_dir), str(e)))
                logger.error(
                    f"Failed to delete AI results directory {ai_results_wsi_dir}: {e}"
                )

            summary = (
                f"WSI {wsi_id} AI results cleanup: "
                f"{len(deleted_dirs)} directories deleted, {len(failed)} failed, "
                f"{total_size / (1024**2):.2f} MB freed"
            )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary,
        }

    def delete_training_task_files(
        self,
        task_id: str,
        model_paths: Optional[List[str]] = None,
        mode: str = "standard",
    ) -> Dict[str, Any]:
        """
        Delete files associated with a training task.

        Deletion modes:
        - "standard": Delete training directory and log file only. Keep trained models.
        - "complete": Delete all files including trained models.

        Files deleted in standard mode:
        - Training directory: uploads/training/{task_id}/ (entire directory with all features)
        - Log directory: uploads/logs/training/{task_id}/

        Additional files deleted in complete mode:
        - Model directories: uploads/models/{model_id}/

        Args:
            task_id: Training task identifier
            model_paths: List of model directory paths to delete (only used in complete mode)
            mode: Deletion mode - "standard" or "complete"

        Returns:
            Dictionary with deletion results (same format as delete_wsi_files)
        """
        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        # 1. Delete task-scoped AI result files (internal inference or external validation)
        touched_ai_result_dirs = set()
        for file_path in self._iter_task_ai_result_files(task_id) or []:
            try:
                size = file_path.stat().st_size
                file_path.unlink()
                deleted_files.append(str(file_path))
                total_size += size
                touched_ai_result_dirs.add(file_path.parent)
                logger.info(f"Deleted task AI result file: {file_path}")
            except Exception as e:
                failed.append((str(file_path), str(e)))
                logger.error(f"Failed to delete task AI result file {file_path}: {e}")

        for result_dir in touched_ai_result_dirs:
            if result_dir.exists() and not any(result_dir.iterdir()):
                try:
                    result_dir.rmdir()
                    deleted_dirs.append(str(result_dir))
                    logger.info(f"Removed empty AI results directory: {result_dir}")
                except Exception as e:
                    logger.warning(
                        f"Could not remove AI results directory {result_dir}: {e}"
                    )

        # 2. Delete training directory (contains features - may be symlinks to cache)
        training_task_dir = self.training_dir / task_id
        if training_task_dir.exists() and training_task_dir.is_dir():
            try:
                # Count symlinks for logging
                features_dir = training_task_dir / "features"
                symlink_count = 0
                if features_dir.exists():
                    symlink_count = sum(
                        1 for f in features_dir.iterdir() if f.is_symlink()
                    )

                size = self._get_dir_size(training_task_dir)
                shutil.rmtree(training_task_dir)
                deleted_dirs.append(str(training_task_dir))
                total_size += size

                if symlink_count > 0:
                    logger.info(
                        f"Deleted training directory: {training_task_dir} "
                        f"({symlink_count} feature symlinks removed, cached features preserved)"
                    )
                else:
                    logger.info(f"Deleted training directory: {training_task_dir}")
            except Exception as e:
                failed.append((str(training_task_dir), str(e)))
                logger.error(
                    f"Failed to delete training directory {training_task_dir}: {e}"
                )

        # 3. Delete log directory (new structure: logs/training/{task_id}/)
        training_log_dir = self.logs_dir / "training" / task_id
        if training_log_dir.exists() and training_log_dir.is_dir():
            try:
                size = self._get_dir_size(training_log_dir)
                shutil.rmtree(training_log_dir)
                deleted_dirs.append(str(training_log_dir))
                total_size += size
                logger.info(f"Deleted training log directory: {training_log_dir}")
            except Exception as e:
                failed.append((str(training_log_dir), str(e)))
                logger.error(
                    f"Failed to delete training log directory {training_log_dir}: {e}"
                )

        # 4. Delete analysis log directory (logs/analysis/{task_id}/)
        analysis_log_dir = self.logs_dir / "analysis" / task_id
        if analysis_log_dir.exists() and analysis_log_dir.is_dir():
            try:
                size = self._get_dir_size(analysis_log_dir)
                shutil.rmtree(analysis_log_dir)
                deleted_dirs.append(str(analysis_log_dir))
                total_size += size
                logger.info(f"Deleted analysis log directory: {analysis_log_dir}")
            except Exception as e:
                failed.append((str(analysis_log_dir), str(e)))
                logger.error(
                    f"Failed to delete analysis log directory {analysis_log_dir}: {e}"
                )

        # 5. Delete model directories (only in complete mode)
        # model_paths can be either model IDs (e.g., "abmil_train_xxx") or full paths
        if mode == "complete" and model_paths:
            for model_path in model_paths:
                # Check if it's a model ID (no path separators) or a full path
                if "/" not in str(model_path) and "\\" not in str(model_path):
                    # It's a model ID, construct the model directory path
                    model_dir = self.models_dir / model_path
                else:
                    # It's a path, get the parent directory if it's a file
                    model_dir = (
                        Path(model_path).parent
                        if Path(model_path).is_file()
                        else Path(model_path)
                    )

                if model_dir.exists() and model_dir.is_dir():
                    # Safety check: only delete if in models directory
                    if str(model_dir).startswith(str(self.models_dir)):
                        try:
                            size = self._get_dir_size(model_dir)
                            shutil.rmtree(model_dir)
                            deleted_dirs.append(str(model_dir))
                            total_size += size
                            logger.info(f"Deleted model directory: {model_dir}")
                        except Exception as e:
                            failed.append((str(model_dir), str(e)))
                            logger.error(
                                f"Failed to delete model directory {model_dir}: {e}"
                            )

        summary = (
            f"Training task {task_id} storage cleanup ({mode} mode): "
            f"{len(deleted_files)} files, {len(deleted_dirs)} directories deleted, "
            f"{len(failed)} failed, {total_size / (1024**2):.2f} MB freed"
        )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary,
            "mode": mode,
        }

    def get_wsi_storage_info(
        self, wsi_id: str, wsi_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get storage information for a WSI.

        Args:
            wsi_id: WSI identifier
            wsi_path: Path to WSI file (optional)

        Returns:
            Dictionary with storage information:
            {
                "wsi_id": str,
                "wsi_file": {"path": str, "size": int, "exists": bool},
                "coordinates": {"path": str, "size": int, "exists": bool},
                "mask": {"path": str, "size": int, "exists": bool},
                "ai_results": {"path": str, "size": int, "exists": bool, "file_count": int},
                "features": List[{"path": str, "size": int, "task_id": str}],
                "total_size": int,
                "total_files": int
            }
        """
        info = {
            "wsi_id": wsi_id,
            "wsi_file": {},
            "coordinates": {},
            "mask": {},
            "ai_results": {},
            "features": [],
            "total_size": 0,
            "total_files": 0,
        }

        # WSI file
        if wsi_path:
            wsi_file_path = Path(wsi_path)
            info["wsi_file"] = self._get_file_info(wsi_file_path)
            if info["wsi_file"]["exists"]:
                info["total_size"] += info["wsi_file"]["size"]
                info["total_files"] += 1

        # Coordinates (search across all params_hash directories)
        # New structure: uploads/coordinates/{params_hash}/{wsi_id}_coords.h5
        coords_files = list_all_cached_coords_for_wsi(self.uploads_dir, wsi_id)
        if coords_files:
            # Aggregate info from all coords files
            total_coords_size = 0
            coords_paths = []
            for coords_file in coords_files:
                file_info = self._get_file_info(coords_file)
                if file_info["exists"]:
                    total_coords_size += file_info["size"]
                    coords_paths.append(str(coords_file))
            info["coordinates"] = {
                "exists": True,
                "paths": coords_paths,
                "size": total_coords_size,
                "file_count": len(coords_paths),
            }
            info["total_size"] += total_coords_size
            info["total_files"] += len(coords_paths)
        else:
            info["coordinates"] = {
                "exists": False,
                "paths": [],
                "size": 0,
                "file_count": 0,
            }

        # Mask
        mask_file = self.masks_dir / f"{wsi_id}_mask.png"
        info["mask"] = self._get_file_info(mask_file)
        if info["mask"]["exists"]:
            info["total_size"] += info["mask"]["size"]
            info["total_files"] += 1

        # AI results directory
        ai_results_dir = self.ai_results_dir / wsi_id
        if ai_results_dir.exists() and ai_results_dir.is_dir():
            size = self._get_dir_size(ai_results_dir)
            file_count = sum(1 for _ in ai_results_dir.rglob("*") if _.is_file())
            info["ai_results"] = {
                "path": str(ai_results_dir),
                "size": size,
                "exists": True,
                "file_count": file_count,
            }
            info["total_size"] += size
            info["total_files"] += file_count
        else:
            info["ai_results"] = {
                "path": str(ai_results_dir),
                "size": 0,
                "exists": False,
                "file_count": 0,
            }

        # Features from training tasks
        if self.training_dir.exists():
            for task_dir in self.training_dir.iterdir():
                if task_dir.is_dir():
                    features_dir = task_dir / "features"
                    if features_dir.exists():
                        feature_file = features_dir / f"{wsi_id}.pt"
                        if feature_file.exists() or feature_file.is_symlink():
                            if feature_file.is_symlink():
                                # For symlinks, get the target file size if it exists
                                try:
                                    target = feature_file.resolve()
                                    size = (
                                        target.stat().st_size if target.exists() else 0
                                    )
                                except Exception:
                                    size = 0
                            else:
                                size = feature_file.stat().st_size
                            info["features"].append(
                                {
                                    "path": str(feature_file),
                                    "size": size,
                                    "task_id": task_dir.name,
                                    "is_symlink": feature_file.is_symlink(),
                                }
                            )
                            info["total_size"] += size
                            info["total_files"] += 1

        # Features from global features cache (uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt)
        if self.features_dir.exists():
            for extractor_dir in self.features_dir.iterdir():
                if extractor_dir.is_dir():
                    for params_hash_dir in extractor_dir.iterdir():
                        if params_hash_dir.is_dir():
                            feature_file = params_hash_dir / f"{wsi_id}.pt"
                            if feature_file.exists():
                                size = feature_file.stat().st_size
                                info["features"].append(
                                    {
                                        "path": str(feature_file),
                                        "size": size,
                                        "extractor": extractor_dir.name,
                                        "params_hash": params_hash_dir.name,
                                        "is_symlink": False,
                                    }
                                )
                                info["total_size"] += size
                                info["total_files"] += 1

        return info

    def get_training_task_storage_info(
        self, task_id: str, model_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get storage information for a training task.

        Args:
            task_id: Training task identifier
            model_paths: List of model paths (optional)

        Returns:
            Dictionary with storage information

        OPTIMIZED: Uses _get_directory_stats for single-pass directory traversal
        instead of separate size and file count calculations.
        """
        info = {
            "task_id": task_id,
            "ai_results": {},
            "training_dir": {},
            "training_logs": {},
            "analysis_logs": {},
            "models": [],
            "total_size": 0,
            "total_files": 0,
        }

        # Task-scoped AI result files across ai_results/{wsi_id}/
        ai_result_size = 0
        ai_result_count = 0
        ai_result_wsi_dirs = set()
        for file_path in self._iter_task_ai_result_files(task_id) or []:
            try:
                ai_result_size += file_path.stat().st_size
                ai_result_count += 1
                ai_result_wsi_dirs.add(str(file_path.parent))
            except Exception:
                continue

        info["ai_results"] = {
            "path": str(self.ai_results_dir),
            "size": ai_result_size,
            "exists": ai_result_count > 0,
            "file_count": ai_result_count,
            "wsi_dir_count": len(ai_result_wsi_dirs),
        }
        info["total_size"] += ai_result_size
        info["total_files"] += ai_result_count

        # Training directory - use optimized single-pass stats
        training_dir = self.training_dir / task_id
        stats = self._get_directory_stats(training_dir)
        info["training_dir"] = {
            "path": str(training_dir),
            "size": stats["size"],
            "exists": training_dir.exists() and training_dir.is_dir(),
            "file_count": stats["file_count"],
        }
        info["total_size"] += stats["size"]
        info["total_files"] += stats["file_count"]

        # Training logs directory - use optimized single-pass stats
        training_log_dir = self.logs_dir / "training" / task_id
        stats = self._get_directory_stats(training_log_dir)
        info["training_logs"] = {
            "path": str(training_log_dir),
            "size": stats["size"],
            "exists": training_log_dir.exists() and training_log_dir.is_dir(),
            "file_count": stats["file_count"],
        }
        info["total_size"] += stats["size"]
        info["total_files"] += stats["file_count"]

        # Analysis logs directory - use optimized single-pass stats
        analysis_log_dir = self.logs_dir / "analysis" / task_id
        stats = self._get_directory_stats(analysis_log_dir)
        info["analysis_logs"] = {
            "path": str(analysis_log_dir),
            "size": stats["size"],
            "exists": analysis_log_dir.exists() and analysis_log_dir.is_dir(),
            "file_count": stats["file_count"],
        }
        info["total_size"] += stats["size"]
        info["total_files"] += stats["file_count"]

        # Model directories - use optimized single-pass stats
        if model_paths:
            for model_path in model_paths:
                model_dir = (
                    Path(model_path).parent
                    if Path(model_path).is_file()
                    else Path(model_path)
                )
                if model_dir.exists() and model_dir.is_dir():
                    stats = self._get_directory_stats(model_dir)
                    info["models"].append(
                        {
                            "path": str(model_dir),
                            "size": stats["size"],
                            "file_count": stats["file_count"],
                        }
                    )
                    info["total_size"] += stats["size"]
                    info["total_files"] += stats["file_count"]

        return info

    # Stats calculation, orphan detection, and cleanup methods are provided by
    # StorageStatsMixin and StorageOrphanMixin via inheritance.

    def reset_derived_data(
        self, progress_callback: Optional[Callable[[int], None]] = None
    ) -> Dict[str, Any]:
        """
        Delete all derived data files, keeping only original WSI files.
        This is a destructive operation used for forcing a complete data reset.

        Deletes:
        - coordinates/
        - masks/
        - features/
        - ai_results/
        - training/
        - models/
        - logs/
        - metadata/

        Preserves:
        - wsi_files/ (original image files)

        Args:
            progress_callback: Optional callback function to report progress (0-100)

        Returns:
            {
                "deleted_files": List[str],
                "deleted_dirs": List[str],
                "failed": List[Tuple[str, str]],
                "total_size": int,
                "summary": str
            }
        """
        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        # Directories to delete (all except wsi_files)
        dirs_to_delete = [
            (self.coords_dir, "coordinates"),
            (self.masks_dir, "masks"),
            (self.features_dir, "features"),
            (self.ai_results_dir, "ai_results"),
            (self.training_dir, "training"),
            (self.models_dir, "models"),
            (self.logs_dir, "logs"),
            (self.metadata_dir, "metadata"),
        ]

        logger.warning(
            "Starting reset of all derived data - this will delete all processed files!"
        )

        total_dirs = len(dirs_to_delete)
        for idx, (dir_path, dir_name) in enumerate(dirs_to_delete):
            if dir_path.exists() and dir_path.is_dir():
                try:
                    # Calculate size before deletion
                    size = self._get_dir_size(dir_path)

                    # Delete the entire directory
                    shutil.rmtree(dir_path)
                    deleted_dirs.append(str(dir_path))
                    total_size += size

                    logger.info(
                        f"Deleted {dir_name} directory: {dir_path} ({size / (1024**2):.2f} MB)"
                    )

                    # Recreate empty directory to maintain structure
                    dir_path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Recreated empty {dir_name} directory: {dir_path}")

                except Exception as e:
                    failed.append((str(dir_path), str(e)))
                    logger.error(
                        f"Failed to delete {dir_name} directory {dir_path}: {e}"
                    )

            # Report progress after each directory (0-90% for directory deletion)
            if progress_callback:
                progress = int(((idx + 1) / total_dirs) * 90)
                progress_callback(progress)

        # Clear all caches since data has been reset
        self._stats_cache = None
        self._orphan_cache = None
        self._dir_mtime_cache.clear()
        self._orphan_dir_mtime_cache.clear()

        # Delete persistent cache files
        try:
            cache_file = self._get_cache_file_path()
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"Deleted storage stats cache file: {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to delete storage stats cache file: {e}")

        try:
            orphan_cache_file = self._get_orphan_cache_file_path()
            if orphan_cache_file.exists():
                orphan_cache_file.unlink()
                logger.info(f"Deleted orphan cache file: {orphan_cache_file}")
        except Exception as e:
            logger.warning(f"Failed to delete orphan cache file: {e}")

        # Report final progress (100%)
        if progress_callback:
            progress_callback(100)

        summary = (
            f"Derived data reset complete: "
            f"{len(deleted_dirs)} directories deleted, "
            f"{len(failed)} failed, {total_size / (1024**2):.2f} MB freed. "
            f"Original WSI files preserved."
        )

        logger.warning(summary)

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary,
        }

    def cleanup_dangling_feature_symlinks(self) -> Dict[str, Any]:
        """
        Find and remove all dangling symlinks in training directories.

        A dangling symlink is one whose target (cached feature file) no longer exists.
        This can happen if cached features were deleted manually or through other means.

        Returns:
            {
                "deleted_symlinks": List[str],
                "failed": List[Tuple[str, str]],
                "total_checked": int,
                "summary": str
            }
        """
        result = cleanup_dangling_symlinks(self.uploads_dir)

        result["summary"] = (
            f"Dangling symlinks cleanup: {len(result['deleted_symlinks'])} symlinks removed, "
            f"{len(result['failed'])} failed, {result['total_checked']} total checked"
        )

        return result

    def save_wsi_metadata(self, wsi_id: str, metadata: Dict[str, Any]) -> str:
        """
        Save WSI metadata to JSON file.

        This persists WSI metadata (width, height, source, age, label, etc.)
        to a JSON file for offline access and data preservation.

        Args:
            wsi_id: WSI identifier
            metadata: Dictionary containing WSI metadata

        Returns:
            Path to the saved metadata file
        """
        # Ensure metadata directory exists
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = self.metadata_dir / f"{wsi_id}.json"

        # Add timestamp to metadata
        metadata_with_timestamp = {
            **metadata,
            "saved_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            + "Z",
        }

        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata_with_timestamp, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved WSI metadata to {metadata_file}")
            return str(metadata_file)
        except Exception as e:
            logger.error(f"Failed to save WSI metadata for {wsi_id}: {e}")
            raise

    def get_wsi_metadata(self, wsi_id: str) -> Optional[Dict[str, Any]]:
        """
        Load WSI metadata from JSON file.

        Args:
            wsi_id: WSI identifier

        Returns:
            Dictionary containing WSI metadata, or None if not found
        """
        metadata_file = self.metadata_dir / f"{wsi_id}.json"

        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load WSI metadata for {wsi_id}: {e}")
            return None
