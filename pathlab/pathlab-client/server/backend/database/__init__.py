"""
PathLab Database Layer

PostgreSQL-based storage for WSI metadata, AI tasks, results, and conversations.
"""

from .database import engine, async_session, get_db, init_db, close_db, safe_session

# Alias for compatibility with background tasks
async_session_maker = async_session
from .models import (
    Base,
    WSISlide,
    WSISlideUserSplit,
    AITask,
    AIResult,
    ChatConversation,
    ChatMessage,
    AnalysisRun,
)

__all__ = [
    "engine",
    "async_session",
    "async_session_maker",
    "safe_session",
    "get_db",
    "init_db",
    "close_db",
    "Base",
    "WSISlide",
    "WSISlideUserSplit",
    "AITask",
    "AIResult",
    "ChatConversation",
    "ChatMessage",
    "AnalysisRun",
]
