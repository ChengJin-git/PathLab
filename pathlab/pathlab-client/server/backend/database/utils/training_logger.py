"""
Training Logger - Hybrid logging system for training tasks

Design:
- Dual output: Database (for querying) + File (for completeness)
- Real-time streaming support via SSE
- Structured logging with metadata
- Thread-safe for concurrent logging
- Automatic log rotation and cleanup

Usage:
    logger = TrainingLogger(task_id, db_session)
    logger.info("Starting training...")
    logger.info("Epoch 1/10", metadata={"epoch": 1, "loss": 0.5})
    logger.warning("GPU memory high", metadata={"gpu_util": 95})
    logger.error("Training failed", metadata={"error": str(e)})
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.database.models import TrainingLog
from backend.database.utils.json_utils import sanitize_for_json


class TrainingLogger:
    """
    Hybrid logger for training tasks.
    Logs to both database (for querying/streaming) and file (for completeness).
    """
    
    def __init__(self, task_id: str, db_session: AsyncSession, log_dir: Optional[str] = None):
        """
        Initialize training logger.

        Args:
            task_id: Training task ID
            db_session: Database session for storing logs
            log_dir: Directory for log files (default: uploads/logs/training/{task_id})
        """
        self.task_id = task_id
        self.db_session = db_session
        self.sequence: Optional[int] = None  # Monotonic per-task sequence, lazy-initialized from DB

        # Setup file logging - new structure: logs/training/{task_id}/
        if log_dir is None:
            from backend.common.config import Config
            log_dir = str(Config.get_uploads_dir() / "logs" / "training" / task_id)

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "training.log"
        
        # Setup Python logger for file output
        self.file_logger = logging.getLogger(f"training.{task_id}")
        self.file_logger.setLevel(logging.DEBUG)
        self.file_logger.handlers.clear()  # Clear existing handlers
        
        # File handler with rotation
        handler = logging.FileHandler(self.log_file, encoding='utf-8')
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.file_logger.addHandler(handler)
        
        # Also log to console for debugging
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.file_logger.addHandler(console_handler)
    
    async def _log(self, level: str, message: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Internal method to log to both database and file.

        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            message: Log message
            metadata: Optional structured metadata (will be sanitized for JSON safety)
        """
        # Sanitize metadata to handle nan/inf values that would break JSON serialization
        # This is critical for training metrics like loss which may contain nan/inf
        safe_metadata = sanitize_for_json(metadata) if metadata else None

        # Lazy-initialize sequence from DB to keep it monotonic across services
        if self.sequence is None:
            try:
                result = await self.db_session.execute(
                    select(func.max(TrainingLog.sequence)).where(TrainingLog.task_id == self.task_id)
                )
                max_seq = result.scalar()
                self.sequence = int(max_seq) if max_seq is not None else 0
            except Exception:
                # Fallback to 0 if DB is not available; file logs will still work
                self.sequence = 0

        self.sequence += 1

        # Log to file (use original metadata for completeness in file logs)
        log_method = getattr(self.file_logger, level.lower(), self.file_logger.info)
        if metadata:
            log_method(f"{message} | {metadata}")
        else:
            log_method(message)

        # Flush file handlers immediately for real-time log updates
        for handler in self.file_logger.handlers:
            handler.flush()

        # Log to database (use sanitized metadata for JSON safety)
        try:
            log_entry = TrainingLog(
                task_id=self.task_id,
                level=level,
                message=message,
                sequence=self.sequence,
                extra_data=safe_metadata  # Use sanitized metadata for JSON safety
            )
            self.db_session.add(log_entry)
            await self.db_session.flush()  # Flush but don't commit (let caller control transaction)
        except Exception as e:
            # If database logging fails, at least we have file logs
            self.file_logger.error(f"Failed to write log to database: {e}")
    
    async def info(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log INFO level message"""
        await self._log("INFO", message, metadata)
    
    async def warning(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log WARNING level message"""
        await self._log("WARNING", message, metadata)
    
    async def error(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log ERROR level message"""
        await self._log("ERROR", message, metadata)
    
    async def debug(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log DEBUG level message"""
        await self._log("DEBUG", message, metadata)
    
    async def close(self):
        """Close logger and cleanup resources"""
        # Close file handlers
        for handler in self.file_logger.handlers:
            handler.close()
        self.file_logger.handlers.clear()
    
    def get_log_file_path(self) -> str:
        """Get the path to the log file"""
        return str(self.log_file)


class TrainingLogReader:
    """
    Reader for training logs with support for streaming and historical queries.
    """
    
    @staticmethod
    async def get_logs(
        db_session: AsyncSession,
        task_id: str,
        level: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> list:
        """
        Get logs for a training task.
        
        Args:
            db_session: Database session
            task_id: Training task ID
            level: Optional log level filter (INFO, WARNING, ERROR, DEBUG)
            limit: Maximum number of logs to return
            offset: Offset for pagination
            
        Returns:
            List of log entries as dictionaries
        """
        from sqlalchemy import select, and_
        
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)
        
        if level:
            query = query.where(TrainingLog.level == level)
        
        query = query.order_by(TrainingLog.created_at, TrainingLog.sequence)
        query = query.limit(limit).offset(offset)
        
        result = await db_session.execute(query)
        logs = result.scalars().all()
        
        return [log.to_dict() for log in logs]
    
    @staticmethod
    async def get_recent_logs(
        db_session: AsyncSession,
        task_id: str,
        count: int = 100
    ) -> list:
        """
        Get the most recent N logs for a training task.
        
        Args:
            db_session: Database session
            task_id: Training task ID
            count: Number of recent logs to return
            
        Returns:
            List of recent log entries as dictionaries
        """
        from sqlalchemy import select, desc
        
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)
        query = query.order_by(desc(TrainingLog.created_at), desc(TrainingLog.sequence))
        query = query.limit(count)
        
        result = await db_session.execute(query)
        logs = result.scalars().all()
        
        # Reverse to get chronological order
        return [log.to_dict() for log in reversed(logs)]
    
    @staticmethod
    def read_log_file(task_id: str, log_dir: Optional[str] = None, tail_lines: Optional[int] = None) -> list:
        """
        Read logs from file (fallback or for complete history).

        Args:
            task_id: Training task ID
            log_dir: Directory for log files
            tail_lines: If specified, return only the last N lines

        Returns:
            List of log lines
        """
        if log_dir is None:
            from backend.common.config import Config
            # New structure: logs/training/{task_id}/training.log
            log_dir = str(Config.get_uploads_dir() / "logs" / "training" / task_id)

        log_file = Path(log_dir) / "training.log"

        # Fallback to old structure for backward compatibility
        if not log_file.exists():
            from backend.common.config import Config
            old_log_file = Config.get_uploads_dir() / "logs" / f"{task_id}.log"
            if old_log_file.exists():
                log_file = old_log_file

        if not log_file.exists():
            return []

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if tail_lines:
            lines = lines[-tail_lines:]

        return [line.rstrip() for line in lines]

