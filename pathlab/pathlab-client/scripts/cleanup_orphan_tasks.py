#!/usr/bin/env python3
"""
Database Cleanup Script for PathLab

Cleans up orphan training tasks and WSI associations:
1. Training tasks with no WSI associations
2. TrainingTaskWSI records referencing non-existent tasks
3. Training tasks stuck in 'pending' or 'running' status

Usage:
    python scripts/cleanup_orphan_tasks.py [--dry-run]
    
Options:
    --dry-run   Show what would be deleted without actually deleting
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "server"))

from sqlalchemy import select, delete, func, text
from backend.database.database import async_session, init_db
from backend.database.models import TrainingTask, TrainingTaskWSI, TrainedModel, TrainingLog


async def cleanup_orphan_tasks(dry_run: bool = False):
    """Clean up orphan training tasks and associations."""
    
    await init_db()
    
    async with async_session() as db:
        print("\n" + "=" * 60)
        print("PathLab Database Cleanup")
        print("=" * 60)
        
        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
        else:
            print("⚠️  LIVE MODE - Changes will be committed\n")
        
        # 1. Find orphan TrainingTaskWSI records (task doesn't exist)
        print("1. Checking for orphan TrainingTaskWSI records...")
        orphan_wsi_query = (
            select(TrainingTaskWSI.task_id, func.count(TrainingTaskWSI.id).label('count'))
            .outerjoin(TrainingTask, TrainingTaskWSI.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id.is_(None))
            .group_by(TrainingTaskWSI.task_id)
        )
        result = await db.execute(orphan_wsi_query)
        orphan_wsi_tasks = result.all()
        
        if orphan_wsi_tasks:
            total_orphan_wsi = sum(row[1] for row in orphan_wsi_tasks)
            print(f"   Found {total_orphan_wsi} orphan WSI associations across {len(orphan_wsi_tasks)} tasks:")
            for task_id, count in orphan_wsi_tasks:
                print(f"      - {task_id}: {count} WSI associations")
            
            if not dry_run:
                for task_id, _ in orphan_wsi_tasks:
                    await db.execute(
                        delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id == task_id)
                    )
                await db.commit()
                print(f"   ✓ Deleted {total_orphan_wsi} orphan WSI associations")
        else:
            print("   ✓ No orphan WSI associations found")
        
        # 2. Find training tasks with no WSI associations
        print("\n2. Checking for training tasks with no WSI associations...")
        empty_tasks_query = (
            select(TrainingTask)
            .outerjoin(TrainingTaskWSI, TrainingTask.task_id == TrainingTaskWSI.task_id)
            .where(TrainingTaskWSI.id.is_(None))
        )
        result = await db.execute(empty_tasks_query)
        empty_tasks = result.scalars().all()
        
        if empty_tasks:
            print(f"   Found {len(empty_tasks)} tasks with no WSI associations:")
            for task in empty_tasks:
                print(f"      - {task.task_id}: {task.task_name} ({task.status})")
            
            if not dry_run:
                for task in empty_tasks:
                    # Delete related logs first
                    await db.execute(
                        delete(TrainingLog).where(TrainingLog.task_id == task.task_id)
                    )
                    # Delete related models
                    await db.execute(
                        delete(TrainedModel).where(TrainedModel.task_id == task.task_id)
                    )
                    # Delete the task
                    await db.delete(task)
                await db.commit()
                print(f"   ✓ Deleted {len(empty_tasks)} empty tasks")
        else:
            print("   ✓ All tasks have WSI associations")
        
        # 3. Find tasks stuck in pending/running (older than 1 hour)
        print("\n3. Checking for stuck tasks (pending/running > 1 hour)...")
        from datetime import datetime, timezone, timedelta
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        stuck_tasks_query = (
            select(TrainingTask)
            .where(TrainingTask.status.in_(["pending", "running"]))
            .where(TrainingTask.updated_at < one_hour_ago)
        )
        result = await db.execute(stuck_tasks_query)
        stuck_tasks = result.scalars().all()
        
        if stuck_tasks:
            print(f"   Found {len(stuck_tasks)} stuck tasks:")
            for task in stuck_tasks:
                age = datetime.now(timezone.utc) - task.updated_at.replace(tzinfo=timezone.utc)
                print(f"      - {task.task_id}: {task.task_name} ({task.status}, {age.total_seconds()/3600:.1f}h old)")
            print("   ⚠️  These tasks may need manual review. Use --force to mark as failed.")
        else:
            print("   ✓ No stuck tasks found")
        
        # 4. Summary statistics
        print("\n" + "-" * 60)
        print("Database Statistics:")
        
        task_count = await db.execute(select(func.count(TrainingTask.id)))
        wsi_assoc_count = await db.execute(select(func.count(TrainingTaskWSI.id)))
        model_count = await db.execute(select(func.count(TrainedModel.id)))
        
        print(f"   Training Tasks: {task_count.scalar()}")
        print(f"   WSI Associations: {wsi_assoc_count.scalar()}")
        print(f"   Trained Models: {model_count.scalar()}")
        
        # Status breakdown
        status_query = (
            select(TrainingTask.status, func.count(TrainingTask.id))
            .group_by(TrainingTask.status)
        )
        result = await db.execute(status_query)
        status_counts = result.all()
        
        if status_counts:
            print("\n   Status Breakdown:")
            for status, count in status_counts:
                print(f"      - {status}: {count}")
        
        print("\n" + "=" * 60)
        if dry_run:
            print("Run without --dry-run to apply changes")
        else:
            print("Cleanup complete!")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(cleanup_orphan_tasks(dry_run=dry_run))

