"""
Database Migration Script: Rebuild tables with DataGroup structure

This script drops all tables and recreates them with the new schema:
- New data_groups table
- datasets.group_id foreign key
- training_tasks.group_id foreign key

WARNING: This will DELETE ALL DATA in the database!
Only use this in a clean/empty environment.

Usage:
    cd pathlab/pathlab-client/server
    python -m backend.database.migrate_to_datagroup
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[3]  # Go up to server directory
sys.path.insert(0, str(project_root))

from backend.database.database import engine, init_db, drop_all_tables


async def run_migration():
    """Run the database migration."""
    print("=" * 60)
    print("PathLab Database Migration: DataGroup Structure")
    print("=" * 60)
    print("\nWARNING: This will DROP ALL TABLES and recreate them!")
    print("All existing data will be LOST.\n")
    
    # Ask for confirmation
    confirm = input("Type 'yes' to continue: ")
    if confirm.lower() != 'yes':
        print("Migration cancelled.")
        return
    
    print("\n[Migration] Dropping all existing tables...")
    await drop_all_tables()
    
    print("\n[Migration] Creating new tables with DataGroup structure...")
    await init_db()
    
    print("\n" + "=" * 60)
    print("✓ Migration completed successfully!")
    print("=" * 60)
    print("\nNew schema includes:")
    print("- data_groups table (data_type, aggregation_level, task_type)")
    print("- datasets.group_id foreign key → data_groups")
    print("- training_tasks.group_id foreign key → data_groups")
    print("\nDataGroups will be created on-demand when users create datasets/tasks.")


def main():
    """Entry point for the migration script."""
    asyncio.run(run_migration())


if __name__ == "__main__":
    main()

