"""
Annotation routes – draft CRUD + ROI extraction proxy + SSE progress

Draft CRUD: direct DB operations (no proxy needed).
Extract: validates WSI access, then proxies to preprocessing service background task.
SSE: polls Redis progress_store for extraction task progress.
"""
import json
import uuid
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    AnnotationDraftRepository,
    WSIRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_wsi_access_permission, get_user_from_token_param
from backend.common.progress_store import get_progress
from ..dependencies import logger, PREPROCESSING_SERVICE_URL
from ..models import AnnotationDraftSaveRequest, AnnotationExtractRequest

router = APIRouter(prefix="/annotation", tags=["Annotation"])


# ── Draft CRUD ──────────────────────────────────────────────────────────────

@router.post("/drafts")
async def save_draft(
    req: AnnotationDraftSaveRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an annotation draft (auto-save)."""
    try:
        draft = await AnnotationDraftRepository.upsert_draft(
            db,
            draft_id=req.draft_id,
            user_id=str(user.id),
            annotations=req.annotations,
            source_dataset_id=req.source_dataset_id,
        )
        await db.commit()
        return draft.to_dict()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to save annotation draft: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save draft: {str(e)}")


@router.get("/drafts")
async def list_drafts(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all drafts for the current user."""
    drafts = await AnnotationDraftRepository.get_drafts_by_user(db, str(user.id))
    return [d.to_dict() for d in drafts]


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific draft."""
    draft = await AnnotationDraftRepository.get_draft(db, draft_id, str(user.id))
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft.to_dict()


@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a draft."""
    deleted = await AnnotationDraftRepository.delete_draft(db, draft_id, str(user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")
    await db.commit()
    return {"ok": True}


# ── Extract ROI regions ─────────────────────────────────────────────────────

@router.post("/extract")
async def extract_regions(
    req: AnnotationExtractRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit ROI extraction task (async with background processing).

    1. Resolve annotations (from draft or request body)
    2. Validate WSI access for every referenced slide
    3. Proxy to preprocessing service which runs extraction in background
    4. Return task_id immediately — client uses SSE to track progress

    The preprocessing service handles DataGroup/Dataset/WSISlide creation.
    """
    user_id = str(user.id)

    # --- 1. Resolve annotations ---
    annotations = req.annotations
    if annotations is None and req.draft_id:
        draft = await AnnotationDraftRepository.get_draft(db, req.draft_id, user_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        annotations = draft.annotations
    if not annotations:
        raise HTTPException(status_code=400, detail="No annotations provided")

    # --- 2. Validate WSI access for every referenced slide ---
    wsi_ids = list(annotations.keys())
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")
        has_access = await check_wsi_access_permission(user, wsi.dataset_id, wsi.user_id, db)
        if not has_access:
            raise HTTPException(status_code=403, detail=f"No access to WSI: {wsi_id}")

    # --- 3. Build region map & proxy to preprocessing ---
    task_id = f"annot_{uuid.uuid4().hex[:12]}"

    # Convert annotations dict to the format expected by preprocessing:
    # { wsi_id: [{ type, x, y, width, height, label, points }, ...] }
    regions: dict = {}
    for wsi_id, roi_list in annotations.items():
        regions[wsi_id] = [
            {
                "type": roi.get("type", "rect"),
                "x": int(round(roi["x"])),
                "y": int(round(roi["y"])),
                "width": int(round(roi["width"])),
                "height": int(round(roi["height"])),
                "label": roi.get("label", "unlabeled"),
                "points": roi.get("points"),
            }
            for roi in roi_list
        ]

    try:
        payload = {
            "regions": regions,
            "dataset_name": req.dataset_name,
            "task_type": req.task_type,
            "user_id": user_id,
            "task_id": task_id,
        }
        if req.source_dataset_id:
            payload["source_dataset_id"] = req.source_dataset_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{PREPROCESSING_SERVICE_URL}/annotation/extract_regions",
                json=payload,
            )
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ROI extraction proxy failed: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    return {"task_id": task_id, "status": "started"}


# ── SSE progress stream ─────────────────────────────────────────────────────

@router.get("/extract/{task_id}/stream")
async def stream_extract_progress(
    task_id: str,
    user: User = Depends(get_user_from_token_param),
):
    """
    SSE endpoint for streaming extraction progress.

    Polls Redis progress_store and yields progress updates.
    Progress values:
      0-99  = in progress
      100   = completed
      -1    = error
      None  = not started or already cleared
    """
    async def event_generator():
        try:
            last_progress = None
            while True:
                progress = await get_progress(task_id)

                if progress != last_progress:
                    yield f"data: {json.dumps({'task_id': task_id, 'progress': progress})}\n\n"
                    last_progress = progress

                # Terminal states: completed or error
                if progress is not None and (progress >= 100 or progress < 0):
                    break

                # Also stop if progress was cleared (task finished and cleaned up)
                if progress is None and last_progress is not None:
                    yield f"data: {json.dumps({'task_id': task_id, 'progress': None, 'done': True})}\n\n"
                    break

                await asyncio.sleep(2)

        except asyncio.CancelledError:
            logger.info(f"SSE annotation extraction client disconnected: {task_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

