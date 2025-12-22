"""
System Statistics API Routes

Provides system-wide statistics including WSI counts, task counts, and label distributions.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab.services.backend.database import get_db
from pathlab.services.backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    Get system statistics including WSI count, task count, and results count.
    
    Returns:
        {
            "wsi_count": int,
            "task_count": int,
            "completed_count": int,
            "results_count": int,
            "labels": {label: count}
        }
    """
    # Get counts from database
    wsi_count = await WSIRepository.count(db)
    task_count = await AITaskRepository.count(db)
    completed_count = await AITaskRepository.count_completed(db)
    results_count = await AIResultRepository.count(db)
    labels_count = await WSIRepository.get_label_distribution(db)

    return {
        "wsi_count": wsi_count,
        "task_count": task_count,
        "completed_count": completed_count,
        "results_count": results_count,
        "labels": labels_count
    }

