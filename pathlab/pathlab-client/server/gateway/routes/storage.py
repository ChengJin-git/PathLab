"""
Storage management routes
Handles storage statistics, orphaned file detection and cleanup
"""
import asyncio
import json
import shutil
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sql_delete
from backend.database import get_db, async_session, safe_session
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    DataGroupRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    StorageTaskRepository,
    OrphanedRecordsRepository,
)
from backend.database.models import TrainingTaskWSI, AIResult, AITask
from backend.auth import current_active_user, User, get_user_from_token_param
from backend.auth.dependencies import require_admin, check_data_ownership
from ..dependencies import logger, storage_manager, migration_manager
from ..models import OrphanedCleanupRequest, StorageConfigRequest, MigrationRequest, ScanDirectoryRequest, CheckExternalFilesRequest, DeleteUnavailableFilesRequest, StartBatchImportRequest, StartDeleteExternalRequest, StartBatchUpdateMetadataRequest
from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.common.file_types import WSI_EXTENSIONS, TIF_EXTENSIONS, SIZE_THRESHOLD, is_patch_file

router = APIRouter(prefix="/storage", tags=["Storage Management"])

# ==============================================================================
# Storage Task Cancellation Mechanism
# ==============================================================================
# Thread-safe set to track cancelled storage tasks
_storage_cancellation_requests: set[str] = set()


def request_storage_task_cancellation(task_id: str) -> bool:
    """
    Request cancellation of a storage task (batch_import or delete_external).

    Returns:
        True if cancellation was requested (task will stop at next iteration)
    """
    _storage_cancellation_requests.add(task_id)
    logger.info(f"Cancellation requested for storage task {task_id}")
    return True


def is_storage_task_cancelled(task_id: str) -> bool:
    """
    Check if a storage task has been requested to cancel.

    Background tasks should call this in their processing loops.
    """
    return task_id in _storage_cancellation_requests


def clear_storage_task_cancellation(task_id: str) -> None:
    """
    Clear the cancellation flag for a storage task after it has been processed.
    """
    _storage_cancellation_requests.discard(task_id)


@router.post("/migrate")
async def start_migration(
    request: MigrationRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
             raise HTTPException(status_code=400, detail="Target path is same as current path")

        # Validate target directory
        target_path_obj = Path(target_dir)
        if not target_path_obj.exists():
            try:
                # Try to create it to check permissions
                target_path_obj.mkdir(parents=True, exist_ok=True)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Target directory does not exist and cannot be created: {target_dir}")

        if not os.access(target_dir, os.W_OK):
            raise HTTPException(status_code=400, detail=f"Target directory is not writable: {target_dir}")

        # Start migration
        success = await migration_manager.start_migration(
            source=current_uploads_dir,
            destination=target_dir,
            delete_source=request.delete_source
        )

        if not success:
            status = migration_manager.get_status()
            if status["status"] == "running":
                raise HTTPException(status_code=409, detail="Migration already in progress")
            else:
                 raise HTTPException(status_code=500, detail="Failed to start migration")

        return {"message": "Migration started", "source": current_uploads_dir, "destination": target_dir}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start migration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start migration: {str(e)}")


@router.get("/migration/status")
async def get_migration_status(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
                db,
                status["source"],
                status["destination"]
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
                "new_path": status["destination"]
            }

        except Exception as e:
            logger.error(f"Migration finalization failed: {e}")
            return {
                "status": "error",
                "error": f"Migration files copied but finalization failed: {str(e)}",
                "progress": 100
            }

    return status

@router.get("/stats")
async def get_storage_stats(
    refresh: bool = Query(False, description="Force refresh cache"),
    user: User = Depends(current_active_user)
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
        stats = await asyncio.to_thread(storage_manager.get_total_storage_stats, refresh)

        # Add human-readable sizes
        stats["total_size_mb"] = stats["total_size"] / (1024 ** 2)
        stats["total_size_gb"] = stats["total_size"] / (1024 ** 3)

        return stats
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get storage stats: {str(e)}")


@router.get("/disk-space")
async def get_disk_space(user: User = Depends(current_active_user)):
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

        free_gb = disk_usage.free / (1024 ** 3)

        return {
            "uploads_dir": str(uploads_dir),
            "total": disk_usage.total,
            "used": disk_usage.used,
            "free": disk_usage.free,
            "total_gb": disk_usage.total / (1024 ** 3),
            "used_gb": disk_usage.used / (1024 ** 3),
            "free_gb": free_gb,
            "usage_percent": (disk_usage.used / disk_usage.total) * 100,
            "warning": free_gb < 10,  # Warning if less than 10GB free
            "critical": free_gb < 1   # Critical if less than 1GB free
        }
    except Exception as e:
        logger.error(f"Failed to get disk space: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get disk space: {str(e)}")


@router.get("/check-upload-space")
async def check_upload_space(
    required_bytes: int,
    user: User = Depends(current_active_user)
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
        free_gb = free_bytes / (1024 ** 3)
        required_gb = required_bytes / (1024 ** 3)

        # Reserve 1GB safety margin
        safety_margin = 1 * (1024 ** 3)  # 1GB
        available_for_upload = free_bytes - safety_margin

        can_upload = required_bytes <= available_for_upload
        remaining_after_upload = (free_bytes - required_bytes) / (1024 ** 3)

        if can_upload:
            message = f"Sufficient space available. {remaining_after_upload:.2f} GB will remain after upload."
        else:
            shortage_gb = (required_bytes - available_for_upload) / (1024 ** 3)
            message = f"Insufficient disk space. Need {shortage_gb:.2f} GB more space (1GB safety margin applied)."

        return {
            "can_upload": can_upload,
            "required_bytes": required_bytes,
            "required_gb": required_gb,
            "free_bytes": free_bytes,
            "free_gb": free_gb,
            "remaining_after_upload_gb": remaining_after_upload,
            "message": message
        }
    except Exception as e:
        logger.error(f"Failed to check upload space: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check upload space: {str(e)}")


@router.get("/config")
async def get_storage_config(user: User = Depends(current_active_user)):
    """Get storage configuration (uploads directory)."""
    return {
        "uploads_dir": str(Config.get_uploads_dir()),
        "source": Config.get_uploads_dir_source(),
    }


@router.post("/config")
async def update_storage_config(
    request: StorageConfigRequest,
    user: User = Depends(require_admin)
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
        raise HTTPException(status_code=500, detail=f"Failed to update storage config: {str(e)}")


@router.get("/wsi/{wsi_id}")
async def get_wsi_storage_info(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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

        # Check ownership
        if not check_data_ownership(wsi.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to view this WSI's storage info")

        # Run file operations in thread pool to avoid blocking event loop
        info = await asyncio.to_thread(
            storage_manager.get_wsi_storage_info,
            wsi_id,
            wsi.wsi_path
        )

        # Add human-readable sizes
        info["total_size_mb"] = info["total_size"] / (1024 ** 2)
        info["total_size_gb"] = info["total_size"] / (1024 ** 3)

        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get WSI storage info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get WSI storage info: {str(e)}")


@router.get("/training/{task_id}")
async def get_training_task_storage_info(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
            raise HTTPException(status_code=404, detail=f"Training task not found: {task_id}")

        # Check ownership
        if not check_data_ownership(task.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to view this task's storage info")

        # Get trained models
        trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
        model_paths = [model.model_path for model in trained_models] if trained_models else []

        # Run file operations in thread pool to avoid blocking event loop
        info = await asyncio.to_thread(
            storage_manager.get_training_task_storage_info,
            task_id,
            model_paths
        )

        # Add human-readable sizes
        info["total_size_mb"] = info["total_size"] / (1024 ** 2)
        info["total_size_gb"] = info["total_size"] / (1024 ** 3)

        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get training task storage info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get training task storage info: {str(e)}")


@router.get("/orphaned")
async def detect_orphaned_files(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
        existing_wsi_ids = [wsi.wsi_id for wsi in wsi_list]

        # Get all training task IDs from database
        training_tasks = await TrainingTaskRepository.get_all(db)
        existing_task_ids = [task.task_id for task in training_tasks]

        # Get all trained model IDs from database
        trained_models = await TrainedModelRepository.get_all(db)
        existing_model_ids = [model.model_id for model in trained_models]

        # Find orphaned files - run in thread pool to avoid blocking event loop
        orphaned = await asyncio.to_thread(
            storage_manager.find_orphaned_files,
            existing_wsi_ids,
            existing_task_ids,
            existing_model_ids
        )

        # Add human-readable sizes
        orphaned["total_orphaned_size_mb"] = orphaned["total_orphaned_size"] / (1024 ** 2)
        orphaned["total_orphaned_size_gb"] = orphaned["total_orphaned_size"] / (1024 ** 3)

        return orphaned
    except Exception as e:
        logger.error(f"Failed to detect orphaned files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to detect orphaned files: {str(e)}")


@router.post("/orphaned/cleanup")
async def cleanup_orphaned_files(
    request: OrphanedCleanupRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
        existing_wsi_ids = [wsi.wsi_id for wsi in wsi_list]

        training_tasks = await TrainingTaskRepository.get_all(db)
        existing_task_ids = [task.task_id for task in training_tasks]

        trained_models = await TrainedModelRepository.get_all(db)
        existing_model_ids = [model.model_id for model in trained_models]

        # Run file operations in thread pool to avoid blocking event loop
        orphaned = await asyncio.to_thread(
            storage_manager.find_orphaned_files,
            existing_wsi_ids,
            existing_task_ids,
            existing_model_ids
        )

        # Clean up - also run in thread pool
        result = await asyncio.to_thread(
            storage_manager.cleanup_orphaned_files,
            orphaned,
            request.categories
        )

        logger.info(result['summary'])

        return result
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup orphaned files: {str(e)}")


@router.get("/orphaned-records")
async def detect_orphaned_records(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
            "orphaned_dataset_permissions": [...],
            "total_orphaned_count": int,
            "summary": {category: count, ...}
        }
    """
    try:
        result = await OrphanedRecordsRepository.detect_orphaned_records(db)
        return result
    except Exception as e:
        logger.error(f"Failed to detect orphaned records: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to detect orphaned records: {str(e)}")


@router.post("/orphaned-records/cleanup")
async def cleanup_orphaned_records(
    request: OrphanedCleanupRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Clean up orphaned database records.
    Admin only operation.

    Request body:
        {
            "categories": ["ai_tasks", "ai_results", "training_task_wsi",
                          "training_logs", "trained_models",
                          "message_feedbacks", "dataset_permissions"]  // optional
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
            db,
            categories=request.categories
        )
        await db.commit()
        logger.info(result['summary'])
        return result
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned records: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to cleanup orphaned records: {str(e)}")


def _scan_directory_for_wsi(directory: str) -> list:
    """
    Scan a directory for WSI and patch files (non-recursive).
    Handles special formats: MRXS (requires data folder), TMAP (may have DT files).

    Supports:
    - WSI files: .svs, .ndpi, .mrxs, .tmap, etc.
    - Patch files: .jpg, .jpeg, .png, .bmp
    - TIF/TIFF files: classified by size (>= 100MB = WSI, < 100MB = patch)

    Returns list of dicts with file info including data_type ('wsi' or 'patch').
    """
    import uuid as uuid_module
    from backend.common.file_types import PATCH_EXTENSIONS

    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    results = []
    seen_stems = set()  # Track processed file stems to avoid duplicates

    # Build a set of all items in directory for quick lookup
    all_items = {item.name: item for item in dir_path.iterdir()}

    for item in dir_path.iterdir():
        if not item.is_file():
            continue

        ext = item.suffix.lower()
        file_size = item.stat().st_size

        # Determine file type: WSI, patch, or skip
        data_type = None
        if ext in WSI_EXTENSIONS:
            data_type = 'wsi'
        elif ext in PATCH_EXTENSIONS:
            data_type = 'patch'
        elif ext in TIF_EXTENSIONS:
            # TIF/TIFF: classify by size
            data_type = 'wsi' if file_size >= SIZE_THRESHOLD else 'patch'

        if data_type is None:
            continue

        # Skip if we've already processed this stem (for MRXS/TMAP handling)
        if item.stem in seen_stems:
            continue
        seen_stems.add(item.stem)

        # Total size includes main file + associated files
        total_size = file_size

        file_info = {
            "path": str(item),
            "filename": item.name,
            "size": file_size,  # Will be updated to include associated files
            "extension": ext,
            "format_type": "standard",
            "data_type": data_type,  # 'wsi' or 'patch'
            "valid": True,
            "validation_message": None,
        }

        # Handle MRXS format - requires data folder with same name
        if ext == '.mrxs':
            file_info["format_type"] = "mrxs"
            data_folder_name = item.stem
            if data_folder_name in all_items and all_items[data_folder_name].is_dir():
                data_folder_path = all_items[data_folder_name]
                file_info["associated_data"] = str(data_folder_path)
                # Calculate total size of data folder
                try:
                    for root, dirs, files in os.walk(data_folder_path):
                        for f in files:
                            total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass  # Ignore errors when calculating folder size
            else:
                file_info["valid"] = False
                file_info["validation_message"] = f"Missing required data folder: {data_folder_name}/"

        # Handle TMAP format - may have DT files
        elif ext == '.tmap':
            file_info["format_type"] = "tmap"
            dt_files = []
            for name, other_item in all_items.items():
                if other_item.is_file() and other_item.stem == item.stem:
                    other_ext = other_item.suffix.lower()
                    if other_ext.startswith('.dt') and len(other_ext) > 3:
                        suffix_num = other_ext[3:]
                        if suffix_num.isdigit():
                            dt_files.append(str(other_item))
                            # Add DT file size to total
                            try:
                                total_size += other_item.stat().st_size
                            except OSError:
                                pass
            if dt_files:
                file_info["associated_data"] = sorted(dt_files)

        # Update size to include associated files
        file_info["size"] = total_size

        results.append(file_info)

    # Sort by filename for consistent ordering
    results.sort(key=lambda x: x["filename"].lower())
    return results


@router.post("/scan-directory")
async def scan_directory(
    request: ScanDirectoryRequest,
    user: User = Depends(require_admin),
):
    """
    Scan a directory for WSI files.
    Admin only operation.

    This scans the specified directory (non-recursive) for WSI files,
    handling special formats like MRXS and TMAP.

    Returns:
        {
            "directory": str,
            "files": [
                {
                    "path": str,
                    "filename": str,
                    "size": int,
                    "extension": str,
                    "format_type": "standard" | "mrxs" | "tmap",
                    "valid": bool,
                    "validation_message": str | null,
                    "associated_data": str | list | null
                }
            ],
            "total_count": int,
            "valid_count": int,
            "total_size": int
        }
    """
    try:
        directory = request.directory_path

        # Validate directory exists
        if not os.path.exists(directory):
            raise HTTPException(status_code=400, detail=f"Directory does not exist: {directory}")

        if not os.path.isdir(directory):
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {directory}")

        if not os.access(directory, os.R_OK):
            raise HTTPException(status_code=400, detail=f"Directory is not readable: {directory}")

        # Scan directory in thread pool to avoid blocking
        files = await asyncio.to_thread(_scan_directory_for_wsi, directory)

        valid_count = sum(1 for f in files if f["valid"])
        total_size = sum(f["size"] for f in files)

        return {
            "directory": directory,
            "files": files,
            "total_count": len(files),
            "valid_count": valid_count,
            "total_size": total_size,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan directory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan directory: {str(e)}")

def _check_wsi_file_availability(wsi_path: str, associated_files: dict = None) -> tuple[bool, str]:
    """
    Check if a WSI file and its associated data are available.

    Uses stored associated_files info to check for required data:
    - MRXS: Requires data folder (stored in associated_files["data_folder"])
    - TMAP: Checks DT files if they were registered (stored in associated_files["dt_files"])

    Args:
        wsi_path: Path to the main WSI file
        associated_files: Dict with format_type and associated data paths (from DB)

    Returns:
        (is_available, message)
    """
    file_path = Path(wsi_path)

    # Check if main file exists
    if not file_path.exists():
        return False, "File not found"

    # If we have associated_files info, use it for validation
    if associated_files:
        format_type = associated_files.get("format_type", "standard")

        # Check MRXS data folder
        if format_type == "mrxs":
            data_folder = associated_files.get("data_folder")
            if data_folder:
                if not Path(data_folder).exists() or not Path(data_folder).is_dir():
                    return False, f"Missing required data folder: {Path(data_folder).name}/"
            else:
                # Fallback: check for data folder with same name as file
                data_folder = file_path.parent / file_path.stem
                if not data_folder.exists() or not data_folder.is_dir():
                    return False, f"Missing required data folder: {file_path.stem}/"

        # Check TMAP DT files (only if they were registered)
        elif format_type == "tmap":
            dt_files = associated_files.get("dt_files", [])
            missing_dt = []
            for dt_file in dt_files:
                if not Path(dt_file).exists():
                    missing_dt.append(Path(dt_file).name)
            if missing_dt:
                return False, f"Missing DT files: {', '.join(missing_dt)}"

    else:
        # Fallback for files registered before this feature: check by extension
        ext = file_path.suffix.lower()
        if ext == '.mrxs':
            data_folder = file_path.parent / file_path.stem
            if not data_folder.exists() or not data_folder.is_dir():
                return False, f"Missing required data folder: {file_path.stem}/"

    return True, "Available"


def _check_external_files_sync(
    wsi_data: list[dict],
    uploads_dir: str
) -> dict:
    """
    Check external files availability synchronously.
    Designed to run in a thread pool via asyncio.to_thread() to avoid blocking the event loop.

    Args:
        wsi_data: List of dicts with keys: wsi_id, original_filename, wsi_path,
                  dataset_id, dataset_name, label, associated_files
        uploads_dir: The system uploads directory path
    """
    available = []
    unavailable = []

    for item in wsi_data:
        wsi_path = item["wsi_path"]

        if not wsi_path.startswith(uploads_dir):
            is_available, message = _check_wsi_file_availability(
                wsi_path,
                item["associated_files"]
            )

            file_info = {
                "wsi_id": item["wsi_id"],
                "original_filename": item["original_filename"],
                "wsi_path": wsi_path,
                "dataset_id": item["dataset_id"],
                "dataset_name": item["dataset_name"],
                "label": item["label"],
            }

            if is_available:
                file_info["status"] = "available"
                available.append(file_info)
            else:
                file_info["status"] = "unavailable"
                file_info["reason"] = message
                unavailable.append(file_info)

    return {
        "total_external": len(available) + len(unavailable),
        "available_count": len(available),
        "unavailable_count": len(unavailable),
        "available": available,
        "unavailable": unavailable,
    }


@router.get("/external-datasets-summary")
async def get_external_datasets_summary(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a lightweight summary of datasets containing externally imported WSI files.

    Only returns dataset names and file counts - NO file availability checks.
    This is a pure database query with no file I/O operations, making it
    much faster than the full /external-datasets endpoint.

    Admin only operation.

    Returns:
        List of datasets with external file counts (no availability status).
    """
    try:
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records with dataset relationship loaded
        wsi_list = await WSIRepository.get_all_with_dataset(db, limit=0)

        # Filter external files and group by dataset (pure string comparison, no file I/O)
        dataset_stats: dict[str, dict] = {}
        for wsi in wsi_list:
            if not wsi.wsi_path.startswith(uploads_dir):
                ds_id = wsi.dataset_id or "uncategorized"
                if ds_id not in dataset_stats:
                    dataset_stats[ds_id] = {
                        "dataset_id": wsi.dataset_id,
                        "dataset_name": wsi.dataset.name if wsi.dataset else "Uncategorized",
                        "total_files": 0,
                    }
                dataset_stats[ds_id]["total_files"] += 1

        datasets = list(dataset_stats.values())
        return {
            "datasets": datasets,
            "total": sum(d["total_files"] for d in datasets)
        }

    except Exception as e:
        logger.error(f"Failed to get external datasets summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get external datasets summary: {str(e)}")


@router.post("/tasks/unbind-dataset")
async def start_unbind_dataset_task(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a background task to unbind (delete records of) all external files in a dataset.

    This removes the database records for externally imported WSI files but does NOT
    delete the actual files on the external drive.

    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records in this dataset
        wsi_list = await WSIRepository.get_by_dataset(db, dataset_id, limit=0)

        # Filter to only external files (use wsi_id, not database id)
        external_wsi_ids = [
            wsi.wsi_id for wsi in wsi_list
            if not wsi.wsi_path.startswith(uploads_dir)
        ]

        if not external_wsi_ids:
            raise HTTPException(
                status_code=400,
                detail="No external files found in this dataset"
            )

        # Generate task ID
        task_id = f"unbind_{uuid.uuid4().hex[:16]}"

        # Get dataset name for display
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        dataset_name = dataset.name if dataset else "Unknown"

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='unbind_dataset',
            total_items=len(external_wsi_ids),
            params={
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "wsi_ids": external_wsi_ids
            }
        )
        await db.commit()

        # Start background task (reuse the delete external task logic)
        background_tasks.add_task(
            _run_delete_external_task,
            task_id,
            str(user.id),
            external_wsi_ids
        )

        return {
            "task_id": task_id,
            "message": f"Unbind dataset task started for '{dataset_name}'",
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "total_files": len(external_wsi_ids)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start unbind dataset task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start unbind dataset task: {str(e)}")


@router.post("/check-external-files")
async def check_external_files(
    request: CheckExternalFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Check availability of externally imported WSI files.

    External files are those whose wsi_path is outside the system's uploads directory.
    This is useful for detecting files that were imported from external drives that
    may have been disconnected.

    Handles special formats:
    - MRXS: Also checks for required data folder
    - TMAP: Checks main file (DT files are optional)

    Admin only operation.

    Returns:
        - available: List of WSI that are still accessible
        - unavailable: List of WSI that are no longer accessible (file not found)
    """
    try:
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records with dataset relationship loaded, optionally filtered by dataset
        if request.dataset_id:
            wsi_list = await WSIRepository.get_by_dataset(db, request.dataset_id, limit=0)
        else:
            wsi_list = await WSIRepository.get_all_with_dataset(db, limit=0)

        # Extract plain data from ORM objects (ORM objects can't cross thread boundaries)
        wsi_data = [
            {
                "wsi_id": wsi.wsi_id,
                "original_filename": wsi.original_filename,
                "wsi_path": wsi.wsi_path,
                "dataset_id": wsi.dataset_id,
                "dataset_name": wsi.dataset.name if wsi.dataset else None,
                "label": wsi.label,
                "associated_files": wsi.associated_files,
            }
            for wsi in wsi_list
        ]

        # Run file availability checks in thread pool to avoid blocking event loop
        result = await asyncio.to_thread(_check_external_files_sync, wsi_data, uploads_dir)
        return result

    except Exception as e:
        logger.error(f"Failed to check external files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check external files: {str(e)}")


@router.post("/delete-unavailable-files")
async def delete_unavailable_files(
    request: DeleteUnavailableFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete WSI records for files that are no longer available.

    This removes the database records for WSI files that cannot be accessed
    (e.g., external drive disconnected). It does NOT delete any actual files.

    Admin only operation.

    Returns:
        - deleted: Number of records deleted
        - failed: Number of records that failed to delete
        - results: Details for each WSI ID
    """
    try:
        deleted_count = 0
        failed_count = 0
        results = []

        for wsi_id in request.wsi_ids:
            try:
                # Get WSI to verify it exists
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if not wsi:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": "WSI not found"
                    })
                    failed_count += 1
                    continue

                # Delete the WSI record (this will cascade delete related records)
                success = await WSIRepository.delete(db, wsi_id)
                if success:
                    await db.commit()
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "deleted",
                        "message": "Record deleted successfully"
                    })
                    deleted_count += 1
                    logger.info(f"Deleted unavailable WSI record: {wsi_id}")
                else:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": "Failed to delete record"
                    })
                    failed_count += 1

            except Exception as e:
                results.append({
                    "wsi_id": wsi_id,
                    "status": "failed",
                    "message": str(e)
                })
                failed_count += 1
                logger.error(f"Failed to delete WSI record {wsi_id}: {e}")

        return {
            "deleted": deleted_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.error(f"Failed to delete unavailable files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete unavailable files: {str(e)}")


# ==============================================================================
# Background Task Functions for Batch Operations
# ==============================================================================

async def _run_batch_import_task(task_id: str, user_id: str, request_params: dict):
    """
    Background task for batch importing WSI files.
    Updates progress in database as it processes files.
    """
    from ..utils import extract_wsi_properties
    import uuid as uuid_module

    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            files = request_params.get('files', [])
            dataset_id = request_params.get('dataset_id')
            dataset_name = request_params.get('dataset_name')
            # data_level in request is actually aggregation_level ('case' or 'file')
            aggregation_level = request_params.get('data_level', 'file')
            task_type = request_params.get('task_type', 'classification')
            default_label = request_params.get('default_label', 'External Import')
            default_event_time = request_params.get('default_event_time')
            default_event_status = request_params.get('default_event_status')

            total_files = len(files)
            results = []
            success_count = 0
            failed_count = 0
            skipped_count = 0

            # Resolve or create dataset
            resolved_dataset_id = None
            resolved_dataset_name = None

            if dataset_id:
                existing_dataset = await DatasetRepository.get_by_id(db, dataset_id)
                if not existing_dataset:
                    await StorageTaskRepository.update_status(
                        db, task_id, 'failed',
                        error_message=f"Dataset not found: {dataset_id}"
                    )
                    await db.commit()
                    return
                resolved_dataset_id = dataset_id
                resolved_dataset_name = existing_dataset.name
            elif dataset_name:
                # Determine data_type from files (default to 'wsi')
                # Check first file to determine if patch or wsi
                data_type = 'wsi'
                if files:
                    first_file_path = files[0].get('path', '') if isinstance(files[0], dict) else files[0].path
                    if is_patch_file(first_file_path):
                        data_type = 'patch'

                # Get or create DataGroup first
                data_group = await DataGroupRepository.get_or_create(
                    db,
                    data_type=data_type,
                    aggregation_level=aggregation_level,
                    task_type=task_type
                )

                # Create dataset with group_id
                dataset = await DatasetRepository.get_or_create(db, dataset_name, group_id=data_group.group_id, user_id=user_id)
                if not dataset.user_id:
                    dataset.user_id = user_id
                    await db.flush()
                resolved_dataset_id = dataset.dataset_id
                resolved_dataset_name = dataset.name
            else:
                await StorageTaskRepository.update_status(
                    db, task_id, 'failed',
                    error_message="Either dataset_id or dataset_name is required"
                )
                await db.commit()
                return

            # Get existing files in dataset to check for duplicates
            existing_wsi = await WSIRepository.get_by_dataset(db, resolved_dataset_id, limit=10000, skip=0)
            existing_set = {wsi.original_filename for wsi in existing_wsi}

            # Process each file
            for i, file_info in enumerate(files):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Batch import task {task_id} cancelled by user at file {i + 1}/{total_files}")
                    clear_storage_task_cancellation(task_id)
                    # Status already updated by cancel endpoint, just exit
                    return

                try:
                    file_path = file_info.get('path') if isinstance(file_info, dict) else file_info.path
                    format_type = file_info.get('format_type', 'standard') if isinstance(file_info, dict) else getattr(file_info, 'format_type', 'standard')
                    associated_data = file_info.get('associated_data') if isinstance(file_info, dict) else getattr(file_info, 'associated_data', None)

                    path_obj = Path(file_path)

                    # Skip if file doesn't exist
                    if not path_obj.exists():
                        results.append({
                            "path": file_path,
                            "wsi_id": None,
                            "status": "failed",
                            "message": "File not found"
                        })
                        failed_count += 1
                        continue

                    # Check for duplicates
                    original_filename = path_obj.name
                    if original_filename in existing_set:
                        results.append({
                            "path": file_path,
                            "wsi_id": None,
                            "status": "skipped",
                            "message": "File already exists in dataset"
                        })
                        skipped_count += 1
                        continue

                    # Extract properties first to get file_size for type detection
                    props = extract_wsi_properties(file_path)
                    file_size = props.get("file_size", 0)

                    # Generate ID based on file type (wsi_xxx or patch_xxx)
                    if is_patch_file(file_path, file_size):
                        wsi_id = f"patch_{uuid_module.uuid4().hex[:16]}"
                    else:
                        wsi_id = f"wsi_{uuid_module.uuid4().hex[:16]}"

                    # Build associated_files JSON
                    associated_files_json = None
                    if format_type in ('mrxs', 'tmap'):
                        associated_files_json = {"format_type": format_type}
                        if format_type == 'mrxs' and associated_data:
                            associated_files_json["data_folder"] = associated_data
                        elif format_type == 'tmap' and associated_data:
                            associated_files_json["dt_files"] = associated_data if isinstance(associated_data, list) else []

                    # Create WSI record
                    wsi_data = {
                        "wsi_id": wsi_id,
                        "original_filename": original_filename,
                        "wsi_path": file_path,
                        "dataset_id": resolved_dataset_id,
                        "file_size": props.get("file_size", 0),
                        "width": props.get("width"),
                        "height": props.get("height"),
                        "mpp": props.get("mpp"),
                        "magnification": props.get("magnification"),
                        "vendor": props.get("vendor"),
                        "user_id": user_id,
                        "associated_files": associated_files_json,
                    }

                    # Set label or survival data based on task type
                    if task_type == "survival":
                        wsi_data["event_time"] = default_event_time
                        wsi_data["event_status"] = default_event_status
                    else:
                        wsi_data["label"] = default_label

                    await WSIRepository.create(db, wsi_data)

                    results.append({
                        "path": file_path,
                        "wsi_id": wsi_id,
                        "status": "success",
                        "message": "Registered successfully"
                    })
                    success_count += 1
                    existing_set.add(original_filename)

                except Exception as e:
                    results.append({
                        "path": file_path if 'file_path' in dir() else str(file_info),
                        "wsi_id": None,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to register WSI in batch import task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_files) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=success_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count
                )
                await db.commit()

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_files,
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results=results
            )
            await db.commit()

            logger.info(f"Batch import task {task_id} completed: {success_count} success, {failed_count} failed, {skipped_count} skipped")

        except Exception as e:
            logger.error(f"Batch import task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()



async def _run_delete_external_task(task_id: str, user_id: str, wsi_ids: list):
    """
    Background task for deleting external WSI records.
    Updates progress in database as it processes files.
    """
    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            total_items = len(wsi_ids)
            results = []
            deleted_count = 0
            failed_count = 0

            for i, wsi_id in enumerate(wsi_ids):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Delete external task {task_id} cancelled by user at item {i + 1}/{total_items}")
                    clear_storage_task_cancellation(task_id)
                    # Status already updated by cancel endpoint, just exit
                    return

                try:
                    # Get WSI to verify it exists and get wsi_path for cache cleanup
                    wsi = await WSIRepository.get_by_id(db, wsi_id)
                    if not wsi:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "WSI not found"
                        })
                        failed_count += 1
                        continue

                    wsi_path = wsi.wsi_path

                    # Delete all associated data before deleting the WSI record
                    # This mirrors the behavior of delete_wsi API in wsi.py
                    try:
                        # Delete training task associations first (foreign key constraint)
                        await db.execute(
                            sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
                        )
                        # Delete AI results
                        await db.execute(
                            sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
                        )
                        # Delete AI tasks
                        await db.execute(
                            sql_delete(AITask).where(AITask.wsi_id == wsi_id)
                        )
                    except Exception as assoc_error:
                        logger.warning(f"Failed to delete associated data for {wsi_id}: {assoc_error}")

                    # Delete the WSI record
                    success = await WSIRepository.delete(db, wsi_id)
                    if success:
                        await db.commit()

                        # Delete all cache files (coordinates, masks, thumbnails, ai_results, features)
                        # Use "complete" mode to delete everything including training features
                        # Pass wsi_path=None to skip deleting the actual WSI file (it's external)
                        try:
                            storage_cleanup = await asyncio.to_thread(
                                storage_manager.delete_wsi_files,
                                wsi_id,
                                None,  # Don't delete the actual WSI file (it's external)
                                "complete"
                            )
                            logger.info(f"Cleaned up cache files for {wsi_id}: {storage_cleanup.get('summary', '')}")
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup cache files for {wsi_id}: {cleanup_error}")

                        results.append({
                            "wsi_id": wsi_id,
                            "status": "deleted",
                            "message": "Record and cache files deleted successfully"
                        })
                        deleted_count += 1
                    else:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "Failed to delete record"
                        })
                        failed_count += 1

                except Exception as e:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to delete WSI {wsi_id} in task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_items) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=deleted_count,
                    failed_count=failed_count
                )
                await db.commit()

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_items,
                success_count=deleted_count,
                failed_count=failed_count,
                results=results
            )
            await db.commit()

            logger.info(f"Delete external task {task_id} completed: {deleted_count} deleted, {failed_count} failed")

        except Exception as e:
            logger.error(f"Delete external task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


async def _run_batch_update_metadata_task(task_id: str, user_id: str, request_params: dict):
    """
    Background task for batch updating WSI metadata.
    Updates progress in database as it processes files.
    Skips updates when the new value matches the existing value.
    """
    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            wsi_ids = request_params.get('wsi_ids', [])
            # Metadata fields to update
            new_label = request_params.get('label')
            new_case_id = request_params.get('case_id')
            new_age = request_params.get('age')
            new_gender = request_params.get('gender')
            new_source = request_params.get('source')
            new_event_time = request_params.get('event_time')
            new_event_status = request_params.get('event_status')

            total_items = len(wsi_ids)
            results = []
            updated_count = 0
            skipped_count = 0
            failed_count = 0

            for i, wsi_id in enumerate(wsi_ids):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Batch update metadata task {task_id} cancelled by user at item {i + 1}/{total_items}")
                    clear_storage_task_cancellation(task_id)
                    return

                try:
                    # Get WSI to check existing values
                    wsi = await WSIRepository.get_by_id(db, wsi_id)
                    if not wsi:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "WSI not found"
                        })
                        failed_count += 1
                        continue

                    # Build update dict, only include fields that are different
                    update_data = {}
                    if new_label is not None and wsi.label != new_label:
                        update_data['label'] = new_label
                    if new_case_id is not None and wsi.case_id != new_case_id:
                        update_data['case_id'] = new_case_id
                    if new_age is not None and wsi.age != new_age:
                        update_data['age'] = new_age
                    if new_gender is not None and wsi.gender != new_gender:
                        update_data['gender'] = new_gender
                    if new_source is not None and wsi.source != new_source:
                        update_data['source'] = new_source
                    if new_event_time is not None and wsi.event_time != new_event_time:
                        update_data['event_time'] = new_event_time
                    if new_event_status is not None and wsi.event_status != new_event_status:
                        update_data['event_status'] = new_event_status

                    # Skip if no changes needed
                    if not update_data:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "skipped",
                            "message": "No changes needed"
                        })
                        skipped_count += 1
                    else:
                        # Perform update
                        await WSIRepository.update(db, wsi_id, update_data)
                        await db.commit()
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "updated",
                            "message": f"Updated {len(update_data)} field(s)"
                        })
                        updated_count += 1

                except Exception as e:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to update WSI {wsi_id} in task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_items) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=updated_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count
                )
                await db.commit()

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_items,
                success_count=updated_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results=results
            )
            await db.commit()

            logger.info(f"Batch update metadata task {task_id} completed: {updated_count} updated, {skipped_count} skipped, {failed_count} failed")

        except Exception as e:
            logger.error(f"Batch update metadata task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


# ==============================================================================
# Background Task API Endpoints
# ==============================================================================

@router.post("/tasks/batch-import")
async def start_batch_import_task(
    request: StartBatchImportRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a batch import background task.
    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        # Generate task ID
        task_id = f"import_{uuid.uuid4().hex[:16]}"

        # Prepare params for storage
        params = {
            "files": [f.model_dump() if hasattr(f, 'model_dump') else f.dict() for f in request.files],
            "dataset_id": request.dataset_id,
            "dataset_name": request.dataset_name,
            "data_level": request.data_level,
            "task_type": request.task_type,
            "default_label": request.default_label,
            "default_event_time": request.default_event_time,
            "default_event_status": request.default_event_status,
        }

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='batch_import',
            total_items=len(request.files),
            params=params
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_batch_import_task,
            task_id,
            str(user.id),
            params
        )

        return {
            "task_id": task_id,
            "message": "Batch import task started",
            "total_files": len(request.files)
        }

    except Exception as e:
        logger.error(f"Failed to start batch import task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start batch import: {str(e)}")


@router.post("/tasks/delete-external")
async def start_delete_external_task(
    request: StartDeleteExternalRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a delete external files background task.
    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        # Generate task ID
        task_id = f"delete_{uuid.uuid4().hex[:16]}"

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='delete_external',
            total_items=len(request.wsi_ids),
            params={"wsi_ids": request.wsi_ids}
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_delete_external_task,
            task_id,
            str(user.id),
            request.wsi_ids
        )

        return {
            "task_id": task_id,
            "message": "Delete external files task started",
            "total_files": len(request.wsi_ids)
        }

    except Exception as e:
        logger.error(f"Failed to start delete external task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start delete external task: {str(e)}")


@router.post("/tasks/batch-update-metadata")
async def start_batch_update_metadata_task(
    request: StartBatchUpdateMetadataRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a batch update metadata background task.
    All authenticated users can update their own WSI metadata.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream

    Optimization: Skips updates when the new value matches the existing value.
    """
    try:
        if not request.wsi_ids:
            raise HTTPException(status_code=400, detail="No WSI IDs provided")

        # Check if at least one field is provided
        has_update = any([
            request.label is not None,
            request.case_id is not None,
            request.age is not None,
            request.gender is not None,
            request.source is not None,
            request.event_time is not None,
            request.event_status is not None,
        ])
        if not has_update:
            return {
                "task_id": "no-op",
                "message": "No metadata fields provided to update, nothing to do",
                "total_items": 0
            }

        # Generate task ID
        task_id = f"update_{uuid.uuid4().hex[:16]}"

        # Prepare params for storage
        params = {
            "wsi_ids": request.wsi_ids,
            "label": request.label,
            "case_id": request.case_id,
            "age": request.age,
            "gender": request.gender,
            "source": request.source,
            "event_time": request.event_time,
            "event_status": request.event_status,
        }

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='batch_update_metadata',
            total_items=len(request.wsi_ids),
            params=params
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_batch_update_metadata_task,
            task_id,
            str(user.id),
            params
        )

        return {
            "task_id": task_id,
            "message": "Batch update metadata task started",
            "total_items": len(request.wsi_ids)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start batch update metadata task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start batch update metadata task: {str(e)}")


@router.get("/tasks/stream")
async def stream_storage_tasks(user: User = Depends(get_user_from_token_param)):
    """
    Server-Sent Events endpoint for real-time storage task updates.
    Streams task status and progress updates to connected clients.

    Admin users see all admin tasks, regular users see nothing (storage tasks are admin-only).

    Note: Uses token query parameter for authentication since EventSource API
    doesn't support custom headers. Token is passed via URL: ?token=<jwt>
    """
    # Only admin users can see storage tasks (they are admin-only operations)
    if not user.is_admin():
        # Non-admin users get empty stream
        async def empty_generator():
            while True:
                yield f"data: {json.dumps({'items': []})}\n\n"
                await asyncio.sleep(5)

        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # For admin users, filter by their user_id to implement targeted push
    # Admin notifications only visible to the admin who created them
    user_id_filter = str(user.id)

    async def event_generator():
        """Generate SSE events with storage task updates"""
        try:
            while True:
                # Use safe_session to ensure proper connection cleanup on cancel
                async with safe_session() as db:
                    try:
                        # Fetch storage tasks for this admin user
                        tasks = await StorageTaskRepository.get_user_tasks(
                            db, user_id=user_id_filter, limit=50
                        )

                        result_tasks = [task.to_dict() for task in tasks]

                        # Send SSE event
                        data = json.dumps({"items": result_tasks})
                        yield f"data: {data}\n\n"
                    except Exception as e:
                        logger.error(f"Error fetching storage tasks in SSE: {e}")
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Wait 2 seconds before next update
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info("SSE storage tasks client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/tasks/{task_id}")
async def get_storage_task(
    task_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get storage task status by ID.
    Admin only operation.
    """
    task = await StorageTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check ownership - admin can only see their own tasks
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return task.to_dict()


@router.delete("/tasks/{task_id}")
async def cancel_storage_task(
    task_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a running storage task (batch_import or delete_external).
    Admin only operation.

    - If the task is running, it will be cancelled at the next iteration
    - If the task is pending, it will be marked as cancelled
    - Already completed/failed/cancelled tasks cannot be cancelled

    Returns:
        {"cancelled": bool, "message": str}
    """
    task = await StorageTaskRepository.get_by_id(db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check ownership
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to cancel this task")

    # Check if task can be cancelled
    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
        return {
            "cancelled": False,
            "message": f"Task {task_id} is already {task.status}"
        }

    # Request cancellation (background task will check this flag)
    request_storage_task_cancellation(task_id)

    # Update database status to cancelled
    await StorageTaskRepository.update_status(
        db,
        task_id,
        status=TaskStatus.CANCELLED,
        error_message="Task cancelled by user"
    )
    await db.commit()

    logger.info(f"Storage task {task_id} cancelled by user {user.id}")

    return {
        "cancelled": True,
        "message": f"Task {task_id} cancelled successfully"
    }