from typing import Any, Optional

"""
Annotation routes – segmentation annotation CRUD + ROI extraction proxy + SSE progress

Annotation CRUD: direct DB operations (no proxy needed).
Extract: validates WSI access, then proxies to preprocessing service background task.
SSE: polls Redis progress_store for extraction task progress.
"""

import json
import uuid
import asyncio
from copy import deepcopy
from pathlib import Path
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageColor, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.database import async_session as _async_session
from backend.database.repositories import (
    SegmentationAnnotationRepository,
    DatasetGrantRepository,
    DatasetRepository,
    AnnotationAuditLogRepository,
    PermissionAuditLogRepository,
    AnnotationOwnershipConflictError,
    VersionConflictError,
    WSIRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import (
    get_dataset_with_access,
    get_user_from_token_param,
    get_wsi_with_access,
)
from backend.auth.annotation_permissions import (
    can_access_shared,
    can_finalize,
    is_annotation_owner,
)
from backend.common.config import Config
from backend.common.coco_utils import coco_to_roi_annotations
from backend.common.file_types import is_patch_file
from backend.common.annotation_summary_cache import (
    build_draft_annotation_summary_cache,
    is_draft_annotation_summary_cache_valid,
    load_draft_annotation_summary_cache,
    rebuild_draft_annotation_summary_cache,
    save_draft_annotation_summary_cache,
)
from backend.common.progress_store import get_progress, set_task_owner, get_task_owner
from backend.common.annotation_pubsub import publish, subscribe_iter
from backend.common.presence_pubsub import publish_presence, subscribe_presence_iter
from ..dependencies import logger
from ..models import (
    AnnotationSaveRequest,
    AnnotationExtractRequest,
    AnnotationDeleteByLabelsRequest,
    SharedAnnotationSaveRequest,
    SharedAnnotationFinalizeRequest,
    BulkDeleteRegionsByCreatorRequest,
    AddCollaboratorRequest,
)
from ..utils import request_preprocessing_service

router = APIRouter(prefix="/annotation", tags=["Annotation"])

GROUND_TRUTH_PREVIEW_CACHE_VERSION = 1
GROUND_TRUTH_PREVIEW_CACHE_HEADERS = {"Cache-Control": "private, max-age=600"}
GROUND_TRUTH_PREVIEW_CACHE_DIR = (
    Config.get_uploads_dir() / "metadata" / "ground_truth_previews"
)


def _normalize_polygon_points(points):
    """Normalize polygon points to int coordinates expected downstream."""
    if not isinstance(points, list):
        return None

    normalized = []
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        normalized.append([int(round(pt[0])), int(round(pt[1]))])

    return normalized if len(normalized) >= 3 else None


def _build_dataset_wsi_lookups(wsis):
    """Build normalized exact/stem filename lookups for GT image → wsi matching."""
    exact_lookup = {}
    stem_lookup = {}
    duplicate_stems = set()

    for wsi in wsis:
        candidate_names = set()
        if getattr(wsi, "original_filename", None):
            candidate_names.add(Path(wsi.original_filename).name)
        if getattr(wsi, "wsi_path", None):
            candidate_names.add(Path(wsi.wsi_path).name)

        for name in candidate_names:
            normalized = Path(name).name.strip().lower()
            if not normalized:
                continue

            exact_lookup.setdefault(normalized, wsi.wsi_id)

            stem = Path(normalized).stem
            if not stem:
                continue
            if stem in stem_lookup and stem_lookup[stem] != wsi.wsi_id:
                duplicate_stems.add(stem)
            else:
                stem_lookup.setdefault(stem, wsi.wsi_id)

    for stem in duplicate_stems:
        stem_lookup.pop(stem, None)

    return exact_lookup, stem_lookup


def _build_single_wsi_gt_lookups(wsi, coco_data=None):
    """Build resilient lookups for a single-WSI GT record."""
    exact_lookup, stem_lookup = _build_dataset_wsi_lookups([wsi])

    images = coco_data.get("images") if isinstance(coco_data, dict) else None
    if isinstance(images, list) and len(images) == 1 and isinstance(images[0], dict):
        image_name = Path(str(images[0].get("file_name") or "")).name.strip().lower()
        if image_name:
            exact_lookup.setdefault(image_name, wsi.wsi_id)

            stem = Path(image_name).stem
            if stem and stem not in stem_lookup:
                stem_lookup[stem] = wsi.wsi_id

    return exact_lookup, stem_lookup


def _convert_gt_record_for_wsi(record, wsi):
    """Convert a GT record to viewer ROIs for the target WSI only."""
    exact_lookup, stem_lookup = _build_single_wsi_gt_lookups(wsi, record.annotations)
    roi_map = coco_to_roi_annotations(
        record.annotations,
        file_name_to_wsi_id=exact_lookup,
        file_stem_to_wsi_id=stem_lookup,
    )
    return {wsi.wsi_id: roi_map.get(wsi.wsi_id, [])} if roi_map.get(wsi.wsi_id) else {}


def _get_gt_image_dimensions_for_wsi(record, wsi):
    """Get the matched COCO image dimensions for a target WSI if available."""
    exact_lookup, stem_lookup = _build_single_wsi_gt_lookups(wsi, record.annotations)
    images = (
        record.annotations.get("images")
        if isinstance(record.annotations, dict)
        else None
    )

    if not isinstance(images, list):
        return None, None

    for image in images:
        if not isinstance(image, dict):
            continue

        image_name = Path(str(image.get("file_name") or "")).name.strip().lower()
        if not image_name:
            continue

        matched_wsi_id = exact_lookup.get(image_name)
        if not matched_wsi_id:
            stem = Path(image_name).stem
            if stem:
                matched_wsi_id = stem_lookup.get(stem)

        if matched_wsi_id != wsi.wsi_id:
            continue

        width = image.get("width")
        height = image.get("height")
        if (
            isinstance(width, (int, float))
            and isinstance(height, (int, float))
            and width > 0
            and height > 0
        ):
            return int(width), int(height)

    return None, None


def _ground_truth_preview_path(wsi_id: str, size: int) -> Path:
    GROUND_TRUTH_PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return GROUND_TRUTH_PREVIEW_CACHE_DIR / f"{wsi_id}_s{int(size)}.png"


def _ground_truth_preview_metadata_path(preview_path: Path) -> Path:
    return preview_path.with_suffix(".json")


def _delete_preview_file_if_possible(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Failed to delete GT preview cache file %s: %s", path, exc)


def _write_ground_truth_preview_metadata(
    metadata_path: Path, cache_key: dict[str, Any]
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temp_metadata_path = metadata_path.with_name(f"{metadata_path.name}.tmp")
    _delete_preview_file_if_possible(temp_metadata_path)
    try:
        temp_metadata_path.write_text(
            json.dumps({"cache_key": cache_key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_metadata_path.replace(metadata_path)
    except Exception:
        _delete_preview_file_if_possible(temp_metadata_path)
        raise


def _save_ground_truth_preview_image(preview_image, preview_path: Path) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    temp_preview_path = preview_path.with_name(f"{preview_path.name}.tmp")
    _delete_preview_file_if_possible(temp_preview_path)

    image_to_save = preview_image.copy()
    image_to_save.info.pop("icc_profile", None)

    try:
        image_to_save.save(temp_preview_path, format="PNG")
        temp_preview_path.replace(preview_path)
    except Exception:
        _delete_preview_file_if_possible(temp_preview_path)
        raise


def _is_ground_truth_preview_cache_valid(
    preview_path: Path, cache_key: dict[str, Any]
) -> bool:
    metadata_path = _ground_truth_preview_metadata_path(preview_path)
    if not preview_path.exists() or not metadata_path.exists():
        return False

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("cache_key") != cache_key:
            return False
        with Image.open(preview_path) as preview:
            preview.load()
        return True
    except Exception as exc:
        logger.warning(
            "Unreadable GT preview cache %s, will regenerate: %s", preview_path, exc
        )
        _delete_preview_file_if_possible(preview_path)
        _delete_preview_file_if_possible(metadata_path)
        return False


def _load_patch_thumbnail(file_path: Path, size: int):
    with Image.open(file_path) as img:
        try:
            img.draft("RGB", (size, size))
        except Exception:
            pass

        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        return img.convert("RGB")


def _color_to_rgba(color: str | None, alpha: int) -> tuple[int, int, int, int]:
    if not color:
        return (139, 92, 246, alpha)

    normalized = str(color).strip() or "#8b5cf6"
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"

    try:
        rgb = ImageColor.getrgb(normalized)
    except Exception:
        rgb = (139, 92, 246)
    return (*rgb, alpha)


def _render_ground_truth_preview(
    file_path: Path,
    size: int,
    regions: list[dict[str, Any]],
    render_width: int,
    render_height: int,
):
    thumbnail = _load_patch_thumbnail(file_path, size).convert("RGBA")
    overlay = Image.new("RGBA", thumbnail.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    scale_x = thumbnail.width / max(int(render_width), 1)
    scale_y = thumbnail.height / max(int(render_height), 1)
    stroke_width = max(1, int(round(min(thumbnail.width, thumbnail.height) / 80)))

    for region in regions:
        stroke = _color_to_rgba(region.get("color"), 255)
        fill = _color_to_rgba(region.get("color"), 46)

        if region.get("type") == "polygon":
            raw_points = region.get("points") or []
            points = []
            for point in raw_points:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                points.append((float(point[0]) * scale_x, float(point[1]) * scale_y))

            if len(points) >= 3:
                draw.polygon(points, fill=fill, outline=stroke, width=stroke_width)
                continue

        x = float(region.get("x") or 0) * scale_x
        y = float(region.get("y") or 0) * scale_y
        width = float(region.get("width") or 0) * scale_x
        height = float(region.get("height") or 0) * scale_y
        draw.rectangle(
            (x, y, x + width, y + height), fill=fill, outline=stroke, width=stroke_width
        )

    return Image.alpha_composite(thumbnail, overlay).convert("RGB")


def _build_ground_truth_preview_cache_key(
    wsi,
    record,
    file_path: Path,
    file_size: int,
    render_width: int,
    render_height: int,
    size: int,
) -> dict[str, Any]:
    return {
        "version": GROUND_TRUTH_PREVIEW_CACHE_VERSION,
        "annotation_id": record.annotation_id,
        "annotation_updated_at": record.updated_at.isoformat()
        if getattr(record, "updated_at", None)
        else None,
        "wsi_path": str(file_path),
        "file_size": int(file_size),
        "file_mtime_ns": file_path.stat().st_mtime_ns,
        "wsi_id": wsi.wsi_id,
        "size": int(size),
        "width": int(render_width),
        "height": int(render_height),
    }


def _ensure_ground_truth_preview_cache(
    wsi,
    record,
    regions: list[dict[str, Any]],
    render_width: int,
    render_height: int,
    size: int,
) -> Path:
    file_path = Path(wsi.wsi_path)
    file_size = int(wsi.file_size or file_path.stat().st_size)
    preview_path = _ground_truth_preview_path(wsi.wsi_id, size)
    metadata_path = _ground_truth_preview_metadata_path(preview_path)
    cache_key = _build_ground_truth_preview_cache_key(
        wsi,
        record,
        file_path,
        file_size,
        render_width,
        render_height,
        size,
    )

    if _is_ground_truth_preview_cache_valid(preview_path, cache_key):
        return preview_path

    preview_image = _render_ground_truth_preview(
        file_path,
        size,
        regions,
        render_width,
        render_height,
    )
    _save_ground_truth_preview_image(preview_image, preview_path)
    _write_ground_truth_preview_metadata(metadata_path, cache_key)
    return preview_path


async def _resolve_wsi_ground_truth_payload(wsi_id: str, user: User, db: AsyncSession):
    wsi = await get_wsi_with_access(
        wsi_id,
        user,
        db,
        with_dataset=True,
        forbidden_detail="You don't have permission to access this WSI",
    )

    elevated_dataset_ids = None
    if wsi.dataset_id:
        from backend.auth.dependencies import get_permitted_dataset_ids

        permitted_dataset_ids = await get_permitted_dataset_ids(user, db)
        if permitted_dataset_ids is None:
            elevated_dataset_ids = {wsi.dataset_id}
        elif wsi.dataset_id in permitted_dataset_ids:
            elevated_dataset_ids = {wsi.dataset_id}
    record_candidates = []

    direct_record = await SegmentationAnnotationRepository.get_with_permission(
        db,
        f"annot_{wsi_id}",
        str(user.id),
        is_admin=user.is_admin(),
        elevated_dataset_ids=elevated_dataset_ids,
    )
    if direct_record and direct_record.status != "draft":
        record_candidates.append(direct_record)

    if wsi.dataset_id:
        dataset_record = await SegmentationAnnotationRepository.get_with_permission(
            db,
            f"annot_{wsi.dataset_id}",
            str(user.id),
            is_admin=user.is_admin(),
            elevated_dataset_ids=elevated_dataset_ids,
        )
        if (
            dataset_record
            and dataset_record.status != "draft"
            and dataset_record.annotation_id
            not in {record.annotation_id for record in record_candidates}
        ):
            record_candidates.append(dataset_record)

    for record in record_candidates:
        roi_map = _convert_gt_record_for_wsi(record, wsi)
        if roi_map:
            gt_width, gt_height = _get_gt_image_dimensions_for_wsi(record, wsi)
            payload = {
                "dataset_id": wsi.dataset_id,
                "annotations": roi_map,
                "record_count": 1,
                "source": "ground_truth",
                "annotation_source": (
                    "imported_gt"
                    if record.source in ("import", "upload")
                    else "user_label"
                ),
                "width": gt_width or wsi.width,
                "height": gt_height or wsi.height,
            }
            return wsi, record, payload

    return (
        wsi,
        None,
        {
            "dataset_id": wsi.dataset_id,
            "annotations": {},
            "record_count": 0,
            "source": "ground_truth",
            "annotation_source": None,
            "width": wsi.width,
            "height": wsi.height,
        },
    )


async def _get_dataset_with_access(dataset_id: str, user: User, db: AsyncSession):
    from backend.database.repositories import DatasetRepository
    from backend.auth.dependencies import check_dataset_access_permission

    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if await check_dataset_access_permission(
        user,
        dataset_id,
        dataset.user_id,
        db,
        is_public=dataset.is_public,
        parent_dataset_id=dataset.parent_dataset_id,
    ):
        return dataset

    raise HTTPException(
        status_code=403,
        detail="You don't have permission to access this dataset",
    )


def _require_personal_annotation_owner(dataset, user: User) -> None:
    if is_annotation_owner(user, dataset):
        return
    raise HTTPException(
        status_code=403,
        detail="Personal annotation is only available to the dataset owner or admin",
    )


async def _get_dataset_wsis(dataset_id: str, db: AsyncSession):
    return await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)


async def _get_dataset_ground_truth_roi_map(
    dataset_id: str, db: AsyncSession, wsis=None
):
    wsis = wsis if wsis is not None else await _get_dataset_wsis(dataset_id, db)
    if not wsis:
        return {}, 0

    gt_records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db, dataset_id, include_drafts=False
    )
    if not gt_records:
        return {}, 0

    dataset_level_record = next(
        (
            record
            for record in gt_records
            if record.annotation_id == f"annot_{dataset_id}"
        ),
        None,
    )
    records_to_use = [dataset_level_record] if dataset_level_record else gt_records

    exact_lookup, stem_lookup = _build_dataset_wsi_lookups(wsis)
    merged_annotations = {}
    used_record_count = 0

    for record in records_to_use:
        roi_map = coco_to_roi_annotations(
            record.annotations,
            file_name_to_wsi_id=exact_lookup,
            file_stem_to_wsi_id=stem_lookup,
        )
        if not roi_map:
            continue

        used_record_count += 1
        for wsi_id, regions in roi_map.items():
            merged_annotations.setdefault(wsi_id, []).extend(regions)

    return merged_annotations, used_record_count


def _build_annotation_summary(annotations, wsis):
    wsis_by_id = {wsi.wsi_id: wsi for wsi in wsis}
    labels = {}
    total_regions = 0
    total_slides = 0
    has_wsi_sources = False

    for wsi_id, regions in annotations.items():
        if not isinstance(regions, list) or len(regions) == 0:
            continue

        total_slides += 1
        wsi = wsis_by_id.get(wsi_id)
        if wsi and not is_patch_file(str(wsi.wsi_path or ""), wsi.file_size or 0):
            has_wsi_sources = True

        labels_on_slide = set()
        for region in regions:
            label = str(region.get("label") or "unlabeled")
            entry = labels.setdefault(
                label,
                {
                    "total_regions": 0,
                    "slide_ids": set(),
                    "color": region.get("color"),
                },
            )
            entry["total_regions"] += 1
            total_regions += 1
            if not entry.get("color") and region.get("color"):
                entry["color"] = region.get("color")
            labels_on_slide.add(label)

        for label in labels_on_slide:
            labels[label]["slide_ids"].add(wsi_id)

    return {
        "total_regions": total_regions,
        "total_slides": total_slides,
        "labels": {
            label: {
                "total_regions": data["total_regions"],
                "total_slides": len(data["slide_ids"]),
                "color": data.get("color"),
            }
            for label, data in labels.items()
        },
        "has_wsi_sources": has_wsi_sources,
    }


async def _resolve_effective_dataset_annotations(
    dataset_id: str, user: User, db: AsyncSession
):
    await _get_dataset_with_access(dataset_id, user, db)
    wsis = await _get_dataset_wsis(dataset_id, db)
    gt_annotations, gt_record_count = await _get_dataset_ground_truth_roi_map(
        dataset_id, db, wsis
    )

    shared_draft = await SegmentationAnnotationRepository.get_shared_draft(
        db, dataset_id
    )
    shared_annotations = (
        shared_draft.annotations
        if shared_draft and isinstance(shared_draft.annotations, dict)
        else None
    )

    draft_annotation = (
        await SegmentationAnnotationRepository.get_latest_draft_by_dataset_for_user(
            db, dataset_id, str(user.id)
        )
    )
    draft_annotations = (
        draft_annotation.annotations
        if draft_annotation and isinstance(draft_annotation.annotations, dict)
        else {}
    )

    effective_annotations = {
        wsi_id: deepcopy(regions) for wsi_id, regions in gt_annotations.items()
    }
    valid_wsi_ids = {wsi.wsi_id for wsi in wsis}

    overlay = (
        shared_annotations if shared_annotations is not None else draft_annotations
    )

    for wsi_id, regions in overlay.items():
        if wsi_id not in valid_wsi_ids:
            continue
        effective_annotations[wsi_id] = (
            deepcopy(regions) if isinstance(regions, list) else []
        )

    return {
        "wsis": wsis,
        "gt_annotations": gt_annotations,
        "effective_annotations": effective_annotations,
        "draft_annotation": draft_annotation,
        "draft_annotations": draft_annotations,
        "gt_record_count": gt_record_count,
        "shared_draft": shared_draft,
    }


# ── Annotation CRUD ──────────────────────────────────────────────────────────


async def _refresh_draft_cache_bg(
    annotation_id: str,
    dataset_id: str,
    user_id: str,
    annotations: Any,
    updated_at: Optional[str],
) -> None:
    """Background task: rebuild draft annotation summary cache with its own DB session."""
    try:
        async with _async_session() as db:
            wsis = await _get_dataset_wsis(dataset_id, db)
            draft_cache = build_draft_annotation_summary_cache(
                annotation_id=annotation_id,
                dataset_id=dataset_id,
                user_id=user_id,
                annotations=annotations if isinstance(annotations, dict) else {},
                wsis=wsis,
                draft_updated_at=updated_at,
            )
            save_draft_annotation_summary_cache(annotation_id, draft_cache)
    except Exception as cache_err:
        logger.warning(
            f"Failed to refresh draft annotation summary cache (bg) for {annotation_id}: {cache_err}"
        )


@router.post("/drafts")
async def save_annotation(
    req: AnnotationSaveRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a segmentation annotation (auto-save)."""
    try:
        if req.source_dataset_id:
            dataset = await _get_dataset_with_access(req.source_dataset_id, user, db)
            _require_personal_annotation_owner(dataset, user)

        annotation = await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id=req.annotation_id,
            user_id=str(user.id),
            annotations=req.annotations,
            source_dataset_id=req.source_dataset_id,
            annotation_mode="personal",
        )
        await db.commit()

        if req.source_dataset_id:
            background_tasks.add_task(
                _refresh_draft_cache_bg,
                annotation_id=req.annotation_id,
                dataset_id=req.source_dataset_id,
                user_id=str(user.id),
                annotations=req.annotations,
                updated_at=annotation.updated_at.isoformat()
                if annotation.updated_at
                else None,
            )

        return annotation.to_dict()
    except AnnotationOwnershipConflictError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="annotation_id already belongs to another user",
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to save annotation: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to save annotation: {str(e)}"
        )


@router.get("/drafts")
async def list_annotations(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List draft annotations for the current user."""
    annotations = await SegmentationAnnotationRepository.get_by_user(
        db, str(user.id), status="draft"
    )
    return [a.to_dict() for a in annotations]


@router.get("/datasets/{dataset_id}/labels")
async def get_dataset_ground_truth_annotations(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return dataset GT converted to viewer ROI format for annotation management."""
    await _get_dataset_with_access(dataset_id, user, db)
    wsis = await _get_dataset_wsis(dataset_id, db)
    if not wsis:
        return {
            "dataset_id": dataset_id,
            "annotations": {},
            "record_count": 0,
            "source": "ground_truth",
            "annotation_source": None,
        }

    merged_annotations, used_record_count = await _get_dataset_ground_truth_roi_map(
        dataset_id, db, wsis
    )
    if not merged_annotations:
        return {
            "dataset_id": dataset_id,
            "annotations": {},
            "record_count": 0,
            "source": "ground_truth",
            "annotation_source": None,
        }

    gt_records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db, dataset_id, include_drafts=False
    )
    has_imported = any(r.source in ("import", "upload") for r in gt_records)
    annotation_source = "imported_gt" if has_imported else "user_label"

    return {
        "dataset_id": dataset_id,
        "annotations": merged_annotations,
        "record_count": used_record_count,
        "source": "ground_truth",
        "annotation_source": annotation_source,
    }


@router.get("/datasets/{dataset_id}/summary")
async def get_dataset_annotation_summary(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's draft annotation summary for the dataset."""
    await _get_dataset_with_access(dataset_id, user, db)

    draft_meta = await SegmentationAnnotationRepository.get_latest_draft_meta_by_dataset_for_user(
        db, dataset_id, str(user.id)
    )
    annotation_id = draft_meta["annotation_id"] if draft_meta else None

    if not draft_meta:
        return {
            "dataset_id": dataset_id,
            "total_regions": 0,
            "total_slides": 0,
            "labels": {},
            "has_wsi_sources": False,
            "source": "effective_dataset",
            "annotation_id": None,
            "label_annotation_source": None,
        }

    wsi_key = await WSIRepository.get_dataset_cache_key(db, dataset_id)
    draft_cache = load_draft_annotation_summary_cache(annotation_id)
    if not is_draft_annotation_summary_cache_valid(
        draft_cache,
        annotation_id,
        draft_meta.get("updated_at"),
        wsi_key,
    ):
        draft_cache = await rebuild_draft_annotation_summary_cache(
            db,
            annotation_id,
            str(user.id),
            dataset_id,
        )

    draft_summary = (draft_cache or {}).get("summary") or {
        "total_regions": 0,
        "total_slides": 0,
        "labels": {},
        "has_wsi_sources": False,
    }
    finalized_records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db, dataset_id, include_drafts=False
    )
    if finalized_records:
        has_imported = any(r.source in ("import", "upload") for r in finalized_records)
        label_annotation_source = "imported_gt" if has_imported else "user_label"
    else:
        label_annotation_source = None

    return {
        "dataset_id": dataset_id,
        **draft_summary,
        "source": "effective_dataset",
        "annotation_id": annotation_id,
        "label_annotation_source": label_annotation_source,
    }


@router.get("/wsi/{wsi_id}/labels")
async def get_wsi_ground_truth_annotations(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return GT for a single WSI/patch, avoiding whole-dataset conversion."""
    _, _, payload = await _resolve_wsi_ground_truth_payload(wsi_id, user, db)
    return payload


@router.get("/wsi/{wsi_id}/label-thumbnail")
async def get_wsi_ground_truth_thumbnail(
    wsi_id: str,
    size: int = Query(
        160, description="Max thumbnail size for GT recommendation previews"
    ),
    user: User = Depends(get_user_from_token_param),
    db: AsyncSession = Depends(get_db),
):
    """Return a cached GT thumbnail PNG for a patch recommendation card."""
    wsi, record, payload = await _resolve_wsi_ground_truth_payload(wsi_id, user, db)
    file_path = Path(wsi.wsi_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {wsi.wsi_path}")

    file_size = int(wsi.file_size or file_path.stat().st_size)
    if not is_patch_file(str(file_path), file_size):
        raise HTTPException(
            status_code=400,
            detail="GT thumbnail preview is currently only supported for patch files",
        )

    regions = payload.get("annotations", {}).get(wsi.wsi_id) or []
    if record is None or not regions:
        raise HTTPException(
            status_code=404, detail=f"Ground truth annotations not found for {wsi_id}"
        )

    render_width = int(payload.get("width") or 0)
    render_height = int(payload.get("height") or 0)
    if render_width <= 0 or render_height <= 0:
        with Image.open(file_path) as img:
            render_width, render_height = img.size

    try:
        preview_path = _ensure_ground_truth_preview_cache(
            wsi,
            record,
            regions,
            render_width,
            render_height,
            max(1, int(size)),
        )
    except Exception as exc:
        logger.warning("Failed to build GT preview cache for %s: %s", wsi_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to render ground truth thumbnail"
        ) from exc

    return FileResponse(
        preview_path,
        media_type="image/png",
        headers=GROUND_TRUTH_PREVIEW_CACHE_HEADERS,
    )


@router.get("/drafts/{annotation_id}")
async def get_annotation(
    annotation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific annotation."""
    annotation = await SegmentationAnnotationRepository.get(
        db, annotation_id, str(user.id)
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.source_dataset_id:
        dataset = await _get_dataset_with_access(annotation.source_dataset_id, user, db)
        _require_personal_annotation_owner(dataset, user)
    return annotation.to_dict()


@router.delete("/drafts/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an annotation."""
    annotation = await SegmentationAnnotationRepository.get(
        db, annotation_id, str(user.id)
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.source_dataset_id:
        dataset = await _get_dataset_with_access(annotation.source_dataset_id, user, db)
        _require_personal_annotation_owner(dataset, user)

    deleted = await SegmentationAnnotationRepository.delete(
        db, annotation_id, str(user.id)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")
    await db.commit()
    return {"ok": True}


@router.post("/datasets/{dataset_id}/delete-by-labels")
async def delete_dataset_annotations_by_labels(
    dataset_id: str,
    req: AnnotationDeleteByLabelsRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete labels across the effective whole-dataset annotation view for the current user."""
    label_set = {label for label in req.labels if label}
    if not label_set:
        raise HTTPException(status_code=400, detail="No labels provided")

    resolved = await _resolve_effective_dataset_annotations(dataset_id, user, db)
    next_draft_annotations = (
        deepcopy(resolved["draft_annotations"])
        if isinstance(resolved["draft_annotations"], dict)
        else {}
    )

    changed = False
    for wsi_id, regions in resolved["effective_annotations"].items():
        filtered_regions = [
            region for region in regions if region.get("label") not in label_set
        ]
        if len(filtered_regions) != len(regions):
            next_draft_annotations[wsi_id] = filtered_regions
            changed = True

    annotation_id = (
        resolved["draft_annotation"].annotation_id
        if resolved["draft_annotation"]
        else str(uuid.uuid4())
    )

    if changed or not resolved["draft_annotation"]:
        try:
            dataset = await _get_dataset_with_access(dataset_id, user, db)
            _require_personal_annotation_owner(dataset, user)
            saved_annotation = await SegmentationAnnotationRepository.upsert(
                db,
                annotation_id=annotation_id,
                user_id=str(user.id),
                annotations=next_draft_annotations,
                source_dataset_id=dataset_id,
                status="draft",
                annotation_mode="personal",
                source="viewer",
            )
            await db.commit()
            draft_cache = build_draft_annotation_summary_cache(
                annotation_id=annotation_id,
                dataset_id=dataset_id,
                user_id=str(user.id),
                annotations=next_draft_annotations,
                wsis=resolved["wsis"],
                draft_updated_at=saved_annotation.updated_at.isoformat()
                if saved_annotation.updated_at
                else None,
            )
            save_draft_annotation_summary_cache(annotation_id, draft_cache)
        except AnnotationOwnershipConflictError:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="annotation_id already belongs to another user",
            )
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to delete dataset annotations by labels: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete dataset annotations: {str(e)}",
            )

    updated_effective_annotations = {
        wsi_id: deepcopy(regions)
        for wsi_id, regions in resolved["gt_annotations"].items()
    }
    valid_wsi_ids = {wsi.wsi_id for wsi in resolved["wsis"]}
    for wsi_id, regions in next_draft_annotations.items():
        if wsi_id not in valid_wsi_ids:
            continue
        updated_effective_annotations[wsi_id] = (
            deepcopy(regions) if isinstance(regions, list) else []
        )

    return {
        "ok": True,
        "annotation_id": annotation_id,
        "summary": {
            "dataset_id": dataset_id,
            **_build_annotation_summary(
                updated_effective_annotations, resolved["wsis"]
            ),
            "source": "effective_dataset",
            "annotation_id": annotation_id,
        },
    }


# ── Extract ROI regions ─────────────────────────────────────────────────────


@router.post("/extract")
async def extract_regions(
    req: AnnotationExtractRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit ROI extraction task (async with background processing).

    1. Resolve annotations (from saved annotation or request body)
    2. Validate WSI access for every referenced slide
    3. Proxy to preprocessing service which runs extraction in background
    4. Return task_id immediately — client uses SSE to track progress

    The preprocessing service handles DataGroup/Dataset/WSISlide creation.
    """
    user_id = str(user.id)

    # --- 1. Resolve annotations ---
    annotations = req.annotations
    if req.dataset_scope:
        if not req.source_dataset_id:
            raise HTTPException(
                status_code=400,
                detail="source_dataset_id is required when dataset_scope=true",
            )
        if req.annotation_mode == "shared":
            dataset = await _get_dataset_with_access(req.source_dataset_id, user, db)
            if not await can_access_shared(user, dataset, db):
                raise HTTPException(status_code=403, detail="Access denied")
        resolved = await _resolve_effective_dataset_annotations(
            req.source_dataset_id, user, db
        )
        valid_wsi_ids = {wsi.wsi_id for wsi in resolved["wsis"]}
        if req.annotation_mode == "shared":
            shared_draft = resolved["shared_draft"]
            overlay: dict = (
                shared_draft.annotations
                if shared_draft and isinstance(shared_draft.annotations, dict)
                else {}
            )
            if not overlay:
                raise HTTPException(
                    status_code=400,
                    detail="No shared annotation found for this dataset",
                )
        else:
            overlay = resolved["draft_annotations"]
        annotations = {
            wsi_id: deepcopy(regions)
            for wsi_id, regions in resolved["gt_annotations"].items()
        }
        for wsi_id, regions in overlay.items():
            if wsi_id in valid_wsi_ids:
                annotations[wsi_id] = (
                    deepcopy(regions) if isinstance(regions, list) else []
                )
    elif annotations is None and req.annotation_id:
        annotation = await SegmentationAnnotationRepository.get(
            db, req.annotation_id, user_id
        )
        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if annotation.source_dataset_id:
            dataset = await _get_dataset_with_access(
                annotation.source_dataset_id, user, db
            )
            _require_personal_annotation_owner(dataset, user)
        annotations = annotation.annotations
    if not annotations:
        raise HTTPException(status_code=400, detail="No annotations provided")

    # --- 2. Validate WSI access for every referenced slide ---
    wsi_ids = list(annotations.keys())
    for wsi_id in wsi_ids:
        await get_wsi_with_access(
            wsi_id,
            user,
            db,
            with_dataset=True,
            not_found_detail=f"WSI not found: {wsi_id}",
            forbidden_detail=f"No access to WSI: {wsi_id}",
        )

    # --- 3. Build region map & proxy to preprocessing ---
    task_id = f"annot_{uuid.uuid4().hex[:12]}"

    # Convert annotations dict to the format expected by preprocessing:
    # { wsi_id: [{ type, x, y, width, height, label, points }, ...] }
    regions: dict[str, Any] = {}
    for wsi_id, roi_list in annotations.items():
        regions[wsi_id] = [
            {
                "type": roi.get("type", "rect"),
                "x": int(round(roi["x"])),
                "y": int(round(roi["y"])),
                "width": int(round(roi["width"])),
                "height": int(round(roi["height"])),
                "label": roi.get("label", "unlabeled"),
                "points": _normalize_polygon_points(roi.get("points")),
            }
            for roi in roi_list
        ]

    payload = {
        "regions": regions,
        "dataset_name": req.dataset_name,
        "task_type": req.task_type,
        "user_id": user_id,
        "task_id": task_id,
    }
    if req.source_dataset_id:
        payload["source_dataset_id"] = req.source_dataset_id
        payload["parent_dataset_id"] = req.source_dataset_id
        from backend.database.repositories import DatasetRepository

        parent_dataset = await DatasetRepository.get_by_id(db, req.source_dataset_id)
        if parent_dataset:
            payload["is_public"] = bool(parent_dataset.is_public)
    if req.source_organ:
        payload["source_organ"] = req.source_organ

    await request_preprocessing_service(
        "POST",
        "/annotation/extract_regions",
        json_body=payload,
        timeout=30.0,
    )

    await set_task_owner(task_id, user_id)

    if req.source_dataset_id:
        try:
            await AnnotationAuditLogRepository.log(
                db,
                req.source_dataset_id,
                user_id,
                "promoted_to_training_reference",
                {
                    "task_id": task_id,
                    "annotation_mode": req.annotation_mode or "personal",
                    "dataset_name": req.dataset_name,
                },
            )
            await db.commit()
        except Exception as audit_err:
            logger.warning(
                f"Failed to write promoted_to_training_reference audit: {audit_err}"
            )

    return {"task_id": task_id, "status": "started"}


# ── SSE progress stream ─────────────────────────────────────────────────────


@router.get("/extract/{task_id}/stream")
async def stream_extract_progress(
    task_id: str,
    user: User = Depends(get_user_from_token_param),
):
    owner_id = await get_task_owner(task_id)
    if owner_id is not None and owner_id != str(user.id) and not user.is_admin():
        raise HTTPException(
            status_code=403, detail="You don't have access to this task"
        )

    async def event_generator():
        try:
            last_progress = None
            while True:
                progress = await get_progress(task_id)

                if progress != last_progress:
                    yield f"data: {json.dumps({'task_id': task_id, 'progress': progress})}\n\n"
                    last_progress = progress

                if progress is not None and (progress >= 100 or progress < 0):
                    break

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


# ── Shared Draft (collaborative annotation) ──────────────────────────────────


def _preserve_created_by(
    existing_annotations: dict[str, Any],
    incoming_annotations: dict[str, Any],
) -> dict[str, Any]:
    existing_by_id: dict[str, Any] = {
        r["id"]: r.get("created_by")
        for regions in existing_annotations.values()
        if isinstance(regions, list)
        for r in regions
        if isinstance(r, dict) and "id" in r
    }
    for regions in incoming_annotations.values():
        if not isinstance(regions, list):
            continue
        for region in regions:
            if isinstance(region, dict) and region.get("id") in existing_by_id:
                region["created_by"] = existing_by_id[region["id"]]
    return incoming_annotations


@router.get("/datasets/{dataset_id}/shared")
async def get_shared_annotation(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not await can_access_shared(user, dataset, db):
        raise HTTPException(status_code=403, detail="Access denied")

    shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
    if shared:
        return {
            "annotation_id": shared.annotation_id,
            "annotations": shared.annotations,
            "version": shared.version,
            "last_edited_by": shared.last_edited_by,
            "updated_at": shared.updated_at.isoformat() + "Z"
            if shared.updated_at
            else None,
            "is_prepopulated": False,
        }

    gt_annotations, gt_record_count = await _get_dataset_ground_truth_roi_map(
        dataset_id, db
    )
    if gt_record_count > 0:
        return {
            "annotation_id": None,
            "annotations": gt_annotations,
            "version": 0,
            "last_edited_by": None,
            "updated_at": None,
            "is_prepopulated": True,
        }

    return {
        "annotation_id": None,
        "annotations": {},
        "version": 0,
        "last_edited_by": None,
        "updated_at": None,
        "is_prepopulated": False,
    }


@router.put("/datasets/{dataset_id}/shared")
async def save_shared_annotation(
    dataset_id: str,
    req: SharedAnnotationSaveRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not await can_access_shared(user, dataset, db):
        raise HTTPException(status_code=403, detail="Access denied")

    existing = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
    incoming = dict(req.annotations)
    if existing and isinstance(existing.annotations, dict):
        incoming = _preserve_created_by(existing.annotations, incoming)

    force = is_annotation_owner(user, dataset)
    owner_user_id = dataset.user_id or str(user.id)

    try:
        saved = await SegmentationAnnotationRepository.upsert_shared(
            db=db,
            dataset_id=dataset_id,
            owner_user_id=owner_user_id,
            last_edited_by=str(user.id),
            annotations=incoming,
            expected_version=req.version,
            force=force,
        )
        await AnnotationAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            "shared_write",
            {
                "version": saved.version,
                "region_count": sum(
                    len(v) for v in saved.annotations.values() if isinstance(v, list)
                )
                if isinstance(saved.annotations, dict)
                else 0,
            },
        )
        await db.commit()
    except VersionConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"error": "version_conflict", "current_version": e.current_version},
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to save shared annotation for dataset {dataset_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    asyncio.create_task(
        publish(
            dataset_id,
            {
                "type": "updated",
                "version": saved.version,
                "changed_by": str(user.id),
                "annotations": saved.annotations,
            },
        )
    )

    return {
        "annotation_id": saved.annotation_id,
        "version": saved.version,
        "updated_at": saved.updated_at.isoformat() + "Z" if saved.updated_at else None,
    }


@router.delete("/datasets/{dataset_id}/shared")
async def delete_shared_annotation(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(
            status_code=403, detail="Only owner or admin can delete shared annotation"
        )

    shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
    region_count = (
        sum(len(v) for v in shared.annotations.values() if isinstance(v, list))
        if shared and isinstance(shared.annotations, dict)
        else 0
    )

    deleted = await SegmentationAnnotationRepository.delete_shared(db, dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Shared annotation not found")

    await db.commit()
    asyncio.create_task(publish(dataset_id, {"type": "shared_deleted"}))

    return {"ok": True, "deleted_regions": region_count}


@router.post("/datasets/{dataset_id}/shared/finalize")
async def finalize_shared_annotation(
    dataset_id: str,
    req: SharedAnnotationFinalizeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(status_code=403, detail="Only owner or admin can finalize")

    shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
    annotations = (
        shared.annotations if shared and isinstance(shared.annotations, dict) else {}
    )

    total_regions = sum(len(v) for v in annotations.values() if isinstance(v, list))
    if total_regions == 0 and not req.force:
        raise HTTPException(status_code=422, detail="empty_annotation")

    gt_annotation_id = f"annot_{dataset_id}"
    owner_user_id = dataset.user_id or str(user.id)

    try:
        gt = await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id=gt_annotation_id,
            user_id=owner_user_id,
            annotations=annotations,
            source_dataset_id=dataset_id,
            status="finalized",
            annotation_mode="personal",
            source="viewer",
        )

        await SegmentationAnnotationRepository.delete_shared(db, dataset_id)
        await AnnotationAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            "finalize",
            {
                "version": shared.version if shared else 0,
                "gt_annotation_id": gt_annotation_id,
                "region_count": total_regions,
            },
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to finalize shared annotation for dataset {dataset_id}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))

    try:
        await rebuild_draft_annotation_summary_cache(
            db, gt_annotation_id, owner_user_id, dataset_id
        )
    except Exception as cache_err:
        logger.warning(
            f"Failed to rebuild annotation summary cache after finalize: {cache_err}"
        )

    asyncio.create_task(
        publish(
            dataset_id,
            {
                "type": "finalized",
                "gt_annotation_id": gt_annotation_id,
            },
        )
    )

    return {
        "gt_annotation_id": gt_annotation_id,
        "version": gt.version if gt else 1,
        "region_count": total_regions,
    }


@router.post("/datasets/{dataset_id}/shared/regions/bulk-delete")
async def bulk_delete_shared_regions_by_creator(
    dataset_id: str,
    req: BulkDeleteRegionsByCreatorRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(
            status_code=403, detail="Only owner or admin can bulk-delete regions"
        )

    try:
        deleted_count = (
            await SegmentationAnnotationRepository.bulk_delete_regions_by_creator(
                db, dataset_id, req.user_id
            )
        )
        await AnnotationAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            "bulk_delete",
            {"target_user_id": req.user_id, "deleted_count": deleted_count},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    if deleted_count > 0:
        shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
        await publish(
            dataset_id,
            {
                "type": "updated",
                "version": shared.version if shared else 0,
                "changed_by": str(user.id),
                "annotations": shared.annotations if shared else {},
            },
        )

    return {"deleted_count": deleted_count}


# ── Collaborator Management ───────────────────────────────────────────────────


@router.get("/datasets/{dataset_id}/collaborators")
async def list_collaborators(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as sa_select
    from backend.auth.models import User as UserModel

    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not await can_access_shared(user, dataset, db):
        raise HTTPException(status_code=403, detail="Access denied")

    all_grants = await DatasetGrantRepository.get_by_dataset(db, dataset_id)
    collab_grants = [g for g in all_grants if g.can_collaborate and g.is_valid()]
    collab_user_ids = [g.user_id for g in collab_grants]

    admins = []
    explicit_members = []

    if collab_user_ids:
        rows = await db.execute(
            sa_select(
                UserModel.id, UserModel.email, UserModel.nickname, UserModel.role
            ).where(UserModel.id.in_([uuid.UUID(uid) for uid in collab_user_ids]))
        )
        user_map = {
            str(r[0]): {"email": r[1], "nickname": r[2], "role": r[3]}
            for r in rows.all()
        }
    else:
        user_map = {}

    admin_rows = await db.execute(
        sa_select(
            UserModel.id, UserModel.email, UserModel.nickname, UserModel.role
        ).where(UserModel.role == UserModel.ROLE_ADMIN)
    )
    for row in admin_rows.all():
        admins.append(
            {
                "user_id": str(row[0]),
                "email": row[1],
                "nickname": row[2],
                "role": "implicit_admin",
            }
        )

    owner_info = None
    if dataset.user_id:
        owner_row = await db.execute(
            sa_select(UserModel.email, UserModel.nickname, UserModel.role).where(
                UserModel.id == uuid.UUID(dataset.user_id)
            )
        )
        owner_data = owner_row.first()
        if owner_data:
            owner_info = {
                "user_id": dataset.user_id,
                "email": owner_data[0],
                "nickname": owner_data[1],
                "role": "owner",
            }

    for g in collab_grants:
        info = user_map.get(g.user_id, {})
        explicit_members.append(
            {
                "user_id": g.user_id,
                "email": info.get("email"),
                "nickname": info.get("nickname"),
                "role": "collaborator",
                "added_by": g.granted_by,
                "created_at": g.created_at.isoformat() + "Z" if g.created_at else None,
            }
        )

    members = []
    if owner_info:
        members.append(owner_info)
    members.extend(admins)
    members.extend(explicit_members)

    return {"dataset_id": dataset_id, "members": members}


@router.post("/datasets/{dataset_id}/collaborators")
async def add_collaborator(
    dataset_id: str,
    req: AddCollaboratorRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as sa_select
    from backend.auth.models import User as UserModel

    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(
            status_code=403, detail="Only owner or admin can add collaborators"
        )

    target_row = await db.execute(
        sa_select(UserModel.role).where(UserModel.id == uuid.UUID(req.user_id))
    )
    target = target_row.first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target[0] == UserModel.ROLE_ADMIN:
        raise HTTPException(status_code=409, detail="admin users have implicit access")

    if not user.is_admin() and target[0] == UserModel.ROLE_ADMIN:
        raise HTTPException(
            status_code=403, detail="Cannot add admin as explicit collaborator"
        )

    existing = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, req.user_id
    )
    if existing and existing.can_collaborate:
        raise HTTPException(status_code=409, detail="User is already a collaborator")

    try:
        if existing:
            existing.can_collaborate = True
            await db.flush()
            grant = existing
        else:
            grant = await DatasetGrantRepository.create(
                db, dataset_id, req.user_id, str(user.id), can_collaborate=True
            )
        await AnnotationAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            "collaborator_add",
            {"target_user_id": req.user_id},
        )
        await PermissionAuditLogRepository.log(
            db, dataset_id, str(user.id), req.user_id, "grant_collaborate", {}
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {"collaborator": grant.to_dict()}


@router.delete("/datasets/{dataset_id}/collaborators/{target_user_id}")
async def remove_collaborator(
    dataset_id: str,
    target_user_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(
            status_code=403, detail="Only owner or admin can remove collaborators"
        )

    if dataset.user_id and target_user_id == dataset.user_id:
        raise HTTPException(status_code=400, detail="cannot remove dataset owner")

    shared = await SegmentationAnnotationRepository.get_shared_draft(db, dataset_id)
    residual_count = 0
    if shared and isinstance(shared.annotations, dict):
        for regions in shared.annotations.values():
            if isinstance(regions, list):
                residual_count += sum(
                    1
                    for r in regions
                    if isinstance(r, dict) and r.get("created_by") == target_user_id
                )

    grant = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, target_user_id
    )
    if not grant or not grant.can_collaborate:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    if grant.can_use_gpu:
        grant.can_collaborate = False
        await db.flush()
    else:
        await DatasetGrantRepository.delete(db, dataset_id, target_user_id)

    child_ids = await DatasetRepository.get_child_dataset_ids(db, [dataset_id])
    for child_id in child_ids:
        child_grant = await DatasetGrantRepository.get_by_dataset_and_user(
            db, child_id, target_user_id
        )
        if not child_grant:
            continue
        if child_grant.can_use_gpu:
            child_grant.can_collaborate = False
            await db.flush()
        else:
            await DatasetGrantRepository.delete(db, child_id, target_user_id)
        await PermissionAuditLogRepository.log(
            db, child_id, str(user.id), target_user_id, "revoke_collaborate_cascade", {}
        )

    await AnnotationAuditLogRepository.log(
        db,
        dataset_id,
        str(user.id),
        "collaborator_remove",
        {"target_user_id": target_user_id, "residual_region_count": residual_count},
    )
    await PermissionAuditLogRepository.log(
        db, dataset_id, str(user.id), target_user_id, "revoke_collaborate", {}
    )
    await db.commit()
    asyncio.create_task(
        publish(dataset_id, {"type": "collaborator_removed", "user_id": target_user_id})
    )
    asyncio.create_task(
        publish(dataset_id, {"type": "access_revoked", "user_id": target_user_id})
    )
    asyncio.create_task(
        publish_presence(
            dataset_id, {"type": "force_disconnect", "user_id": target_user_id}
        )
    )

    return {"ok": True, "residual_region_count": residual_count}


# ── Ground-Truth DELETE ───────────────────────────────────────────────────────


@router.delete("/datasets/{dataset_id}/labels")
async def delete_dataset_ground_truth(
    dataset_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as sa_select, delete as sa_delete
    from backend.database.models import TrainingTask, SegmentationAnnotation as SAModel

    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not can_finalize(user, dataset):
        raise HTTPException(
            status_code=403, detail="Only owner or admin can delete ground truth"
        )

    active_statuses = ["pending", "patching", "extracting", "training", "resuming"]
    active_tasks = await db.execute(
        sa_select(TrainingTask.task_id).where(TrainingTask.status.in_(active_statuses))
    )
    if active_tasks.first():
        raise HTTPException(
            status_code=400,
            detail="active training tasks exist – wait for them to complete before deleting GT",
        )

    result = await db.execute(
        sa_delete(SAModel).where(SAModel.annotation_id == f"annot_{dataset_id}")
    )
    await db.flush()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Ground truth not found")

    await db.commit()

    try:
        await rebuild_draft_annotation_summary_cache(
            db, f"annot_{dataset_id}", dataset.user_id or "", dataset_id
        )
    except Exception:
        pass

    await publish(dataset_id, {"type": "gt_deleted"})
    return {"ok": True}


# ── Annotation Audit Log ──────────────────────────────────────────────────────


@router.get("/audit")
async def list_annotation_audit(
    dataset_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin only")

    from sqlalchemy import select as sa_select
    from backend.auth.models import User as UserModel
    from backend.database.models import Dataset

    entries, total = await asyncio.gather(
        AnnotationAuditLogRepository.list_entries(
            db, dataset_id=dataset_id, event_type=event_type, limit=limit, offset=offset
        ),
        AnnotationAuditLogRepository.count_entries(
            db, dataset_id=dataset_id, event_type=event_type
        ),
    )

    user_ids = set()
    dataset_ids = set()
    for e in entries:
        if e.user_id:
            user_ids.add(e.user_id)
        if e.dataset_id:
            dataset_ids.add(e.dataset_id)
        if isinstance(e.event_metadata, dict):
            if tid := e.event_metadata.get("target_user_id"):
                user_ids.add(tid)

    user_display: dict[str, str] = {}
    if user_ids:
        rows = await db.execute(
            sa_select(UserModel.id, UserModel.nickname, UserModel.email).where(
                UserModel.id.in_([uuid.UUID(uid) for uid in user_ids])
            )
        )
        for row in rows.all():
            user_display[str(row[0])] = row[1] or row[2] or str(row[0])

    dataset_name: dict[str, str] = {}
    if dataset_ids:
        rows = await db.execute(
            sa_select(Dataset.dataset_id, Dataset.name).where(
                Dataset.dataset_id.in_(list(dataset_ids))
            )
        )
        for row in rows.all():
            dataset_name[row[0]] = row[1] or row[0]

    def _enrich(e) -> dict:
        d = e.to_dict()
        d["user_display"] = user_display.get(e.user_id) if e.user_id else None
        d["dataset_name"] = dataset_name.get(e.dataset_id)
        if (
            isinstance(d.get("event_metadata"), dict)
            and "target_user_id" in d["event_metadata"]
        ):
            tid = d["event_metadata"]["target_user_id"]
            d["event_metadata"] = {
                **d["event_metadata"],
                "target_user_display": user_display.get(tid, tid),
            }
        return d

    return {"entries": [_enrich(e) for e in entries], "count": total}


@router.get("/audit/export")
async def export_annotation_audit_csv(
    dataset_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin only")

    entries = await AnnotationAuditLogRepository.list_entries(
        db, dataset_id=dataset_id, event_type=event_type, limit=5000, offset=0
    )

    import io
    import csv as _csv

    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(
        ["id", "dataset_id", "user_id", "event_type", "event_metadata", "created_at"]
    )
    for e in entries:
        writer.writerow(
            [
                e.id,
                e.dataset_id,
                e.user_id or "",
                e.event_type,
                json.dumps(e.event_metadata, ensure_ascii=False),
                e.created_at.isoformat() + "Z" if e.created_at else "",
            ]
        )

    csv_bytes = buf.getvalue().encode("utf-8-sig")

    from fastapi.responses import Response

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="annotation_audit.csv"'},
    )


# ── Shared Draft SSE Stream ───────────────────────────────────────────────────


@router.get("/datasets/{dataset_id}/shared/stream")
async def stream_shared_annotation(
    dataset_id: str,
    user: User = Depends(get_user_from_token_param),
    db: AsyncSession = Depends(get_db),
):
    dataset = await _get_dataset_with_access(dataset_id, user, db)
    if not await can_access_shared(user, dataset, db):
        raise HTTPException(status_code=403, detail="Access denied")

    async def event_generator():
        try:
            async for raw in subscribe_iter(dataset_id):
                try:
                    msg_data = json.loads(raw)
                except Exception:
                    yield f"data: {raw}\n\n"
                    continue
                if msg_data.get("type") == "access_revoked" and msg_data.get(
                    "user_id"
                ) == str(user.id):
                    yield f"data: {raw}\n\n"
                    return
                yield f"data: {raw}\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE shared annotation client disconnected: {dataset_id}")
        except Exception as exc:
            logger.warning(f"SSE shared annotation error for {dataset_id}: {exc}")

    async def keepalive_generator():
        import json as _json

        keepalive = _json.dumps({"type": "keepalive"})
        while True:
            await asyncio.sleep(30)
            yield f"data: {keepalive}\n\n"

    async def merged():
        import asyncio as _asyncio

        event_gen = event_generator().__aiter__()
        keepalive_gen = keepalive_generator().__aiter__()

        event_task = _asyncio.ensure_future(event_gen.__anext__())
        keepalive_task = _asyncio.ensure_future(keepalive_gen.__anext__())

        try:
            while True:
                done, _ = await _asyncio.wait(
                    [event_task, keepalive_task],
                    return_when=_asyncio.FIRST_COMPLETED,
                )
                for t in done:
                    try:
                        yield t.result()
                        if t is event_task:
                            event_task = _asyncio.ensure_future(event_gen.__anext__())
                        else:
                            keepalive_task = _asyncio.ensure_future(
                                keepalive_gen.__anext__()
                            )
                    except StopAsyncIteration:
                        return
        except asyncio.CancelledError:
            pass
        finally:
            event_task.cancel()
            keepalive_task.cancel()

    return StreamingResponse(
        merged(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Cursor Presence WebSocket ─────────────────────────────────────────────────


@router.websocket("/datasets/{dataset_id}/presence")
async def presence_websocket(
    websocket: WebSocket,
    dataset_id: str,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from backend.auth.dependencies import _get_user_from_jwt

    if not token:
        await websocket.close(code=4001)
        return

    try:
        user = await _get_user_from_jwt(token, db)
    except Exception:
        await websocket.close(code=4001)
        return

    try:
        dataset = await _get_dataset_with_access(dataset_id, user, db)
    except HTTPException:
        await websocket.close(code=4003)
        return

    if not await can_access_shared(user, dataset, db):
        await websocket.close(code=4003)
        return

    await websocket.accept()

    user_id = str(user.id)
    nickname = user.nickname or user.email or user_id

    await publish_presence(
        dataset_id, {"type": "join", "user_id": user_id, "nickname": nickname}
    )

    async def ws_to_redis():
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except Exception:
                    continue
                if msg.get("type") == "cursor":
                    await publish_presence(
                        dataset_id,
                        {
                            "type": "cursor",
                            "user_id": user_id,
                            "nickname": nickname,
                            "wsi_id": msg.get("wsi_id", ""),
                            "x": float(msg.get("x", 0)),
                            "y": float(msg.get("y", 0)),
                        },
                    )
                elif msg.get("type") == "annotation_patch":
                    op = msg.get("op")
                    if op not in ("add", "update", "delete"):
                        continue
                    patch: dict = {
                        "type": "annotation_patch",
                        "user_id": user_id,
                        "wsi_id": msg.get("wsi_id", ""),
                        "op": op,
                    }
                    if op == "add" and isinstance(msg.get("region"), dict):
                        patch["region"] = msg["region"]
                    elif (
                        op == "update"
                        and isinstance(msg.get("region_id"), str)
                        and isinstance(msg.get("region_updates"), dict)
                    ):
                        patch["region_id"] = msg["region_id"]
                        patch["region_updates"] = msg["region_updates"]
                    elif op == "delete" and isinstance(msg.get("region_id"), str):
                        patch["region_id"] = msg["region_id"]
                    else:
                        continue
                    await publish_presence(dataset_id, patch)
        except (WebSocketDisconnect, Exception):
            pass

    async def redis_to_ws():
        try:
            async for raw in subscribe_presence_iter(dataset_id):
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if (
                    msg.get("type") == "force_disconnect"
                    and msg.get("user_id") == user_id
                ):
                    await websocket.close(code=4003)
                    return
                if msg.get("user_id") == user_id:
                    continue
                try:
                    await websocket.send_text(raw)
                except Exception:
                    break
        except Exception:
            pass

    ws_task = asyncio.ensure_future(ws_to_redis())
    redis_task = asyncio.ensure_future(redis_to_ws())

    try:
        await asyncio.wait([ws_task, redis_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        ws_task.cancel()
        redis_task.cancel()
        await publish_presence(
            dataset_id, {"type": "leave", "user_id": user_id, "nickname": nickname}
        )
