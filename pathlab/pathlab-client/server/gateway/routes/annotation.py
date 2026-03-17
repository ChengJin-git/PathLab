from typing import Any

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
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageColor, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    SegmentationAnnotationRepository,
    WSIRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import (
    get_dataset_with_access,
    get_user_from_token_param,
    get_wsi_with_access,
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
from backend.common.progress_store import get_progress
from ..dependencies import logger
from ..models import (
    AnnotationSaveRequest,
    AnnotationExtractRequest,
    AnnotationDeleteByLabelsRequest,
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

    elevated_dataset_ids = {wsi.dataset_id} if wsi.dataset_id else None
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
            "width": wsi.width,
            "height": wsi.height,
        },
    )


async def _get_dataset_with_access(dataset_id: str, user: User, db: AsyncSession):
    return await get_dataset_with_access(
        dataset_id,
        user,
        db,
        forbidden_detail="You don't have permission to access this dataset",
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

    for wsi_id, regions in draft_annotations.items():
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
    }


# ── Annotation CRUD ──────────────────────────────────────────────────────────


@router.post("/drafts")
async def save_annotation(
    req: AnnotationSaveRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a segmentation annotation (auto-save)."""
    try:
        if req.source_dataset_id:
            await _get_dataset_with_access(req.source_dataset_id, user, db)

        annotation = await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id=req.annotation_id,
            user_id=str(user.id),
            annotations=req.annotations,
            source_dataset_id=req.source_dataset_id,
        )
        await db.commit()

        if req.source_dataset_id:
            try:
                wsis = await _get_dataset_wsis(req.source_dataset_id, db)
                draft_cache = build_draft_annotation_summary_cache(
                    annotation_id=req.annotation_id,
                    dataset_id=req.source_dataset_id,
                    user_id=str(user.id),
                    annotations=req.annotations
                    if isinstance(req.annotations, dict)
                    else {},
                    wsis=wsis,
                    draft_updated_at=annotation.updated_at.isoformat()
                    if annotation.updated_at
                    else None,
                )
                save_draft_annotation_summary_cache(req.annotation_id, draft_cache)
            except Exception as cache_err:
                logger.warning(
                    f"Failed to refresh draft annotation summary cache for {req.annotation_id}: {cache_err}"
                )

        return annotation.to_dict()
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


@router.get("/datasets/{dataset_id}/ground-truth")
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
        }

    return {
        "dataset_id": dataset_id,
        "annotations": merged_annotations,
        "record_count": used_record_count,
        "source": "ground_truth",
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
    return {
        "dataset_id": dataset_id,
        **draft_summary,
        "source": "effective_dataset",
        "annotation_id": annotation_id,
    }


@router.get("/wsi/{wsi_id}/ground-truth")
async def get_wsi_ground_truth_annotations(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return GT for a single WSI/patch, avoiding whole-dataset conversion."""
    _, _, payload = await _resolve_wsi_ground_truth_payload(wsi_id, user, db)
    return payload


@router.get("/wsi/{wsi_id}/ground-truth-thumbnail")
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
    return annotation.to_dict()


@router.delete("/drafts/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an annotation."""
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
            saved_annotation = await SegmentationAnnotationRepository.upsert(
                db,
                annotation_id=annotation_id,
                user_id=str(user.id),
                annotations=next_draft_annotations,
                source_dataset_id=dataset_id,
                status="draft",
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
        resolved = await _resolve_effective_dataset_annotations(
            req.source_dataset_id, user, db
        )
        annotations = resolved["effective_annotations"]
    elif annotations is None and req.annotation_id:
        annotation = await SegmentationAnnotationRepository.get(
            db, req.annotation_id, user_id
        )
        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")
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

    await request_preprocessing_service(
        "POST",
        "/annotation/extract_regions",
        json_body=payload,
        timeout=30.0,
    )

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
