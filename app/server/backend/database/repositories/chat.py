"""
ChatRepository - Data Access Layer
"""

import copy
import logging
import uuid as _uuid_module
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import ChatConversation, ChatMessage, StorageTask, utc_now


class ChatRepository:
    """Repository for Chat Conversation and Message operations"""

    @staticmethod
    async def create_conversation(
        db: AsyncSession, conversation_data: Dict[str, Any]
    ) -> ChatConversation:
        """Create a new conversation"""
        conversation = ChatConversation(**conversation_data)
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def get_conversation(
        db: AsyncSession, conversation_id: str, *, include_messages: bool = True
    ) -> Optional[ChatConversation]:
        """Get conversation by ID with messages"""
        query = select(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        if include_messages:
            query = query.options(selectinload(ChatConversation.messages), selectinload(ChatConversation.parent_conversation))
        result = await db.execute(query)
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
        db: AsyncSession, user_id: str, skip: int = 0, limit: int = 50
    ) -> List[ChatConversation]:
        """Get all conversations for a user"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .where(~ChatConversation.conversation_id.in_(select(StorageTask.params['conversation_id'].as_string()).where(StorageTask.task_type == 'chat_delete', StorageTask.status != 'completed')))
            .options(selectinload(ChatConversation.parent_conversation))
            .order_by(desc(ChatConversation.updated_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def clone_messages_to_conversation(
        db: AsyncSession,
        source_conversation: ChatConversation,
        target_conversation_id: str,
    ) -> int:
        """Clone all source messages into a new conversation, preserving order and variants."""
        cloned_count = 0
        source_messages = sorted(source_conversation.messages, key=lambda message: message.id)

        for source_message in source_messages:
            db.add(
                ChatMessage(
                    conversation_id=target_conversation_id,
                    role=source_message.role,
                    content=source_message.content,
                    extra_metadata=copy.deepcopy(source_message.extra_metadata),
                    created_at=source_message.created_at,
                    variant_group_id=source_message.variant_group_id,
                    is_active_variant=source_message.is_active_variant,
                )
            )
            cloned_count += 1

        if cloned_count > 0:
            await db.execute(
                update(ChatConversation)
                .where(ChatConversation.conversation_id == target_conversation_id)
                .values(updated_at=utc_now())
            )

        await db.flush()
        return cloned_count

    @staticmethod
    async def add_message(
        db: AsyncSession, message_data: Dict[str, Any]
    ) -> ChatMessage:
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
        db: AsyncSession, conversation_id: str, skip: int = 0, limit: int = 100
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
        content: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ChatMessage]:
        """Update a message's content"""
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        message = result.scalar_one_or_none()
        if message:
            message.content = content
            if extra_metadata is not None:
                existing = message.extra_metadata or {}
                message.extra_metadata = {**existing, **extra_metadata}
            await db.flush()
            await db.refresh(message)
        return message

    @staticmethod
    async def update_conversation_title(
        db: AsyncSession,
        conversation_id: str,
        title: str,
    ) -> bool:
        """Update a conversation's title. Returns True if found and updated."""
        result = await db.execute(
            update(ChatConversation)
            .where(ChatConversation.conversation_id == conversation_id)
            .values(title=title)
        )
        return result.rowcount > 0

    @staticmethod
    async def get_conversation_first_user_message(
        db: AsyncSession,
        conversation_id: str,
    ) -> Optional[str]:
        """Return the content of the first user message in a conversation (for title generation)."""
        result = await db.execute(
            select(ChatMessage.content)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.id)
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row

    @staticmethod
    async def delete_messages_from_id(
        db: AsyncSession, conversation_id: str, message_id: int
    ) -> int:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.id == message_id)
            .where(ChatMessage.conversation_id == conversation_id)
        )
        target_message = result.scalar_one_or_none()

        if not target_message:
            return 0

        group_result = await db.execute(
            select(ChatMessage.variant_group_id)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.id >= message_id)
            .where(ChatMessage.variant_group_id.is_not(None))
        )
        variant_group_ids = [row[0] for row in group_result.fetchall()]

        delete_result = await db.execute(
            delete(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.id >= message_id)
        )

        if variant_group_ids:
            await db.execute(
                delete(ChatMessage).where(
                    ChatMessage.variant_group_id.in_(variant_group_ids)
                )
            )

        await db.flush()
        return delete_result.rowcount

    @staticmethod
    async def prepare_variant_group(
        db: AsyncSession, old_ai_message_id: int, *, conversation_id: str,
        through_message_id: int,
    ) -> str:
        await db.scalar(select(ChatConversation.conversation_id).where(
            ChatConversation.conversation_id == conversation_id
        ).with_for_update())
        result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.id == old_ai_message_id,
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
            )
        )
        old_msg = result.scalar_one_or_none()
        if not old_msg:
            raise ValueError(f"Message {old_ai_message_id} not found")

        group_id = old_msg.variant_group_id or str(_uuid_module.uuid4())
        old_msg.variant_group_id = group_id
        await db.flush()
        await db.execute(update(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.variant_group_id == group_id,
        ).values(is_active_variant=False))
        anchor = await db.scalar(select(func.min(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.variant_group_id == group_id,
        ))
        descendants = (await db.scalars(select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.id > anchor,
            ChatMessage.id <= through_message_id,
        ))).all()
        for message in descendants:
            if message.variant_group_id != group_id:
                message.extra_metadata = {
                    **(message.extra_metadata or {}), "superseded_by_regeneration": group_id,
                }
        await db.flush()
        return group_id

    @staticmethod
    async def activate_variant(db: AsyncSession, message_id: int, *, conversation_id: str) -> bool:
        await db.scalar(select(ChatConversation.conversation_id).where(
            ChatConversation.conversation_id == conversation_id
        ).with_for_update())
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.conversation_id == conversation_id)
        )
        msg = result.scalar_one_or_none()
        if not msg or not msg.variant_group_id or (msg.extra_metadata or {}).get("superseded_by_regeneration"):
            return False

        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.variant_group_id == msg.variant_group_id)
            .values(is_active_variant=False)
        )
        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == message_id)
            .values(is_active_variant=True)
        )
        await db.flush()
        return True

    @staticmethod
    async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        from ..models import MessageFeedback

        message_ids = select(ChatMessage.id).where(
            ChatMessage.conversation_id == conversation_id
        )
        await db.execute(
            delete(MessageFeedback).where(MessageFeedback.message_id.in_(message_ids))
        )
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.parent_conversation_id == conversation_id)
            .values(parent_conversation_id=None)
        )
        # First delete all messages (due to foreign key constraint)
        await db.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        )

        # Then delete the conversation
        result = await db.execute(
            delete(ChatConversation).where(
                ChatConversation.conversation_id == conversation_id
            )
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def count_user_conversations(db: AsyncSession, user_id: str) -> int:
        """Count total conversations for a user"""
        result = await db.execute(
            select(func.count(ChatConversation.id)).where(
                ChatConversation.user_id == user_id
            )
            .where(~ChatConversation.conversation_id.in_(select(StorageTask.params['conversation_id'].as_string()).where(StorageTask.task_type == 'chat_delete', StorageTask.status != 'completed')))
        )
        return result.scalar()
