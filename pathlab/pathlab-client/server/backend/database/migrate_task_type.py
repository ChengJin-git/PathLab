"""
Database Migration Script: Add task_type column to datasets table

This script adds the 'task_type' column to the datasets table for existing databases.
The column is used to store the analysis type: 'classification' or 'survival'.

Usage:
    cd pathlab/pathlab-client/server
    python -m backend.database.migrate_task_type

Note: This migration is idempotent - it checks if the column exists before adding it.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[4]  # Go up to repo root
sys.path.insert(0, str(project_root))

from backend.database.database import engine
from sqlalchemy import text


async def check_column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table using PRAGMA table_info."""
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    column_names = [col[1] for col in columns]
    return column_name in column_names


async def migrate():
    """Add task_type column to datasets table if it doesn't exist."""
    print("=" * 60)
    print("PathLab Database Migration: Add task_type to datasets")
    print("=" * 60)
    
    async with engine.begin() as conn:
        # Check if column already exists
        if await check_column_exists(conn, "datasets", "task_type"):
            print("\n[Migration] Column 'task_type' already exists in datasets table.")
            print("[Migration] No migration needed.")
            return True
        
        print("\n[Migration] Adding 'task_type' column to datasets table...")
        
        try:
            # Add the task_type column with default value 'classification'
            await conn.execute(text(
                "ALTER TABLE datasets ADD COLUMN task_type TEXT DEFAULT 'classification' NOT NULL"
            ))
            print("[Migration] ✓ Column 'task_type' added successfully")
            
            # Verify the column was added
            if await check_column_exists(conn, "datasets", "task_type"):
                print("[Migration] ✓ Verified: Column exists in table")
            else:
                print("[Migration] ✗ Error: Column verification failed")
                return False
            
            print("\n" + "=" * 60)
            print("✓ Migration completed successfully!")
            print("=" * 60)
            return True
            
        except Exception as e:
            print(f"\n[Migration] ✗ Error during migration: {e}")
            return False


if __name__ == "__main__":
    success = asyncio.run(migrate())
    sys.exit(0 if success else 1)

