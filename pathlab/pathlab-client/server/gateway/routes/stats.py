"""
System Statistics API Routes

Provides system-wide statistics including WSI counts, task counts, and label distributions.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.database.models import WSISlide, AITask, TrainingTask
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
    DatasetPermissionRepository,
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
            "labels": {label: count},
            "event_status": {"event": count, "censored": count}
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
    event_status_count = await WSIRepository.get_event_status_distribution(db, user_id=user_id_filter)

    return {
        "wsi_count": wsi_count,
        "task_count": task_count,
        "completed_count": completed_count,
        "results_count": results_count,
        "labels": labels_count,
        "event_status": event_status_count
    }


@router.get("/recent-activity")
async def get_recent_activity(
    upload_limit: int = Query(5, ge=1, le=20, description="Number of recent uploads to return"),
    task_limit: int = Query(5, ge=1, le=20, description="Number of recent tasks to return"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get recent activity for the current user.
    Users see their own data + data from datasets they have elevated permissions for.
    Admin sees all.

    Returns:
        {
            "recent_uploads": [...],  # Recently uploaded WSI files
            "recent_tasks": [...]     # Recently submitted tasks (AI + Training)
        }
    """
    is_admin = user.is_admin()
    user_id = str(user.id)

    # Get datasets the user has elevated permissions for (non-admin only)
    permitted_dataset_ids = []
    if not is_admin:
        permissions = await DatasetPermissionRepository.get_valid_by_user(db, user_id)
        permitted_dataset_ids = [p.dataset_id for p in permissions]

    # Get recent uploads (WSI slides)
    # User can see: their own uploads OR uploads in datasets they have permission for
    uploads_query = select(WSISlide).options(selectinload(WSISlide.dataset))
    if not is_admin:
        if permitted_dataset_ids:
            # User's own uploads OR uploads in permitted datasets
            uploads_query = uploads_query.where(
                or_(
                    WSISlide.user_id == user_id,
                    WSISlide.dataset_id.in_(permitted_dataset_ids)
                )
            )
        else:
            # Only user's own uploads
            uploads_query = uploads_query.where(WSISlide.user_id == user_id)
    uploads_query = uploads_query.order_by(desc(WSISlide.created_at)).limit(upload_limit)
    uploads_result = await db.execute(uploads_query)
    recent_uploads = uploads_result.scalars().all()

    # Get recent AI tasks
    # User can see: their own tasks only (tasks are always owned by the user who created them)
    ai_tasks_query = select(AITask)
    if not is_admin:
        ai_tasks_query = ai_tasks_query.where(AITask.user_id == user_id)
    ai_tasks_query = ai_tasks_query.order_by(desc(AITask.created_at)).limit(task_limit)
    ai_tasks_result = await db.execute(ai_tasks_query)
    recent_ai_tasks = ai_tasks_result.scalars().all()

    # Get recent training tasks
    # User can see: their own tasks only
    # Note: must load data_group relationship for to_dict() to work
    training_tasks_query = select(TrainingTask).options(selectinload(TrainingTask.data_group))
    if not is_admin:
        training_tasks_query = training_tasks_query.where(TrainingTask.user_id == user_id)
    training_tasks_query = training_tasks_query.order_by(desc(TrainingTask.created_at)).limit(task_limit)
    training_tasks_result = await db.execute(training_tasks_query)
    recent_training_tasks = training_tasks_result.scalars().all()

    # Combine and sort tasks by created_at
    all_tasks = []
    for task in recent_ai_tasks:
        task_dict = task.to_dict()
        task_dict["task_category"] = "inference"
        all_tasks.append(task_dict)
    for task in recent_training_tasks:
        task_dict = task.to_dict()
        task_dict["task_category"] = "training"
        all_tasks.append(task_dict)

    # Sort by created_at descending and limit
    all_tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    recent_tasks = all_tasks[:task_limit]

    return {
        "recent_uploads": [wsi.to_dict() for wsi in recent_uploads],
        "recent_tasks": recent_tasks
    }
