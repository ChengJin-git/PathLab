#!/usr/bin/env python3
"""
Generate compact debug chat records directly in DB.

Usage:
  uv run python gateway/tests/scripts/generate_chat_records.py \
    --source-conversation-id conv_671c13c2e283415b
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.database.database import async_session
from backend.database.models import ChatConversation, ChatMessage
from backend.database.repositories.chat import ChatRepository

META_BLOCK_START = "[PATHLAB_RESEARCH_META]"
META_BLOCK_END = "[/PATHLAB_RESEARCH_META]"
EMPTY_ASSISTANT_RESPONSE = "[EMPTY_ASSISTANT_RESPONSE]"


@dataclass
class GenerateSummary:
    source_conversation_id: str
    target_conversation_id: str
    source_message_count: int
    generated_message_count: int
    dry_run: bool


def generate_debug_conversation_id(source_conversation_id: str) -> str:
    """Generate a safe debug conversation ID."""
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", source_conversation_id).strip("_")
    if not normalized:
        normalized = "source"
    return f"conv_debug_{normalized}_{uuid.uuid4().hex[:8]}"


def compact_assistant_content(content: str, max_chars: int) -> str:
    """
    Compact assistant message to reduce token cost in follow-up debugging.

    Rules:
    - Keep PATHLAB research meta blocks unchanged (frontend relies on these markers).
    - Normalize blank assistant output to a readable placeholder.
    - Truncate long plain text with a deterministic suffix.
    """
    text = content if content is not None else ""

    if META_BLOCK_START in text and META_BLOCK_END in text:
        return text

    if not text.strip():
        return EMPTY_ASSISTANT_RESPONSE

    if len(text) <= max_chars:
        return text

    head = text[:max_chars].rstrip()
    return (
        f"{head}\n\n"
        f"[DEBUG_TRUNCATED original_len={len(text)} max_chars={max_chars}]"
    )


def _build_debug_message_payloads(
    source_messages: list[ChatMessage],
    max_assistant_chars: int,
    keep_blank_assistant: bool,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in source_messages:
        role = message.role
        content = message.content or ""

        if role == "assistant":
            content = compact_assistant_content(content, max_assistant_chars)
            if not keep_blank_assistant and content == EMPTY_ASSISTANT_RESPONSE:
                continue
        elif role == "user" and not content.strip():
            content = "[EMPTY_USER_MESSAGE]"

        payload: dict[str, Any] = {
            "role": role,
            "content": content,
        }

        if message.extra_metadata:
            payload["extra_metadata"] = message.extra_metadata

        payloads.append(payload)
    return payloads


async def generate_debug_chat_records(
    source_conversation_id: str,
    target_conversation_id: str | None = None,
    user_id: str | None = None,
    title: str | None = None,
    max_assistant_chars: int = 320,
    dry_run: bool = False,
    keep_blank_assistant: bool = False,
) -> GenerateSummary:
    if max_assistant_chars < 20:
        raise ValueError("max_assistant_chars must be >= 20")

    async with async_session() as db:
        source_conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.conversation_id == source_conversation_id
                )
            )
        ).scalar_one_or_none()
        if source_conversation is None:
            raise ValueError(
                f"source conversation not found: {source_conversation_id}"
            )

        source_messages = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == source_conversation_id)
                .order_by(ChatMessage.id.asc())
            )
        ).scalars().all()
        if not source_messages:
            raise ValueError(
                f"source conversation has no messages: {source_conversation_id}"
            )

        target_id = target_conversation_id or generate_debug_conversation_id(
            source_conversation_id
        )

        payloads = _build_debug_message_payloads(
            source_messages=source_messages,
            max_assistant_chars=max_assistant_chars,
            keep_blank_assistant=keep_blank_assistant,
        )

        if dry_run:
            return GenerateSummary(
                source_conversation_id=source_conversation_id,
                target_conversation_id=target_id,
                source_message_count=len(source_messages),
                generated_message_count=len(payloads),
                dry_run=True,
            )

        existing = await ChatRepository.get_conversation(db, target_id)
        if existing is not None:
            raise ValueError(f"target conversation already exists: {target_id}")

        target_title = title or f"[DEBUG] {source_conversation.title or source_conversation_id}"
        conversation = await ChatRepository.create_conversation(
            db,
            {
                "conversation_id": target_id,
                "user_id": user_id or source_conversation.user_id,
                "title": target_title,
            },
        )

        for payload in payloads:
            await ChatRepository.add_message(
                db,
                {
                    "conversation_id": conversation.conversation_id,
                    **payload,
                },
            )
        await db.commit()

        return GenerateSummary(
            source_conversation_id=source_conversation_id,
            target_conversation_id=conversation.conversation_id,
            source_message_count=len(source_messages),
            generated_message_count=len(payloads),
            dry_run=False,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone one AI chat conversation into a compact debug conversation."
    )
    parser.add_argument(
        "--source-conversation-id",
        required=True,
        help="Existing conversation ID to copy from (e.g. conv_671c13c2e283415b).",
    )
    parser.add_argument(
        "--target-conversation-id",
        help="Custom target conversation ID. Auto-generated if omitted.",
    )
    parser.add_argument(
        "--user-id",
        help="Override target user_id. Default: source conversation user_id.",
    )
    parser.add_argument(
        "--title",
        help="Override target conversation title.",
    )
    parser.add_argument(
        "--max-assistant-chars",
        type=int,
        default=320,
        help="Max chars kept for assistant plain-text messages.",
    )
    parser.add_argument(
        "--keep-blank-assistant",
        action="store_true",
        help="Keep normalized blank assistant messages instead of dropping them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview result only, do not write to DB.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    summary = await generate_debug_chat_records(
        source_conversation_id=args.source_conversation_id,
        target_conversation_id=args.target_conversation_id,
        user_id=args.user_id,
        title=args.title,
        max_assistant_chars=args.max_assistant_chars,
        dry_run=args.dry_run,
        keep_blank_assistant=args.keep_blank_assistant,
    )
    print(
        "generate_chat_records:",
        {
            "source_conversation_id": summary.source_conversation_id,
            "target_conversation_id": summary.target_conversation_id,
            "source_message_count": summary.source_message_count,
            "generated_message_count": summary.generated_message_count,
            "dry_run": summary.dry_run,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
