#!/usr/bin/env python3
"""
Script to delete coords files for all WSI in a specific dataset.

Usage:
    python delete_dataset_coords.py "Dataset Name" /path/to/coords/storage
"""

import sys
import asyncio
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "pathlab" / "pathlab-client" / "server"))

from backend.database.models import Dataset, WSISlide
from backend.database.database import get_database_url


async def get_dataset_wsi_ids(db: AsyncSession, dataset_name: str) -> list:
    """Get all WSI IDs in a dataset by name."""
    result = await db.execute(
        select(Dataset).where(Dataset.name == dataset_name)
    )
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        print(f"❌ Dataset '{dataset_name}' not found")
        return []
    
    print(f"✓ Found dataset: {dataset.name} (ID: {dataset.dataset_id})")
    
    # Get all WSI in this dataset
    wsi_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset.dataset_id)
    )
    wsi_ids = [row[0] for row in wsi_result.fetchall()]
    print(f"✓ Found {len(wsi_ids)} WSI slides in dataset")
    
    return wsi_ids


async def delete_coords_for_wsi(coords_root: Path, wsi_ids: list) -> dict:
    """Delete coords files for given WSI IDs."""
    stats = {
        "total": len(wsi_ids),
        "deleted": 0,
        "not_found": 0,
        "errors": []
    }
    
    for wsi_id in wsi_ids:
        # Pattern: coordinates/{params_hash}/{wsi_id}_coords.h5
        coords_dir = coords_root / "coordinates"
        
        if not coords_dir.exists():
            stats["not_found"] += 1
            continue
        
        # Find all coords files for this WSI
        found = False
        for coords_file in coords_dir.rglob(f"{wsi_id}_coords.h5"):
            try:
                coords_file.unlink()
                stats["deleted"] += 1
                found = True
                print(f"  ✓ Deleted: {coords_file.relative_to(coords_root)}")
            except Exception as e:
                stats["errors"].append(f"{wsi_id}: {str(e)}")
                print(f"  ❌ Error deleting {coords_file}: {e}")
        
        if not found:
            stats["not_found"] += 1
    
    return stats


async def main():
    if len(sys.argv) < 2:
        print("Usage: python delete_dataset_coords.py 'Dataset Name' [coords_root_path]")
        print("Example: python delete_dataset_coords.py 'Gastric_Intestinal_Metaplasia (Nanfang Cohort)' /ssd/Pathlab_Storage")
        sys.exit(1)
    
    dataset_name = sys.argv[1]
    coords_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/ssd/Pathlab_Storage")
    
    print(f"\n📋 Dataset: {dataset_name}")
    print(f"📁 Coords root: {coords_root}\n")

    # Connect to database
    db_url = get_database_url()
    print(f"📊 Connecting to database...")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # Get WSI IDs
        wsi_ids = await get_dataset_wsi_ids(db, dataset_name)
        
        if not wsi_ids:
            print("No WSI found to delete")
            await engine.dispose()
            return
        
        # Delete coords
        print(f"\n🗑️  Deleting coords files...\n")
        stats = await delete_coords_for_wsi(coords_root, wsi_ids)
        
        # Summary
        print(f"\n📊 Summary:")
        print(f"  Total WSI: {stats['total']}")
        print(f"  Deleted: {stats['deleted']}")
        print(f"  Not found: {stats['not_found']}")
        if stats['errors']:
            print(f"  Errors: {len(stats['errors'])}")
            for error in stats['errors'][:5]:
                print(f"    - {error}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

