"""Reference-label reading, publication and extraction. Editing lives in viewer.py."""

import asyncio
import csv
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, FileResponse, StreamingResponse
from PIL import Image, ImageDraw, ImageColor
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User, current_active_user
from backend.auth.dependencies import (
    get_wsi_with_access,
    get_dataset_with_access,
    get_user_from_token_param,
)
from backend.database import get_db
from backend.database.models import ViewerRegion, Dataset
from backend.database.repositories import AnnotationAuditLogRepository
from backend.common.config import Config
from backend.common.progress_store import get_progress, set_task_owner, get_task_owner
from backend.services.viewer_annotations import dataset_region_map, RegionValue
from backend.services.dataset_access import accessible_dataset_ids
from gateway.models import AnnotationExtractRequest
from gateway.utils import request_preprocessing_service
from backend.services.viewer_labels import resolve_labels

router = APIRouter(prefix="/annotation", tags=["Reference annotations"])


@router.get("/wsi/{wsi_id}/labels")
async def get_wsi_ground_truth_annotations(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    task_type: str | None = None,
):
    _, _, payload = await resolve_labels(wsi_id, user, db, task_type)
    return payload


@router.get("/wsi/{wsi_id}/label-thumbnail")
async def get_wsi_ground_truth_thumbnail(
    wsi_id: str,
    size: int = Query(160, ge=32, le=1024),
    user=Depends(get_user_from_token_param),
    db=Depends(get_db),
    task_type: str | None = None,
):
    slide, record, payload = await resolve_labels(wsi_id, user, db, task_type)
    if record is None:
        raise HTTPException(404, "Reference labels unavailable")
    if slide.data_type != "patch":
        raise HTTPException(422, "Thumbnail requires a patch image")
    source = Path(slide.wsi_path)

    def render():
        stat = source.stat()
        key = hashlib.sha256(
            f"{wsi_id}:{record.annotation_id}:{record.updated_at}:{stat.st_mtime_ns}:{size}".encode()
        ).hexdigest()
        root = Config.get_uploads_dir() / "metadata" / "ground_truth_previews"
        root.mkdir(parents=True, exist_ok=True)
        path = root / (key + ".png")
        if path.is_file():
            return path
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((size, size))
            sx = image.width / payload["width"]
            sy = image.height / payload["height"]
            draw = ImageDraw.Draw(image, "RGBA")
            for region in payload["annotations"].get(wsi_id, []):
                color = (*ImageColor.getrgb(region.get("color", "#6366f1")), 60)
                points = region.get("points") or [
                    [region["x"], region["y"]],
                    [region["x"] + region["width"], region["y"]],
                    [region["x"] + region["width"], region["y"] + region["height"]],
                    [region["x"], region["y"] + region["height"]],
                ]
                draw.polygon(
                    [(x * sx, y * sy) for x, y in points],
                    fill=color,
                    outline=(*color[:3], 255),
                    width=1,
                )
            temporary = path.with_suffix(".tmp")
            image.save(temporary, format="PNG")
            temporary.replace(path)
        return path

    return FileResponse(
        await asyncio.to_thread(render),
        media_type="image/png",
        headers={"Cache-Control": "private,max-age=600"},
    )


@router.get("/datasets/{dataset_id}/summary")
async def get_dataset_annotation_summary(
    dataset_id: str, user=Depends(current_active_user), db=Depends(get_db)
):
    await get_dataset_with_access(dataset_id, user, db)
    rows = (
        await db.execute(
            select(
                ViewerRegion.label,
                func.count(),
                func.count(func.distinct(ViewerRegion.wsi_id)),
            )
            .where(
                ViewerRegion.dataset_id == dataset_id,
                ViewerRegion.user_id == str(user.id),
                ViewerRegion.layer == "personal",
                ViewerRegion.deleted.is_(False),
            )
            .group_by(ViewerRegion.label)
        )
    ).all()
    return {
        "dataset_id": dataset_id,
        "labels": {
            label: {"total_regions": count, "total_slides": slides}
            for label, count, slides in rows
        },
        "total_regions": sum(row[1] for row in rows),
        "source": "effective_dataset",
    }


@router.post("/extract")
async def extract_regions(
    req: AnnotationExtractRequest, user=Depends(current_active_user), db=Depends(get_db)
):
    if not req.dataset_name.strip():
        raise HTTPException(422, "Dataset name is required")
    parent = None
    if req.source_dataset_id:
        parent = await get_dataset_with_access(req.source_dataset_id, user, db)
    if req.annotation_mode == "shared" and (
        not parent
        or not await db.scalar(
            accessible_dataset_ids(user, write=True).where(
                Dataset.dataset_id == parent.dataset_id
            )
        )
    ):
        raise HTTPException(403, "Team annotation access denied")
    values = (
        await dataset_region_map(db, user, parent.dataset_id, req.annotation_mode)
        if req.dataset_scope and parent
        else req.annotations
    )
    values = {sid: regions for sid, regions in (values or {}).items() if regions}
    if not values or sum(map(len, values.values())) > 10000:
        raise HTTPException(422, "Select between 1 and 10000 regions")
    regions = {}
    for sid, items in values.items():
        slide = await get_wsi_with_access(sid, user, db, with_dataset=True)
        if parent and slide.dataset_id != parent.dataset_id:
            raise HTTPException(422, "Selected images belong to another dataset")
        if not parent and slide.dataset_id:
            raise HTTPException(422, "Source dataset is required")
        if (
            req.task_type in {"patch_segmentation", "patch_detection"}
            and slide.data_type != "patch"
        ):
            raise HTTPException(422, "Spatial labels require patch images")
        regions[sid] = []
        for item in items:
            value = RegionValue.model_validate(
                {
                    key: item[key]
                    for key in [
                        "type",
                        "x",
                        "y",
                        "width",
                        "height",
                        "points",
                        "holes",
                        "label",
                        "color",
                        "task_type",
                    ]
                    if key in item
                }
            )
            if max(value.width, value.height) > 8192:
                raise HTTPException(
                    422, "Extraction regions are limited to 8192 pixels"
                )
            if (
                slide.width
                and value.x + value.width > slide.width
                or slide.height
                and value.y + value.height > slide.height
            ):
                raise HTTPException(422, "Region is outside the slide")
            regions[sid] = [
                *regions[sid],
                value.model_dump(exclude={"color", "task_type"}),
            ]
    identity = "annot_" + uuid4().hex[:12]
    await set_task_owner(identity, str(user.id))
    await request_preprocessing_service(
        "POST",
        "/annotation/extract_regions",
        json_body={
            "regions": regions,
            "dataset_name": req.dataset_name,
            "task_type": req.task_type,
            "user_id": str(user.id),
            "task_id": identity,
            "source_dataset_id": parent.dataset_id if parent else None,
            "parent_dataset_id": parent.dataset_id if parent else None,
            "is_public": False,
            "source_organ": req.source_organ,
        },
        timeout=30,
    )
    if parent:
        await AnnotationAuditLogRepository.log(
            db,
            parent.dataset_id,
            str(user.id),
            "derive",
            {"task_id": identity, "layer": req.annotation_mode},
        )
        await db.commit()
    return {"task_id": identity, "status": "started"}


@router.get("/extract/{task_id}/stream")
async def stream_extract_progress(
    task_id: str, user=Depends(get_user_from_token_param)
):
    owner = await get_task_owner(task_id)
    if owner is None or owner != str(user.id) and not user.is_admin():
        raise HTTPException(404, "Task not found")

    async def stream():
        last = None
        while True:
            progress = await get_progress(task_id)
            if progress != last:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "task_id": task_id,
                            "progress": progress,
                            "done": progress is None or progress >= 100 or progress < 0,
                        }
                    )
                    + "\n\n"
                )
                last = progress
            if progress is not None and (progress >= 100 or progress < 0):
                return
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/audit")
async def list_annotation_audit(
    dataset_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    if not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    rows = await AnnotationAuditLogRepository.list_entries(
        db, dataset_id=dataset_id, event_type=event_type, limit=limit, offset=offset
    )
    count = await AnnotationAuditLogRepository.count_entries(
        db, dataset_id=dataset_id, event_type=event_type
    )
    return {
        "entries": [
            {**row.to_dict(), "dataset_name": None, "user_display": None}
            for row in rows
        ],
        "count": count,
    }


@router.get("/audit/export")
async def export_annotation_audit_csv(
    dataset_id: Optional[str] = None,
    event_type: Optional[str] = None,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    if not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    rows = await AnnotationAuditLogRepository.list_entries(
        db, dataset_id=dataset_id, event_type=event_type, limit=5000, offset=0
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["id", "dataset_id", "user_id", "event_type", "metadata", "created_at"]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.dataset_id,
                row.user_id,
                row.event_type,
                json.dumps(row.event_metadata),
                row.created_at.isoformat(),
            ]
        )
    return Response(
        out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="annotation_audit.csv"'},
    )
