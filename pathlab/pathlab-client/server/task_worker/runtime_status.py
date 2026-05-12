from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

_redis_client = import_module("backend.common.redis_client")
get_redis = _redis_client.get_redis
make_key = _redis_client.make_key

RUNTIME_STATUS_KEY = make_key("task_worker", "runtime_status")
RUNTIME_STATUS_TTL_SECONDS = 20

logger = logging.getLogger("task_worker.runtime_status")


def build_runtime_status_snapshot(queue: Any, *, is_running: bool = True) -> dict[str, Any]:
    max_concurrent = getattr(queue, "max_concurrent", None)
    try:
        gpu_count = int(getattr(queue, "gpu_count", 0) or 0)
    except (TypeError, ValueError):
        gpu_count = 0
    task_timeout = getattr(queue, "task_timeout", None)
    running_tasks = getattr(queue, "_running_tasks", {})
    gpu_assignments = getattr(queue, "_gpu_assignments", {}) or {}
    if not isinstance(gpu_assignments, Mapping):
        gpu_assignments = {}
    pending_tasks = getattr(queue, "_pending_tasks", {})
    patching_tasks = getattr(queue, "_patching_tasks", {})
    bad_gpus = getattr(queue, "_bad_gpus", set())
    gpu_stage_details = getattr(queue, "_gpu_stage_details", {}) or {}
    queue_obj = getattr(queue, "_queue", None)
    queue_size = queue_obj.qsize() if queue_obj is not None else 0
    descriptor_counts = getattr(queue, "descriptor_queue_counts", {}) or {}
    running_tasks_info = [
        {"task_id": task_id, "gpu": gpu_assignments.get(task_id)}
        for task_id in sorted(running_tasks.keys())
    ]

    return {
        "is_running": is_running,
        "max_concurrent": max_concurrent,
        "gpu_count": gpu_count,
        "task_timeout": task_timeout,
        "running_count": len(running_tasks),
        "pending_count": len(pending_tasks),
        "patching_count": len(patching_tasks),
        "queue_size": queue_size,
        "descriptor_pending_count": int(descriptor_counts.get("pending", 0)),
        "descriptor_processing_count": int(descriptor_counts.get("processing", 0)),
        "descriptor_dlq_count": int(descriptor_counts.get("dlq", 0)),
        "running_task_ids": sorted(running_tasks.keys()),
        "running_tasks": running_tasks_info,
        "pending_task_ids": sorted(pending_tasks.keys()),
        "patching_task_ids": sorted(patching_tasks.keys()),
        "bad_gpu_ids": sorted(bad_gpus),
        "gpu_stage_details": dict(gpu_stage_details),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def empty_runtime_status(*, is_running: bool) -> dict[str, Any]:
    return {
        "is_running": is_running,
        "max_concurrent": None,
        "gpu_count": 0,
        "task_timeout": None,
        "running_count": 0,
        "pending_count": 0,
        "patching_count": 0,
        "queue_size": 0,
        "descriptor_pending_count": 0,
        "descriptor_processing_count": 0,
        "descriptor_dlq_count": 0,
        "running_task_ids": [],
        "running_tasks": [],
        "pending_task_ids": [],
        "patching_task_ids": [],
        "bad_gpu_ids": [],
        "gpu_stage_details": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def publish_runtime_status(queue: Any, redis: Any = None) -> None:
    try:
        r = redis if redis is not None else get_redis()
        try:
            task_dispatch = import_module("gateway.task_dispatch")
            queue.descriptor_queue_counts = await task_dispatch.get_task_descriptor_queue_counts(redis=r)
        except Exception as exc:
            logger.warning(f"Failed to collect descriptor queue counts: {exc}")
            queue.descriptor_queue_counts = {"pending": 0, "processing": 0, "dlq": 0}
        snapshot = build_runtime_status_snapshot(queue, is_running=True)
        await r.set(RUNTIME_STATUS_KEY, json.dumps(snapshot), ex=RUNTIME_STATUS_TTL_SECONDS)
    except Exception as exc:
        logger.warning(f"Failed to publish runtime status: {exc}")


async def get_runtime_status(redis: Any = None) -> dict[str, Any] | None:
    try:
        r = redis if redis is not None else get_redis()
        raw = await r.get(RUNTIME_STATUS_KEY)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        return None
