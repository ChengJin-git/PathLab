"""
Dataset Migration Script

This script migrates existing wsi_slides data to use the new datasets table.
It:
1. Creates the datasets table if it doesn't exist
2. Reads all unique dataset_name values from wsi_slides
3. Creates dataset records with UUIDs for each unique name
4. Updates wsi_slides to reference the new dataset_id

Usage:
    python -m backend.database.migrate_datasets

Note: This script should be run once to migrate existing data.
Backup your database before running this script!
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from backend.database.database import async_session, engine, init_db


async def check_migration_needed() -> bool:
    """Check if migration is needed by looking at table structure."""
    async with engine.begin() as conn:
        # Check if datasets table exists
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='datasets'"
        ))
        datasets_table_exists = result.fetchone() is not None
        
        # Check if wsi_slides has dataset_name column
        result = await conn.execute(text("PRAGMA table_info(wsi_slides)"))
        columns = {row[1]: row[2] for row in result.fetchall()}  # name: type
        
        has_dataset_name = "dataset_name" in columns
        has_dataset_id = "dataset_id" in columns
        
        print(f"[Migration] datasets table exists: {datasets_table_exists}")
        print(f"[Migration] wsi_slides has dataset_name: {has_dataset_name}")
        print(f"[Migration] wsi_slides has dataset_id: {has_dataset_id}")
        
        # Migration needed if:
        # - We have dataset_name column (old schema)
        # - OR datasets table doesn't exist yet
        return has_dataset_name or not datasets_table_exists


async def migrate():
    """Run the migration."""
    print("[Migration] Starting dataset migration...")
    
    # Initialize database (creates tables if needed)
    await init_db()
    
    # Check if migration is needed
    migration_needed = await check_migration_needed()
    if not migration_needed:
        print("[Migration] No migration needed - schema is already up to date")
        return
    
    async with async_session() as session:
        try:
            # Step 1: Get unique dataset_name values from wsi_slides
            print("[Migration] Step 1: Reading unique dataset names...")
            result = await session.execute(text(
                "SELECT DISTINCT dataset_name FROM wsi_slides WHERE dataset_name IS NOT NULL"
            ))
            dataset_names = [row[0] for row in result.fetchall()]
            print(f"[Migration] Found {len(dataset_names)} unique datasets: {dataset_names}")
            
            if not dataset_names:
                print("[Migration] No datasets to migrate")
                return
            
            # Step 2: Create dataset records
            print("[Migration] Step 2: Creating dataset records...")
            name_to_id_map = {}
            for name in dataset_names:
                # Check if dataset already exists
                existing = await session.execute(text(
                    "SELECT dataset_id FROM datasets WHERE name = :name"
                ), {"name": name})
                existing_row = existing.fetchone()
                
                if existing_row:
                    dataset_uuid = existing_row[0]
                    print(f"  - Dataset '{name}' already exists with ID: {dataset_uuid}")
                else:
                    dataset_uuid = str(uuid.uuid4())
                    await session.execute(text(
                        "INSERT INTO datasets (dataset_id, name, created_at, updated_at) "
                        "VALUES (:dataset_id, :name, datetime('now'), datetime('now'))"
                    ), {"dataset_id": dataset_uuid, "name": name})
                    print(f"  - Created dataset '{name}' with ID: {dataset_uuid}")
                
                name_to_id_map[name] = dataset_uuid
            
            # Step 3: Update wsi_slides to use dataset_id
            print("[Migration] Step 3: Updating wsi_slides references...")
            for name, dataset_uuid in name_to_id_map.items():
                result = await session.execute(text(
                    "UPDATE wsi_slides SET dataset_id = :dataset_id "
                    "WHERE dataset_name = :dataset_name"
                ), {"dataset_id": dataset_uuid, "dataset_name": name})
                print(f"  - Updated {result.rowcount} slides for dataset '{name}'")
            
            # Commit all changes
            await session.commit()
            print("[Migration] Migration completed successfully!")
            
            # Print summary
            print("\n[Migration] Summary:")
            print(f"  - Migrated {len(dataset_names)} datasets")
            for name, dataset_uuid in name_to_id_map.items():
                print(f"    • '{name}' → {dataset_uuid}")
                
        except Exception as e:
            await session.rollback()
            print(f"[Migration] Migration failed: {e}")
            raise


async def main():
    """Main entry point."""
    print("=" * 60)
    print("PathLab Dataset Migration Script")
    print("=" * 60)
    print()
    print("⚠ WARNING: Please backup your database before proceeding!")
    print()
    
    await migrate()


if __name__ == "__main__":
    asyncio.run(main())

