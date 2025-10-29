"""
Database Initialization and Data Migration Script

This script:
1. Creates all database tables
2. Migrates existing JSON data to PostgreSQL
3. Validates data integrity
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parents[4]  # Go up to repo root
sys.path.insert(0, str(project_root))

from smartresearch.services.backend.database import init_db, async_session
from smartresearch.services.backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)


async def migrate_wsi_metadata():
    """Migrate WSI metadata from JSON files to database"""
    print("\n[1/3] Migrating WSI metadata...")
    
    metadata_dir = project_root / "uploads" / "metadata"
    if not metadata_dir.exists():
        print("  ⚠ No metadata directory found, skipping...")
        return
    
    json_files = list(metadata_dir.glob("*.json"))
    print(f"  Found {len(json_files)} metadata files")
    
    migrated = 0
    skipped = 0
    
    async with async_session() as db:
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                wsi_id = json_file.stem
                
                # Check if already exists
                existing = await WSIRepository.get_by_id(db, wsi_id)
                if existing:
                    skipped += 1
                    continue
                
                # Prepare data for database
                wsi_data = {
                    "wsi_id": wsi_id,
                    "case_id": data.get("case_id"),
                    "label": data.get("label"),
                    "wsi_path": data.get("wsi_path", ""),
                    "mpp": data.get("mpp"),
                    "vendor": data.get("vendor"),
                    "width": data.get("width"),
                    "height": data.get("height"),
                    "magnification": data.get("magnification"),
                }
                
                await WSIRepository.create(db, wsi_data)
                migrated += 1
                
            except Exception as e:
                print(f"  ✗ Error migrating {json_file.name}: {e}")
        
        await db.commit()
    
    print(f"  ✓ Migrated: {migrated}, Skipped: {skipped}")


async def migrate_ai_tasks():
    """Migrate AI tasks from JSON files to database"""
    print("\n[2/3] Migrating AI tasks...")
    
    tasks_dir = project_root / "uploads" / "tasks"
    if not tasks_dir.exists():
        print("  ⚠ No tasks directory found, skipping...")
        return
    
    json_files = list(tasks_dir.glob("*.json"))
    print(f"  Found {len(json_files)} task files")
    
    migrated = 0
    skipped = 0
    
    async with async_session() as db:
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                task_id = json_file.stem
                
                # Check if already exists
                existing = await AITaskRepository.get_by_id(db, task_id)
                if existing:
                    skipped += 1
                    continue
                
                # Prepare data for database
                task_data = {
                    "task_id": task_id,
                    "wsi_id": data.get("wsi_id", ""),
                    "task_type": data.get("task_type", "wsi-classification"),
                    "status": data.get("status", "completed"),
                    "progress": data.get("progress", 100),
                    "params": data.get("params"),
                    "error_message": data.get("error_message"),
                }
                
                # Parse timestamps if available
                if "created_at" in data:
                    try:
                        task_data["created_at"] = datetime.fromisoformat(data["created_at"])
                    except:
                        pass
                
                if "started_at" in data:
                    try:
                        task_data["started_at"] = datetime.fromisoformat(data["started_at"])
                    except:
                        pass
                
                if "finished_at" in data:
                    try:
                        task_data["finished_at"] = datetime.fromisoformat(data["finished_at"])
                    except:
                        pass
                
                await AITaskRepository.create(db, task_data)
                migrated += 1
                
            except Exception as e:
                print(f"  ✗ Error migrating {json_file.name}: {e}")
        
        await db.commit()
    
    print(f"  ✓ Migrated: {migrated}, Skipped: {skipped}")


async def migrate_ai_results():
    """Migrate AI results from JSON files to database"""
    print("\n[3/3] Migrating AI results...")
    
    results_dir = project_root / "uploads" / "ai_results"
    if not results_dir.exists():
        print("  ⚠ No ai_results directory found, skipping...")
        return
    
    json_files = list(results_dir.glob("*.json"))
    print(f"  Found {len(json_files)} result files")
    
    migrated = 0
    skipped = 0
    
    async with async_session() as db:
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                wsi_id = json_file.stem
                
                # Check if already exists
                existing = await AIResultRepository.get_by_wsi_id(db, wsi_id)
                if existing:
                    skipped += 1
                    continue
                
                # Prepare data for database
                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": data.get("task_id"),
                    "pred": data.get("pred"),
                    "probs": data.get("probs"),
                    "attention_weights": data.get("attention_weights"),
                    "metadata": data.get("metadata"),
                }
                
                await AIResultRepository.create(db, result_data)
                migrated += 1
                
            except Exception as e:
                print(f"  ✗ Error migrating {json_file.name}: {e}")
        
        await db.commit()
    
    print(f"  ✓ Migrated: {migrated}, Skipped: {skipped}")


async def validate_migration():
    """Validate migrated data"""
    print("\n[Validation] Checking migrated data...")
    
    async with async_session() as db:
        wsi_count = await WSIRepository.count(db)
        task_count = await AITaskRepository.count(db)
        result_count = await AIResultRepository.count(db)
        
        print(f"  ✓ WSI Slides: {wsi_count}")
        print(f"  ✓ AI Tasks: {task_count}")
        print(f"  ✓ AI Results: {result_count}")
        
        if wsi_count > 0:
            label_dist = await WSIRepository.get_label_distribution(db)
            print(f"  ✓ Label Distribution: {label_dist}")


async def main():
    """Main migration function"""
    print("=" * 60)
    print("SmartResearch Database Initialization & Migration")
    print("=" * 60)
    
    # Step 1: Create tables
    print("\n[Step 1] Creating database tables...")
    await init_db()
    
    # Step 2: Migrate data
    print("\n[Step 2] Migrating existing data from JSON files...")
    await migrate_wsi_metadata()
    await migrate_ai_tasks()
    await migrate_ai_results()
    
    # Step 3: Validate
    await validate_migration()
    
    print("\n" + "=" * 60)
    print("✓ Database initialization and migration completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

