"""
PathLab Gateway Service

Main entry point that registers all route modules.
Most route logic has been moved to separate files in routes/ directory.
"""
import asyncio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db, close_db, get_db
from backend.database.repositories import TrainingTaskRepository
from .dependencies import logger, AI_SERVICE_URL, PREPROCESSING_SERVICE_URL
from .pipeline import run_training_pipeline
from .task_queue import init_task_queue, shutdown_task_queue, get_task_queue, TaskType
from .routes import (
    auth_router,
    stats_router,
    wsi_router,
    wsi_upload_router,
    training_router,
    ai_tasks_router,
    results_router,
    models_router,
    chat_router,
    parse_router,
    storage_router,
    queue_router,
)

# Create FastAPI app
app = FastAPI(title="PathLab Gateway")

# Enable CORS for dev and on-prem SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize database and task queue on startup, resume interrupted tasks"""
    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")

    # Initialize task queue manager
    logger.info("Initializing task queue manager...")
    await init_task_queue(max_concurrent=1)
    logger.info("✓ Task queue manager initialized")

    # Resume interrupted training tasks
    # Tasks with status 'running', 'extracting', or 'training' were interrupted
    # by system shutdown/crash and need to be resumed
    await resume_interrupted_tasks()


async def wait_for_services_ready(timeout: float = 60.0, check_interval: float = 2.0) -> bool:
    """
    Wait for AI and Preprocessing services to be ready.

    Args:
        timeout: Maximum time to wait in seconds
        check_interval: Time between health checks in seconds

    Returns:
        True if all services are ready, False if timeout
    """
    services = [
        ("AI", f"{AI_SERVICE_URL}/health"),
        ("Preprocessing", f"{PREPROCESSING_SERVICE_URL}/health"),
    ]

    elapsed = 0.0
    while elapsed < timeout:
        all_ready = True
        for name, url in services:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
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
        logger.info(f"Waiting for services to be ready... ({elapsed:.0f}s/{timeout:.0f}s)")

    logger.warning(f"Timeout waiting for services after {timeout}s")
    return False


def _handle_task_exception(task: asyncio.Task, task_id: str):
    """Callback to handle exceptions from background tasks"""
    try:
        exc = task.exception()
        if exc is not None:
            logger.error(f"Background task for {task_id} failed with exception: {exc}")
    except asyncio.CancelledError:
        logger.warning(f"Background task for {task_id} was cancelled")


async def resume_interrupted_tasks():
    """
    Resume training tasks that were interrupted by system shutdown or crash.

    Interrupted tasks are those with status 'running', 'extracting', or 'training'.
    Failed tasks (status='failed') are NOT resumed as they failed normally.

    This function:
    1. First checks if there are any interrupted tasks (quick check)
    2. If yes, waits for dependent services (AI, Preprocessing) to be ready
    3. Restarts the training pipeline for each task
    """
    async for db in get_db():
        try:
            # Quick check: are there any interrupted tasks?
            interrupted_tasks = await TrainingTaskRepository.get_interrupted_tasks(db)

            if not interrupted_tasks:
                logger.info("No interrupted tasks to resume")
                return

            logger.info(f"Found {len(interrupted_tasks)} interrupted task(s) to resume")

            # Only wait for services if we have tasks to resume
            services_ready = await wait_for_services_ready(timeout=60.0)
            if not services_ready:
                logger.error("Cannot resume interrupted tasks: dependent services are not ready")
                # Mark all interrupted tasks as failed since we can't resume them
                for task in interrupted_tasks:
                    try:
                        await TrainingTaskRepository.update_status(
                            db, task.task_id, "failed",
                            error_message="Failed to resume: dependent services not available after system restart"
                        )
                    except Exception as e:
                        logger.error(f"Failed to mark task {task.task_id} as failed: {e}")
                await db.commit()
                return

            for task in interrupted_tasks:
                try:
                    # Try to claim the task atomically (multi-instance safe)
                    # Only one instance can successfully claim a task
                    claimed = await TrainingTaskRepository.try_claim_for_resume(db, task.task_id)
                    await db.commit()

                    if not claimed:
                        # Another instance already claimed this task
                        logger.info(f"Task {task.task_id} already claimed by another instance, skipping")
                        continue

                    # Get associated WSI IDs
                    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)

                    if not wsi_ids:
                        logger.warning(f"Task {task.task_id} has no associated WSI IDs, marking as failed")
                        await TrainingTaskRepository.update_status(
                            db, task.task_id, "failed",
                            error_message="No associated WSI IDs found during resume"
                        )
                        await db.commit()
                        continue

                    logger.info(f"Resuming task: {task.task_id} ({task.task_name})")
                    logger.info(f"  - Status before interruption: {task.status}")
                    logger.info(f"  - Progress before interruption: {task.progress}%")
                    logger.info(f"  - WSI count: {len(wsi_ids)}")

                    # Submit task to queue instead of directly creating asyncio task
                    # The queue manages concurrency to prevent GPU overload
                    # Note: The pipeline uses force_recompute=False, so it will
                    # reuse cached patches and features where available
                    task_queue = get_task_queue()
                    # Pass pipeline args as kwargs dict (task_id is reserved for queue)
                    pipeline_kwargs = {
                        "task_id": task.task_id,
                        "data_level": task.data_level,
                        "wsi_ids": wsi_ids,
                        "preprocessing_config": task.preprocessing_config or {},
                        "model_config": task.model_config or {},
                        "huggingface_token": None,  # Token is not persisted for security
                    }
                    await task_queue.submit(
                        task_id=task.task_id,
                        task_type=TaskType.TRAINING,
                        coro_func=run_training_pipeline,
                        **pipeline_kwargs
                    )

                    logger.info(f"✓ Task {task.task_id} queued for resume (claimed by this instance)")

                except Exception as e:
                    logger.error(f"Failed to resume task {task.task_id}: {e}")
                    # Mark the task as failed if we can't resume it
                    try:
                        await TrainingTaskRepository.update_status(
                            db, task.task_id, "failed",
                            error_message=f"Failed to resume after system restart: {str(e)}"
                        )
                        await db.commit()
                    except Exception as update_err:
                        logger.error(f"Failed to update task status: {update_err}")

        except Exception as e:
            logger.error(f"Failed to check for interrupted tasks: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown task queue and close database connections"""
    logger.info("Shutting down task queue manager...")
    await shutdown_task_queue()
    logger.info("✓ Task queue manager stopped")

    logger.info("Closing database connections...")
    await close_db()
    logger.info("✓ Database connections closed")


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "gateway"}


# Register route modules
app.include_router(auth_router)
app.include_router(stats_router)
app.include_router(wsi_router)
app.include_router(wsi_upload_router)
app.include_router(training_router)
app.include_router(ai_tasks_router)
app.include_router(results_router)
app.include_router(models_router)
app.include_router(chat_router)
app.include_router(parse_router)
app.include_router(storage_router)
app.include_router(queue_router)

logger.info("Gateway service initialized with all route modules")

