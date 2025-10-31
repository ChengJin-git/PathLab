"""
Database Initialization Script

This script creates all database tables.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[4]  # Go up to repo root
sys.path.insert(0, str(project_root))

from smartresearch.services.backend.database import init_db


async def main():
    """Main initialization function"""
    print("=" * 60)
    print("SmartResearch Database Initialization")
    print("=" * 60)

    print("\nCreating database tables...")
    await init_db()

    print("\n" + "=" * 60)
    print("✓ Database initialization completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

