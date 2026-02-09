"""
ScopedSession - Short-lived database session manager for AI Service

This module provides utilities for creating short-lived database sessions
that prevent connection hogging during long-running training tasks.

Problem:
- Training endpoints hold database connections for hours via Depends(get_db)
- Long-held connections block other operations (Gateway, delete, rerun)
- This causes connection pool exhaustion when multiple tasks run concurrently

Solution:
- Create short-lived sessions only when needed for specific DB operations
- Release sessions immediately after each operation
- Pass session_maker to trainers instead of long-lived sessions
- Use batched async log writes to reduce database write frequency
"""

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Dict, List

import anyio

from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.database import async_session_maker
from backend.database.utils.training_logger import TrainingLogger
from backend.database.utils.json_utils import sanitize_for_json


logger = logging.getLogger("ai.scoped_session")


# =============================================================================
# Batched Log Entry
# =============================================================================

@dataclass
class LogEntry:
    """A log entry waiting to be written to database."""
    level: str
    message: str
    metadata: Optional[Dict[str, Any]]
    timestamp: datetime
    sequence: int


class ScopedSession:
    """
    Helper to create short-lived DB sessions for AI Service operations.
    
    Ensures that we don't hold a DB connection open during long-running training.
    Each database operation creates a new session, commits, and closes it immediately.
    
    Usage:
        scoped = ScopedSession(task_id)
        
        # For simple DB operations:
        async with scoped.session() as (training_logger, db):
            await TrainingTaskRepository.update_status(db, task_id, TaskStatus.RUNNING)
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

        Includes timeout protection to prevent indefinite blocking on
        long-running database operations.

        Follows the same pattern as safe_session() in database.py:
        - The main operation is NOT shielded (allows timeout/cancellation to work)
        - Only cleanup (rollback/close) is shielded to ensure proper resource release
        """
        timeout = Config.DB_OPERATION_TIMEOUT
        session = self._session_maker()
        training_logger = TrainingLogger(self.task_id, session, self.log_dir)
        try:
            async with asyncio.timeout(timeout):
                yield training_logger, session
                await session.commit()
        except TimeoutError:
            with anyio.CancelScope(shield=True):
                await session.rollback()
            logger.error(
                f"[{self.task_id}] Database operation timed out after {timeout}s."
            )
            raise
        except Exception:
            with anyio.CancelScope(shield=True):
                await session.rollback()
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await training_logger.close()
                await session.close()


class ScopedTrainingLogger:
    """
    TrainingLogger with batched async writes to reduce database load.

    Key features:
    - Logs immediately to file for real-time file access
    - Queues database writes and flushes them in batches every few seconds
    - Reduces database write frequency from "per log" to "per batch"
    - SSE log stream still works since database eventually gets updated

    This reduces database write frequency and connection usage during training.
    """

    # Batch settings
    BATCH_INTERVAL = 8.0  # Flush to database every N seconds (increased to reduce lock contention)
    MAX_BATCH_SIZE = 50   # Max entries per batch write
    MAX_BACKOFF_INTERVAL = 30.0  # Maximum backoff interval on consecutive failures

    def __init__(self, task_id: str, log_dir: Optional[str] = None):
        """
        Initialize scoped training logger with batched writes.

        Args:
            task_id: Training task ID
            log_dir: Optional custom log directory
        """
        self.task_id = task_id
        self.log_dir = log_dir
        self._session_maker = async_session_maker

        # Log queue for batched database writes
        self._queue: deque[LogEntry] = deque()
        self._sequence = 0
        self._sequence_initialized = False

        # Background flush task
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._consecutive_failures = 0  # Track consecutive flush failures for backoff

        # Setup file logging (immediate writes to file)
        self._setup_file_logger()

    def _setup_file_logger(self):
        """Setup file logger for immediate file writes."""
        if self.log_dir is None:
            log_dir = str(Config.get_uploads_dir() / "logs" / "training" / self.task_id)
        else:
            log_dir = self.log_dir

        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "training.log"

        # Setup Python logger for file output
        self._file_logger = logging.getLogger(f"training.{self.task_id}")
        self._file_logger.setLevel(logging.DEBUG)
        self._file_logger.handlers.clear()

        # File handler
        handler = logging.FileHandler(self._log_file, encoding='utf-8')
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self._file_logger.addHandler(handler)

        # Console handler for debugging
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self._file_logger.addHandler(console_handler)

    async def _init_sequence(self):
        """Initialize sequence number from database (one-time).

        Follows the same pattern as safe_session() in database.py:
        - The main operation is NOT shielded (allows timeout/cancellation to work)
        - Only cleanup (rollback/close) is shielded to ensure proper resource release
        """
        if self._sequence_initialized:
            return

        from sqlalchemy import select, func
        from backend.database.models import TrainingLog

        session = self._session_maker()
        try:
            result = await session.execute(
                select(func.max(TrainingLog.sequence)).where(
                    TrainingLog.task_id == self.task_id
                )
            )
            max_seq = result.scalar()
            self._sequence = int(max_seq) if max_seq is not None else 0
            self._sequence_initialized = True
        except Exception as e:
            logger.warning(f"[{self.task_id}] Failed to init sequence from DB: {type(e).__name__}: {e}")
            self._sequence = 0
            self._sequence_initialized = True
        finally:
            with anyio.CancelScope(shield=True):
                await session.close()

    def _start_flush_task(self):
        """Start the background flush task if not already running."""
        if self._flush_task is None or self._flush_task.done():
            self._running = True
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self):
        """Background loop that flushes queued logs to database.

        Uses exponential backoff on consecutive failures to avoid hammering
        the database when it's under heavy write lock contention.
        """
        while self._running:
            try:
                # Calculate sleep interval with exponential backoff on failures
                if self._consecutive_failures > 0:
                    backoff = min(
                        self.BATCH_INTERVAL * (2 ** self._consecutive_failures),
                        self.MAX_BACKOFF_INTERVAL
                    )
                    logger.debug(
                        f"[{self.task_id}] Flush backoff: {backoff:.1f}s "
                        f"(failures={self._consecutive_failures})"
                    )
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(self.BATCH_INTERVAL)
                await self._flush_to_db()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.task_id}] Error in flush loop: {e}")

    async def _flush_to_db(self):
        """Flush queued log entries to database in a single transaction.

        Includes timeout protection to prevent indefinite blocking on database operations.
        Tracks consecutive failures for exponential backoff in _flush_loop().

        Follows the same pattern as safe_session() in database.py:
        - The main operation is NOT shielded (allows timeout/cancellation to work)
        - Only cleanup (rollback/close) is shielded to ensure proper resource release
        """
        if not self._queue:
            return

        # Take up to MAX_BATCH_SIZE entries
        batch: List[LogEntry] = []
        while self._queue and len(batch) < self.MAX_BATCH_SIZE:
            batch.append(self._queue.popleft())

        if not batch:
            return

        from backend.database.models import TrainingLog

        timeout = Config.DB_OPERATION_TIMEOUT
        session = self._session_maker()
        try:
            async with asyncio.timeout(timeout):
                for entry in batch:
                    log_record = TrainingLog(
                        task_id=self.task_id,
                        level=entry.level,
                        message=entry.message,
                        sequence=entry.sequence,
                        extra_data=entry.metadata
                    )
                    session.add(log_record)
                await session.commit()
            logger.debug(f"[{self.task_id}] Flushed {len(batch)} logs to database")
            # Reset backoff counter on success
            self._consecutive_failures = 0
        except TimeoutError:
            with anyio.CancelScope(shield=True):
                await session.rollback()
            self._consecutive_failures += 1
            logger.error(
                f"[{self.task_id}] Log flush timed out after {timeout}s "
                f"(consecutive failures: {self._consecutive_failures})."
            )
            # Re-queue entries on failure
            for entry in reversed(batch):
                self._queue.appendleft(entry)
        except Exception as e:
            # Shield rollback to ensure it completes even if cancelled
            with anyio.CancelScope(shield=True):
                await session.rollback()
            self._consecutive_failures += 1
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(
                f"[{self.task_id}] Failed to flush logs to DB: {error_msg} "
                f"(consecutive failures: {self._consecutive_failures})"
            )
            # Re-queue entries on failure
            for entry in reversed(batch):
                self._queue.appendleft(entry)
        finally:
            # Shield close to ensure connection is returned to pool
            with anyio.CancelScope(shield=True):
                await session.close()

    async def _log(self, level: str, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Queue a log entry for batched database write."""
        # Initialize sequence on first log
        await self._init_sequence()
        self._sequence += 1

        # Sanitize metadata for JSON safety
        safe_metadata = sanitize_for_json(metadata) if metadata else None

        # Log to file immediately (for real-time file access)
        log_method = getattr(self._file_logger, level.lower(), self._file_logger.info)
        if metadata:
            log_method(f"{message} | {metadata}")
        else:
            log_method(message)

        # Flush file handlers immediately
        for handler in self._file_logger.handlers:
            handler.flush()

        # Queue for batched database write
        entry = LogEntry(
            level=level,
            message=message,
            metadata=safe_metadata,
            timestamp=datetime.utcnow(),
            sequence=self._sequence
        )
        self._queue.append(entry)

        # Start flush task if not running
        self._start_flush_task()

    async def info(self, message: str, metadata: Optional[dict] = None):
        """Log INFO level message."""
        await self._log("INFO", message, metadata)

    async def warning(self, message: str, metadata: Optional[dict] = None):
        """Log WARNING level message."""
        await self._log("WARNING", message, metadata)

    async def error(self, message: str, metadata: Optional[dict] = None):
        """Log ERROR level message."""
        await self._log("ERROR", message, metadata)

    async def debug(self, message: str, metadata: Optional[dict] = None):
        """Log DEBUG level message."""
        await self._log("DEBUG", message, metadata)

    async def close(self):
        """Stop flush task and flush remaining logs to database."""
        self._running = False

        # Cancel flush task
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush of remaining logs
        await self._flush_to_db()

        # Close file handlers
        for handler in self._file_logger.handlers:
            handler.close()
        self._file_logger.handlers.clear()

