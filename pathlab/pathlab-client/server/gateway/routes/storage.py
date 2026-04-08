"""
Storage management routes
Handles storage statistics, orphaned file detection and cleanup.

Batch task operations are in storage_tasks.py.
Directory scanning and external file management are in storage_scan.py.
"""

import asyncio
import shutil
import os
import importlib
from pathlib import Path
from typing import Callable, cast
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .access_control import User, assert_owner
from ..dependencies import logger, storage_manager, migration_manager
from ..models import OrphanedCleanupRequest, StorageConfigRequest, MigrationRequest

_backend_database = importlib.import_module("backend.database")
_backend_repositories = importlib.import_module("backend.database.repositories")
_backend_auth = importlib.import_module("backend.auth")
_backend_auth_dependencies = importlib.import_module("backend.auth.dependencies")
_backend_common_config = importlib.import_module("backend.common.config")

get_db = cast(Callable[..., AsyncSession], _backend_database.get_db)
WSIRepository = _backend_repositories.WSIRepository
TrainingTaskRepository = _backend_repositories.TrainingTaskRepository
TrainedModelRepository = _backend_repositories.TrainedModelRepository
OrphanedRecordsRepository = _backend_repositories.OrphanedRecordsRepository
current_active_user = cast(Callable[..., object], _backend_auth.current_active_user)
require_admin = cast(Callable[..., object], _backend_auth_dependencies.require_admin)
Config = _backend_common_config.Config

router = APIRouter(prefix="/storage", tags=["Storage Management"])


@router.post("/migrate")
async def start_migration(
    request: MigrationRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Start migrating data to a new storage location.
    Admin only operation.

    This runs asynchronously in the background.
    """
    try:
        current_uploads_dir = str(Config.get_uploads_dir())
        target_dir = request.target_path

        # Validate paths
        if not target_dir:
            raise HTTPException(status_code=400, detail="Target path is required")

        if os.path.abspath(current_uploads_dir) == os.path.abspath(target_dir):
            raise HTTPException(
                status_code=400, detail="Target path is same as current path"
            )

        # Validate target directory
        target_path_obj = Path(target_dir)
        if not target_path_obj.exists():
            try:
                # Try to create it to check permissions
                target_path_obj.mkdir(parents=True, exist_ok=True)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target directory does not exist and cannot be created: {target_dir}",
                )

        if not os.access(target_dir, os.W_OK):
            raise HTTPException(
                status_code=400,
                detail=f"Target directory is not writable: {target_dir}",
            )

        # Start migration
        success = await migration_manager.start_migration(
            source=current_uploads_dir,
            destination=target_dir,
            delete_source=request.delete_source,
        )

        if not success:
            status = migration_manager.get_status()
            if status["status"] == "running":
                raise HTTPException(
                    status_code=409, detail="Migration already in progress"
                )
            else:
                raise HTTPException(status_code=500, detail="Failed to start migration")

        return {
            "message": "Migration started",
            "source": current_uploads_dir,
            "destination": target_dir,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start migration: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start migration: {str(e)}"
        )


@router.get("/migration/status")
async def get_migration_status(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """
    Get the status of the current migration task.
    Admin only operation.

    If migration is completed, this endpoint will also trigger:
    1. Database path updates
    2. Config update
    3. Source cleanup (if requested)
    4. Reset of migration manager
    """
    status = migration_manager.get_status()

    if status["status"] == "completed":
        try:
            # Migration just finished successfully
            # Now we need to update the database and config

            # 1. Update DB
            await migration_manager.update_database_paths(
                db, status["source"], status["destination"]
            )

            # 2. Update Config
            Config.set_uploads_dir(status["destination"])
            Config.ensure_directories()
            storage_manager.set_uploads_dir(status["destination"])

            # 3. Cleanup Source (if requested)
            if status["delete_source"]:
                migration_manager.cleanup_source()

            # 4. Reset manager
            migration_manager.reset()

            return {
                "status": "success",
                "message": "Migration completed and applied successfully",
                "new_path": status["destination"],
            }

        except Exception as e:
            logger.error(f"Migration finalization failed: {e}")
            return {
                "status": "error",
                "error": f"Migration files copied but finalization failed: {str(e)}",
                "progress": 100,
            }

    return status


@router.get("/stats")
async def get_storage_stats(
    refresh: bool = Query(False, description="Force refresh cache"),
    user: User = Depends(require_admin),
):
    """
    Get overall storage statistics with caching.

    Results are cached for 60 seconds to improve performance.
    Use refresh=true to force recalculation.

    Returns:
        {
            "uploads_dir": str,
            "total_size": int,  # bytes
            "total_size_mb": float,
            "total_size_gb": float,
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
            "timestamp": str,
            "cached": bool  # True if result is from cache
        }
    """
    try:
        # Run in thread pool to avoid blocking event loop for large directories
        stats = await asyncio.to_thread(
            storage_manager.get_total_storage_stats, refresh
        )

        # Add human-readable sizes
        stats["total_size_mb"] = stats["total_size"] / (1024**2)
        stats["total_size_gb"] = stats["total_size"] / (1024**3)

        return stats
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get storage stats: {str(e)}"
        )


@router.get("/disk-space")
async def get_disk_space(user: User = Depends(require_admin)):
    """
    Get disk space information for the uploads directory.

    Returns:
        {
            "uploads_dir": str,
            "total": int,  # Total disk space in bytes
            "used": int,   # Used disk space in bytes
            "free": int,   # Free disk space in bytes
            "total_gb": float,
            "used_gb": float,
            "free_gb": float,
            "usage_percent": float,  # Percentage of disk used
            "warning": bool,  # True if free space < 10GB
            "critical": bool  # True if free space < 1GB
        }
    """
    try:
        uploads_dir = Config.get_uploads_dir()
        disk_usage = shutil.disk_usage(uploads_dir)

        free_gb = disk_usage.free / (1024**3)

        return {
            "uploads_dir": str(uploads_dir),
            "total": disk_usage.total,
            "used": disk_usage.used,
            "free": disk_usage.free,
            "total_gb": disk_usage.total / (1024**3),
            "used_gb": disk_usage.used / (1024**3),
            "free_gb": free_gb,
            "usage_percent": (disk_usage.used / disk_usage.total) * 100,
            "warning": free_gb < 10,  # Warning if less than 10GB free
            "critical": free_gb < 1,  # Critical if less than 1GB free
        }
    except Exception as e:
        logger.error(f"Failed to get disk space: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get disk space: {str(e)}"
        )


@router.get("/check-upload-space")
async def check_upload_space(
    required_bytes: int, user: User = Depends(current_active_user)
):
    """
    Check if there is enough disk space for an upload.

    Args:
        required_bytes: Required space in bytes for the upload

    Returns:
        {
            "can_upload": bool,
            "required_bytes": int,
            "required_gb": float,
            "free_bytes": int,
            "free_gb": float,
            "remaining_after_upload_gb": float,
            "message": str
        }
    """
    try:
        uploads_dir = Config.get_uploads_dir()
        disk_usage = shutil.disk_usage(uploads_dir)

        free_bytes = disk_usage.free
        free_gb = free_bytes / (1024**3)
        required_gb = required_bytes / (1024**3)

        # Reserve 1GB safety margin
        safety_margin = 1 * (1024**3)  # 1GB
        available_for_upload = free_bytes - safety_margin

        can_upload = required_bytes <= available_for_upload
        remaining_after_upload = (free_bytes - required_bytes) / (1024**3)

        if can_upload:
            message = f"Sufficient space available. {remaining_after_upload:.2f} GB will remain after upload."
        else:
            shortage_gb = (required_bytes - available_for_upload) / (1024**3)
            message = f"Insufficient disk space. Need {shortage_gb:.2f} GB more space (1GB safety margin applied)."

        return {
            "can_upload": can_upload,
            "required_bytes": required_bytes,
            "required_gb": required_gb,
            "free_bytes": free_bytes,
            "free_gb": free_gb,
            "remaining_after_upload_gb": remaining_after_upload,
            "message": message,
        }
    except Exception as e:
        logger.error(f"Failed to check upload space: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to check upload space: {str(e)}"
        )


@router.get("/config")
async def get_storage_config(user: User = Depends(require_admin)):
    """Get storage configuration (uploads directory)."""
    return {
        "uploads_dir": str(Config.get_uploads_dir()),
        "source": Config.get_uploads_dir_source(),
    }


@router.post("/config")
async def update_storage_config(
    request: StorageConfigRequest, user: User = Depends(require_admin)
):
    """Update storage configuration (uploads directory). Admin only."""
    try:
        uploads_dir = Config.set_uploads_dir(request.uploads_dir)
        Config.ensure_directories()
        storage_manager.set_uploads_dir(str(uploads_dir))
        return {
            "uploads_dir": str(uploads_dir),
            "message": "Storage location updated. Restart services to apply across all modules.",
            "restart_required": True,
        }
    except Exception as e:
        logger.error(f"Failed to update storage config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update storage config: {str(e)}"
        )


@router.get("/wsi/{wsi_id}")
async def get_wsi_storage_info(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get storage information for a specific WSI.
    Users can only view storage info for their own WSIs.

    Returns detailed information about all files associated with the WSI.
    """
    try:
        # Get WSI from database
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        assert_owner(
            str(wsi.user_id),
            user,
            "You don't have permission to view this WSI's storage info",
        )

        # Run file operations in thread pool to avoid blocking event loop
        info = await asyncio.to_thread(
            storage_manager.get_wsi_storage_info,
            wsi_id,
            cast(str | None, wsi.wsi_path),
        )

        # Add human-readable sizes
        info["total_size_mb"] = info["total_size"] / (1024**2)
        info["total_size_gb"] = info["total_size"] / (1024**3)

        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get WSI storage info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get WSI storage info: {str(e)}"
        )


@router.get("/training/{task_id}")
async def get_training_task_storage_info(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get storage information for a specific training task.
    Users can only view storage info for their own training tasks.

    Returns detailed information about all files associated with the training task.
    """
    try:
        # Get training task from database
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {task_id}"
            )

        assert_owner(
            str(task.user_id),
            user,
            "You don't have permission to view this task's storage info",
        )

        # Get trained models
        trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
        model_paths = (
            [str(model.model_path) for model in trained_models]
            if trained_models
            else []
        )

        # Run file operations in thread pool to avoid blocking event loop
        info = await asyncio.to_thread(
            storage_manager.get_training_task_storage_info, task_id, model_paths
        )

        # Add human-readable sizes
        info["total_size_mb"] = info["total_size"] / (1024**2)
        info["total_size_gb"] = info["total_size"] / (1024**3)

        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get training task storage info: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get training task storage info: {str(e)}",
        )


@router.get("/orphaned")
async def detect_orphaned_files(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """
    Detect orphaned files (files that exist in filesystem but not in database).
    Admin only operation.

    Returns:
        {
            "orphaned_wsi_files": [...],
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
    try:
        # Get all WSI IDs from database
        wsi_list = await WSIRepository.get_all(db)
        existing_wsi_ids = [str(wsi.wsi_id) for wsi in wsi_list]

        # Get all training task IDs from database
        training_tasks = await TrainingTaskRepository.get_all(db)
        existing_task_ids: list[str] = [
            str(getattr(task, "task_id")) for task in training_tasks
        ]

        # Get all trained model IDs from database
        trained_models = await TrainedModelRepository.get_all(db)
        existing_model_ids = [str(model.model_id) for model in trained_models]

        # Find orphaned files - run in thread pool to avoid blocking event loop
        orphaned = await asyncio.to_thread(
            storage_manager.find_orphaned_files,
            existing_wsi_ids,
            existing_task_ids,
            existing_model_ids,
        )

        # Add human-readable sizes
        orphaned["total_orphaned_size_mb"] = orphaned["total_orphaned_size"] / (1024**2)
        orphaned["total_orphaned_size_gb"] = orphaned["total_orphaned_size"] / (1024**3)

        return orphaned
    except Exception as e:
        logger.error(f"Failed to detect orphaned files: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to detect orphaned files: {str(e)}"
        )


@router.post("/orphaned/cleanup")
async def cleanup_orphaned_files(
    request: OrphanedCleanupRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Clean up orphaned files.
    Admin only operation.

    Request body:
        {
            "categories": ["wsi_files", "coordinates", "masks", "features_cache",
                          "ai_results", "training_dirs", "logs"]  // optional
        }

    Returns:
        {
            "deleted_files": [...],
            "deleted_dirs": [...],
            "failed": [...],
            "total_size": int,
            "summary": str
        }
    """
    try:
        # First detect orphaned files
        wsi_list = await WSIRepository.get_all(db)
        existing_wsi_ids = [str(wsi.wsi_id) for wsi in wsi_list]

        training_tasks = await TrainingTaskRepository.get_all(db)
        existing_task_ids: list[str] = [
            str(getattr(task, "task_id")) for task in training_tasks
        ]

        trained_models = await TrainedModelRepository.get_all(db)
        existing_model_ids = [str(model.model_id) for model in trained_models]

        # Run file operations in thread pool to avoid blocking event loop
        orphaned = await asyncio.to_thread(
            storage_manager.find_orphaned_files,
            existing_wsi_ids,
            existing_task_ids,
            existing_model_ids,
        )

        # Clean up - also run in thread pool
        result = await asyncio.to_thread(
            storage_manager.cleanup_orphaned_files,
            orphaned,
            request.categories or [],
        )

        logger.info(result["summary"])

        return result
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned files: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cleanup orphaned files: {str(e)}"
        )


@router.get("/orphaned-records")
async def detect_orphaned_records(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """
    Detect orphaned database records (records whose referenced entities no longer exist).
    Admin only operation.

    This is the inverse of orphaned files detection:
    - Orphaned files: files exist but no database record
    - Orphaned records: database records exist but referenced entities deleted

    Returns:
        {
            "orphaned_ai_tasks": [...],
            "orphaned_ai_results": [...],
            "orphaned_training_task_wsi": [...],
            "orphaned_training_logs": [...],
            "orphaned_trained_models": [...],
            "orphaned_message_feedbacks": [...],
            "orphaned_dataset_grants": [...],
            "total_orphaned_count": int,
            "summary": {category: count, ...}
        }
    """
    try:
        result = await OrphanedRecordsRepository.detect_orphaned_records(db)
        return result
    except Exception as e:
        logger.error(f"Failed to detect orphaned records: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to detect orphaned records: {str(e)}"
        )


@router.post("/orphaned-records/cleanup")
async def cleanup_orphaned_records(
    request: OrphanedCleanupRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Clean up orphaned database records.
    Admin only operation.

    Request body:
        {
            "categories": ["ai_tasks", "ai_results", "training_task_wsi",
                          "training_logs", "trained_models",
                          "message_feedbacks", "dataset_grants"]
        }

    Returns:
        {
            "deleted_counts": {category: count, ...},
            "total_deleted": int,
            "summary": str
        }
    """
    try:
        result = await OrphanedRecordsRepository.cleanup_orphaned_records(
            db, categories=request.categories
        )
        await db.commit()
        logger.info(result["summary"])
        return result
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned records: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to cleanup orphaned records: {str(e)}"
        )


# ==============================================================================
# Include sub-routers for batch tasks and scanning/external file management
# ==============================================================================
from .storage_tasks import router as storage_tasks_router
from .storage_scan import router as storage_scan_router

router.include_router(storage_tasks_router)
router.include_router(storage_scan_router)
