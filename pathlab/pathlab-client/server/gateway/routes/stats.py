"""
System Statistics API Routes

Provides system-wide statistics including WSI counts, task counts, and label distributions.
"""
import asyncio
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_, case
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session
from backend.database.models import (
    WSISlide, AITask, TrainingTask,
    ChatConversation, ChatMessage, AnnotationDraft, MessageFeedback,
)
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
    DatasetPermissionRepository,
)
from backend.auth import current_active_user, require_admin, User

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("")
async def get_stats(
    user: User = Depends(current_active_user),
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

    # Execute all 6 count queries in parallel using separate sessions
    # (AsyncSession is not safe for concurrent use from multiple coroutines,
    #  so each query gets its own short-lived session)
    async def _count_wsi():
        async with async_session() as db:
            return await WSIRepository.count(db, user_id=user_id_filter)

    async def _count_tasks():
        async with async_session() as db:
            return await AITaskRepository.count(db, user_id=user_id_filter)

    async def _count_completed():
        async with async_session() as db:
            return await AITaskRepository.count_completed(db, user_id=user_id_filter)

    async def _count_results():
        async with async_session() as db:
            return await AIResultRepository.count(db, user_id=user_id_filter)

    async def _get_labels():
        async with async_session() as db:
            return await WSIRepository.get_label_distribution(db, user_id=user_id_filter)

    async def _get_event_status():
        async with async_session() as db:
            return await WSIRepository.get_event_status_distribution(db, user_id=user_id_filter)

    (wsi_count, task_count, completed_count, results_count,
     labels_count, event_status_count) = await asyncio.gather(
        _count_wsi(),
        _count_tasks(),
        _count_completed(),
        _count_results(),
        _get_labels(),
        _get_event_status(),
    )

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


@router.get("/user-usage")
async def get_user_usage_stats(
    user: User = Depends(require_admin),
):
    """
    Get per-user usage statistics for all non-admin users (admin only).

    Returns a list of users with their usage counts across all features:
    WSI uploads, AI tasks, training tasks, chat conversations/messages,
    annotation drafts, and feedback submissions.
    """
    from backend.auth.models import User as UserModel

    async with async_session() as db:
        # Sub-queries for each metric, grouped by user_id
        wsi_sq = (
            select(WSISlide.user_id, func.count(WSISlide.id).label("wsi_count"))
            .group_by(WSISlide.user_id)
            .subquery()
        )
        ai_task_sq = (
            select(AITask.user_id, func.count(AITask.id).label("ai_task_count"))
            .group_by(AITask.user_id)
            .subquery()
        )
        training_sq = (
            select(TrainingTask.user_id, func.count(TrainingTask.id).label("training_count"))
            .group_by(TrainingTask.user_id)
            .subquery()
        )
        conv_sq = (
            select(ChatConversation.user_id, func.count(ChatConversation.id).label("conversation_count"))
            .group_by(ChatConversation.user_id)
            .subquery()
        )
        msg_sq = (
            select(
                ChatConversation.user_id,
                func.count(ChatMessage.id).label("message_count"),
            )
            .join(ChatMessage, ChatMessage.conversation_id == ChatConversation.conversation_id)
            .where(ChatMessage.role == "user")
            .group_by(ChatConversation.user_id)
            .subquery()
        )
        annotation_sq = (
            select(AnnotationDraft.user_id, func.count(AnnotationDraft.id).label("annotation_count"))
            .group_by(AnnotationDraft.user_id)
            .subquery()
        )
        feedback_sq = (
            select(
                MessageFeedback.user_id,
                func.count(MessageFeedback.id).label("feedback_count"),
                func.sum(case((MessageFeedback.feedback_type == "thumbs_up", 1), else_=0)).label("thumbs_up"),
                func.sum(case((MessageFeedback.feedback_type == "thumbs_down", 1), else_=0)).label("thumbs_down"),
            )
            .group_by(MessageFeedback.user_id)
            .subquery()
        )

        # Cast user id to string for joining
        from sqlalchemy import cast, String
        user_id_str = func.cast(UserModel.id, String)

        query = (
            select(
                user_id_str.label("user_id"),
                UserModel.email,
                UserModel.nickname,
                UserModel.role,
                func.coalesce(wsi_sq.c.wsi_count, 0).label("wsi_count"),
                func.coalesce(ai_task_sq.c.ai_task_count, 0).label("ai_task_count"),
                func.coalesce(training_sq.c.training_count, 0).label("training_count"),
                func.coalesce(conv_sq.c.conversation_count, 0).label("conversation_count"),
                func.coalesce(msg_sq.c.message_count, 0).label("message_count"),
                func.coalesce(annotation_sq.c.annotation_count, 0).label("annotation_count"),
                func.coalesce(feedback_sq.c.feedback_count, 0).label("feedback_count"),
                func.coalesce(feedback_sq.c.thumbs_up, 0).label("thumbs_up"),
                func.coalesce(feedback_sq.c.thumbs_down, 0).label("thumbs_down"),
            )
            .outerjoin(wsi_sq, wsi_sq.c.user_id == user_id_str)
            .outerjoin(ai_task_sq, ai_task_sq.c.user_id == user_id_str)
            .outerjoin(training_sq, training_sq.c.user_id == user_id_str)
            .outerjoin(conv_sq, conv_sq.c.user_id == user_id_str)
            .outerjoin(msg_sq, msg_sq.c.user_id == user_id_str)
            .outerjoin(annotation_sq, annotation_sq.c.user_id == user_id_str)
            .outerjoin(feedback_sq, feedback_sq.c.user_id == user_id_str)
            .where(UserModel.role != UserModel.ROLE_ADMIN)
            .where(UserModel.is_active == True)
            .order_by(UserModel.email)
        )

        result = await db.execute(query)
        rows = result.all()

    users = []
    for row in rows:
        users.append({
            "user_id": row.user_id,
            "email": row.email,
            "nickname": row.nickname,
            "role": row.role,
            "wsi_count": row.wsi_count,
            "ai_task_count": row.ai_task_count,
            "training_count": row.training_count,
            "conversation_count": row.conversation_count,
            "message_count": row.message_count,
            "annotation_count": row.annotation_count,
            "feedback_count": row.feedback_count,
            "thumbs_up": row.thumbs_up,
            "thumbs_down": row.thumbs_down,
        })

    return {"users": users}