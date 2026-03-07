"""
Migration helpers for chat_conversations schema drift.

This backfills columns that were added to the ORM after some deployments had
already created the ``chat_conversations`` table. Safe to run multiple times.
"""

import asyncio
import logging
import os
import sys

from sqlalchemy import text

# Ensure the server directory is on the path so imports work when run as a module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logger = logging.getLogger("migrate_chat_conversations_schema")


async def table_exists(conn, table_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
        ),
        {"t": table_name},
    )
    return bool(result.scalar())


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table_name, "c": column_name},
    )
    return bool(result.scalar())


async def ensure_chat_conversations_schema(conn) -> None:
    table_name = "chat_conversations"
    if not await table_exists(conn, table_name):
        logger.info("Table chat_conversations does not exist yet — skipping schema patch")
        return

    if not await column_exists(conn, table_name, "conversation_type"):
        logger.info("Adding missing column chat_conversations.conversation_type")
        await conn.execute(
            text(
                "ALTER TABLE chat_conversations "
                "ADD COLUMN conversation_type VARCHAR(50) NOT NULL DEFAULT 'ai_chat'"
            )
        )
    else:
        logger.info("Column chat_conversations.conversation_type already exists — skipping")

    if not await column_exists(conn, table_name, "report_context"):
        logger.info("Adding missing column chat_conversations.report_context")
        await conn.execute(
            text(
                "ALTER TABLE chat_conversations "
                "ADD COLUMN report_context TEXT NULL"
            )
        )
    else:
        logger.info("Column chat_conversations.report_context already exists — skipping")


async def migrate() -> None:
    from backend.database.database import engine

    async with engine.begin() as conn:
        await ensure_chat_conversations_schema(conn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(migrate())