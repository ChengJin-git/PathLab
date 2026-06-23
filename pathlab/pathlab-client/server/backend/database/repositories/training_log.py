"""
TrainingLogRepository - Redis Streams backend
"""
import json
import logging
from typing import List, Optional, Dict, Any

from backend.common.redis_client import get_redis, make_key
from backend.database.utils.json_utils import sanitize_for_json

logger = logging.getLogger(__name__)


class _TrainingLogEntry:
    """Lightweight stand-in for the old TrainingLog ORM model.

    Consumers call `.to_dict()` and `.sequence` — this object provides both
    so gateway code needs zero changes.
    """

    __slots__ = ("stream_id", "task_id", "level", "message", "sequence",
                 "extra_data", "created_at")

    def __init__(self, stream_id: str, fields: Dict[str, str]):
        self.stream_id = stream_id
        self.task_id = fields.get("task_id", "")
        self.level = fields.get("level", "INFO")
        self.message = fields.get("message", "")
        self.sequence = int(fields.get("sequence", "0"))

        raw = fields.get("extra_data", "")
        if raw:
            try:
                self.extra_data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                self.extra_data = None
        else:
            self.extra_data = None

        self.created_at = fields.get("created_at", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.stream_id,
            "task_id": self.task_id,
            "level": self.level,
            "message": self.message,
            "sequence": self.sequence,
            "metadata": sanitize_for_json(self.extra_data) if self.extra_data else None,
            "created_at": self.created_at,
        }


class TrainingLogRepository:
    """Repository for Training Log operations — backed by Redis Streams.

    The ``db`` parameter is kept in method signatures for backward compatibility
    with call sites that pass a SQLAlchemy session; it is **not** used.
    """

    @staticmethod
    async def create(db, log_data: Dict[str, Any]) -> _TrainingLogEntry:
        r = get_redis()
        task_id = log_data["task_id"]
        stream_key = make_key("training_logs", task_id)
        seq_key = make_key("training_logs", task_id, "seq")

        sequence = log_data.get("sequence")
        if sequence is None:
            stored = await r.get(seq_key)
            sequence = (int(stored) + 1) if stored else 1

        extra = log_data.get("extra_data")
        fields: Dict[str, str] = {
            "task_id": task_id,
            "level": log_data.get("level", "INFO"),
            "message": log_data.get("message", ""),
            "sequence": str(sequence),
            "extra_data": json.dumps(extra) if extra else "",
            "created_at": log_data.get("created_at", ""),
        }
        sid = await r.xadd(stream_key, fields)
        await r.set(seq_key, str(sequence))
        return _TrainingLogEntry(sid, fields)

    @staticmethod
    async def get_by_task_id(
        db,
        task_id: str,
        level: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[_TrainingLogEntry]:
        r = get_redis()
        stream_key = make_key("training_logs", task_id)

        try:
            raw = await r.xrange(stream_key)
        except Exception:
            return []

        entries = [_TrainingLogEntry(sid, fields) for sid, fields in raw]

        if level:
            entries = [e for e in entries if e.level == level]

        return entries[offset: offset + limit]

    @staticmethod
    async def get_recent(
        db,
        task_id: str,
        count: int = 100,
    ) -> List[_TrainingLogEntry]:
        r = get_redis()
        stream_key = make_key("training_logs", task_id)

        try:
            raw = await r.xrevrange(stream_key, count=count)
        except Exception:
            return []

        entries = [_TrainingLogEntry(sid, fields) for sid, fields in raw]
        entries.reverse()
        return entries

    @staticmethod
    async def get_logs_after_sequence(
        db,
        task_id: str,
        after_sequence: int,
        limit: int = 100,
    ) -> List[_TrainingLogEntry]:
        r = get_redis()
        stream_key = make_key("training_logs", task_id)

        try:
            raw = await r.xrange(stream_key)
        except Exception:
            return []

        entries = [
            _TrainingLogEntry(sid, fields)
            for sid, fields in raw
            if int(fields.get("sequence", "0")) > after_sequence
        ]
        return entries[:limit]

    @staticmethod
    async def delete_by_task_id(db, task_id: str) -> bool:
        r = get_redis()
        stream_key = make_key("training_logs", task_id)
        seq_key = make_key("training_logs", task_id, "seq")
        deleted = await r.delete(stream_key, seq_key)
        return deleted > 0

