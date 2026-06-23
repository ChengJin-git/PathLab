from __future__ import annotations

import asyncio
from contextlib import suppress
import httpx
from sqlalchemy import select, text

from backend.common.config import Config
from backend.auth.models import User
from backend.database import async_session, close_db, get_db, init_db
from backend.database.repositories import (
    DatasetGrantRepository,
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
from .routes.asr import startup_prewarm_local_asr
from .routes.chat_pdf_vectorstore import prewarm_embedding_model
from .routes.chat_training_recommendation import (
    get_bundled_training_knowledge_status,
    prewarm_training_recommendation_sources,
)


def _is_external_validation_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and task_id.startswith("extval_")


def _is_batch_inference_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and task_id.startswith("binfer_")


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

    await cleanup_progress_files()
    await cleanup_old_tasks()
    await cleanup_expired_permissions()
    await cleanup_pdf_cache_runtime()
    await log_bundled_training_readiness()

    training_rag_prewarm_task, chat_context_prewarm_task = (
        start_background_prewarm_tasks(has_cuda=False)
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
    logger.info("Worker owns recovery; Gateway skipping heavy resume logic.")
