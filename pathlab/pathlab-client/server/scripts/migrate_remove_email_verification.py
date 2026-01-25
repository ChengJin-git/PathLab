#!/usr/bin/env python3
"""
Migration Script: Remove Email Verification Requirement

This script:
1. Sets is_verified=True for all existing users (no email verification needed)
2. Ensures all users can login without email verification

Usage:
    cd pathlab/pathlab-client/server
    python scripts/migrate_remove_email_verification.py
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from backend.database.database import engine


async def migrate():
    """Run the migration to remove email verification requirement."""
    print("=" * 60)
    print("Migration: Remove Email Verification Requirement")
    print("=" * 60)
    
    async with engine.begin() as conn:
        # Check current state
        result = await conn.execute(text("SELECT COUNT(*) FROM users"))
        total_users = result.scalar()
        print(f"\nTotal users in database: {total_users}")
        
        # Check unverified users
        result = await conn.execute(text("SELECT COUNT(*) FROM users WHERE is_verified = 0 OR is_verified IS NULL"))
        unverified_count = result.scalar()
        print(f"Unverified users: {unverified_count}")
        
        if unverified_count > 0:
            # List unverified users
            result = await conn.execute(text("SELECT id, email, role FROM users WHERE is_verified = 0 OR is_verified IS NULL"))
            rows = result.fetchall()
            print("\nUnverified users to be updated:")
            for row in rows:
                print(f"  - {row[1]} (role: {row[2]})")
            
            # Update all users to verified
            await conn.execute(text("UPDATE users SET is_verified = 1 WHERE is_verified = 0 OR is_verified IS NULL"))
            print(f"\n✅ Updated {unverified_count} users to is_verified=True")
        else:
            print("\n✅ All users are already verified. No changes needed.")
        
        # Verify the update
        result = await conn.execute(text("SELECT COUNT(*) FROM users WHERE is_verified = 0 OR is_verified IS NULL"))
        remaining = result.scalar()
        if remaining == 0:
            print("\n✅ Migration completed successfully!")
            print("   All users can now login without email verification.")
        else:
            print(f"\n⚠ Warning: {remaining} users still unverified")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())

