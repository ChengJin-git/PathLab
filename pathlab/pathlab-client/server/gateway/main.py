from typing import Any

"""
PathLab Gateway Service

Main entry point that registers all route modules.
Most route logic has been moved to separate files in routes/ directory.
"""

import asyncio
import httpx
from pathlib import Path
from contextlib import asynccontextmanager, suppress
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, close_db, get_db, async_session
from backend.auth.models import User
from backend.ai.schemas.base import TaskStatus
from backend.common.chat_context_cache import (
    set_cached_context_kwargs,
    set_cached_context_kwargs_admin,
)
from backend.database.repositories import (
    AITaskRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    ExportTaskRepository,
    StorageTaskRepository,
    WSIRepository,
    DatasetGrantRepository,
    SegmentationAnnotationRepository,
)
from backend.database.models import TrainingTask
from sqlalchemy.orm import selectinload
from .dependencies import logger, AI_SERVICE_URL, PREPROCESSING_SERVICE_URL
from .pipeline import run_training_pipeline
from .task_queue import init_task_queue, shutdown_task_queue, get_task_queue, TaskType
from .routes.chat_training_recommendation import (
    get_bundled_training_knowledge_status,
    prewarm_training_recommendation_sources,
)
from .routes.chat_pdf_vectorstore import prewarm_embedding_model
from .routes.asr import startup_prewarm_local_asr
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
    annotation_router,
    training_options_router,
)
from backend.common.config import Config


async def _build_chat_context_cache_for_user(user_id: str | None) -> dict[str, Any]:
    async with async_session() as db:
        stats = await WSIRepository.get_chat_context_stats(
            db, user_id=user_id, elevated_dataset_ids=None
        )
        trained_models = await TrainedModelRepository.get_all(
            db, limit=200, offset=0, user_id=user_id
        )
        trained_models_total = await TrainedModelRepository.count(db, user_id=user_id)
        training_tasks = await TrainingTaskRepository.get_all(
            db, limit=10, offset=0, user_id=user_id
        )
        training_tasks_stats = await TrainingTaskRepository.get_status_counts(
            db, user_id=user_id
        )
        inference_tasks = await AITaskRepository.get_recent(
            db, limit=10, user_id=user_id
        )
        inference_tasks_stats = await AITaskRepository.get_status_counts(
            db, user_id=user_id
        )

    wsi_count = stats.get("total_count", 0)
    data_type_dist = stats.get("data_types", {})
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val}"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val}"
    else:
        data_types_info = "None"

    own_public_datasets_count = 0
    own_private_datasets_count = 0
    elevated_datasets_count = 0
    other_public_datasets_count = 0
    datasets_details = []
    for d in stats.get("datasets") or []:
        access_type = d.get("access_type", "own")
        name = d.get("dataset_name", "unknown")
        did = d.get("dataset_id", "unknown")
        fc = d.get("file_count", 0)
        dt = d.get("data_type", "unknown")
        if access_type == "elevated":
            elevated_datasets_count += 1
            marker = " [ELEVATED ACCESS - temporary permission]"
        elif access_type == "public":
            other_public_datasets_count += 1
            marker = " [PUBLIC ACCESS - shared by other user]"
        elif access_type == "other_user":
            marker = " [OTHER USER'S DATA - admin view]"
        else:
            if d.get("is_public"):
                own_public_datasets_count += 1
            else:
                own_private_datasets_count += 1
            marker = ""
        datasets_details.append(
            f"  - {name} (dataset_id={did}): {fc} files, type={dt}{marker}"
        )
    if datasets_details:
        datasets_list = "\n".join(datasets_details)
    else:
        datasets_list = "  None"

    _task_ids = list({str(m.task_id) for m in trained_models if m.task_id})
    _task_meta: dict[str, tuple[str, str, str]] = {}
    if _task_ids:
        async with async_session() as _db:
            _stmt = (
                select(TrainingTask)
                .options(selectinload(TrainingTask.data_group))
                .where(TrainingTask.task_id.in_(_task_ids))
            )
            _result = await _db.execute(_stmt)
            for _task in _result.scalars().all():
                _dg = _task.data_group
                _task_meta[str(_task.task_id)] = (
                    str((_dg.task_type if _dg else None) or "unknown"),
                    str((_dg.data_type if _dg else None) or "unknown"),
                    str(_task.task_name or ""),
                )

    model_summaries = []
    for m in trained_models:
        _tt, _dt, _tn = _task_meta.get(
            str(m.task_id) if m.task_id else "", ("unknown", "unknown", "")
        )
        model_summaries.append(
            {
                "id": m.model_id,
                "task_type": _tt,
                "data_type": _dt,
                "classes": [c.lower() for c in (m.classes or [])],
                "dataset_names": [],
                "dataset_sources": [],
                "task_name": _tn.lower(),
                "line": f"  - {m.model_name} (id={m.model_id}, task_type={_tt}, trained_on_task={m.task_id}, task_name={_tn or 'unknown'})",
                # embedding field populated below (after batch encode)
                "embedding": None,
            }
        )

    # Batch-encode model descriptions for semantic retrieval at query time.
    # We encode the full `line` string so the embedding captures model name,
    # task_type, data_type and task_id — all the fields a user might ask about.
    if model_summaries:
        try:
            from .routes.chat_pdf_vectorstore import _embed_texts

            _lines = [s["line"] for s in model_summaries]
            _vecs = _embed_texts(_lines)  # shape: (N, 384)
            for _i, _s in enumerate(model_summaries):
                _s["embedding"] = _vecs[_i].tolist()
        except Exception as _emb_exc:
            logger.warning(f"[ChatCtxCache] model embedding failed: {_emb_exc}")

    training_tasks_total = training_tasks_stats.get("total", 0)
    training_tasks_completed = training_tasks_stats.get("completed", 0)
    training_tasks_running = training_tasks_stats.get("running", 0)
    training_tasks_failed = training_tasks_stats.get("failed", 0)

    if training_tasks:
        training_tasks_list = "\n".join(
            [
                f"  - [{str(t.status).upper()}] {t.task_name} (id={t.task_id})"
                for t in training_tasks
            ]
        )
    else:
        training_tasks_list = "  None - user has not created any training tasks yet"

    inference_tasks_total = inference_tasks_stats.get("total", 0)
    inference_tasks_completed = inference_tasks_stats.get("completed", 0)
    inference_tasks_running = inference_tasks_stats.get("running", 0)

    if inference_tasks:
        inference_tasks_list = "\n".join(
            [
                f"  - [{str(t.status).upper()}] {t.task_type} on {t.wsi_id} (id={t.task_id})"
                for t in inference_tasks
            ]
        )
    else:
        inference_tasks_list = "  None - user has not run any inference tasks yet"

    return {
        "wsi_count": wsi_count,
        "data_types_info": data_types_info,
        "datasets_list": datasets_list,
        "own_public_datasets_count": own_public_datasets_count,
        "own_private_datasets_count": own_private_datasets_count,
        "elevated_datasets_count": elevated_datasets_count,
        "other_public_datasets_count": other_public_datasets_count,
        "trained_models_total": trained_models_total,
        "model_summaries": model_summaries,
        "training_tasks_total": training_tasks_total,
        "training_tasks_completed": training_tasks_completed,
        "training_tasks_running": training_tasks_running,
        "training_tasks_failed": training_tasks_failed,
        "training_tasks_list": training_tasks_list,
        "inference_tasks_total": inference_tasks_total,
        "inference_tasks_completed": inference_tasks_completed,
        "inference_tasks_running": inference_tasks_running,
        "inference_tasks_list": inference_tasks_list,
    }


async def _startup_prewarm_chat_context_cache() -> None:
    try:
        async with async_session() as db:
            result = await db.execute(select(User.id).where(User.role != "admin"))
            user_ids = [str(row[0]) for row in result.all()]

        total = len(user_ids)
        warmed = 0
        failed = 0

        for uid in user_ids:
            try:
                kwargs = await _build_chat_context_cache_for_user(uid)
                await set_cached_context_kwargs(uid, kwargs)
                warmed += 1
            except Exception as exc:
                failed += 1
                logger.warning(f"Chat context prewarm failed user={uid}: {exc}")

        try:
            admin_kwargs = await _build_chat_context_cache_for_user(user_id=None)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Startup: Initialize database and task queue, resume interrupted tasks.
    Shutdown: Shutdown task queue and close database connections.
    """
    # === Startup ===
    training_rag_prewarm_task: asyncio.Task[None] | None = None
    chat_context_prewarm_task: asyncio.Task[None] | None = None

    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")

    # Initialize Redis connection pool
    from backend.common.redis_client import init_redis, close_redis

    logger.info("Initializing Redis...")
    await init_redis()
    logger.info("✓ Redis initialized")

    async with async_session() as db:
        _backfilled = await WSIRepository.backfill_source_from_dataset(db)
        if _backfilled:
            logger.info(f"✓ Backfilled WSI source for {_backfilled} record(s)")

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
        logger.info(
            f"Detected {gpu_count} GPUs, max_concurrent={max_concurrent} (from config)"
        )

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

    await cleanup_all_progress()

    # Resume interrupted training tasks
    # Tasks with status 'pending', 'queued', 'patching', 'extracting', or 'training'
    # were interrupted by system shutdown/crash and need to be resumed.
    # Pending/queued tasks lose their in-memory queue position across restart.
    await resume_interrupted_tasks()

    # Cleanup old finished tasks (completed/failed/cancelled older than 7 days)
    await cleanup_old_tasks()

    await cleanup_expired_permissions()

    # Cleanup expired PDF cache files
    from .routes.chat_pdf import cleanup_expired_pdf_cache

    # Run synchronous cleanup in thread pool
    await asyncio.get_event_loop().run_in_executor(None, cleanup_expired_pdf_cache)

    # Log current readiness, then kick off bundled training-RAG warmup in the
    # background so the first training recommendation request does not pay the
    # entire cold-start cost.
    try:
        bundled_status = get_bundled_training_knowledge_status()
        ready_count = sum(1 for ok in bundled_status.values() if ok)
        logger.info(
            f"Bundled training recommendation knowledge status: "
            f"{ready_count}/{len(bundled_status)} source(s) ready"
        )
    except Exception as e:
        logger.error(
            f"Failed to inspect bundled training recommendation knowledge: {e}"
        )

    try:
        import torch

        has_cuda = bool(torch.cuda.is_available())
    except Exception:
        has_cuda = False

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
        except Exception as e:
            logger.error(f"Bundled training recommendation startup prewarm failed: {e}")

    training_rag_prewarm_task = asyncio.create_task(_startup_prewarm_training_rag())
    chat_context_prewarm_task = asyncio.create_task(
        _startup_prewarm_chat_context_cache()
    )
    startup_prewarm_local_asr()

    try:
        yield  # Application runs here
    finally:
        # === Shutdown ===
        if (
            training_rag_prewarm_task is not None
            and not training_rag_prewarm_task.done()
        ):
            training_rag_prewarm_task.cancel()
            with suppress(asyncio.CancelledError):
                await training_rag_prewarm_task

        if (
            chat_context_prewarm_task is not None
            and not chat_context_prewarm_task.done()
        ):
            chat_context_prewarm_task.cancel()
            with suppress(asyncio.CancelledError):
                await chat_context_prewarm_task

        logger.info("Shutting down task queue manager...")
        await shutdown_task_queue()
        logger.info("✓ Task queue manager stopped")

        logger.info("Closing database connections...")
        await close_db()
        logger.info("✓ Database connections closed")

        logger.info("Closing Redis connections...")
        await close_redis()
        logger.info("✓ Redis connections closed")


# Create FastAPI app with lifespan
app = FastAPI(title="PathLab Gateway", lifespan=lifespan)

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
app.mount(
    "/avatars",
    StaticFiles(directory=str(Config.get_uploads_dir() / "avatars")),
    name="avatars",
)

# Serve frontend static assets (images, js, css) for direct Gateway access without Nginx
# In production Nginx serves these; this ensures they work on dev / direct 127.0.0.1:6100 access
_renderer_dist = (
    Path(__file__).resolve().parent.parent.parent / "src" / "renderer" / "dist"
)
if _renderer_dist.is_dir():
    _images_dir = _renderer_dist / "images"
    if _images_dir.is_dir():
        app.mount(
            "/images", StaticFiles(directory=str(_images_dir)), name="frontend-images"
        )
    _assets_dir = _renderer_dist / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets"
        )


async def wait_for_services_ready(
    timeout: float = 60.0, check_interval: float = 2.0
) -> bool:
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
        logger.info(
            f"Waiting for services to be ready... ({elapsed:.0f}s/{timeout:.0f}s)"
        )

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
            training_deleted = await TrainingTaskRepository.cleanup_old_finished_tasks(
                db, days=cleanup_days
            )
            total_deleted += training_deleted

            # Cleanup export tasks
            export_deleted = await ExportTaskRepository.cleanup_old_tasks(
                db, days=cleanup_days
            )
            total_deleted += export_deleted

            # Cleanup storage tasks
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
        except Exception as e:
            logger.error(f"Failed to cleanup old tasks: {e}")
        break  # Only need one iteration


async def cleanup_expired_permissions():
    async for db in get_db():
        try:
            expired = await DatasetGrantRepository.get_all_expired(db)
            # Expired grants should not delete historical annotations or drafts.
            # Permission expiry only affects future access checks.
            count = await DatasetGrantRepository.delete_expired(db)
            if count > 0:
                await db.commit()
                logger.info(f"✓ Cleaned up {count} expired dataset grant(s)")
        except Exception as e:
            logger.error(f"Failed to cleanup expired grants: {e}")
        break


async def resume_interrupted_tasks():
    """
    Resume training tasks that were interrupted by system shutdown or crash.

    Recoverable tasks are those with status 'pending', 'queued', 'patching',
    'extracting', 'training', or 'resuming'.
    - 'pending' and 'queued' tasks are included because the in-memory queue is lost on restart
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
                logger.error(
                    "Cannot resume interrupted tasks: dependent services are not ready"
                )
                # Mark all interrupted tasks as failed since we can't resume them
                for task in interrupted_tasks:
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message="Failed to resume: dependent services not available after system restart",
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to mark task {task.task_id} as failed: {e}"
                        )
                await db.commit()
                return

            for task in interrupted_tasks:
                try:
                    # Tasks already in 'resuming' state were claimed by a previous restart
                    # but the pipeline never started. Skip CAS and re-submit directly.
                    already_resuming = task.status == TaskStatus.RESUMING

                    if already_resuming:
                        logger.info(
                            f"Task {task.task_id} is already in 'resuming' state "
                            f"(claimed by a previous restart but never started), re-submitting to queue"
                        )
                    else:
                        # Try to claim the task atomically (multi-instance safe)
                        # Only one instance can successfully claim a task
                        claimed = await TrainingTaskRepository.try_claim_for_resume(
                            db, task.task_id
                        )
                        await db.commit()

                        if not claimed:
                            # Another instance already claimed this task
                            logger.info(
                                f"Task {task.task_id} already claimed by another instance, skipping"
                            )
                            continue

                    # Get associated WSI IDs
                    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)

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

                    # Submit task to queue instead of directly creating asyncio task
                    # The queue manages concurrency to prevent GPU overload
                    # Note: The pipeline uses force_recompute=False, so it will
                    # reuse cached patches and features where available
                    task_queue = get_task_queue()
                    # Pass pipeline args as kwargs dict
                    # Note: task_id is automatically added by task_queue.submit(), don't include it here
                    # Get data_type and task_type from DataGroup relationship
                    data_type = task.data_group.data_type if task.data_group else "wsi"
                    task_type = (
                        task.data_group.task_type
                        if task.data_group
                        else "classification"
                    )

                    if task_type == "external_validation":
                        # External validation tasks use a dedicated pipeline, not run_training_pipeline.
                        # All necessary params were persisted in model_config at submission time.
                        from gateway.routes.results import _run_external_validation

                        model_config = task.model_config or {}

                        # model_task_type / model_data_type were added to model_config after the
                        # resume fix. For tasks submitted before that change, fall back to a DB
                        # lookup via the original training task so that survival and segmentation
                        # models are also recovered correctly.
                        resolved_model_task_type = model_config.get("model_task_type")
                        resolved_model_data_type = model_config.get("model_data_type")

                        if not resolved_model_task_type or not resolved_model_data_type:
                            src_task_id = model_config.get("model_task_id", "")
                            if src_task_id:
                                src_task = await TrainingTaskRepository.get_by_id(
                                    db, src_task_id
                                )
                                if src_task and src_task.data_group:
                                    if not resolved_model_task_type:
                                        resolved_model_task_type = (
                                            src_task.data_group.task_type
                                        )
                                    if not resolved_model_data_type:
                                        resolved_model_data_type = (
                                            src_task.data_group.data_type
                                        )

                        # Final safe defaults
                        resolved_model_task_type = (
                            resolved_model_task_type or "classification"
                        )
                        resolved_model_data_type = resolved_model_data_type or data_type

                        ext_pipeline_kwargs = {
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
                            **ext_pipeline_kwargs,
                        )
                    else:
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
                            **pipeline_kwargs,
                        )

                    logger.info(
                        f"✓ Task {task.task_id} queued for resume (claimed by this instance)"
                    )

                except Exception as e:
                    logger.error(f"Failed to resume task {task.task_id}: {e}")
                    # Mark the task as failed if we can't resume it
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message=f"Failed to resume after system restart: {str(e)}",
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
app.include_router(storage_router)
app.include_router(queue_router)
app.include_router(asr_router)
app.include_router(heatmap_router)
app.include_router(settings_router)
app.include_router(gpu_router)
app.include_router(annotation_router)
app.include_router(training_options_router)

logger.info("Gateway service initialized with all route modules")
