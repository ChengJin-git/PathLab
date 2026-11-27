"""Viewer orchestration; geometry, persistence, search and inference stay in services."""

import asyncio
import json
from typing import Literal
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from backend.auth import current_active_user
from backend.auth.dependencies import (
    get_wsi_with_access,
    get_user_from_header_or_param,
)
from backend.database import get_db, safe_session
from backend.database.models import Dataset, WSISlide, ViewerRegion
from backend.services import viewer_annotations as annotations
from backend.services.dataset_access import accessible_dataset_ids, can_manage_dataset
from backend.services import viewer_features, viewer_assistance
from backend.ai.feature_contracts import FeatureContract

_cpu_slots = asyncio.Semaphore(2)


async def cpu_call(function, *args, **kwargs):
    try:
        await asyncio.wait_for(_cpu_slots.acquire(), 0.15)
    except TimeoutError:
        raise HTTPException(429, "viewer_busy") from None
    job = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(job)
    finally:
        try:
            if not job.done():
                await job
        finally:
            _cpu_slots.release()


router = APIRouter(prefix="/viewer", tags=["Viewer"])


async def slide_features(db, slide):
    from backend.services.feature_inventory import registered_features

    registered = await registered_features(db, slide)
    produced = await cpu_call(viewer_features.available_features, slide)
    return list({item["path"]: item for item in [*produced, *registered]}.values())


@router.get("/slides/{wsi_id}/context")
async def context(wsi_id: str, user=Depends(current_active_user), db=Depends(get_db)):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    dataset = slide.dataset
    team = bool(
        dataset
        and await db.scalar(
            accessible_dataset_ids(user, write=True).where(
                Dataset.dataset_id == dataset.dataset_id
            )
        )
    )
    manage = bool(dataset and await can_manage_dataset(db, user, dataset))
    previous = (
        await db.scalar(
            select(WSISlide.wsi_id)
            .where(WSISlide.dataset_id == slide.dataset_id, WSISlide.wsi_id < wsi_id)
            .order_by(WSISlide.wsi_id.desc())
            .limit(1)
        )
        if dataset
        else None
    )
    following = (
        await db.scalar(
            select(WSISlide.wsi_id)
            .where(WSISlide.dataset_id == slide.dataset_id, WSISlide.wsi_id > wsi_id)
            .order_by(WSISlide.wsi_id)
            .limit(1)
        )
        if dataset
        else None
    )
    return {
        "wsi_id": wsi_id,
        "name": slide.original_filename,
        "dataset_id": slide.dataset_id,
        "dataset_name": dataset.name if dataset else None,
        "width": slide.width,
        "height": slide.height,
        "mpp": slide.mpp,
        "data_type": slide.data_type,
        "can_personal": True,
        "can_shared": team,
        "can_manage": manage,
        "previous": previous,
        "next": following,
    }


@router.get("/slides/{wsi_id}/regions")
async def regions(
    wsi_id: str,
    layer: Literal["personal", "shared"] = "personal",
    after: str = "",
    limit: int = Query(500, ge=1, le=1000),
    x: float | None = None,
    y: float | None = None,
    width: float | None = Query(None, gt=0),
    height: float | None = Query(None, gt=0),
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    bbox = (x, y, width, height)
    if any(value is not None for value in bbox) and not all(
        value is not None for value in bbox
    ):
        raise HTTPException(422, "Complete viewport required")
    return await annotations.list_regions(
        db,
        user,
        wsi_id,
        layer,
        after=after,
        limit=limit,
        bbox=bbox if x is not None else None,
    )


@router.post("/slides/{wsi_id}/regions")
async def mutate(
    wsi_id: str,
    body: annotations.RegionMutation,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    return await annotations.mutate_regions(db, user, wsi_id, body)


@router.post("/slides/{wsi_id}/regions/selection")
async def selected_regions(
    wsi_id: str,
    body: annotations.RegionSelection,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    return await annotations.resolve_regions(db, user, wsi_id, body)


@router.get("/slides/{wsi_id}/events")
async def events(
    wsi_id: str,
    request: Request,
    layer: Literal["personal", "shared"] = "shared",
    workspace_id: str | None = None,
    user=Depends(get_user_from_header_or_param),
):
    async def access(db, active):
        slide = await annotations.slide_access(db, active, wsi_id, layer)
        if workspace_id:
            from backend.services.workspaces import resolve_scope

            scope = await resolve_scope(db, active, workspace_id)
            if not await db.scalar(
                select(Dataset.dataset_id).where(
                    Dataset.dataset_id == slide.dataset_id,
                    Dataset.dataset_id.in_(scope.datasets(active)),
                )
            ):
                raise HTTPException(403, "Resource is outside the accessible workspace")

    async with safe_session() as db:
        await access(db, user)

    async def stream():
        last = None
        while not await request.is_disconnected():
            async with safe_session() as db:
                try:
                    active = await get_user_from_header_or_param(
                        token=request.query_params.get("token"),
                        authorization=request.headers.get("authorization"),
                    )
                    await access(db, active)
                except HTTPException:
                    yield 'data: {"type":"access_revoked"}\n\n'
                    return
                stamp = await db.scalar(
                    select(func.max(ViewerRegion.updated_at)).where(
                        *annotations.region_scope(active, wsi_id, layer)
                    )
                )
            current = stamp.isoformat() if stamp else ""
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "changed" if current != last else "keepalive",
                        "revision": current,
                    }
                )
                + "\n\n"
            )
            last = current
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

class GeometryOperation(BaseModel):
    operation: Literal["union", "difference", "split", "brush", "erase"]
    regions: list[annotations.RegionGeometry] = Field(
        default_factory=list, max_length=100
    )
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=4096)
    radius: float = Field(10, gt=0, le=4096)


@router.post("/slides/{wsi_id}/geometry")
async def geometry(
    wsi_id: str,
    body: GeometryOperation,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    slide = await get_wsi_with_access(wsi_id, user, db)

    def calculate():
        from shapely.geometry import Polygon, box, LineString
        from shapely.ops import unary_union, split

        shapes = [
            Polygon(r.points, r.holes)
            if r.type == "polygon"
            else box(r.x, r.y, r.x + r.width, r.y + r.height)
            for r in body.regions
        ]
        if body.operation in {"brush", "erase"}:
            if len(body.points) < 2:
                raise ValueError("select_example")
            stroke = LineString(body.points).buffer(body.radius, quad_segs=8)
            base = unary_union(shapes)
            result = (
                base.difference(stroke)
                if body.operation == "erase"
                else base.union(stroke)
            )
        elif body.operation == "split":
            if len(body.points) < 2 or len(shapes) != 1:
                raise ValueError("select_example")
            result = split(shapes[0], LineString(body.points))
        elif body.operation == "difference":
            if len(shapes) < 2:
                raise ValueError("select_example")
            result = shapes[0].difference(unary_union(shapes[1:]))
        else:
            result = unary_union(shapes)
        if slide.width and slide.height:
            result = result.intersection(box(0, 0, slide.width, slide.height))
        parts = (
            [result]
            if result.geom_type == "Polygon"
            else list(getattr(result, "geoms", []))
        )
        output = []
        for shape in parts[:100]:
            if shape.is_empty or shape.geom_type != "Polygon":
                continue
            shape = shape.simplify(max(0.25, body.radius / 12), preserve_topology=True)
            x, y, right, bottom = shape.bounds
            output.append(
                {
                    "type": "polygon",
                    "x": x,
                    "y": y,
                    "width": right - x,
                    "height": bottom - y,
                    "points": list(shape.exterior.coords)[:-1],
                    "holes": [list(ring.coords)[:-1] for ring in shape.interiors],
                }
            )
        return {"regions": output}

    try:
        return await cpu_call(calculate)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

class RegionChangeReference(BaseModel):
    id: str
    revision: int = Field(ge=1)


class PublishReference(BaseModel):
    layer: Literal["personal", "shared"]
    regions: list[RegionChangeReference] = Field(min_length=1, max_length=100)
    task_type: Literal["patch_segmentation", "patch_detection"] = "patch_segmentation"


@router.post("/slides/{wsi_id}/reference-labels")
async def publish_reference(
    wsi_id: str,
    body: PublishReference,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.services.viewer_reference import publish

    return await publish(db, user, wsi_id, body)


@router.get("/slides/{wsi_id}/capabilities")
async def capabilities(
    wsi_id: str, user=Depends(current_active_user), db=Depends(get_db)
):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    features = await slide_features(db, slide)
    from backend.services.viewer_prompt_models import models

    return {
        "features": [
            {
                key: value
                for key, value in item.items()
                if key not in {"path", "coords_path", "contract"}
            }
            for item in features
        ],
        "prompt_models": [
            {"id": item["id"], "name": item.get("name", item["id"])}
            for item in models()
        ],
    }


class FeatureRegistration(BaseModel):
    feature_path: str = Field(max_length=2000)
    coordinates_path: str = Field(max_length=2000)
    contract: FeatureContract


@router.post("/slides/{wsi_id}/features")
async def register_features(
    wsi_id: str,
    body: FeatureRegistration,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    from pathlib import Path
    from backend.common.config import Config

    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    if not user.is_admin():
        raise HTTPException(403, "Feature registration requires administrator access")
    path, coords = (
        Path(body.feature_path).resolve(),
        Path(body.coordinates_path).resolve(),
    )
    if (
        not path.is_file()
        or not coords.is_file()
        or path.suffix not in {".pt", ".npy"}
        or coords.suffix != ".h5"
    ):
        raise HTTPException(422, "Invalid feature or coordinate files")
    if not path.is_relative_to(
        Config.get_uploads_dir().resolve()
    ) or not coords.is_relative_to(Config.get_uploads_dir().resolve()):
        raise HTTPException(422, "Use managed feature storage")
    try:
        await cpu_call(
            viewer_features.validate_registration,
            path,
            coords,
            body.contract.model_dump(),
            slide,
        )
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        raise HTTPException(422, "feature_coordinates_mismatch") from exc
    fields = dict(slide.associated_files or {})
    fields["viewer_features"] = [
        item
        for item in fields.get("viewer_features", [])
        if item.get("feature_path") != str(path)
    ] + [{"feature_path": str(path)}]
    slide.associated_files = fields
    from backend.services.feature_inventory import register_manifest

    await register_manifest(db, slide, path)
    await db.commit()
    return {"registered": True}


@router.post("/slides/{wsi_id}/assist")
async def assist(
    wsi_id: str,
    body: viewer_assistance.AssistRequest,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    if (
        slide.width
        and body.region.x + body.region.width > slide.width
        or slide.height
        and body.region.y + body.region.height > slide.height
    ):
        raise HTTPException(422, "region_outside_slide")
    try:
        return await cpu_call(viewer_assistance.assist, slide, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class SearchFeatures(BaseModel):
    feature_id: str = Field(max_length=64)
    query: str = Field("", max_length=500)
    region: annotations.RegionGeometry | None = None
    negative_regions: list[annotations.RegionGeometry] = Field(
        default_factory=list, max_length=10
    )


@router.post("/slides/{wsi_id}/search")
async def feature_search(
    wsi_id: str,
    body: SearchFeatures,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    features = await slide_features(db, slide)
    item = next((item for item in features if item["id"] == body.feature_id), None)
    if item is None:
        return {"status": "handoff", "reason": "features_missing", "regions": []}
    if not item["image_similarity"]:
        return {
            "status": "handoff",
            "reason": "feature_coordinates_missing",
            "regions": [],
        }
    box = lambda r: (r.x, r.y, r.width, r.height) if r else None
    try:
        regions = await cpu_call(
            viewer_features.search,
            item,
            query=body.query,
            box=box(body.region),
            negative_boxes=[box(r) for r in body.negative_regions],
        )
    except viewer_features.MissingCapability as exc:
        return {"status": "handoff", "reason": exc.code, "regions": []}
    except (ValueError, OSError, RuntimeError, KeyError):
        return {
            "status": "handoff",
            "reason": "feature_coordinates_mismatch",
            "regions": [],
        }
    return {
        "status": "ready",
        "regions": regions,
        "model_id": item["model_id"],
        "score_type": "semantic" if body.query else "similarity",
    }


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    language: Literal["en-US", "zh-CN", "zh-HK"] = "zh-CN"
    layer: Literal["personal", "shared"] = "personal"
    task_id: str | None = None
    feature_id: str | None = None
    selected_ids: list[str] = Field(default_factory=list, max_length=100)
    selection: annotations.RegionGeometry | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


@router.post("/slides/{wsi_id}/assistant")
async def assistant(
    wsi_id: str,
    body: AssistantRequest,
    request: Request,
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.services.viewer_results import result_entries
    from backend.services.viewer_assistant import decide

    slide = await annotations.slide_access(db, user, wsi_id, body.layer)
    items = await result_entries(db, user, wsi_id)
    selected = (
        await db.scalars(
            select(ViewerRegion).where(
                *annotations.region_scope(user, wsi_id, body.layer),
                ViewerRegion.region_id.in_(body.selected_ids),
                ViewerRegion.deleted.is_(False),
            )
        )
    ).all()
    features = await slide_features(db, slide)
    context = {
        "dataset": slide.dataset.name if slide.dataset else None,
        "results": items[:20],
        "selected": [annotations.serialize(row) for row in selected],
        "features": [
            {
                key: item[key]
                for key in ["id", "model_id", "text_similarity", "image_similarity"]
            }
            for item in features
        ],
        "selected_feature": body.feature_id,
        "selected_result": body.task_id,
        "selection": body.selection.model_dump() if body.selection else None,
    }
    await db.commit()
    try:
        decision = await decide(context, body.message, body.language, body.history)
    except Exception as exc:
        raise HTTPException(502, "assistant_unavailable") from exc
    if await request.is_disconnected():
        raise HTTPException(499, "cancelled")
    await annotations.slide_access(db, user, wsi_id, body.layer)
    if decision.scope == "main_workspace":
        decision.action = "handoff"
    response = {"message": decision.message, "action": decision.action, "regions": []}
    if decision.action == "handoff":
        return {
            **response,
            "reason": "complex_request" if decision.scope == "main_workspace" else None,
            "goal": body.message,
        }
    if decision.action in {"semantic", "similar"}:
        feature_id = decision.feature_id or body.feature_id
        if not feature_id:
            return {**response, "action": "handoff", "reason": "features_missing"}
        result = await feature_search(
            wsi_id,
            SearchFeatures(
                feature_id=feature_id,
                query=decision.query if decision.action == "semantic" else "",
                region=body.selection,
            ),
            user,
            db,
        )
        return {
            **response,
            **result,
            "action": "handoff" if result["status"] == "handoff" else "highlight",
        }
    if decision.action == "annotations":
        rows = (
            await db.scalars(
                select(ViewerRegion)
                .where(
                    *annotations.region_scope(user, wsi_id, body.layer),
                    ViewerRegion.deleted.is_(False),
                    ViewerRegion.label.icontains(decision.query, autoescape=True),
                )
                .limit(20)
            )
        ).all()
        response.update(
            action="highlight", regions=[annotations.serialize(row) for row in rows]
        )
    elif decision.action == "attention":
        task = next(
            (
                item
                for item in items
                if item["task_id"] == body.task_id and item.get("has_heatmap")
            ),
            None,
        )
        if task is None:
            return {**response, "action": "handoff", "reason": "results_missing"}
        response.update(action="attention", task_id=task["task_id"])
    elif decision.action == "filter":
        if not any(
            item["task_id"] == body.task_id
            and item.get("task_type") == "patch_detection"
            for item in items
        ):
            return {**response, "action": "handoff", "reason": "results_missing"}
        response["threshold"] = decision.threshold
    elif decision.action == "label":
        response.update(
            label=decision.label, selected_ids=[row.region_id for row in selected]
        )
    elif decision.action == "measure":
        from shapely.geometry import Polygon, box

        shapes = [
            Polygon(row.geometry["points"], row.geometry.get("holes", []))
            if row.geometry["type"] == "polygon"
            else box(row.x, row.y, row.x + row.width, row.y + row.height)
            for row in selected
        ]
        response["measurement"] = {
            "count": len(shapes),
            "area_px": sum(shape.area for shape in shapes),
            "area_um2": sum(shape.area for shape in shapes) * slide.mpp**2
            if slide.mpp
            else None,
        }
    return response
