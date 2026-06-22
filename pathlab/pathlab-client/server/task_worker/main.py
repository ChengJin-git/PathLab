from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from importlib import import_module
from typing import Any

from gateway.task_dispatch import (
    ack_task_descriptor,
    acquire_job_lock,
    claim_task_descriptor,
    dequeue_task_descriptor,
    fail_task_descriptor,
    is_task_cancelled,
    quarantine_task_descriptor,
    rescue_processing_descriptors,
    release_job_lock,
    set_worker_heartbeat,
    CANCEL_CHANNEL,
)
from task_worker.handlers import dispatch_descriptor
from task_worker.runtime_status import publish_runtime_status

logger = logging.getLogger("task_worker")

DequeueFn = Callable[[float], Awaitable[Any]]
DispatchFn = Callable[[Any], Awaitable[None]]
HeartbeatFn = Callable[[], Awaitable[None]]
CancelTaskFn = Callable[[str], Awaitable[Any]]
GetCancelMessageFn = Callable[[float], Awaitable[Any]]


class TaskWorkerRuntime:
    def __init__(
        self,
        dequeue: DequeueFn | None = None,
        dispatch: DispatchFn | None = None,
        heartbeat: HeartbeatFn | None = None,
        cancel_task: CancelTaskFn | None = None,
        get_cancel_message: GetCancelMessageFn | None = None,
    ) -> None:
        self._shutdown_event = asyncio.Event()
        self._dequeue = dequeue
        self._dispatch = dispatch
        self._heartbeat = heartbeat
        self._cancel_task = cancel_task
        self._get_cancel_message = get_cancel_message

    async def run_once(self) -> None:
        try:
            if self._dequeue is not None:
                descriptor = await self._dequeue(1.0)
                raw_descriptor = None
            else:
                claimed = await claim_task_descriptor(1.0)
                if claimed is None:
                    return
                descriptor, raw_descriptor = claimed
        except Exception as exc:
            logger.error(f"Failed to dequeue task descriptor: {exc}")
            return

        if descriptor is None:
            return

        job_id = getattr(descriptor, "job_id", None)
        if raw_descriptor is not None:
            if not isinstance(job_id, str) or not job_id:
                logger.error("Failed to process task descriptor: missing job_id")
                try:
                    await quarantine_task_descriptor(raw_descriptor, descriptor=descriptor, error="missing job_id")
                except Exception as qe:
                    logger.error(f"Failed to quarantine descriptor with missing job_id: {qe}")
                return
            try:
                if await is_task_cancelled(job_id):
                    logger.info(f"Skipping cancelled task descriptor {job_id}")
                    await ack_task_descriptor(raw_descriptor, descriptor=descriptor)
                    return
                if not await acquire_job_lock(job_id):
                    logger.info(f"Skipping duplicate task descriptor {job_id}")
                    await ack_task_descriptor(raw_descriptor, descriptor=descriptor)
                    return
            except Exception as exc:
                logger.error(f"Failed to prepare task descriptor {job_id}: {exc}")
                return

        lock_acquired = raw_descriptor is not None and isinstance(job_id, str)
        try:
            dispatch_fn = self._dispatch if self._dispatch is not None else dispatch_descriptor
            await dispatch_fn(descriptor)
            if raw_descriptor is not None:
                await ack_task_descriptor(raw_descriptor, descriptor=descriptor)
        except Exception as exc:
            if job_id is not None:
                logger.error(f"Failed to process task descriptor {job_id}: {exc}")
            else:
                logger.error(f"Failed to process task descriptor: {exc}")
            if raw_descriptor is not None and isinstance(job_id, str):
                try:
                    await fail_task_descriptor(raw_descriptor, descriptor, exc)
                except Exception as fail_exc:
                    logger.error(f"Failed to record descriptor failure {job_id}: {fail_exc}")
        finally:
            if lock_acquired:
                try:
                    await release_job_lock(str(job_id))
                except Exception as exc:
                    logger.warning(f"Failed to release job lock {job_id}: {exc}")

    async def heartbeat_once(self) -> None:
        try:
            heartbeat_fn = self._heartbeat if self._heartbeat is not None else set_worker_heartbeat
            await heartbeat_fn()
        except Exception as exc:
            logger.warning(f"Heartbeat failed: {exc}")

        try:
            from gateway.task_queue import get_task_queue
            from backend.common.config import Config

            queue = get_task_queue()
            configured_max_concurrent = Config.get_max_concurrent(default=1)
            if getattr(queue, "max_concurrent", None) != configured_max_concurrent:
                await queue.set_max_concurrent(configured_max_concurrent)
            await publish_runtime_status(queue)
        except Exception as exc:
            logger.warning(f"Runtime snapshot publish failed: {exc}")

    async def handle_cancel_message(self, raw: str | bytes) -> None:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Ignoring invalid cancellation payload")
            return

        if not isinstance(payload, dict):
            logger.warning("Ignoring invalid cancellation payload")
            return

        task_id = payload.get("task_id")
        if not task_id:
            logger.warning("Ignoring cancellation payload without task_id")
            return

        try:
            cancel_fn = self._cancel_task
            if cancel_fn is None:
                from gateway.task_queue import get_task_queue

                cancel_fn = get_task_queue().cancel_task
            await cancel_fn(str(task_id))
        except Exception as exc:
            logger.error(f"Failed to cancel task {task_id}: {exc}")

    async def run_loop(self) -> None:
        while not self._shutdown_event.is_set():
            await self.run_once()

    async def heartbeat_loop(self, interval: float = 5.0) -> None:
        while not self._shutdown_event.is_set():
            await self.heartbeat_once()
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=interval
                )
            except asyncio.TimeoutError:
                pass

    def set_cancel_message_source(self, get_cancel_message: GetCancelMessageFn) -> None:
        self._get_cancel_message = get_cancel_message

    async def cancel_loop(self) -> None:
        while not self._shutdown_event.is_set():
            get_msg = self._get_cancel_message
            if get_msg is None:
                get_msg = _get_cancel_message
            try:
                message = await get_msg(1.0)
            except Exception as exc:
                logger.error(f"Cancellation message source failed: {exc}")
                await asyncio.sleep(1.0)
                continue
            if message is not None:
                await self.handle_cancel_message(message)


async def _get_cancel_message(timeout: float) -> str | bytes | None:
    return None


async def _initialize_task_queue_runtime() -> None:
    try:
        from backend.common.gpu_utils import get_gpu_count, probe_all_gpu_health

        gpu_count = get_gpu_count()
    except ImportError:
        logger.warning("Could not import gpu_utils, assuming 1 GPU")
        gpu_count = 1
        probe_all_gpu_health = None

    gpu_health: dict[int, bool] = {}
    if gpu_count > 0 and probe_all_gpu_health is not None:
        gpu_health = probe_all_gpu_health()

    healthy_gpu_count = (
        sum(1 for ok in gpu_health.values() if ok) if gpu_health else gpu_count
    )
    bad_gpu_indices = [idx for idx, ok in gpu_health.items() if not ok]

    from backend.common.config import Config

    max_concurrent = Config.get_max_concurrent(default=1)
    logger.info(
        f"Detected {gpu_count} GPU(s) ({healthy_gpu_count} healthy, {len(bad_gpu_indices)} bad), "
        f"max_concurrent={max_concurrent} (bad GPUs excluded from scheduling)"
    )

    from gateway.task_queue import init_task_queue, get_task_queue

    logger.info("Initializing task queue manager...")
    await init_task_queue(max_concurrent=max_concurrent, gpu_count=gpu_count)
    logger.info("Task queue manager initialized")

    if bad_gpu_indices:
        task_queue = get_task_queue()
        for bad_idx in bad_gpu_indices:
            task_queue.mark_gpu_bad(bad_idx)
        logger.warning(
            f"Excluded {len(bad_gpu_indices)} unhealthy GPU(s) from scheduling: "
            f"{['cuda:' + str(i) for i in bad_gpu_indices]}"
        )


async def _run_recovery() -> None:
    try:
        rescued = await rescue_processing_descriptors()
        if rescued:
            logger.info(f"Requeued {rescued} processing task descriptor(s)")
    except Exception as exc:
        logger.error(f"Processing descriptor recovery failed: {exc}")

    try:
        recovery = import_module("task_worker.recovery")
    except ImportError:
        logger.info("Recovery module not available, skipping recovery")
        return

    try:
        await recovery.resume_interrupted_tasks()
    except Exception as exc:
        logger.error(f"Recovery failed: {exc}")


async def _startup() -> TaskWorkerRuntime:
    from backend.common.config import Config
    from backend.database import init_db
    from backend.common.redis_client import init_redis

    Config.ensure_directories()

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    logger.info("Initializing Redis...")
    await init_redis()
    logger.info("Redis initialized")

    await _initialize_task_queue_runtime()
    await _run_recovery()

    runtime = TaskWorkerRuntime()
    return runtime


async def _shutdown(runtime: TaskWorkerRuntime) -> None:
    runtime._shutdown_event.set()

    from gateway.task_queue import shutdown_task_queue

    logger.info("Shutting down task queue manager...")
    await shutdown_task_queue()
    logger.info("Task queue manager stopped")

    from backend.common.redis_client import close_redis

    logger.info("Closing Redis connections...")
    await close_redis()
    logger.info("Redis connections closed")

    from backend.database import close_db

    logger.info("Closing database connections...")
    await close_db()
    logger.info("Database connections closed")


async def _subscribe_cancel_channel() -> Any:
    from backend.common.redis_client import get_redis

    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CANCEL_CHANNEL)
    return pubsub


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    runtime = await _startup()

    try:
        pubsub = None
        try:
            pubsub = await _subscribe_cancel_channel()
        except Exception as exc:
            logger.warning(f"Failed to subscribe to cancel channel: {exc}")

        async def pubsub_get_message(timeout: float) -> str | bytes | None:
            if pubsub is None:
                return None
            try:
                message = await pubsub.get_message(timeout=timeout)
                if message is not None and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, (str, bytes)):
                        return data
                return None
            except Exception as exc:
                logger.warning(f"Failed to read cancellation message: {exc}")
                return None

        if pubsub is not None:
            runtime.set_cancel_message_source(pubsub_get_message)

        tasks = [
            asyncio.create_task(runtime.heartbeat_loop()),
            asyncio.create_task(runtime.cancel_loop()),
            asyncio.create_task(runtime.run_loop()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Task worker shutting down...")
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        await _shutdown(runtime)
        logger.info("Task worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
