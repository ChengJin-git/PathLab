"""
Storage Manager

Centralized storage management for all file resources.
Handles file deletion, storage statistics, and orphaned file cleanup.
"""

import os
import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from backend.ai.tasks.feature_cache import cleanup_dangling_symlinks

logger = logging.getLogger(__name__)


class StorageManager:
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
        
    def delete_wsi_files(self, wsi_id: str, wsi_path: Optional[str] = None, mode: str = "standard") -> Dict:
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
        
        # 2. Delete coordinates file
        coords_file = self.coords_dir / f"{wsi_id}_coords.h5"
        if coords_file.exists():
            try:
                size = coords_file.stat().st_size
                coords_file.unlink()
                deleted_files.append(str(coords_file))
                total_size += size
                logger.info(f"Deleted coordinates: {coords_file}")
            except Exception as e:
                failed.append((str(coords_file), str(e)))
                logger.error(f"Failed to delete coordinates {coords_file}: {e}")

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
                logger.error(f"Failed to delete AI results directory {ai_results_wsi_dir}: {e}")

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
                        # Check both old naming convention and new naming
                        for pattern in [f"{wsi_id}_features.pt", f"{wsi_id}.pt"]:
                            feature_file = features_dir / pattern
                            if feature_file.exists() or feature_file.is_symlink():
                                try:
                                    if feature_file.is_symlink():
                                        # Just remove symlink
                                        feature_file.unlink()
                                        deleted_files.append(str(feature_file))
                                        logger.info(f"Deleted feature symlink: {feature_file}")
                                    else:
                                        size = feature_file.stat().st_size
                                        feature_file.unlink()
                                        deleted_files.append(str(feature_file))
                                        total_size += size
                                        logger.info(f"Deleted feature file: {feature_file}")
                                except Exception as e:
                                    failed.append((str(feature_file), str(e)))
                                    logger.error(f"Failed to delete feature file {feature_file}: {e}")

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
                                        logger.info(f"Deleted cached features: {feature_file}")
                                        # Clean up empty params_hash directory
                                        if not any(params_hash_dir.iterdir()):
                                            params_hash_dir.rmdir()
                                            logger.info(f"Removed empty params_hash dir: {params_hash_dir}")
                                    except Exception as e:
                                        failed.append((str(feature_file), str(e)))
                                        logger.error(f"Failed to delete cached features {feature_file}: {e}")

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
            "mode": mode
        }
    
    def delete_training_task_files(self, task_id: str, model_paths: Optional[List[str]] = None, mode: str = "standard") -> Dict:
        """
        Delete files associated with a training task.

        Deletion modes:
        - "standard": Delete training directory and log file only. Keep trained models.
        - "complete": Delete all files including trained models.

        Files deleted in standard mode:
        - Training directory: uploads/training/{task_id}/ (entire directory with all features)
        - Log file: uploads/logs/{task_id}.log

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

        # 1. Delete training directory (contains features - may be symlinks to cache)
        training_task_dir = self.training_dir / task_id
        if training_task_dir.exists() and training_task_dir.is_dir():
            try:
                # Count symlinks for logging
                features_dir = training_task_dir / "features"
                symlink_count = 0
                if features_dir.exists():
                    symlink_count = sum(1 for f in features_dir.iterdir() if f.is_symlink())

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
                logger.error(f"Failed to delete training directory {training_task_dir}: {e}")

        # 2. Delete log file
        log_file = self.logs_dir / f"{task_id}.log"
        if log_file.exists():
            try:
                size = log_file.stat().st_size
                log_file.unlink()
                deleted_files.append(str(log_file))
                total_size += size
                logger.info(f"Deleted log file: {log_file}")
            except Exception as e:
                failed.append((str(log_file), str(e)))
                logger.error(f"Failed to delete log file {log_file}: {e}")

        # 3. Delete model directories (only in complete mode)
        # model_paths can be either model IDs (e.g., "abmil_train_xxx") or full paths
        if mode == "complete" and model_paths:
            for model_path in model_paths:
                # Check if it's a model ID (no path separators) or a full path
                if '/' not in str(model_path) and '\\' not in str(model_path):
                    # It's a model ID, construct the model directory path
                    model_dir = self.models_dir / model_path
                else:
                    # It's a path, get the parent directory if it's a file
                    model_dir = Path(model_path).parent if Path(model_path).is_file() else Path(model_path)

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
                            logger.error(f"Failed to delete model directory {model_dir}: {e}")

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
            "mode": mode
        }

    def get_wsi_storage_info(self, wsi_id: str, wsi_path: Optional[str] = None) -> Dict:
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
            "total_files": 0
        }

        # WSI file
        if wsi_path:
            wsi_file_path = Path(wsi_path)
            info["wsi_file"] = self._get_file_info(wsi_file_path)
            if info["wsi_file"]["exists"]:
                info["total_size"] += info["wsi_file"]["size"]
                info["total_files"] += 1

        # Coordinates
        coords_file = self.coords_dir / f"{wsi_id}_coords.h5"
        info["coordinates"] = self._get_file_info(coords_file)
        if info["coordinates"]["exists"]:
            info["total_size"] += info["coordinates"]["size"]
            info["total_files"] += 1

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
            file_count = sum(1 for _ in ai_results_dir.rglob('*') if _.is_file())
            info["ai_results"] = {
                "path": str(ai_results_dir),
                "size": size,
                "exists": True,
                "file_count": file_count
            }
            info["total_size"] += size
            info["total_files"] += file_count
        else:
            info["ai_results"] = {
                "path": str(ai_results_dir),
                "size": 0,
                "exists": False,
                "file_count": 0
            }

        # Features from training tasks (check both naming conventions)
        if self.training_dir.exists():
            for task_dir in self.training_dir.iterdir():
                if task_dir.is_dir():
                    features_dir = task_dir / "features"
                    if features_dir.exists():
                        # Check both new naming ({wsi_id}.pt) and old naming ({wsi_id}_features.pt)
                        for pattern in [f"{wsi_id}.pt", f"{wsi_id}_features.pt"]:
                            feature_file = features_dir / pattern
                            if feature_file.exists() or feature_file.is_symlink():
                                if feature_file.is_symlink():
                                    # For symlinks, get the target file size if it exists
                                    try:
                                        target = feature_file.resolve()
                                        size = target.stat().st_size if target.exists() else 0
                                    except Exception:
                                        size = 0
                                else:
                                    size = feature_file.stat().st_size
                                info["features"].append({
                                    "path": str(feature_file),
                                    "size": size,
                                    "task_id": task_dir.name,
                                    "is_symlink": feature_file.is_symlink()
                                })
                                info["total_size"] += size
                                info["total_files"] += 1
                                break  # Only count once per task

        # Features from global features cache (uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt)
        if self.features_dir.exists():
            for extractor_dir in self.features_dir.iterdir():
                if extractor_dir.is_dir():
                    for params_hash_dir in extractor_dir.iterdir():
                        if params_hash_dir.is_dir():
                            feature_file = params_hash_dir / f"{wsi_id}.pt"
                            if feature_file.exists():
                                size = feature_file.stat().st_size
                                info["features"].append({
                                    "path": str(feature_file),
                                    "size": size,
                                    "extractor": extractor_dir.name,
                                    "params_hash": params_hash_dir.name,
                                    "is_symlink": False
                                })
                                info["total_size"] += size
                                info["total_files"] += 1

        return info

    def get_training_task_storage_info(self, task_id: str, model_paths: Optional[List[str]] = None) -> Dict:
        """
        Get storage information for a training task.

        Args:
            task_id: Training task identifier
            model_paths: List of model paths (optional)

        Returns:
            Dictionary with storage information
        """
        info = {
            "task_id": task_id,
            "training_dir": {},
            "log_file": {},
            "models": [],
            "total_size": 0,
            "total_files": 0
        }

        # Training directory
        training_dir = self.training_dir / task_id
        if training_dir.exists() and training_dir.is_dir():
            size = self._get_dir_size(training_dir)
            file_count = sum(1 for _ in training_dir.rglob('*') if _.is_file())
            info["training_dir"] = {
                "path": str(training_dir),
                "size": size,
                "exists": True,
                "file_count": file_count
            }
            info["total_size"] += size
            info["total_files"] += file_count
        else:
            info["training_dir"] = {
                "path": str(training_dir),
                "size": 0,
                "exists": False,
                "file_count": 0
            }

        # Log file
        log_file = self.logs_dir / f"{task_id}.log"
        info["log_file"] = self._get_file_info(log_file)
        if info["log_file"]["exists"]:
            info["total_size"] += info["log_file"]["size"]
            info["total_files"] += 1

        # Model directories
        if model_paths:
            for model_path in model_paths:
                model_dir = Path(model_path).parent if Path(model_path).is_file() else Path(model_path)
                if model_dir.exists() and model_dir.is_dir():
                    size = self._get_dir_size(model_dir)
                    file_count = sum(1 for _ in model_dir.rglob('*') if _.is_file())
                    info["models"].append({
                        "path": str(model_dir),
                        "size": size,
                        "file_count": file_count
                    })
                    info["total_size"] += size
                    info["total_files"] += file_count

        return info

    def get_total_storage_stats(self) -> Dict:
        """
        Get overall storage statistics.

        Returns:
            Dictionary with storage statistics:
            {
                "uploads_dir": str,
                "total_size": int,
                "breakdown": {
                    "coordinates": {"size": int, "file_count": int},
                    "masks": {"size": int, "file_count": int},
                    "ai_results": {"size": int, "file_count": int},
                    "features_cache": {"size": int, "file_count": int},
                    "training": {"size": int, "file_count": int},
                    "models": {"size": int, "file_count": int},
                    "logs": {"size": int, "file_count": int},
                    "wsi_files": {"size": int, "file_count": int}
                },
                "timestamp": str
            }
        """
        stats = {
            "uploads_dir": str(self.uploads_dir),
            "total_size": 0,
            "breakdown": {},
            "timestamp": datetime.utcnow().isoformat()
        }

        # Coordinates
        coords_stats = self._get_directory_stats(self.coords_dir)
        stats["breakdown"]["coordinates"] = coords_stats
        stats["total_size"] += coords_stats["size"]

        # Masks
        masks_stats = self._get_directory_stats(self.masks_dir)
        stats["breakdown"]["masks"] = masks_stats
        stats["total_size"] += masks_stats["size"]

        # AI results
        ai_results_stats = self._get_directory_stats(self.ai_results_dir)
        stats["breakdown"]["ai_results"] = ai_results_stats
        stats["total_size"] += ai_results_stats["size"]

        # Global features cache
        features_cache_dir = self.uploads_dir / "features"
        features_cache_stats = self._get_directory_stats(features_cache_dir)
        stats["breakdown"]["features_cache"] = features_cache_stats
        stats["total_size"] += features_cache_stats["size"]

        # Training
        training_stats = self._get_directory_stats(self.training_dir)
        stats["breakdown"]["training"] = training_stats
        stats["total_size"] += training_stats["size"]

        # Models
        models_stats = self._get_directory_stats(self.models_dir)
        stats["breakdown"]["models"] = models_stats
        stats["total_size"] += models_stats["size"]

        # Logs
        logs_stats = self._get_directory_stats(self.logs_dir)
        stats["breakdown"]["logs"] = logs_stats
        stats["total_size"] += logs_stats["size"]

        # WSI files (in uploads/wsi_files)
        wsi_files_size = 0
        wsi_files_count = 0
        if self.wsi_files_dir.exists():
            for item in self.wsi_files_dir.iterdir():
                if item.is_file():
                    wsi_files_size += item.stat().st_size
                    wsi_files_count += 1
        stats["breakdown"]["wsi_files"] = {
            "size": wsi_files_size,
            "file_count": wsi_files_count
        }
        stats["total_size"] += wsi_files_size

        return stats

    # Helper methods

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
        """Get directory statistics."""
        if directory.exists() and directory.is_dir():
            size = self._get_dir_size(directory)
            file_count = sum(1 for _ in directory.rglob('*') if _.is_file())
            return {
                "size": size,
                "file_count": file_count
            }
        else:
            return {
                "size": 0,
                "file_count": 0
            }

    def find_orphaned_files(self, existing_wsi_ids: List[str], existing_task_ids: List[str]) -> Dict[str, Any]:
        """
        Find files that exist in the file system but not in the database.

        Args:
            existing_wsi_ids: List of WSI IDs that exist in the database
            existing_task_ids: List of training task IDs that exist in the database

        Returns:
            {
                "orphaned_wsi_files": [{"path": str, "size": int, "wsi_id": str}, ...],
                "orphaned_coordinates": [...],
                "orphaned_masks": [...],
                "orphaned_features_cache": [...],
                "orphaned_ai_results": [...],
                "orphaned_training_dirs": [...],
                "orphaned_logs": [...],
                "total_orphaned_size": int,
                "total_orphaned_count": int
            }
        """
        result = {
            "orphaned_wsi_files": [],
            "orphaned_coordinates": [],
            "orphaned_masks": [],
            "orphaned_features_cache": [],
            "orphaned_ai_results": [],
            "orphaned_training_dirs": [],
            "orphaned_logs": [],
            "total_orphaned_size": 0,
            "total_orphaned_count": 0
        }

        existing_wsi_set = set(existing_wsi_ids)
        existing_task_set = set(existing_task_ids)

        # Check WSI files
        if self.wsi_files_dir.exists():
            for item in self.wsi_files_dir.iterdir():
                if item.is_file() and item.suffix.lower() in ['.svs', '.tif', '.tiff', '.ndpi', '.mrxs', '.scn']:
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

        # Check coordinates
        coords_dir = self.uploads_dir / "coordinates"
        if coords_dir.exists():
            for item in coords_dir.glob("*_coords.h5"):
                wsi_id = item.stem.replace("_coords", "")
                if wsi_id not in existing_wsi_set:
                    size = item.stat().st_size
                    result["orphaned_coordinates"].append({
                        "path": str(item),
                        "size": size,
                        "wsi_id": wsi_id
                    })
                    result["total_orphaned_size"] += size
                    result["total_orphaned_count"] += 1

        # Check masks
        masks_dir = self.uploads_dir / "masks"
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

        # Check global features cache
        # Structure: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
        features_cache_dir = self.uploads_dir / "features"
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

        # Check AI results
        ai_results_dir = self.uploads_dir / "ai_results"
        if ai_results_dir.exists():
            for wsi_dir in ai_results_dir.iterdir():
                if wsi_dir.is_dir():
                    wsi_id = wsi_dir.name
                    if wsi_id not in existing_wsi_set:
                        size = self._get_dir_size(wsi_dir)
                        result["orphaned_ai_results"].append({
                            "path": str(wsi_dir),
                            "size": size,
                            "wsi_id": wsi_id
                        })
                        result["total_orphaned_size"] += size
                        result["total_orphaned_count"] += 1

        # Check training directories
        training_dir = self.uploads_dir / "training"
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

        # Check logs
        logs_dir = self.uploads_dir / "logs"
        if logs_dir.exists():
            for item in logs_dir.glob("*.log"):
                task_id = item.stem
                if task_id not in existing_task_set:
                    size = item.stat().st_size
                    result["orphaned_logs"].append({
                        "path": str(item),
                        "size": size,
                        "task_id": task_id
                    })
                    result["total_orphaned_size"] += size
                    result["total_orphaned_count"] += 1

        return result

    def cleanup_orphaned_files(self, orphaned_files: Dict[str, Any], categories: List[str] = None) -> Dict[str, Any]:
        """
        Clean up orphaned files.

        Args:
            orphaned_files: Result from find_orphaned_files()
            categories: List of categories to clean up. If None, clean up all.
                       Options: ["wsi_files", "coordinates", "masks",
                                "ai_results", "training_dirs", "logs"]

        Returns:
            {
                "deleted_files": [str, ...],
                "deleted_dirs": [str, ...],
                "failed": [(str, str), ...],
                "total_size": int,
                "summary": str
            }
        """
        if categories is None:
            categories = ["wsi_files", "coordinates", "masks", "features_cache",
                         "ai_results", "training_dirs", "logs"]

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

        summary = (
            f"Orphaned files cleanup: {len(deleted_files)} files, "
            f"{len(deleted_dirs)} directories deleted, {len(failed)} failed, "
            f"{total_size / (1024**2):.2f} MB freed"
        )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary
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

    def save_wsi_metadata(self, wsi_id: str, metadata: Dict) -> str:
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
            "saved_at": datetime.utcnow().isoformat() + 'Z'
        }

        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata_with_timestamp, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved WSI metadata to {metadata_file}")
            return str(metadata_file)
        except Exception as e:
            logger.error(f"Failed to save WSI metadata for {wsi_id}: {e}")
            raise

    def get_wsi_metadata(self, wsi_id: str) -> Optional[Dict]:
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
            with open(metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load WSI metadata for {wsi_id}: {e}")
            return None
