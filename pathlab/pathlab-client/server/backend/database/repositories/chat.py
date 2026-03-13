"""
ChatRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import ChatConversation, ChatMessage, utc_now


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
    async def get_conversation_meta(db: AsyncSession, conversation_id: str) -> Optional[ChatConversation]:
        """Get conversation by ID without loading messages (lightweight)."""
        result = await db.execute(
            select(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_message(db: AsyncSession, message_id: int) -> Optional[ChatMessage]:
        """Get a chat message by ID with its parent conversation loaded."""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.id == message_id)
            .options(selectinload(ChatMessage.conversation))
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
    async def update_conversation_title(
        db: AsyncSession,
        conversation_id: str,
        title: str
    ) -> Optional[ChatConversation]:
        """Update a conversation's title"""
        result = await db.execute(
            select(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation:
            conversation.title = title
            conversation.updated_at = utc_now()
            await db.flush()
            await db.refresh(conversation)
        return conversation

    @staticmethod
    async def add_message(db: AsyncSession, message_data: Dict) -> ChatMessage:
        """Add a message to a conversation"""
        message = ChatMessage(**message_data)
        db.add(message)

        # Update conversation's updated_at timestamp
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.conversation_id == message_data["conversation_id"])
            .values(updated_at=utc_now())
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
    async def update_message(
        db: AsyncSession,
        message_id: int,
        content: str
    ) -> Optional[ChatMessage]:
        """Update a message's content"""
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        message = result.scalar_one_or_none()
        if message:
            message.content = content
            await db.flush()
            await db.refresh(message)
        return message

    @staticmethod
    async def delete_messages_from_id(
        db: AsyncSession,
        conversation_id: str,
        message_id: int
    ) -> int:
        """
        Delete a message and all subsequent messages in a conversation.
        Used for conversation branching - delete from a point to start a new branch.

        Args:
            db: Database session
            conversation_id: Conversation ID
            message_id: The message ID from which to start deletion (inclusive)

        Returns:
            Number of deleted messages
        """
        # Get the message to find its created_at timestamp
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.id == message_id)
            .where(ChatMessage.conversation_id == conversation_id)
        )
        target_message = result.scalar_one_or_none()

        if not target_message:
            return 0

        # Delete all messages with id >= message_id in this conversation
        # (messages are ordered by id which corresponds to creation order)
        delete_result = await db.execute(
            delete(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.id >= message_id)
        )

        await db.flush()
        return delete_result.rowcount

    @staticmethod
    async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        # First delete all messages (due to foreign key constraint)
        await db.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        )

        # Then delete the conversation
        result = await db.execute(
            delete(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def count_user_conversations(db: AsyncSession, user_id: str) -> int:
        """Count total conversations for a user"""
        result = await db.execute(
            select(func.count(ChatConversation.id))
            .where(ChatConversation.user_id == user_id)
        )
        return result.scalar()


