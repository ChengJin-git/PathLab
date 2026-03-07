#!/usr/bin/env python3
"""
Reset admin user password.
Usage: python reset_admin_password.py [new_password]
Default password: Smartlab2022
"""

import asyncio
import hashlib
import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent))


async def reset_admin_password(new_password: str = "Smartlab2022"):
    """Reset admin user password."""
    from sqlalchemy import select, update
    from fastapi_users.password import PasswordHelper
    
    from backend.database.database import async_session
    from backend.auth.models import User
    
    password_helper = PasswordHelper()
    
    # Generate bcrypt hash
    hashed_password = password_helper.hash(new_password)
    
    # Generate SHA256 hash for secure login
    password_sha256 = hashlib.sha256(new_password.encode()).hexdigest()
    
    async with async_session() as session:
        # Find admin user
        result = await session.execute(
            select(User).where(User.email == "admin")
        )
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            print("❌ Admin user not found!")
            print("Looking for users with admin role...")
            result = await session.execute(
                select(User).where(User.role == "admin")
            )
            admin_users = result.scalars().all()
            if admin_users:
                print(f"Found {len(admin_users)} admin user(s):")
                for u in admin_users:
                    print(f"  - {u.email} (id: {u.id})")
            else:
                print("No admin users found in database.")
            return False
        
        # Update password
        admin_user.hashed_password = hashed_password
        admin_user.password_sha256 = password_sha256
        
        await session.commit()
        
        print(f"✓ Admin password reset successfully!")
        print(f"  Username: admin")
        print(f"  Password: {new_password}")
        return True


if __name__ == "__main__":
    password = sys.argv[1] if len(sys.argv) > 1 else "Smartlab2022"
    print(f"Resetting admin password to: {password}")
    asyncio.run(reset_admin_password(password))
