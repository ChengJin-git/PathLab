"""
FeedbackRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, delete, func, desc, insert, cast, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import ChatMessage, MessageFeedback


class FeedbackRepository:
    """Repository for Message Feedback operations"""

    @staticmethod
    async def _update_feedback_fields(
        existing: MessageFeedback,
        feedback_type: Optional[str],
        feedback_type_provided: bool,
        task_helpfulness: Optional[str],
        task_helpfulness_provided: bool,
        related_task_id: Optional[str],
        time_to_action_seconds: Optional[float],
        message_content: Optional[str],
        context_messages: Optional[List[dict[str, Any]]],
        task_type: Optional[str],
        task_title: Optional[str],
    ) -> None:
        """Apply provided fields to an existing feedback record."""
        if feedback_type_provided:
            existing.feedback_type = feedback_type
        if task_helpfulness_provided:
            existing.task_helpfulness = task_helpfulness
        if related_task_id is not None:
            existing.related_task_id = related_task_id
        if time_to_action_seconds is not None:
            existing.time_to_action_seconds = time_to_action_seconds
        if message_content is not None:
            existing.message_content = message_content
        if context_messages is not None:
            existing.context_messages = context_messages
        if task_type is not None:
            existing.task_type = task_type
        if task_title is not None:
            existing.task_title = task_title

    @staticmethod
    async def upsert_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str,
        feedback_type: Optional[str] = None,
        feedback_type_provided: bool = False,
        task_helpfulness: Optional[str] = None,
        task_helpfulness_provided: bool = False,
        related_task_id: Optional[str] = None,
        time_to_action_seconds: Optional[float] = None,
        message_content: Optional[str] = None,
        context_messages: Optional[List[dict[str, Any]]] = None,
        task_type: Optional[str] = None,
        task_title: Optional[str] = None
    ) -> MessageFeedback:
        """
        Create or update feedback for a message.
        Uses upsert logic: if feedback exists, update it; otherwise, create new.
        Preserves message content and task info for admin review even if conversation is deleted.

        Race-condition safe under PostgreSQL READ COMMITTED:
        Uses SAVEPOINT + IntegrityError catch to handle concurrent inserts
        (UNIQUE constraint on message_id + user_id).
        """
        # Check if feedback already exists
        result = await db.execute(
            select(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing feedback
            await FeedbackRepository._update_feedback_fields(
                existing, feedback_type, feedback_type_provided,
                task_helpfulness, task_helpfulness_provided, related_task_id,
                time_to_action_seconds, message_content, context_messages,
                task_type, task_title,
            )
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            # Create new feedback — use SAVEPOINT for concurrent insert safety
            feedback = MessageFeedback(
                message_id=message_id,
                user_id=user_id,
                feedback_type=feedback_type,
                task_helpfulness=task_helpfulness,
                related_task_id=related_task_id,
                time_to_action_seconds=time_to_action_seconds,
                message_content=message_content,
                context_messages=context_messages,
                task_type=task_type,
                task_title=task_title
            )
            try:
                async with db.begin_nested():
                    db.add(feedback)
                    await db.flush()
                    await db.refresh(feedback)
                    return feedback
            except IntegrityError:
                # Another concurrent request created feedback for same message+user
                logger.debug(f"Feedback concurrent insert for message_id={message_id}, user_id={user_id}, falling back to update")
                result = await db.execute(
                    select(MessageFeedback)
                    .where(MessageFeedback.message_id == message_id)
                    .where(MessageFeedback.user_id == user_id)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    await FeedbackRepository._update_feedback_fields(
                        existing, feedback_type, feedback_type_provided,
                        task_helpfulness, task_helpfulness_provided, related_task_id,
                        time_to_action_seconds, message_content, context_messages,
                        task_type, task_title,
                    )
                    await db.flush()
                    await db.refresh(existing)
                    return existing
                raise  # Should not happen

    @staticmethod
    async def get_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str
    ) -> Optional[MessageFeedback]:
        """Get feedback for a specific message and user"""
        result = await db.execute(
            select(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_feedbacks_for_conversation(
        db: AsyncSession,
        conversation_id: str,
        user_id: str
    ) -> List[MessageFeedback]:
        """Get all feedbacks for messages in a conversation"""
        result = await db.execute(
            select(MessageFeedback)
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(MessageFeedback.user_id == user_id)
        )
        return result.scalars().all()

    @staticmethod
    async def delete_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str
    ) -> bool:
        """Delete feedback for a message"""
        result = await db.execute(
            delete(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_all_feedbacks(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> tuple[List[dict[str, Any]], int]:
        """
        Get all feedbacks with pagination and filtering (admin only).
        Returns tuple of (feedbacks list with username, total count).
        """
        from backend.auth.models import User as AuthUser
        from sqlalchemy import cast, String

        # Build base query - join with User table to get username
        # Note: user_id in MessageFeedback is stored as string, User.id is UUID
        query = (
            select(MessageFeedback, AuthUser.email, AuthUser.nickname)
            .outerjoin(AuthUser, MessageFeedback.user_id == cast(AuthUser.id, String))
            .options(selectinload(MessageFeedback.message))
        )

        # Apply filters
        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        # Get total count (only count MessageFeedback rows)
        count_subquery = select(MessageFeedback.id)
        if feedback_type_filter:
            count_subquery = count_subquery.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            count_subquery = count_subquery.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            count_subquery = count_subquery.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            count_subquery = count_subquery.where(MessageFeedback.created_at >= date_from)
        if date_to:
            count_subquery = count_subquery.where(MessageFeedback.created_at <= date_to)
        count_query = select(func.count()).select_from(count_subquery.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Apply pagination and ordering
        query = query.order_by(desc(MessageFeedback.created_at)).offset(skip).limit(limit)

        result = await db.execute(query)
        rows = result.all()

        # Convert to dict with username
        feedbacks_with_username = []
        for row in rows:
            feedback = row[0]  # MessageFeedback object
            email = row[1]  # User.email (username)
            nickname = row[2]  # User.nickname

            feedback_dict = feedback.to_dict()
            # Use nickname if available, otherwise use email (username)
            feedback_dict["username"] = nickname or email or None
            feedbacks_with_username.append(feedback_dict)

        return feedbacks_with_username, total

    @staticmethod
    async def get_feedback_stats(db: AsyncSession) -> Dict[str, Any]:
        """
        Get feedback statistics (admin only).
        Returns counts of different feedback types and helpfulness ratings.
        """
        # Total count
        total_result = await db.execute(select(func.count(MessageFeedback.id)))
        total = total_result.scalar() or 0

        # Thumbs up count
        thumbs_up_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.feedback_type == 'thumbs_up')
        )
        thumbs_up = thumbs_up_result.scalar() or 0

        # Thumbs down count
        thumbs_down_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.feedback_type == 'thumbs_down')
        )
        thumbs_down = thumbs_down_result.scalar() or 0

        # Helpful count
        helpful_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.task_helpfulness == 'helpful')
        )
        helpful = helpful_result.scalar() or 0

        # Not helpful count
        not_helpful_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.task_helpfulness == 'not_helpful')
        )
        not_helpful = not_helpful_result.scalar() or 0

        # Unique users count
        unique_users_result = await db.execute(
            select(func.count(func.distinct(MessageFeedback.user_id)))
        )
        unique_users = unique_users_result.scalar() or 0

        # Average time to action (only for records with time data)
        avg_time_result = await db.execute(
            select(func.avg(MessageFeedback.time_to_action_seconds))
            .where(MessageFeedback.time_to_action_seconds.isnot(None))
        )
        avg_time = avg_time_result.scalar()
        avg_time_to_action = round(avg_time, 1) if avg_time else None

        return {
            "total_feedbacks": total,
            "thumbs_up_count": thumbs_up,
            "thumbs_down_count": thumbs_down,
            "helpful_count": helpful,
            "not_helpful_count": not_helpful,
            "unique_users": unique_users,
            "avg_time_to_action_seconds": avg_time_to_action
        }

    @staticmethod
    async def delete_all_feedbacks(db: AsyncSession, batch_size: int = 1000) -> int:
        """
        Delete all feedbacks in batches (admin only).
        Uses batch deletion to handle large datasets efficiently.
        Returns the number of deleted records.
        """
        total_deleted = 0

        while True:
            # Get batch of IDs to delete
            result = await db.execute(
                select(MessageFeedback.id).limit(batch_size)
            )
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Delete this batch
            await db.execute(
                delete(MessageFeedback).where(MessageFeedback.id.in_(ids_to_delete))
            )
            await db.commit()
            total_deleted += len(ids_to_delete)

            # If we got fewer than batch_size, we're done
            if len(ids_to_delete) < batch_size:
                break

        return total_deleted

    @staticmethod
    async def get_feedbacks_count(
        db: AsyncSession,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> int:
        """
        Get total count of feedbacks matching filters.
        Used for export progress tracking.
        """
        query = select(func.count(MessageFeedback.id))

        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        result = await db.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_feedbacks_batch(
        db: AsyncSession,
        offset: int,
        limit: int,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[MessageFeedback]:
        """
        Get a batch of feedbacks for streaming export.
        Returns feedbacks without the total count for efficiency.
        """
        query = select(MessageFeedback).options(selectinload(MessageFeedback.message))

        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        query = query.order_by(MessageFeedback.id).offset(offset).limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

