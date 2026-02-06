"""
ScopedSession - Short-lived database session manager for AI Service

This module provides utilities for creating short-lived database sessions
that prevent connection hogging during long-running training tasks.

Problem:
- Training endpoints hold database connections for hours via Depends(get_db)
- SQLite in WAL mode allows only one writer at a time
- Long-held connections block other operations (Gateway, delete, rerun)
- This causes system-wide deadlocks when multiple tasks run concurrently

Solution:
- Create short-lived sessions only when needed for specific DB operations
- Release sessions immediately after each operation
- Pass session_maker to trainers instead of long-lived sessions
- Each log write creates and closes its own session
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from backend.common.config import Config
from backend.database import async_session_maker
from backend.database.utils.training_logger import TrainingLogger


logger = logging.getLogger("ai.scoped_session")


class ScopedSession:
    """
    Helper to create short-lived DB sessions for AI Service operations.
    
    Ensures that we don't hold a DB connection open during long-running training.
    Each database operation creates a new session, commits, and closes it immediately.
    
    Usage:
        scoped = ScopedSession(task_id)
        
        # For simple DB operations:
        async with scoped.session() as (training_logger, db):
            await TrainingTaskRepository.update_status(db, task_id, "running")
        # Session is automatically closed after the block
        
        # For trainers that need to create their own sessions:
        trainer = MyTrainer(...)
        result = await trainer.train_model(
            session_maker=scoped.get_session_maker(),
            ...
        )
    """
    
    def __init__(self, task_id: str, log_dir: Optional[str] = None):
        """
        Initialize scoped session manager.
        
        Args:
            task_id: Training task ID for logging
            log_dir: Optional custom log directory
        """
        self.task_id = task_id
        self.log_dir = log_dir
        self._session_maker = async_session_maker
    
    def get_session_maker(self) -> Callable:
        """Return the session maker factory for trainers to use."""
        return self._session_maker
    
    @asynccontextmanager
    async def session(self):
        """
        Create a short-lived database session with timeout protection.
        
        Yields:
            tuple: (TrainingLogger, AsyncSession) - logger and db session
            
        The session is automatically committed on success, rolled back on error,
        and closed when the context exits.
        
        Includes timeout protection to prevent indefinite blocking on SQLite locks.
        """
        timeout = Config.DB_OPERATION_TIMEOUT
        try:
            async with asyncio.timeout(timeout):
                async with self._session_maker() as db:
                    training_logger = TrainingLogger(self.task_id, db, self.log_dir)
                    try:
                        yield training_logger, db
                        await db.commit()
                    except Exception:
                        await db.rollback()
                        raise
                    finally:
                        await training_logger.close()
        except asyncio.TimeoutError:
            logger.error(
                f"[{self.task_id}] Database operation timed out after {timeout}s. "
                "This may indicate SQLite lock contention."
            )
            raise Exception(
                f"Database operation timed out after {timeout}s. "
                "SQLite lock contention detected."
            )


class ScopedTrainingLogger:
    """
    TrainingLogger that creates short-lived sessions for each log write.
    
    Unlike the original TrainingLogger which holds a session reference,
    this version creates a new session for each log operation and closes it immediately.
    
    This prevents the logger from holding database connections during training.
    """
    
    def __init__(self, task_id: str, log_dir: Optional[str] = None):
        """
        Initialize scoped training logger.
        
        Args:
            task_id: Training task ID
            log_dir: Optional custom log directory
        """
        self.task_id = task_id
        self.log_dir = log_dir
        self._session_maker = async_session_maker
        self._scoped = ScopedSession(task_id, log_dir)
    
    async def info(self, message: str, metadata: Optional[dict] = None):
        """Log INFO level message with a short-lived session."""
        async with self._scoped.session() as (logger, db):
            await logger.info(message, metadata)
    
    async def warning(self, message: str, metadata: Optional[dict] = None):
        """Log WARNING level message with a short-lived session."""
        async with self._scoped.session() as (logger, db):
            await logger.warning(message, metadata)
    
    async def error(self, message: str, metadata: Optional[dict] = None):
        """Log ERROR level message with a short-lived session."""
        async with self._scoped.session() as (logger, db):
            await logger.error(message, metadata)
    
    async def debug(self, message: str, metadata: Optional[dict] = None):
        """Log DEBUG level message with a short-lived session."""
        async with self._scoped.session() as (logger, db):
            await logger.debug(message, metadata)
    
    async def close(self):
        """No-op: sessions are closed immediately after each operation."""
        pass

