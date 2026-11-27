from __future__ import annotations

import asyncio
from contextlib import suppress
import httpx

from backend.common.config import Config
from backend.database import close_db, get_db, init_db
from backend.database.repositories import (
    ExportTaskRepository,
    StorageTaskRepository,
    TrainingTaskRepository,
)

from .dependencies import AI_SERVICE_URL, PREPROCESSING_SERVICE_URL, logger
from .routes.asr import startup_prewarm_local_asr
from .routes.chat_pdf_vectorstore import prewarm_embedding_model
from .routes.chat_training_recommendation import (
    get_bundled_training_knowledge_status,
    prewarm_training_recommendation_sources,
)


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


async def cleanup_pdf_cache_runtime() -> None:
    from backend.services.articles.reader import cleanup_expired_pdf_cache

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
) -> asyncio.Task[None]:
    Config.ensure_directories()

    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")

    await initialize_redis_connections()

    # Progress belongs to running AI/Worker tasks. A Gateway restart must not
    # erase it; terminal-task cleanup and Redis TTL handle stale progress.
    await cleanup_old_tasks()
    await cleanup_pdf_cache_runtime()
    await log_bundled_training_readiness()

    training_rag_prewarm_task = start_background_prewarm_tasks(has_cuda=False)

    await initialize_runtime_clients(app)
    return training_rag_prewarm_task


async def shutdown_gateway_runtime(
    app: object,
    training_rag_prewarm_task: asyncio.Task[None] | None,
) -> None:
    await cancel_background_task(training_rag_prewarm_task)
    await shutdown_runtime_clients(app)

    logger.info("Closing database connections...")
    await close_db()
    logger.info("✓ Database connections closed")

    await close_redis_connections()


def start_background_prewarm_tasks(
    has_cuda: bool,
) -> asyncio.Task[None]:
    async def _startup_prewarm_training_rag() -> None:
        try:
            embedding_status = await asyncio.to_thread(prewarm_embedding_model)
            logger.info(
                "Training recommendation embedding warmup ready: "
                f"{embedding_status.get('model_name')} on {embedding_status.get('device')}"
            )
            results = await prewarm_training_recommendation_sources(
                force_upgrade=False,
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
    startup_prewarm_local_asr()
    return training_task


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
