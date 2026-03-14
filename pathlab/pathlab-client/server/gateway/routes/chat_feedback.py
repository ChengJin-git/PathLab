"""
Chat feedback management routes
Handles message feedback CRUD, admin feedback management, and async export
"""
import csv
import io
import json
import os
import uuid
import tempfile
from datetime import datetime
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import ChatRepository, FeedbackRepository, ExportTaskRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership
from ..dependencies import logger
from ..models import MessageFeedbackRequest

router = APIRouter()


async def _require_message_access(
    message_id: int,
    user: User,
    db: AsyncSession,
):
    """Ensure the current user can access the target message via its conversation."""
    message = await ChatRepository.get_message(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    conversation = message.conversation
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to access this message")

    return message


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: int,
    req: MessageFeedbackRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit or update feedback for a message.
    Supports thumbs up/down ratings and task helpfulness feedback.
    """
    # Validate feedback values
    if req.feedback_type and req.feedback_type not in ["thumbs_up", "thumbs_down"]:
        raise HTTPException(status_code=400, detail="feedback_type must be 'thumbs_up' or 'thumbs_down'")
    if req.task_helpfulness and req.task_helpfulness not in ["helpful", "not_helpful"]:
        raise HTTPException(status_code=400, detail="task_helpfulness must be 'helpful' or 'not_helpful'")

    await _require_message_access(message_id, user, db)

    provided_fields = getattr(req, 'model_fields_set', set())

    # Upsert feedback (convert UUID to string for storage)
    feedback = await FeedbackRepository.upsert_feedback(
        db=db,
        message_id=message_id,
        user_id=str(user.id),
        feedback_type=req.feedback_type,
        feedback_type_provided='feedback_type' in provided_fields,
        task_helpfulness=req.task_helpfulness,
        task_helpfulness_provided='task_helpfulness' in provided_fields,
        related_task_id=req.related_task_id,
        time_to_action_seconds=req.time_to_action_seconds,
        message_content=req.message_content,
        context_messages=req.context_messages,
        task_type=req.task_type,
        task_title=req.task_title
    )
    await db.commit()
    return feedback.to_dict()


@router.get("/messages/{message_id}/feedback")
async def get_feedback(
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get feedback for a specific message."""
    await _require_message_access(message_id, user, db)

    feedback = await FeedbackRepository.get_feedback(db, message_id, str(user.id))
    if not feedback:
        return {"message_id": message_id, "feedback": None}
    return feedback.to_dict()


@router.delete("/messages/{message_id}/feedback")
async def delete_feedback(
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete feedback for a message."""
    await _require_message_access(message_id, user, db)

    success = await FeedbackRepository.delete_feedback(db, message_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")
    await db.commit()
    return {"message": "Feedback deleted successfully"}


@router.get("/conversations/{conversation_id}/feedbacks")
async def get_conversation_feedbacks(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all feedbacks for messages in a conversation."""
    # Verify user has access to this conversation
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to access this conversation")

    feedbacks = await FeedbackRepository.get_feedbacks_for_conversation(db, conversation_id, str(user.id))
    return {"feedbacks": [f.to_dict() for f in feedbacks]}


# ============================================================================
# Admin Feedback Management Endpoints
# ============================================================================

@router.get("/admin/feedbacks")
async def get_admin_feedbacks(
    skip: int = 0,
    limit: int = 50,
    feedback_type: Optional[str] = None,
    helpfulness: Optional[str] = None,
    user_id: Optional[str] = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all feedbacks with pagination and filtering (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    feedbacks, total = await FeedbackRepository.get_all_feedbacks(
        db=db,
        skip=skip,
        limit=limit,
        feedback_type_filter=feedback_type,
        helpfulness_filter=helpfulness,
        user_id_filter=user_id
    )

    # feedbacks is already a list of dicts with username included
    return {
        "feedbacks": feedbacks,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/admin/feedbacks/stats")
async def get_admin_feedback_stats(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get feedback statistics (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    stats = await FeedbackRepository.get_feedback_stats(db)
    return stats


@router.get("/admin/feedbacks/export")
async def export_admin_feedbacks(
    format: str = "json",
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Export all feedbacks (admin only).
    Supports JSON and CSV formats.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get all feedbacks (no pagination for export)
    feedbacks, _ = await FeedbackRepository.get_all_feedbacks(db=db, skip=0, limit=10000)

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # Header
        writer.writerow([
            "id", "message_id", "user_id", "feedback_type",
            "task_helpfulness", "related_task_id", "created_at", "updated_at"
        ])
        # Data rows
        for f in feedbacks:
            # f is already a dict from get_all_feedbacks()
            writer.writerow([
                f.get("id"),
                f.get("message_id"),
                f.get("user_id"),
                f.get("feedback_type"),
                f.get("task_helpfulness"),
                f.get("related_task_id"),
                f.get("created_at"),
                f.get("updated_at")
            ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=feedbacks.csv"}
        )
    else:
        # JSON format (default)
        # feedbacks is already a list of dicts from get_all_feedbacks()
        return {"feedbacks": feedbacks}


@router.delete("/admin/feedbacks/reset")
async def reset_all_feedbacks(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete all feedbacks (admin only).
    This is a destructive operation that cannot be undone.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    deleted_count = await FeedbackRepository.delete_all_feedbacks(db)
    await db.commit()
    return {"message": f"Successfully deleted {deleted_count} feedbacks", "deleted_count": deleted_count}


# Async Export Endpoints


async def process_export_task(
    task_id: str,
    export_type: str,
    file_format: str,
    filter_params: dict[str, Any],
    db_session_maker
):
    """
    Background task to process export in batches.
    Writes directly to file to avoid memory issues.
    """
    async with db_session_maker() as db:
        try:
            # Mark as processing
            await ExportTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            # Parse filter params
            date_from = None
            date_to = None
            if filter_params:
                if filter_params.get('date_from'):
                    # Parse ISO date and strip timezone for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
                    date_from = datetime.fromisoformat(filter_params['date_from'].replace('Z', '+00:00')).replace(tzinfo=None)
                if filter_params.get('date_to'):
                    # Parse ISO date and strip timezone for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
                    date_to = datetime.fromisoformat(filter_params['date_to'].replace('Z', '+00:00')).replace(tzinfo=None)

            # Get total count
            total_count = await FeedbackRepository.get_feedbacks_count(
                db=db,
                feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                user_id_filter=filter_params.get('user_id') if filter_params else None,
                date_from=date_from,
                date_to=date_to
            )

            if total_count == 0:
                await ExportTaskRepository.update_status(
                    db, task_id, 'completed',
                    progress=100,
                    total_records=0,
                    file_path=None
                )
                await db.commit()
                return

            # Create temp file
            export_dir = os.path.join(tempfile.gettempdir(), 'pathlab_exports')
            os.makedirs(export_dir, exist_ok=True)

            file_ext = 'csv' if file_format == 'csv' else 'json'
            file_path = os.path.join(export_dir, f'feedbacks_{task_id}.{file_ext}')

            # Batch export
            batch_size = 1000
            processed = 0

            if file_format == 'csv':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # Header
                    writer.writerow([
                        "id", "message_id", "user_id", "feedback_type",
                        "task_helpfulness", "related_task_id", "time_to_action_seconds",
                        "created_at", "updated_at"
                    ])

                    offset = 0
                    while offset < total_count:
                        feedbacks = await FeedbackRepository.get_feedbacks_batch(
                            db=db,
                            offset=offset,
                            limit=batch_size,
                            feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                            helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                            user_id_filter=filter_params.get('user_id') if filter_params else None,
                            date_from=date_from,
                            date_to=date_to
                        )

                        for f_obj in feedbacks:
                            f_dict = f_obj.to_dict()
                            writer.writerow([
                                f_dict.get("id"),
                                f_dict.get("message_id"),
                                f_dict.get("user_id"),
                                f_dict.get("feedback_type"),
                                f_dict.get("task_helpfulness"),
                                f_dict.get("related_task_id"),
                                f_dict.get("time_to_action_seconds"),
                                f_dict.get("created_at"),
                                f_dict.get("updated_at")
                            ])

                        processed += len(feedbacks)
                        progress = min(99, int(processed / total_count * 100))
                        await ExportTaskRepository.update_status(db, task_id, 'processing', progress=progress)
                        await db.commit()

                        offset += batch_size
                        if len(feedbacks) < batch_size:
                            break
            else:
                # JSON format
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('{"feedbacks": [')
                    first = True

                    offset = 0
                    while offset < total_count:
                        feedbacks = await FeedbackRepository.get_feedbacks_batch(
                            db=db,
                            offset=offset,
                            limit=batch_size,
                            feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                            helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                            user_id_filter=filter_params.get('user_id') if filter_params else None,
                            date_from=date_from,
                            date_to=date_to
                        )

                        for f_obj in feedbacks:
                            if not first:
                                f.write(',')
                            first = False
                            f.write(json.dumps(f_obj.to_dict()))

                        processed += len(feedbacks)
                        progress = min(99, int(processed / total_count * 100))
                        await ExportTaskRepository.update_status(db, task_id, 'processing', progress=progress)
                        await db.commit()

                        offset += batch_size
                        if len(feedbacks) < batch_size:
                            break

                    f.write(']}')

            # Mark as completed
            await ExportTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                file_path=file_path,
                total_records=processed
            )
            await db.commit()

        except Exception as e:
            logger.error(f"Export task {task_id} failed: {e}")
            await ExportTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()



@router.post("/admin/feedbacks/export-async")
async def start_async_export(
    background_tasks: BackgroundTasks,
    format: str = "json",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    feedback_type: Optional[str] = None,
    helpfulness: Optional[str] = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start an async export task (admin only).
    Returns task_id for polling status.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task_id = str(uuid.uuid4())
    filter_params = {
        "date_from": date_from,
        "date_to": date_to,
        "feedback_type": feedback_type,
        "helpfulness": helpfulness
    }

    # Create task record
    await ExportTaskRepository.create(
        db=db,
        task_id=task_id,
        user_id=str(user.id),
        export_type='feedbacks',
        file_format=format,
        filter_params=filter_params
    )
    await db.commit()

    # Get db session maker for background task
    from backend.database import async_session_maker

    # Schedule background task
    background_tasks.add_task(
        process_export_task,
        task_id,
        'feedbacks',
        format,
        filter_params,
        async_session_maker
    )

    return {"task_id": task_id, "status": "pending"}


@router.get("/admin/feedbacks/export-async/{task_id}")
async def get_export_status(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get export task status (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task = await ExportTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")

    return task.to_dict()


@router.get("/admin/feedbacks/export-async/{task_id}/download")
async def download_export_file(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download exported file (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task = await ExportTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")

    if task.status != 'completed':
        raise HTTPException(status_code=400, detail=f"Export not ready. Status: {task.status}")

    if not task.file_path:
        raise HTTPException(status_code=404, detail="No file generated (possibly empty export)")

    if not os.path.exists(task.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")

    filename = f"feedbacks_export.{task.file_format}"
    media_type = "text/csv" if task.file_format == "csv" else "application/json"

    return FileResponse(
        path=task.file_path,
        filename=filename,
        media_type=media_type
    )