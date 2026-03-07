#!/usr/bin/env python3
"""
查询用户的 password_sha256 值
用于在新机器上手动设置这个值
"""
import sys
import os
from pathlib import Path

# Add server directory to path
server_dir = Path(__file__).parent.parent
sys.path.insert(0, str(server_dir))

import asyncio
from sqlalchemy import select
from backend.database.database import async_session
from backend.auth.models import User


async def get_password_sha256(username: str):
    """查询指定用户的 password_sha256 值"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.email == username)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"❌ 用户 '{username}' 不存在")
            return None
        
        if not user.password_sha256:
            print(f"⚠️  用户 '{username}' 还没有 password_sha256（旧用户，需要迁移）")
            print(f"   可以使用密码迁移功能，或者手动计算并设置")
            return None
        
        print(f"✅ 用户: {user.email}")
        print(f"   Role: {user.role}")
        print(f"   password_sha256: {user.password_sha256}")
        print(f"\n📋 复制这个值到新机器的数据库中：")
        print(f"   UPDATE users SET password_sha256 = '{user.password_sha256}' WHERE email = '{username}';")
        
        return user.password_sha256


async def list_all_users():
    """列出所有用户及其 password_sha256 状态"""
    async with async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        print(f"\n📊 所有用户列表 ({len(users)} 个):\n")
        for user in users:
            has_sha256 = "✅" if user.password_sha256 else "❌"
            print(f"  {has_sha256} {user.email} (role: {user.role})")
            if user.password_sha256:
                print(f"     password_sha256: {user.password_sha256}")


async def main():
    if len(sys.argv) > 1:
        username = sys.argv[1]
        await get_password_sha256(username)
    else:
        await list_all_users()
        print("\n💡 用法: python get_password_sha256.py <username>")
        print("   例如: python get_password_sha256.py admin")


if __name__ == "__main__":
    asyncio.run(main())
