"""
PathLab Database Layer

SQLite-based storage for WSI metadata, AI tasks, results, and conversations.
"""

from .database import engine, async_session, get_db, init_db, close_db

# Alias for compatibility with background tasks
async_session_maker = async_session
from .models import Base, WSISlide, AITask, AIResult, ChatConversation, ChatMessage

__all__ = [
    "engine",
    "async_session",
    "async_session_maker",
    "get_db",
    "init_db",
    "close_db",
    "Base",
    "WSISlide",
    "AITask",
    "AIResult",
    "ChatConversation",
    "ChatMessage",
]

