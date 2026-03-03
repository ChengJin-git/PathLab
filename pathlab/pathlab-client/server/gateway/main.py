"""
PathLab Gateway Service

Main entry point that registers all route modules.
Most route logic has been moved to separate files in routes/ directory.
"""
import asyncio
import httpx
import os
import sys
import importlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, close_db, get_db
from backend.ai.schemas.base import TaskStatus
from backend.database.repositories import (
    TrainingTaskRepository,
    ExportTaskRepository,
    StorageTaskRepository,
)
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
    storage_router,
    queue_router,
    asr_router,
    heatmap_router,
    settings_router,
    gpu_router,
)
from backend.common.config import Config

# Import agent chat router (removed - replaced by research_chat)

# Import research chat router (deep-research proxy)
research_chat_router = None
try:
    from gateway.routes.research_chat import router as research_chat_router
    logger.info("✅ Research chat router loaded successfully")
    print("✅ Research chat router loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load research chat router: {e}")
    print(f"❌ Failed to load research chat router: {e}")
    import traceback
    traceback.print_exc()
    research_chat_router = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Startup: Initialize database and task queue, resume interrupted tasks.
    Shutdown: Shutdown task queue and close database connections.
    """
    # === Startup ===
    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")

    # Detect GPU count and determine max_concurrent
    try:
        from backend.common.gpu_utils import get_gpu_count
        gpu_count = get_gpu_count()
    except ImportError:
        logger.warning("Could not import gpu_utils, assuming 1 GPU")
        gpu_count = 1

    # Single GPU: max_concurrent is locked to 1
    # Multiple GPUs: read from config (persisted setting) or default to 1
    if gpu_count == 1:
        max_concurrent = 1
        logger.info(f"Detected 1 GPU, max_concurrent locked to 1")
    else:
        # Read persisted setting from config, default to 1 if not set
        max_concurrent = Config.get_max_concurrent(default=1)
        logger.info(f"Detected {gpu_count} GPUs, max_concurrent={max_concurrent} (from config)")

    # Initialize task queue manager
    logger.info("Initializing task queue manager...")
    await init_task_queue(max_concurrent=max_concurrent, gpu_count=gpu_count)
    logger.info("✓ Task queue manager initialized")

    # Clean up stale progress files from previous process lifetime
    # MUST happen BEFORE resume_interrupted_tasks() to avoid race condition:
    # The worker loop (started by init_task_queue above) can pick up resumed tasks
    # and start writing progress files while resume_interrupted_tasks() is still awaiting.
    # If cleanup ran after resume, it could delete freshly-written progress files.
    from backend.common.progress_store import cleanup_all_progress
    cleanup_all_progress()

    # Resume interrupted training tasks
    # Tasks with status 'pending', 'running', 'extracting', or 'training' were interrupted
    # by system shutdown/crash and need to be resumed (pending tasks lose their queue position)
    await resume_interrupted_tasks()

    # Cleanup old finished tasks (completed/failed/cancelled older than 7 days)
    await cleanup_old_tasks()

    yield  # Application runs here

    # === Shutdown ===
    logger.info("Shutting down task queue manager...")
    await shutdown_task_queue()
    logger.info("✓ Task queue manager stopped")

    logger.info("Closing database connections...")
    await close_db()
    logger.info("✓ Database connections closed")


# Create FastAPI app with lifespan
app = FastAPI(title="PathLab Gateway", lifespan=lifespan)

# Add request logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    """Log all incoming requests for debugging"""
    if request.url.path == "/chat":
        logger.info(f"[Middleware] Incoming request: {request.method} {request.url.path}?{request.url.query}")
        print(f"[Middleware] Incoming request: {request.method} {request.url.path}?{request.url.query}")
    response = await call_next(request)
    if request.url.path == "/chat":
        logger.info(f"[Middleware] Response status: {response.status_code}")
        print(f"[Middleware] Response status: {response.status_code}")
    return response

# Enable CORS for dev and on-prem SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve user avatars as static files
# These are stored in uploads/avatars/
app.mount("/avatars", StaticFiles(directory=str(Config.get_uploads_dir() / "avatars")), name="avatars")


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

async def cleanup_old_tasks():
    """
    Cleanup old finished tasks on startup.

    Deletes tasks (completed, failed, cancelled) older than 7 days.
    This prevents "zombie" tasks from accumulating in the database.

    Cleans up:
    - Training tasks (TrainingTaskRepository)
    - Export tasks (ExportTaskRepository)
    - Storage tasks (StorageTaskRepository)
    """
    cleanup_days = Config.CLEANUP_OLD_TASKS_DAYS
    async for db in get_db():
        try:
            total_deleted = 0

            # Cleanup training tasks
            training_deleted = await TrainingTaskRepository.cleanup_old_finished_tasks(db, days=cleanup_days)
            total_deleted += training_deleted

            # Cleanup export tasks
            export_deleted = await ExportTaskRepository.cleanup_old_tasks(db, days=cleanup_days)
            total_deleted += export_deleted

            # Cleanup storage tasks
            storage_deleted = await StorageTaskRepository.cleanup_old_tasks(db, days=cleanup_days)
            total_deleted += storage_deleted

            if total_deleted > 0:
                await db.commit()
                logger.info(
                    f"✓ Cleaned up {total_deleted} old task(s): "
                    f"training={training_deleted}, export={export_deleted}, storage={storage_deleted}"
                )
            else:
                logger.info("No old tasks to cleanup")
        except Exception as e:
            logger.error(f"Failed to cleanup old tasks: {e}")
        break  # Only need one iteration


async def resume_interrupted_tasks():
    """
    Resume training tasks that were interrupted by system shutdown or crash.

    Recoverable tasks are those with status 'pending', 'running', 'extracting',
    'training', or 'resuming'.
    - 'pending' tasks are included because the in-memory queue is lost on restart
    - 'resuming' tasks are included because a previous restart may have claimed them
      but the pipeline never started (e.g., due to another crash)
    - Failed tasks (status='failed') are NOT resumed as they failed normally.

    This function:
    1. First checks if there are any recoverable tasks (quick check)
    2. If yes, waits for dependent services (AI, Preprocessing) to be ready
    3. For tasks in interrupted states: claims them via CAS (sets to 'resuming')
    4. For tasks already in 'resuming': skips CAS (already claimed by a previous restart)
    5. Submits all claimed tasks to the GPU task queue
    """
    async for db in get_db():
        try:
            # Quick check: are there any recoverable tasks?
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
                            db, task.task_id, TaskStatus.FAILED,
                            error_message="Failed to resume: dependent services not available after system restart"
                        )
                    except Exception as e:
                        logger.error(f"Failed to mark task {task.task_id} as failed: {e}")
                await db.commit()
                return

            for task in interrupted_tasks:
                try:
                    # Tasks already in 'resuming' state were claimed by a previous restart
                    # but the pipeline never started. Skip CAS and re-submit directly.
                    already_resuming = (task.status == TaskStatus.RESUMING)

                    if already_resuming:
                        logger.info(
                            f"Task {task.task_id} is already in 'resuming' state "
                            f"(claimed by a previous restart but never started), re-submitting to queue"
                        )
                    else:
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
                            db, task.task_id, TaskStatus.FAILED,
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
                    # Pass pipeline args as kwargs dict
                    # Note: task_id is automatically added by task_queue.submit(), don't include it here
                    # Get data_type and task_type from DataGroup relationship
                    data_type = task.data_group.data_type if task.data_group else "wsi"
                    task_type = task.data_group.task_type if task.data_group else "classification"
                    pipeline_kwargs = {
                        "data_type": data_type,
                        "wsi_ids": wsi_ids,
                        "preprocessing_config": task.preprocessing_config or {},
                        "model_config": task.model_config or {},
                        # Token is not persisted for security. During resume:
                        # - If features are already cached: no model loading needed, works fine
                        # - If model checkpoint already downloaded: no token needed, works fine
                        # - If model needs downloading (first use of a private HF model): will fail
                        #   with auth error — user must re-submit the task with their HF token
                        "huggingface_token": None,
                        "training_task_type": task_type,  # Use same param name as pipeline
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
                            db, task.task_id, TaskStatus.FAILED,
                            error_message=f"Failed to resume after system restart: {str(e)}"
                        )
                        await db.commit()
                    except Exception as update_err:
                        logger.error(f"Failed to update task status: {update_err}")

        except Exception as e:
            logger.error(f"Failed to check for interrupted tasks: {e}")


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
if research_chat_router is not None:
    try:
        app.include_router(research_chat_router)
        logger.info("✅ Research chat router registered at /agent/research/*")
        print("✅ Research chat router registered at /agent/research/*")
    except Exception as e:
        logger.error(f"❌ Failed to register research chat router: {e}")
        print(f"❌ Failed to register research chat router: {e}")
        import traceback
        traceback.print_exc()
else:
    logger.warning("⚠️ Research chat router is None, skipping registration")
    print("⚠️ Research chat router is None, skipping registration")
app.include_router(storage_router)
app.include_router(queue_router)
app.include_router(asr_router)
app.include_router(heatmap_router)
app.include_router(settings_router)
app.include_router(gpu_router)

logger.info("Gateway service initialized with all route modules")

