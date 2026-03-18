"""
Dataset Download Routes

API endpoints for downloading datasets from external sources
(HuggingFace, Kaggle, GEO, generic URLs).

Tasks are managed in-memory — they are lost on server restart.
Progress is streamed via SSE.
"""
import asyncio
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from backend.auth import current_active_user, User, get_user_from_token_param
from backend.common.config import Config
from ..services.dataset_downloader import (
    DownloadRequest,
    DownloadStatus,
    create_download_task,
    get_task,
    get_user_tasks,
    request_cancellation,
)

router = APIRouter(prefix="/datasets/download", tags=["Dataset Download"])


@router.post("")
async def start_download(
    req: DownloadRequest,
    user: User = Depends(current_active_user),
):
    """
    Create a background download task.

    Returns the task_id immediately. Progress can be monitored via
    GET /datasets/download/{task_id}/stream (SSE).
    """
    uploads_dir = str(Config.get_uploads_dir())

    # Check disk space (rough check)
    downloads_root = Path(uploads_dir) / "downloads"
    downloads_root.mkdir(parents=True, exist_ok=True)
    try:
        usage = shutil.disk_usage(uploads_dir)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            raise HTTPException(
                status_code=507,
                detail=f"Insufficient disk space: {free_gb:.1f} GB free. At least 1 GB required.",
            )
    except OSError:
        pass  # disk_usage can fail on some systems

    # If HF token not provided in request, try global settings
    if req.source_type == "huggingface" and not req.token:
        settings = Config.get_global_settings()
        hf_token = settings.get("huggingface_token", "")
        if hf_token:
            req.token = hf_token

    # If Kaggle credentials not provided, try global settings
    if req.source_type == "kaggle" and (not req.kaggle_username or not req.kaggle_key):
        settings = Config.get_global_settings()
        req.kaggle_username = req.kaggle_username or settings.get("kaggle_username", "")
        req.kaggle_key = req.kaggle_key or settings.get("kaggle_key", "")

    task = create_download_task(req, uploads_dir, str(user.id))

    return {
        "task_id": task.task_id,
        "message": f"Download task created for {req.source_type.value}: {req.identifier}",
    }


@router.get("/{task_id}/stream")
async def download_progress_stream(
    task_id: str,
    user: User = Depends(get_user_from_token_param),
):
    """
    SSE endpoint streaming real-time download progress.

    Uses token query parameter for authentication since EventSource API
    doesn't support custom headers: ?token=<jwt>
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    async def event_generator():
        last_hash = None
        try:
            while True:
                t = get_task(task_id)
                if not t:
                    yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                    break

                data = json.dumps({
                    "task_id": t.task_id,
                    "source_type": t.source_type.value,
                    "identifier": t.identifier,
                    "status": t.status.value,
                    "progress": t.progress.model_dump(),
                    "files": [f.model_dump() for f in t.files],
                    "total_size": t.total_size,
                    "error": t.error,
                })

                import hashlib
                data_hash = hashlib.md5(data.encode()).hexdigest()
                if data_hash != last_hash:
                    yield f"data: {data}\n\n"
                    last_hash = data_hash

                # Stop streaming when terminal
                if t.status in (
                    DownloadStatus.COMPLETED,
                    DownloadStatus.FAILED,
                    DownloadStatus.CANCELLED,
                ):
                    break

                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{task_id}")
async def cancel_download(
    task_id: str,
    user: User = Depends(current_active_user),
):
    """Cancel a running download task."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    if task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED):
        raise HTTPException(status_code=400, detail=f"Task already {task.status.value}")

    request_cancellation(task_id)
    task.status = DownloadStatus.CANCELLED

    return {"message": f"Cancellation requested for task {task_id}"}


@router.get("/list")
async def list_downloads(
    user: User = Depends(current_active_user),
):
    """List all download tasks for the current user."""
    tasks = get_user_tasks(str(user.id))
    return {
        "items": [
            {
                "task_id": t.task_id,
                "source_type": t.source_type.value,
                "identifier": t.identifier,
                "status": t.status.value,
                "progress": t.progress.model_dump(),
                "files": [f.model_dump() for f in t.files],
                "total_size": t.total_size,
                "error": t.error,
                "created_at": t.created_at,
            }
            for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)
        ]
    }
