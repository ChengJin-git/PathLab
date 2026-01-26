#!/usr/bin/env python3
"""
Database Migration Script for Feedback Context Fields

Adds the following columns to the message_feedbacks table:
- message_content: TEXT - The rated message content (for thumbs up/down)
- context_messages: JSON - Previous message(s) for context
- task_type: VARCHAR(50) - 'training', 'inference', 'analysis'
- task_title: VARCHAR(500) - Task name/title

This preserves feedback data even if users delete conversations.

Usage:
    cd /srv/share/research_demo/pathlab/pathlab-client/server
    python -m backend.database.migrate_feedback_context

    OR run directly:
    python /srv/share/research_demo/pathlab/pathlab-client/server/backend/database/migrate_feedback_context.py
"""

import sys
import asyncio
from pathlib import Path

# Add server directory to path so we can import backend modules
script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]  # Go up to server directory
sys.path.insert(0, str(server_dir))

from sqlalchemy import text
from backend.database import engine


async def migrate():
    """Add new columns to message_feedbacks table for context preservation."""
    print("=" * 60)
    print("Migrating message_feedbacks table - Adding context fields")
    print("=" * 60)

    async with engine.begin() as conn:
        # Check if columns already exist
        result = await conn.execute(text("PRAGMA table_info(message_feedbacks)"))
        columns = {row[1] for row in result.fetchall()}

        # Add message_content column
        if "message_content" not in columns:
            print("Adding message_content column...")
            await conn.execute(text(
                "ALTER TABLE message_feedbacks ADD COLUMN message_content TEXT"
            ))
            print("✓ message_content column added")
        else:
            print("✓ message_content column already exists")

        # Add context_messages column (JSON stored as TEXT in SQLite)
        if "context_messages" not in columns:
            print("Adding context_messages column...")
            await conn.execute(text(
                "ALTER TABLE message_feedbacks ADD COLUMN context_messages JSON"
            ))
            print("✓ context_messages column added")
        else:
            print("✓ context_messages column already exists")

        # Add task_type column
        if "task_type" not in columns:
            print("Adding task_type column...")
            await conn.execute(text(
                "ALTER TABLE message_feedbacks ADD COLUMN task_type VARCHAR(50)"
            ))
            print("✓ task_type column added")
        else:
            print("✓ task_type column already exists")

        # Add task_title column
        if "task_title" not in columns:
            print("Adding task_title column...")
            await conn.execute(text(
                "ALTER TABLE message_feedbacks ADD COLUMN task_title VARCHAR(500)"
            ))
            print("✓ task_title column added")
        else:
            print("✓ task_title column already exists")

    print("\n" + "=" * 60)
    print("✓ Migration completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())

