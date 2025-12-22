"""
Storage management routes
Handles storage statistics, orphaned file detection and cleanup
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab.services.backend.database import get_db
from pathlab.services.backend.database.repositories import (
    WSIRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
)
from ..dependencies import logger, storage_manager
from ..models import OrphanedCleanupRequest

router = APIRouter(prefix="/storage", tags=["Storage Management"])


@router.get("/stats")
async def get_storage_stats():
    """
    Get overall storage statistics.

    Returns:
        {
            "uploads_dir": str,
            "total_size": int,  # bytes
            "total_size_mb": float,
            "total_size_gb": float,
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
    try:
        stats = storage_manager.get_total_storage_stats()

        # Add human-readable sizes
        stats["total_size_mb"] = stats["total_size"] / (1024 ** 2)
        stats["total_size_gb"] = stats["total_size"] / (1024 ** 3)

        return stats
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get storage stats: {str(e)}")


@router.get("/wsi/{wsi_id}")
async def get_wsi_storage_info(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get storage information for a specific WSI.

    Returns detailed information about all files associated with the WSI.
    """
    try:
        # Get WSI from database
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        info = storage_manager.get_wsi_storage_info(wsi_id, wsi.wsi_path)

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
async def get_training_task_storage_info(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get storage information for a specific training task.

    Returns detailed information about all files associated with the training task.
    """
    try:
        # Get training task from database
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {task_id}")

        # Get trained models
        trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
        model_paths = [model.model_path for model in trained_models] if trained_models else []

        info = storage_manager.get_training_task_storage_info(task_id, model_paths)

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
async def detect_orphaned_files(db: AsyncSession = Depends(get_db)):
    """
    Detect orphaned files (files that exist in filesystem but not in database).

    Returns:
        {
            "orphaned_wsi_files": [...],
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
    try:
        # Get all WSI IDs from database
        wsi_list = await WSIRepository.get_all(db)
        existing_wsi_ids = [wsi.wsi_id for wsi in wsi_list]

        # Get all training task IDs from database
        training_tasks = await TrainingTaskRepository.get_all(db)
        existing_task_ids = [task.task_id for task in training_tasks]

        # Find orphaned files
        orphaned = storage_manager.find_orphaned_files(existing_wsi_ids, existing_task_ids)

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
    db: AsyncSession = Depends(get_db)
):
    """
    Clean up orphaned files.

    Request body:
        {
            "categories": ["wsi_files", "coordinates", "thumbnails", "masks",
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

        orphaned = storage_manager.find_orphaned_files(existing_wsi_ids, existing_task_ids)

        # Clean up
        result = storage_manager.cleanup_orphaned_files(orphaned, request.categories)

        logger.info(result['summary'])

        return result
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup orphaned files: {str(e)}")

