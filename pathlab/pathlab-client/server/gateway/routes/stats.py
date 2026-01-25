"""
System Statistics API Routes

Provides system-wide statistics including WSI counts, task counts, and label distributions.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)
from backend.auth import current_active_user, User

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("")
async def get_stats(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get system statistics including WSI count, task count, and results count.
    Users see only their own data stats, admin sees all.

    Returns:
        {
            "wsi_count": int,
            "task_count": int,
            "completed_count": int,
            "results_count": int,
            "labels": {label: count}
        }
    """
    # Filter by user_id (admin sees all, others see only their own)
    user_id_filter = None if user.is_admin() else str(user.id)

    # Get counts from database
    wsi_count = await WSIRepository.count(db, user_id=user_id_filter)
    task_count = await AITaskRepository.count(db, user_id=user_id_filter)
    completed_count = await AITaskRepository.count_completed(db, user_id=user_id_filter)
    results_count = await AIResultRepository.count(db, user_id=user_id_filter)
    labels_count = await WSIRepository.get_label_distribution(db, user_id=user_id_filter)

    return {
        "wsi_count": wsi_count,
        "task_count": task_count,
        "completed_count": completed_count,
        "results_count": results_count,
        "labels": labels_count
    }

