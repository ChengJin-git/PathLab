#!/usr/bin/env python3
"""Destructively clear all persisted chat history and chat feedback data.

Usage:
  python server/scripts/reset_chat_history.py --yes

Optional:
  python server/scripts/reset_chat_history.py --yes --drop-chat-patch-uploads
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from sqlalchemy import delete, func, select

from backend.common.config import Config
from backend.database import async_session
from backend.database.models import ChatConversation, ChatMessage, MessageFeedback


async def _count_rows(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def _reset_chat_history(drop_chat_patch_uploads: bool) -> None:
    async with async_session() as session:
        conversation_count = await _count_rows(session, ChatConversation)
        message_count = await _count_rows(session, ChatMessage)
        feedback_count = await _count_rows(session, MessageFeedback)

        print('About to permanently delete:')
        print(f'  chat_conversations: {conversation_count}')
        print(f'  chat_messages:      {message_count}')
        print(f'  message_feedbacks:  {feedback_count}')

        await session.execute(delete(MessageFeedback))
        await session.execute(delete(ChatMessage))
        await session.execute(delete(ChatConversation))
        await session.commit()

    print('Database chat history cleared.')

    if drop_chat_patch_uploads:
        chat_patch_dir = Config.get_uploads_dir() / 'chat_patch_inference'
        if chat_patch_dir.exists():
            shutil.rmtree(chat_patch_dir)
            print(f'Removed uploads directory: {chat_patch_dir}')
        else:
            print(f'Uploads directory not found, skipped: {chat_patch_dir}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Permanently delete all persisted chat history.')
    parser.add_argument('--yes', action='store_true', help='required confirmation flag')
    parser.add_argument(
        '--drop-chat-patch-uploads',
        action='store_true',
        help='also remove uploads/chat_patch_inference artifacts from disk',
    )
    args = parser.parse_args()

    if not args.yes:
        parser.error('Refusing to run without --yes')

    asyncio.run(_reset_chat_history(drop_chat_patch_uploads=args.drop_chat_patch_uploads))


if __name__ == '__main__':
    main()

