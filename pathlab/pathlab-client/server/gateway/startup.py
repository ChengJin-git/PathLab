from __future__ import annotations

import asyncio
from contextlib import suppress
from importlib import import_module
from types import SimpleNamespace
from typing import Any

import httpx
from sqlalchemy import select, text

from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.auth.models import User
from backend.database import async_session, close_db, get_db, init_db
from backend.database.repositories import (
    DatasetGrantRepository,
    DatasetRepository,
    ExportTaskRepository,
    StorageTaskRepository,
    TrainingTaskRepository,
    WSIRepository,
)

from .chat.context_cache import (
    set_cached_context_kwargs,
    set_cached_context_kwargs_admin,
)
from .chat.context_builder import build_chat_context_for_user
from .dependencies import AI_SERVICE_URL, PREPROCESSING_SERVICE_URL, logger
from .pipeline import run_patching_then_submit, run_training_pipeline
from .routes.asr import startup_prewarm_local_asr
from .routes.chat_pdf_vectorstore import prewarm_embedding_model
from .routes.chat_training_recommendation import (
    get_bundled_training_knowledge_status,
    prewarm_training_recommendation_sources,
)
from .task_queue import TaskType, get_task_queue, init_task_queue, shutdown_task_queue


async def wait_for_services_ready(
    timeout: float = 60.0, check_interval: float = 2.0
) -> bool:
    services = [
        ("AI", f"{AI_SERVICE_URL}/health"),
        ("Preprocessing", f"{PREPROCESSING_SERVICE_URL}/health"),
    ]

    elapsed = 0.0
    while elapsed < timeout:
        all_ready = True
        for _name, url in services:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(url)
                    if response.status_code != 200:
                        all_ready = False
                        break
            except Exception:
                all_ready = False
                break

        if all_ready:
            logger.info("✓ All dependent services are ready")
            return True

        await asyncio.sleep(check_interval)
        elapsed += check_interval
        logger.info(
            f"Waiting for services to be ready... ({elapsed:.0f}s/{timeout:.0f}s)"
        )

    logger.warning(f"Timeout waiting for services after {timeout}s")
    return False


async def initialize_runtime_clients(app: object) -> None:
    app.state.ai_client = httpx.AsyncClient(
        base_url=AI_SERVICE_URL,
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
    )
    app.state.preprocessing_client = httpx.AsyncClient(
        base_url=PREPROCESSING_SERVICE_URL,
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
    )


async def shutdown_runtime_clients(app: object) -> None:
    await app.state.ai_client.aclose()
    await app.state.preprocessing_client.aclose()


async def cancel_background_task(task: asyncio.Task[None] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def apply_gateway_schema_migration() -> None:
    async with async_session() as db:
        await db.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "deactivated_by_maintenance BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await db.commit()


async def initialize_redis_connections() -> None:
    from backend.common.redis_client import init_redis

    logger.info("Initializing Redis...")
    await init_redis()
    logger.info("✓ Redis initialized")


async def close_redis_connections() -> None:
    from backend.common.redis_client import close_redis

    logger.info("Closing Redis connections...")
    await close_redis()
    logger.info("✓ Redis connections closed")


async def backfill_wsi_sources() -> None:
    async with async_session() as db:
        backfilled = await WSIRepository.backfill_source_from_dataset(db)
        if backfilled:
            logger.info(f"✓ Backfilled WSI source for {backfilled} record(s)")


async def initialize_task_queue_runtime() -> dict[str, Any]:
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

    max_concurrent = Config.get_max_concurrent(default=1)
    logger.info(
        f"Detected {gpu_count} GPU(s) ({healthy_gpu_count} healthy, {len(bad_gpu_indices)} bad), "
        f"max_concurrent={max_concurrent} (bad GPUs excluded from scheduling)"
    )

    logger.info("Initializing task queue manager...")
    await init_task_queue(max_concurrent=max_concurrent, gpu_count=gpu_count)
    logger.info("✓ Task queue manager initialized")

    if bad_gpu_indices:
        task_queue = get_task_queue()
        for bad_idx in bad_gpu_indices:
            task_queue.mark_gpu_bad(bad_idx)
        logger.warning(
            f"Excluded {len(bad_gpu_indices)} unhealthy GPU(s) from scheduling: "
            f"{['cuda:' + str(i) for i in bad_gpu_indices]}"
        )

    has_cuda = healthy_gpu_count > 0
    return {"has_cuda": has_cuda}


async def cleanup_progress_files() -> None:
    from backend.common.progress_store import cleanup_all_progress

    await cleanup_all_progress()


async def cleanup_pdf_cache_runtime() -> None:
    from .routes.chat_pdf import cleanup_expired_pdf_cache

    await asyncio.get_event_loop().run_in_executor(None, cleanup_expired_pdf_cache)


async def log_bundled_training_readiness() -> None:
    try:
        bundled_status = get_bundled_training_knowledge_status()
        ready_count = sum(1 for ok in bundled_status.values() if ok)
        logger.info(
            f"Bundled training recommendation knowledge status: "
            f"{ready_count}/{len(bundled_status)} source(s) ready"
        )
    except Exception as exc:
        logger.error(
            f"Failed to inspect bundled training recommendation knowledge: {exc}"
        )


async def initialize_gateway_runtime(
    app: object,
) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
    Config.ensure_directories()

    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")

    await apply_gateway_schema_migration()
    logger.info("✓ Schema migration applied (deactivated_by_maintenance)")

    await initialize_redis_connections()
    await backfill_wsi_sources()

    queue_runtime = await initialize_task_queue_runtime()

    await cleanup_progress_files()
    await resume_interrupted_tasks()
    await cleanup_old_tasks()
    await cleanup_expired_permissions()
    await cleanup_pdf_cache_runtime()
    await log_bundled_training_readiness()

    training_rag_prewarm_task, chat_context_prewarm_task = (
        start_background_prewarm_tasks(
            has_cuda=bool(queue_runtime.get("has_cuda", False))
        )
    )

    await initialize_runtime_clients(app)
    return training_rag_prewarm_task, chat_context_prewarm_task


async def shutdown_gateway_runtime(
    app: object,
    training_rag_prewarm_task: asyncio.Task[None] | None,
    chat_context_prewarm_task: asyncio.Task[None] | None,
) -> None:
    await cancel_background_task(training_rag_prewarm_task)
    await cancel_background_task(chat_context_prewarm_task)
    await shutdown_runtime_clients(app)

    logger.info("Shutting down task queue manager...")
    await shutdown_task_queue()
    logger.info("✓ Task queue manager stopped")

    logger.info("Closing database connections...")
    await close_db()
    logger.info("✓ Database connections closed")

    await close_redis_connections()


async def startup_prewarm_chat_context_cache() -> None:
    try:
        async with async_session() as db:
            result = await db.execute(select(User.id).where(User.role != "admin"))
            user_ids = [str(row[0]) for row in result.all()]

        total = len(user_ids)
        warmed = 0
        failed = 0

        for user_id in user_ids:
            try:
                kwargs = await build_chat_context_for_user(user_id)
                await set_cached_context_kwargs(user_id, kwargs)
                warmed += 1
            except Exception as exc:
                failed += 1
                logger.warning(f"Chat context prewarm failed user={user_id}: {exc}")

        try:
            admin_kwargs = await build_chat_context_for_user(user_id=None)
            await set_cached_context_kwargs_admin(admin_kwargs)
            logger.info("Chat context startup prewarm finished for admin global scope")
        except Exception as exc:
            logger.warning(f"Chat context prewarm failed for admin global scope: {exc}")

        logger.info(
            f"Chat context startup prewarm finished: total={total}, warmed={warmed}, failed={failed}"
        )
    except asyncio.CancelledError:
        logger.info("Chat context startup prewarm cancelled")
        raise
    except Exception as exc:
        logger.error(f"Chat context startup prewarm failed: {exc}")


def start_background_prewarm_tasks(
    has_cuda: bool,
) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
    async def _startup_prewarm_training_rag() -> None:
        try:
            embedding_status = await asyncio.to_thread(prewarm_embedding_model)
            logger.info(
                "Training recommendation embedding warmup ready: "
                f"{embedding_status.get('model_name')} on {embedding_status.get('device')}"
            )
            results = await prewarm_training_recommendation_sources(
                force_upgrade=False,
                skip_marker_gpu_queue=has_cuda,
                prewarm_embedding=False,
            )
            success = sum(1 for ok in results.values() if ok)
            logger.info(
                f"Bundled training recommendation startup prewarm finished: "
                f"{success}/{len(results)} source(s) ready"
            )
        except asyncio.CancelledError:
            logger.info("Bundled training recommendation startup prewarm cancelled")
            raise
        except Exception as exc:
            logger.error(
                f"Bundled training recommendation startup prewarm failed: {exc}"
            )

    training_task = asyncio.create_task(_startup_prewarm_training_rag())
    chat_task = asyncio.create_task(startup_prewarm_chat_context_cache())
    startup_prewarm_local_asr()
    return training_task, chat_task


async def cleanup_old_tasks() -> None:
    cleanup_days = Config.CLEANUP_OLD_TASKS_DAYS
    async for db in get_db():
        try:
            total_deleted = 0

            training_deleted = await TrainingTaskRepository.cleanup_old_finished_tasks(
                db, days=cleanup_days
            )
            total_deleted += training_deleted

            export_deleted = await ExportTaskRepository.cleanup_old_tasks(
                db, days=cleanup_days
            )
            total_deleted += export_deleted

            storage_deleted = await StorageTaskRepository.cleanup_old_tasks(
                db, days=cleanup_days
            )
            total_deleted += storage_deleted

            if total_deleted > 0:
                await db.commit()
                logger.info(
                    f"✓ Cleaned up {total_deleted} old task(s): "
                    f"training={training_deleted}, export={export_deleted}, storage={storage_deleted}"
                )
            else:
                logger.info("No old tasks to cleanup")
        except Exception as exc:
            logger.error(f"Failed to cleanup old tasks: {exc}")
        break


async def cleanup_expired_permissions() -> None:
    async for db in get_db():
        try:
            await DatasetGrantRepository.get_all_expired(db)
            count = await DatasetGrantRepository.delete_expired(db)
            if count > 0:
                await db.commit()
                logger.info(f"✓ Cleaned up {count} expired dataset grant(s)")
        except Exception as exc:
            logger.error(f"Failed to cleanup expired grants: {exc}")
        break


async def resume_interrupted_tasks() -> None:
    async for db in get_db():
        try:
            interrupted_tasks = await TrainingTaskRepository.get_interrupted_tasks(db)

            if not interrupted_tasks:
                logger.info("No interrupted tasks to resume")
                return

            logger.info(f"Found {len(interrupted_tasks)} interrupted task(s) to resume")

            services_ready = await wait_for_services_ready(timeout=60.0)
            if not services_ready:
                logger.error(
                    "Cannot resume interrupted tasks: dependent services are not ready"
                )
                for task in interrupted_tasks:
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message="Failed to resume: dependent services not available after system restart",
                        )
                    except Exception as exc:
                        logger.error(
                            f"Failed to mark task {task.task_id} as failed: {exc}"
                        )
                await db.commit()
                return

            for task in interrupted_tasks:
                try:
                    already_resuming = task.status == TaskStatus.RESUMING

                    if already_resuming:
                        logger.info(
                            f"Task {task.task_id} is already in 'resuming' state "
                            f"(claimed by a previous restart but never started), re-submitting to queue"
                        )
                    else:
                        claimed = await TrainingTaskRepository.try_claim_for_resume(
                            db, task.task_id
                        )
                        await db.commit()

                        if not claimed:
                            logger.info(
                                f"Task {task.task_id} already claimed by another instance, skipping"
                            )
                            continue

                    data_type = task.data_group.data_type if task.data_group else "wsi"
                    task_type = (
                        task.data_group.task_type
                        if task.data_group
                        else "classification"
                    )

                    if task_type == "batch_inference":
                        from gateway.routes.inference_batch import _run_batch_inference

                        cfg = task.model_config or {}
                        task_queue = get_task_queue()
                        await task_queue.submit(
                            task_id=task.task_id,
                            task_type=TaskType.BATCH_INFERENCE,
                            coro_func=_run_batch_inference,
                            model_task_id=cfg.get("model_task_id", ""),
                            model_id=cfg.get("model_id", ""),
                            dataset_id=cfg.get("dataset_id", ""),
                        )
                        logger.info(
                            f"✓ Resumed batch inference task {task.task_id} (claimed by this instance)"
                        )
                        continue

                    if task_type == "external_validation":
                        external_validation_dataset_id = (task.model_config or {}).get(
                            "dataset_id", ""
                        )
                        wsi_ids = (
                            await DatasetRepository.get_wsi_ids(
                                db, external_validation_dataset_id
                            )
                            if external_validation_dataset_id
                            else []
                        )
                    else:
                        wsi_ids = await TrainingTaskRepository.get_wsi_ids(
                            db, task.task_id
                        )

                    if not wsi_ids:
                        logger.warning(
                            f"Task {task.task_id} has no associated WSI IDs, marking as failed"
                        )
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message="No associated WSI IDs found during resume",
                        )
                        await db.commit()
                        continue

                    logger.info(f"Resuming task: {task.task_id} ({task.task_name})")
                    logger.info(f"  - Status before interruption: {task.status}")
                    logger.info(f"  - Progress before interruption: {task.progress}%")
                    logger.info(f"  - WSI count: {len(wsi_ids)}")

                    task_queue = get_task_queue()

                    if task_type == "external_validation":
                        from gateway.routes.results import _run_external_validation

                        model_config = task.model_config or {}
                        resolved_model_task_type = model_config.get("model_task_type")
                        resolved_model_data_type = model_config.get("model_data_type")

                        if not resolved_model_task_type or not resolved_model_data_type:
                            source_task_id = model_config.get("model_task_id", "")
                            if source_task_id:
                                source_task = await TrainingTaskRepository.get_by_id(
                                    db, source_task_id
                                )
                                if source_task and source_task.data_group:
                                    if not resolved_model_task_type:
                                        resolved_model_task_type = (
                                            source_task.data_group.task_type
                                        )
                                    if not resolved_model_data_type:
                                        resolved_model_data_type = (
                                            source_task.data_group.data_type
                                        )

                        resolved_model_task_type = (
                            resolved_model_task_type or "classification"
                        )
                        resolved_model_data_type = resolved_model_data_type or data_type

                        external_validation_kwargs = {
                            "model_task_id": model_config.get("model_task_id", ""),
                            "model_id": model_config.get("model_id", ""),
                            "model_classes": task.classes,
                            "model_task_type": resolved_model_task_type,
                            "model_data_type": resolved_model_data_type,
                            "dataset_id": model_config.get("dataset_id", ""),
                            "wsi_ids": wsi_ids,
                        }
                        await task_queue.submit(
                            task_id=task.task_id,
                            task_type=TaskType.EXTERNAL_VALIDATION,
                            coro_func=_run_external_validation,
                            **external_validation_kwargs,
                        )
                    else:
                        pipeline_kwargs = {
                            "data_type": data_type,
                            "wsi_ids": wsi_ids,
                            "preprocessing_config": task.preprocessing_config or {},
                            "model_config": task.model_config or {},
                            "huggingface_token": None,
                            "training_task_type": task_type,
                        }

                        if data_type == "wsi" and task.status in (
                            TaskStatus.EXTRACTING,
                            TaskStatus.TRAINING,
                        ):
                            gpu_kwargs = {**pipeline_kwargs, "patching_complete": True}
                            await task_queue.submit(
                                task_id=task.task_id,
                                task_type=TaskType.TRAINING,
                                coro_func=run_training_pipeline,
                                **gpu_kwargs,
                            )
                            logger.info(
                                "  - Resumed at GPU stage (patching already done, "
                                "submitting with patching_complete=True)"
                            )
                        elif data_type == "wsi":
                            patching_coro = run_patching_then_submit(
                                task.task_id, pipeline_kwargs
                            )
                            patching_task = asyncio.create_task(patching_coro)
                            task_queue.register_patching_task(
                                task.task_id, patching_task
                            )
                            logger.info(
                                f"  - Resumed at patching stage (pre-queue, status was '{task.status}')"
                            )
                        else:
                            await task_queue.submit(
                                task_id=task.task_id,
                                task_type=TaskType.TRAINING,
                                coro_func=run_training_pipeline,
                                **pipeline_kwargs,
                            )
                            logger.info(
                                "  - Patch task resumed directly to GPU queue "
                                "(data_type=patch, no patching stage)"
                            )

                    logger.info(
                        f"✓ Task {task.task_id} queued for resume (claimed by this instance)"
                    )
                except Exception as exc:
                    logger.error(f"Failed to resume task {task.task_id}: {exc}")
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message=f"Failed to resume after system restart: {str(exc)}",
                        )
                        await db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update task status: {update_error}")

        except Exception as exc:
            logger.error(f"Failed to check for interrupted tasks: {exc}")
