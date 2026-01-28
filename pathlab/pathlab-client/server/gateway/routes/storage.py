"""
Storage management routes
Handles storage statistics, orphaned file detection and cleanup
"""
import asyncio
import shutil
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin, check_data_ownership
from ..dependencies import logger, storage_manager, migration_manager
from ..models import OrphanedCleanupRequest, StorageConfigRequest, MigrationRequest, ScanDirectoryRequest, BatchRegisterRequest
from backend.common.config import Config
from backend.common.file_types import WSI_EXTENSIONS, TIF_EXTENSIONS, SIZE_THRESHOLD

router = APIRouter(prefix="/storage", tags=["Storage Management"])


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


def _scan_directory_for_wsi(directory: str) -> list:
    """
    Scan a directory for WSI files (non-recursive).
    Handles special formats: MRXS (requires data folder), TMAP (may have DT files).

    Returns list of dicts with file info.
    """
    import uuid as uuid_module

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

        # Check if it's a WSI file
        is_wsi = False
        if ext in WSI_EXTENSIONS:
            is_wsi = True
        elif ext in TIF_EXTENSIONS and file_size >= SIZE_THRESHOLD:
            is_wsi = True

        if not is_wsi:
            continue

        # Skip if we've already processed this stem (for MRXS/TMAP handling)
        if item.stem in seen_stems:
            continue
        seen_stems.add(item.stem)

        file_info = {
            "path": str(item),
            "filename": item.name,
            "size": file_size,
            "extension": ext,
            "format_type": "standard",
            "valid": True,
            "validation_message": None,
        }

        # Handle MRXS format - requires data folder with same name
        if ext == '.mrxs':
            file_info["format_type"] = "mrxs"
            data_folder_name = item.stem
            if data_folder_name in all_items and all_items[data_folder_name].is_dir():
                file_info["associated_data"] = str(all_items[data_folder_name])
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
            if dt_files:
                file_info["associated_data"] = sorted(dt_files)

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


@router.post("/batch-register")
async def batch_register_wsi(
    request: BatchRegisterRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Batch register WSI files from scanned directory.
    Admin only operation.

    This registers multiple WSI files to a dataset without copying them.
    Files must already exist on the server.

    Args:
        request: BatchRegisterRequest with file paths and dataset info

    Returns:
        {
            "total": int,
            "success": int,
            "failed": int,
            "dataset_id": str,
            "dataset_name": str,
            "results": [
                {
                    "path": str,
                    "wsi_id": str | null,
                    "status": "success" | "failed" | "skipped",
                    "message": str
                }
            ]
        }
    """
    import uuid as uuid_module
    from ..utils import extract_wsi_properties

    try:
        if not request.files:
            raise HTTPException(status_code=400, detail="No files provided")

        # Resolve or create dataset
        resolved_dataset_id = None
        dataset_name = None

        if request.dataset_id:
            existing_dataset = await DatasetRepository.get_by_id(db, request.dataset_id)
            if not existing_dataset:
                raise HTTPException(status_code=400, detail=f"Dataset not found: {request.dataset_id}")
            resolved_dataset_id = request.dataset_id
            dataset_name = existing_dataset.name
        elif request.dataset_name:
            dataset = await DatasetRepository.get_or_create(db, request.dataset_name)
            # Set owner to current admin user
            if not dataset.user_id:
                dataset.user_id = str(user.id)
                await db.flush()
            resolved_dataset_id = dataset.dataset_id
            dataset_name = dataset.name
        else:
            raise HTTPException(status_code=400, detail="Either dataset_id or dataset_name is required")

        results = []
        success_count = 0
        failed_count = 0
        skipped_count = 0

        # Get existing filenames to check for duplicates
        existing_filenames = await WSIRepository.get_existing_original_filenames(
            db,
            [Path(f).name for f in request.files],
            user_id=None  # Admin sees all
        )
        existing_set = set(existing_filenames)

        for file_path in request.files:
            try:
                wsi_file = Path(file_path)
                original_filename = wsi_file.name

                # Check if file already registered
                if original_filename in existing_set:
                    results.append({
                        "path": file_path,
                        "wsi_id": None,
                        "status": "skipped",
                        "message": f"File already registered: {original_filename}"
                    })
                    skipped_count += 1
                    continue

                # Validate file exists
                if not os.path.exists(file_path):
                    results.append({
                        "path": file_path,
                        "wsi_id": None,
                        "status": "failed",
                        "message": f"File not found: {file_path}"
                    })
                    failed_count += 1
                    continue

                # Generate UUID
                wsi_id = str(uuid_module.uuid4())

                # Get file size
                file_size = os.path.getsize(file_path)

                # Extract WSI properties (run in thread to avoid blocking)
                wsi_props = await asyncio.to_thread(extract_wsi_properties, file_path)

                # Generate case_id
                case_id = f"case_{wsi_id[:8]}"

                # Create WSI data
                wsi_data = {
                    "wsi_id": wsi_id,
                    "original_filename": original_filename,
                    "dataset_id": resolved_dataset_id,
                    "label": request.default_label or "Unknown",
                    "case_id": case_id,
                    "wsi_path": file_path,
                    "file_size": file_size,
                    "event_time": request.default_event_time,
                    "event_status": request.default_event_status,
                    "mpp": wsi_props["mpp"],
                    "vendor": wsi_props["vendor"],
                    "width": wsi_props["width"],
                    "height": wsi_props["height"],
                    "magnification": wsi_props["magnification"],
                    "user_id": str(user.id),
                }

                wsi = await WSIRepository.create(db, wsi_data)

                # Save metadata to JSON file
                try:
                    storage_manager.save_wsi_metadata(wsi_id, wsi_data)
                except Exception as meta_err:
                    logger.warning(f"Failed to save metadata file for {wsi_id}: {meta_err}")

                results.append({
                    "path": file_path,
                    "wsi_id": wsi_id,
                    "status": "success",
                    "message": "Registered successfully"
                })
                success_count += 1
                existing_set.add(original_filename)  # Prevent duplicates within batch

                logger.info(f"Batch registered WSI: {original_filename} -> {wsi_id}")

            except Exception as e:
                results.append({
                    "path": file_path,
                    "wsi_id": None,
                    "status": "failed",
                    "message": str(e)
                })
                failed_count += 1
                logger.error(f"Failed to register WSI {file_path}: {e}")

        # Commit all changes
        await db.commit()

        return {
            "total": len(request.files),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "dataset_id": resolved_dataset_id,
            "dataset_name": dataset_name,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to batch register WSI files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to batch register: {str(e)}")

