"""Slide-scoped object editing, optimistic revisions and idempotent transactions."""

import hashlib
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func, text
from backend.auth.dependencies import get_wsi_with_access
from backend.database.models import ViewerRegion, ViewerOperation, Dataset, utc_now
from backend.services.dataset_access import accessible_dataset_ids


class RegionGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: Literal["rect", "polygon"]
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=4096)
    holes: list[list[tuple[float, float]]] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.type == "polygon":
            if len(self.points) < 3:
                raise ValueError("Polygon needs three vertices")
            if sum(map(len, self.holes)) + len(self.points) > 4096:
                raise ValueError("Polygon is too detailed")
            from shapely.geometry import Polygon

            shape = Polygon(self.points, self.holes)
            if not shape.is_valid or shape.is_empty or shape.area <= 0:
                raise ValueError("Invalid polygon")
            x, y, right, bottom = shape.bounds
            if x < 0 or y < 0:
                raise ValueError("Polygon is outside the slide")
            self.x, self.y, self.width, self.height = x, y, right - x, bottom - y
        elif self.points or self.holes:
            raise ValueError("Rectangle cannot contain polygon vertices")
        return self


class RegionValue(RegionGeometry):
    label: str = Field(min_length=1, max_length=100)
    color: str = Field("#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    task_type: Literal[
        "patch_segmentation", "patch_detection", "patch_classification"
    ] = "patch_segmentation"


class RegionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    revision: int = Field(ge=0)
    value: RegionValue | None = None


class RegionMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    layer: Literal["personal", "shared"]
    changes: list[RegionChange] = Field(min_length=1, max_length=100)


async def slide_access(db, user, wsi_id, layer="personal", write=False):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    if slide.data_type == "patch" and (not slide.width or not slide.height):
        import asyncio
        from PIL import Image

        def dimensions():
            with Image.open(slide.wsi_path) as image:
                return image.size

        try:
            slide.width, slide.height = await asyncio.to_thread(dimensions)
        except OSError:
            raise HTTPException(422, "Image file unavailable") from None
    if layer == "shared":
        if not slide.dataset_id or not await db.scalar(
            accessible_dataset_ids(user, write=True).where(
                Dataset.dataset_id == slide.dataset_id
            )
        ):
            raise HTTPException(403, "Team annotation access denied")
    return slide


def region_scope(user, wsi_id, layer):
    return (
        ViewerRegion.wsi_id == wsi_id,
        ViewerRegion.layer == layer,
        True if layer == "shared" else ViewerRegion.user_id == str(user.id),
    )


def serialize(row):
    return {
        "id": row.region_id,
        "revision": row.revision,
        **row.geometry,
        "label": row.label,
        "color": row.color,
        "task_type": row.task_type,
        "created_by": row.created_by,
        "edited_by": row.edited_by,
        "layer": row.layer,
        "updated_at": row.updated_at.isoformat() + "Z",
    }


async def list_regions(db, user, wsi_id, layer, *, after="", limit=500, bbox=None):
    await slide_access(db, user, wsi_id, layer)
    query = select(ViewerRegion).where(
        *region_scope(user, wsi_id, layer), ViewerRegion.deleted.is_(False)
    )
    if bbox:
        x, y, width, height = bbox
        query = query.where(
            ViewerRegion.x < x + width,
            ViewerRegion.y < y + height,
            ViewerRegion.x + ViewerRegion.width > x,
            ViewerRegion.y + ViewerRegion.height > y,
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.where(ViewerRegion.region_id > after)
            .order_by(ViewerRegion.region_id)
            .limit(limit + 1)
        )
    ).all()
    return {
        "items": [serialize(row) for row in rows[:limit]],
        "total": total,
        "next_cursor": rows[limit - 1].region_id if len(rows) > limit else None,
    }


class RegionSelection(BaseModel):
    layer: Literal["personal", "shared"]
    ids: list[str] = Field(max_length=100)


async def resolve_regions(db, user, wsi_id, body):
    await slide_access(db, user, wsi_id, body.layer)
    rows = (
        await db.scalars(
            select(ViewerRegion).where(
                *region_scope(user, wsi_id, body.layer),
                ViewerRegion.region_id.in_(body.ids),
            )
        )
    ).all()
    return {
        "items": [serialize(row) for row in rows if not row.deleted],
        "revisions": {row.region_id: row.revision for row in rows},
    }


async def mutate_regions(db, user, wsi_id, body):
    slide = await slide_access(db, user, wsi_id, body.layer, write=True)
    uid = str(user.id)
    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": body.operation_id},
        )
    previous = await db.get(ViewerOperation, body.operation_id)
    if previous:
        if (
            previous.user_id != uid
            or previous.wsi_id != wsi_id
            or previous.fingerprint != fingerprint
        ):
            raise HTTPException(409, "Operation identity already used")
        return previous.response
    ids = [change.id for change in body.changes]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate region IDs")
    if db.bind.dialect.name == "postgresql":
        for identity in sorted(ids):
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "region:" + identity},
            )
    rows = {
        row.region_id: row
        for row in (
            await db.scalars(
                select(ViewerRegion)
                .where(ViewerRegion.region_id.in_(ids))
                .order_by(ViewerRegion.region_id)
                .with_for_update()
            )
        ).all()
    }
    for change in body.changes:
        row = rows.get(change.id)
        if row and (
            row.wsi_id != wsi_id
            or row.layer != body.layer
            or (body.layer == "personal" and row.user_id != uid)
        ):
            raise HTTPException(404, "Region not found")
        if (row.revision if row else 0) != change.revision:
            raise HTTPException(
                409,
                {
                    "code": "region_conflict",
                    "region_id": change.id,
                    "current": serialize(row) if row and not row.deleted else None,
                },
            )
        if change.value:
            value = change.value
            if (
                slide.width
                and value.x + value.width > slide.width + 0.01
                or slide.height
                and value.y + value.height > slide.height + 0.01
            ):
                raise HTTPException(422, "Region is outside the slide")
    result = []
    for change in body.changes:
        row = rows.get(change.id)
        if row is None:
            if change.value is None:
                raise HTTPException(404, "Region not found")
            row = ViewerRegion(
                region_id=change.id,
                wsi_id=wsi_id,
                dataset_id=slide.dataset_id,
                layer=body.layer,
                user_id=uid,
                created_by=uid,
                edited_by=uid,
                revision=0,
            )
            db.add(row)
        row.revision += 1
        row.edited_by = uid
        row.updated_at = utc_now()
        row.deleted = change.value is None
        if change.value:
            value = change.value
            row.geometry = value.model_dump(exclude={"label", "color", "task_type"})
            for field in ["x", "y", "width", "height", "label", "color", "task_type"]:
                setattr(row, field, getattr(value, field))
        result.append(
            {
                "id": row.region_id,
                "revision": row.revision,
                "value": None if row.deleted else serialize(row),
            }
        )
    response = {"changes": result, "operation_id": body.operation_id}
    db.add(
        ViewerOperation(
            operation_id=body.operation_id,
            user_id=uid,
            wsi_id=wsi_id,
            fingerprint=fingerprint,
            response=response,
        )
    )
    if slide.dataset_id:
        from backend.database.repositories import AnnotationAuditLogRepository

        await AnnotationAuditLogRepository.log(
            db,
            slide.dataset_id,
            uid,
            "region_edit",
            {"operation_id": body.operation_id, "layer": body.layer, "region_ids": ids},
        )
    await db.commit()
    return response


async def dataset_region_map(db, user, dataset_id, layer):
    query = select(ViewerRegion).where(
        ViewerRegion.dataset_id == dataset_id,
        ViewerRegion.layer == layer,
        ViewerRegion.deleted.is_(False),
    )
    if layer == "personal":
        query = query.where(ViewerRegion.user_id == str(user.id))
    rows = (await db.scalars(query.limit(10001))).all()
    if len(rows) > 10000:
        raise HTTPException(422, "Select fewer regions for extraction")
    output = {}
    for row in rows:
        output.setdefault(row.wsi_id, []).append(serialize(row))
    return output
