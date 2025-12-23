"""
Storage Manager

Centralized storage management for all file resources.
Handles file deletion, storage statistics, and orphaned file cleanup.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Centralized storage manager for all file resources.
    
    Manages file lifecycle for:
    - WSI files and their derivatives (coordinates, thumbnails, features, AI results)
    - Training tasks (features, logs, models)
    - AI tasks and results
    """
    
    def __init__(self, uploads_dir: str):
        """
        Initialize storage manager.
        
        Args:
            uploads_dir: Root uploads directory path
        """
        self.uploads_dir = Path(uploads_dir)
        self.coords_dir = self.uploads_dir / "coordinates"
        self.thumbnails_dir = self.uploads_dir / "thumbnails"
        self.masks_dir = self.uploads_dir / "masks"
        self.ai_results_dir = self.uploads_dir / "ai_results"
        self.training_dir = self.uploads_dir / "training"
        self.models_dir = self.uploads_dir / "models"
        self.logs_dir = self.uploads_dir / "logs"
        
    def delete_wsi_files(self, wsi_id: str, wsi_path: Optional[str] = None, mode: str = "standard") -> Dict:
        """
        Delete files associated with a WSI.

        Deletion modes:
        - "standard" (recommended): Delete WSI file and direct derivatives (coords, thumbnail, mask)
                                   Keep training-related files (features in training tasks)
        - "complete": Delete all associated files including training features

        Files deleted in standard mode:
        - WSI file itself (if wsi_path provided and in uploads directory)
        - Coordinates: uploads/coordinates/{wsi_id}_coords.h5
        - Thumbnail: uploads/thumbnails/{wsi_id}.jpeg
        - Masks: uploads/masks/{wsi_id}_mask.npy
        - AI results: uploads/ai_results/{wsi_id}/ (entire directory)

        Additional files deleted in complete mode:
        - Features: uploads/training/*/features/{wsi_id}_features.pt (all training tasks)

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
        
        # 3. Delete thumbnail
        thumbnail_file = self.thumbnails_dir / f"{wsi_id}.jpeg"
        if thumbnail_file.exists():
            try:
                size = thumbnail_file.stat().st_size
                thumbnail_file.unlink()
                deleted_files.append(str(thumbnail_file))
                total_size += size
                logger.info(f"Deleted thumbnail: {thumbnail_file}")
            except Exception as e:
                failed.append((str(thumbnail_file), str(e)))
                logger.error(f"Failed to delete thumbnail {thumbnail_file}: {e}")
        
        # 4. Delete mask file
        mask_file = self.masks_dir / f"{wsi_id}_mask.npy"
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
        
        # 5. Delete AI results directory
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
        
        # 6. Delete feature files from training tasks (only in complete mode)
        # Note: Features are stored in uploads/training/{task_id}/features/{wsi_id}_features.pt
        # In standard mode, we keep these valuable training features
        if mode == "complete" and self.training_dir.exists():
            for task_dir in self.training_dir.iterdir():
                if task_dir.is_dir():
                    features_dir = task_dir / "features"
                    if features_dir.exists():
                        feature_file = features_dir / f"{wsi_id}_features.pt"
                        if feature_file.exists():
                            try:
                                size = feature_file.stat().st_size
                                feature_file.unlink()
                                deleted_files.append(str(feature_file))
                                total_size += size
                                logger.info(f"Deleted feature file: {feature_file}")
                            except Exception as e:
                                failed.append((str(feature_file), str(e)))
                                logger.error(f"Failed to delete feature file {feature_file}: {e}")

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
    
    def delete_training_task_files(self, task_id: str, model_paths: Optional[List[str]] = None) -> Dict:
        """
        Delete all files associated with a training task.
        
        Files deleted:
        - Training directory: uploads/training/{task_id}/ (entire directory with all features)
        - Log file: uploads/logs/{task_id}.log
        - Model directories: uploads/models/{model_id}/ (if model_paths provided)
        
        Args:
            task_id: Training task identifier
            model_paths: List of model directory paths to delete (optional)
            
        Returns:
            Dictionary with deletion results (same format as delete_wsi_files)
        """
        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0
        
        # 1. Delete training directory (contains all features)
        training_task_dir = self.training_dir / task_id
        if training_task_dir.exists() and training_task_dir.is_dir():
            try:
                size = self._get_dir_size(training_task_dir)
                shutil.rmtree(training_task_dir)
                deleted_dirs.append(str(training_task_dir))
                total_size += size
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
        
        # 3. Delete model directories
        if model_paths:
            for model_path in model_paths:
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
            f"Training task {task_id} storage cleanup: "
            f"{len(deleted_files)} files, {len(deleted_dirs)} directories deleted, "
            f"{len(failed)} failed, {total_size / (1024**2):.2f} MB freed"
        )

        return {
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "failed": failed,
            "total_size": total_size,
            "summary": summary
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
                "thumbnail": {"path": str, "size": int, "exists": bool},
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
            "thumbnail": {},
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

        # Thumbnail
        thumbnail_file = self.thumbnails_dir / f"{wsi_id}.jpeg"
        info["thumbnail"] = self._get_file_info(thumbnail_file)
        if info["thumbnail"]["exists"]:
            info["total_size"] += info["thumbnail"]["size"]
            info["total_files"] += 1

        # Mask
        mask_file = self.masks_dir / f"{wsi_id}_mask.npy"
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

        # Features from training tasks
        if self.training_dir.exists():
            for task_dir in self.training_dir.iterdir():
                if task_dir.is_dir():
                    features_dir = task_dir / "features"
                    if features_dir.exists():
                        feature_file = features_dir / f"{wsi_id}_features.pt"
                        if feature_file.exists():
                            size = feature_file.stat().st_size
                            info["features"].append({
                                "path": str(feature_file),
                                "size": size,
                                "task_id": task_dir.name
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
                    "thumbnails": {"size": int, "file_count": int},
                    "masks": {"size": int, "file_count": int},
                    "ai_results": {"size": int, "file_count": int},
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

        # Thumbnails
        thumbnails_stats = self._get_directory_stats(self.thumbnails_dir)
        stats["breakdown"]["thumbnails"] = thumbnails_stats
        stats["total_size"] += thumbnails_stats["size"]

        # Masks
        masks_stats = self._get_directory_stats(self.masks_dir)
        stats["breakdown"]["masks"] = masks_stats
        stats["total_size"] += masks_stats["size"]

        # AI results
        ai_results_stats = self._get_directory_stats(self.ai_results_dir)
        stats["breakdown"]["ai_results"] = ai_results_stats
        stats["total_size"] += ai_results_stats["size"]

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

        # WSI files (in uploads root, excluding subdirectories)
        wsi_files_size = 0
        wsi_files_count = 0
        if self.uploads_dir.exists():
            for item in self.uploads_dir.iterdir():
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
        """Get total size of a directory in bytes."""
        total = 0
        try:
            for item in directory.rglob('*'):
                if item.is_file():
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
                "orphaned_thumbnails": [...],
                "orphaned_masks": [...],
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
            "orphaned_thumbnails": [],
            "orphaned_masks": [],
            "orphaned_ai_results": [],
            "orphaned_training_dirs": [],
            "orphaned_logs": [],
            "total_orphaned_size": 0,
            "total_orphaned_count": 0
        }

        existing_wsi_set = set(existing_wsi_ids)
        existing_task_set = set(existing_task_ids)

        # Check WSI files
        for item in self.uploads_dir.iterdir():
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

        # Check thumbnails
        thumbnails_dir = self.uploads_dir / "thumbnails"
        if thumbnails_dir.exists():
            for item in thumbnails_dir.glob("*.jpeg"):
                wsi_id = item.stem
                if wsi_id not in existing_wsi_set:
                    size = item.stat().st_size
                    result["orphaned_thumbnails"].append({
                        "path": str(item),
                        "size": size,
                        "wsi_id": wsi_id
                    })
                    result["total_orphaned_size"] += size
                    result["total_orphaned_count"] += 1

        # Check masks
        masks_dir = self.uploads_dir / "masks"
        if masks_dir.exists():
            for item in masks_dir.glob("*_mask.npy"):
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
                       Options: ["wsi_files", "coordinates", "thumbnails", "masks",
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
            categories = ["wsi_files", "coordinates", "thumbnails", "masks",
                         "ai_results", "training_dirs", "logs"]

        deleted_files = []
        deleted_dirs = []
        failed = []
        total_size = 0

        category_map = {
            "wsi_files": "orphaned_wsi_files",
            "coordinates": "orphaned_coordinates",
            "thumbnails": "orphaned_thumbnails",
            "masks": "orphaned_masks",
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

