from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User
from backend.auth.dependencies import check_data_ownership
from backend.database.repositories import ChatRepository


async def require_conversation_access(
    db: AsyncSession,
    conversation_id: str,
    user: User,
):
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(str(conversation.user_id), user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this conversation",
        )

    return conversation


async def require_message_access(
    db: AsyncSession,
    message_id: int,
    user: User,
):
    message = await ChatRepository.get_message(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    conversation = message.conversation
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this message",
        )

    return message
