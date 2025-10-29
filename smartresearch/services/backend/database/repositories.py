"""
Data Access Layer (Repository Pattern)

Provides high-level database operations for all models.
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import WSISlide, AITask, AIResult, ChatConversation, ChatMessage


class WSIRepository:
    """Repository for WSI Slide operations"""

    @staticmethod
    async def create(db: AsyncSession, wsi_data: Dict) -> WSISlide:
        """Create a new WSI slide record"""
        wsi = WSISlide(**wsi_data)
        db.add(wsi)
        await db.flush()
        await db.refresh(wsi)
        return wsi

    @staticmethod
    async def get_by_id(db: AsyncSession, wsi_id: str) -> Optional[WSISlide]:
        """Get WSI by wsi_id"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[WSISlide]:
        """Get all WSI slides with pagination"""
        result = await db.execute(
            select(WSISlide)
            .order_by(desc(WSISlide.created_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_label(db: AsyncSession, label: str) -> List[WSISlide]:
        """Get all WSI slides with specific label"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.label == label)
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, wsi_id: str, update_data: Dict) -> Optional[WSISlide]:
        """Update WSI slide"""
        update_data["updated_at"] = datetime.utcnow()
        await db.execute(
            update(WSISlide)
            .where(WSISlide.wsi_id == wsi_id)
            .values(**update_data)
        )
        await db.flush()
        return await WSIRepository.get_by_id(db, wsi_id)

    @staticmethod
    async def delete(db: AsyncSession, wsi_id: str) -> bool:
        """Delete WSI slide"""
        result = await db.execute(
            delete(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total WSI slides"""
        result = await db.execute(select(func.count(WSISlide.id)))
        return result.scalar()

    @staticmethod
    async def get_label_distribution(db: AsyncSession) -> Dict[str, int]:
        """Get distribution of labels"""
        result = await db.execute(
            select(WSISlide.label, func.count(WSISlide.id))
            .group_by(WSISlide.label)
        )
        return {label: count for label, count in result.all() if label}


class AITaskRepository:
    """Repository for AI Task operations"""

    @staticmethod
    async def create(db: AsyncSession, task_data: Dict) -> AITask:
        """Create a new AI task"""
        task = AITask(**task_data)
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[AITask]:
        """Get task by task_id"""
        result = await db.execute(
            select(AITask).where(AITask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> List[AITask]:
        """Get all tasks for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_latest_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AITask]:
        """Get latest task for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Optional[AITask]:
        """Update task status"""
        update_data = {"status": status}
        
        if progress is not None:
            update_data["progress"] = progress
        
        if error_message is not None:
            update_data["error_message"] = error_message
        
        if status == "running" and not await AITaskRepository._has_started(db, task_id):
            update_data["started_at"] = datetime.utcnow()
        
        if status in ["completed", "failed"]:
            update_data["finished_at"] = datetime.utcnow()
            update_data["progress"] = 100 if status == "completed" else update_data.get("progress", 0)
        
        await db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await AITaskRepository.get_by_id(db, task_id)

    @staticmethod
    async def _has_started(db: AsyncSession, task_id: str) -> bool:
        """Check if task has started_at timestamp"""
        result = await db.execute(
            select(AITask.started_at).where(AITask.task_id == task_id)
        )
        started_at = result.scalar_one_or_none()
        return started_at is not None

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total tasks"""
        result = await db.execute(select(func.count(AITask.id)))
        return result.scalar()

    @staticmethod
    async def count_completed(db: AsyncSession) -> int:
        """Count completed tasks"""
        result = await db.execute(
            select(func.count(AITask.id)).where(AITask.status == "completed")
        )
        return result.scalar()


class AIResultRepository:
    """Repository for AI Result operations"""

    @staticmethod
    async def create(db: AsyncSession, result_data: Dict) -> AIResult:
        """Create a new AI result"""
        result = AIResult(**result_data)
        db.add(result)
        await db.flush()
        await db.refresh(result)
        return result

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AIResult]:
        """Get latest result for a WSI"""
        result = await db.execute(
            select(AIResult)
            .where(AIResult.wsi_id == wsi_id)
            .order_by(desc(AIResult.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> Optional[AIResult]:
        """Get result by task_id"""
        result = await db.execute(
            select(AIResult).where(AIResult.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total results"""
        result = await db.execute(select(func.count(AIResult.id)))
        return result.scalar()


class ChatRepository:
    """Repository for Chat Conversation and Message operations"""

    @staticmethod
    async def create_conversation(db: AsyncSession, conversation_data: Dict) -> ChatConversation:
        """Create a new conversation"""
        conversation = ChatConversation(**conversation_data)
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def get_conversation(db: AsyncSession, conversation_id: str) -> Optional[ChatConversation]:
        """Get conversation by ID with messages"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.conversation_id == conversation_id)
            .options(selectinload(ChatConversation.messages))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_conversations(
        db: AsyncSession,
        user_id: str,
        skip: int = 0,
        limit: int = 50
    ) -> List[ChatConversation]:
        """Get all conversations for a user"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(desc(ChatConversation.updated_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def add_message(db: AsyncSession, message_data: Dict) -> ChatMessage:
        """Add a message to a conversation"""
        message = ChatMessage(**message_data)
        db.add(message)
        
        # Update conversation's updated_at timestamp
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.conversation_id == message_data["conversation_id"])
            .values(updated_at=datetime.utcnow())
        )
        
        await db.flush()
        await db.refresh(message)
        return message

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        conversation_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[ChatMessage]:
        """Get messages for a conversation"""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        result = await db.execute(
            delete(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        await db.flush()
        return result.rowcount > 0

