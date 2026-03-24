"""Dataset annotation summary cache helpers."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from backend.common.config import Config
from .coco_utils import coco_to_roi_annotations
from backend.common.file_types import is_patch_file


CACHE_VERSION = (
    3  # bumped: wsi lookup now includes original_filename (fixes uuid-path mismatch)
)


def _to_isoformat(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def _latest_updated_at_iso(items: Iterable[Any]) -> Optional[str]:
    latest_value: datetime | None = None
    for item in items:
        updated_at = getattr(item, "updated_at", None)
        if not isinstance(updated_at, datetime):
            continue
        if latest_value is None or updated_at > latest_value:
            latest_value = updated_at
    return _to_isoformat(latest_value)


def _build_cache_key(
    finalized_annotations_key: dict[str, Any],
    wsi_key: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "finalized_annotations": {
            "count": int(finalized_annotations_key.get("count") or 0),
            "latest_updated_at": finalized_annotations_key.get("latest_updated_at"),
        },
        "wsis": {
            "count": int(wsi_key.get("count") or 0),
            "latest_updated_at": wsi_key.get("latest_updated_at"),
        },
    }


def _cache_dir() -> Path:
    path = Config.get_uploads_dir() / "metadata" / "annotation_summaries"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_dataset_annotation_summary_cache_path(dataset_id: str) -> Path:
    return _cache_dir() / f"{dataset_id}.json"


def get_draft_annotation_summary_cache_path(annotation_id: str) -> Path:
    return _cache_dir() / "drafts" / f"{annotation_id}.json"


def load_dataset_annotation_summary_cache(dataset_id: str) -> Optional[dict[str, Any]]:
    path = get_dataset_annotation_summary_cache_path(dataset_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_draft_annotation_summary_cache(annotation_id: str) -> Optional[dict[str, Any]]:
    path = get_draft_annotation_summary_cache_path(annotation_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_dataset_annotation_summary_cache(
    dataset_id: str, cache_data: dict[str, Any]
) -> None:
    path = get_dataset_annotation_summary_cache_path(dataset_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def save_draft_annotation_summary_cache(
    annotation_id: str, cache_data: dict[str, Any]
) -> None:
    path = get_draft_annotation_summary_cache_path(annotation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def is_dataset_annotation_summary_cache_valid(
    cache_data: Optional[dict[str, Any]],
    finalized_annotations_key: dict[str, Any],
    wsi_key: dict[str, Any],
) -> bool:
    if not cache_data or not isinstance(cache_data, dict):
        return False
    return cache_data.get("cache_key") == _build_cache_key(
        finalized_annotations_key, wsi_key
    )


def _build_draft_cache_key(
    annotation_id: str,
    draft_updated_at: Optional[str],
    wsi_key: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "annotation_id": annotation_id,
        "draft_updated_at": draft_updated_at,
        "wsis": {
            "count": int(wsi_key.get("count") or 0),
            "latest_updated_at": wsi_key.get("latest_updated_at"),
        },
    }


def is_draft_annotation_summary_cache_valid(
    cache_data: Optional[dict[str, Any]],
    annotation_id: str,
    draft_updated_at: Optional[str],
    wsi_key: dict[str, Any],
) -> bool:
    if not cache_data or not isinstance(cache_data, dict):
        return False
    return cache_data.get("cache_key") == _build_draft_cache_key(
        annotation_id, draft_updated_at, wsi_key
    )


def _build_dataset_wsi_lookups(
    wsis: Iterable[Any],
) -> tuple[Dict[str, str], Dict[str, str]]:
    """Build normalized exact/stem filename lookups for COCO file_name → wsi_id matching.

    Candidates are taken from ``original_filename`` first (the name the user uploaded
    and the name referenced by COCO ``images[].file_name``), then from the ``wsi_path``
    basename (which is UUID-based for privacy-protected uploads).  All keys are
    lowercased to match ``_normalize_file_key`` used by ``coco_to_roi_annotations``.
    """
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, set[str]] = {}

    for wsi in wsis:
        candidate_names: set[str] = set()

        # original_filename is the canonical name that COCO file_name references
        original_filename = str(getattr(wsi, "original_filename", "") or "").strip()
        if original_filename:
            name = Path(original_filename).name.strip().lower()
            if name:
                candidate_names.add(name)

        # wsi_path basename as secondary candidate (UUID-based for uploaded files)
        wsi_path_str = str(getattr(wsi, "wsi_path", "") or "").strip()
        if wsi_path_str:
            name = Path(wsi_path_str).name.strip().lower()
            if name:
                candidate_names.add(name)

        for name in candidate_names:
            exact_lookup.setdefault(name, wsi.wsi_id)
            stem = Path(name).stem
            if stem:
                stem_candidates.setdefault(stem, set()).add(wsi.wsi_id)

    # Only keep stems that map unambiguously to a single WSI
    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


def _build_slide_summary_from_regions(
    regions: Any, is_wsi_source: bool
) -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = {}
    total_regions = 0
    for region in regions if isinstance(regions, list) else []:
        if not isinstance(region, dict):
            continue
        label = str(region.get("label") or "unlabeled")
        entry = labels.setdefault(label, {"count": 0, "color": region.get("color")})
        entry["count"] += 1
        total_regions += 1
        if not entry.get("color") and region.get("color"):
            entry["color"] = region.get("color")
    return {
        "total_regions": total_regions,
        "labels": labels,
        "is_wsi_source": bool(is_wsi_source),
    }


def _aggregate_slide_summaries(
    slide_summaries: Dict[str, dict[str, Any]],
) -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = {}
    total_regions = 0
    total_slides = 0
    has_wsi_sources = False

    for slide in slide_summaries.values():
        slide_total = int(slide.get("total_regions") or 0)
        if slide_total <= 0:
            continue

        total_regions += slide_total
        total_slides += 1
        has_wsi_sources = has_wsi_sources or bool(slide.get("is_wsi_source"))

        slide_labels = slide.get("labels")
        if not isinstance(slide_labels, dict):
            continue

        for label, data in slide_labels.items():
            if not isinstance(data, dict):
                continue
            entry = labels.setdefault(
                label,
                {"total_regions": 0, "total_slides": 0, "color": data.get("color")},
            )
            entry["total_regions"] += int(data.get("count") or 0)
            entry["total_slides"] += 1
            if not entry.get("color") and data.get("color"):
                entry["color"] = data.get("color")

    return {
        "total_regions": total_regions,
        "total_slides": total_slides,
        "labels": labels,
        "has_wsi_sources": has_wsi_sources,
    }


def build_dataset_annotation_summary_cache(
    dataset_id: str,
    annotations: Dict[str, list[dict[str, Any]]],
    wsis: Iterable[Any],
    finalized_annotations_key: Optional[dict[str, Any]] = None,
    wsi_key: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    wsis = list(wsis)
    wsi_source_map = {
        wsi.wsi_id: not is_patch_file(
            str(getattr(wsi, "wsi_path", "") or ""), getattr(wsi, "file_size", 0) or 0
        )
        for wsi in wsis
    }
    finalized_annotations_key = finalized_annotations_key or {
        "count": 0,
        "latest_updated_at": None,
    }
    wsi_key = wsi_key or {
        "count": len(wsis),
        "latest_updated_at": _latest_updated_at_iso(wsis),
    }
    slide_summaries = {
        wsi_id: _build_slide_summary_from_regions(regions, wsi_source_map[wsi_id])
        for wsi_id, regions in annotations.items()
        if wsi_id in wsi_source_map
    }
    return {
        "version": CACHE_VERSION,
        "dataset_id": dataset_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_key": _build_cache_key(finalized_annotations_key, wsi_key),
        "summary": _aggregate_slide_summaries(slide_summaries),
        "slides": slide_summaries,
    }


def build_draft_annotation_summary_cache(
    annotation_id: str,
    dataset_id: str,
    user_id: str,
    annotations: Dict[str, list[dict[str, Any]]],
    wsis: Iterable[Any],
    draft_updated_at: Optional[str] = None,
    wsi_key: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    wsis = list(wsis)
    wsi_source_map = {
        wsi.wsi_id: not is_patch_file(
            str(getattr(wsi, "wsi_path", "") or ""), getattr(wsi, "file_size", 0) or 0
        )
        for wsi in wsis
    }
    wsi_key = wsi_key or {
        "count": len(wsis),
        "latest_updated_at": _latest_updated_at_iso(wsis),
    }
    slide_summaries = {
        wsi_id: _build_slide_summary_from_regions(regions, wsi_source_map[wsi_id])
        for wsi_id, regions in (annotations or {}).items()
        if wsi_id in wsi_source_map
    }
    return {
        "version": CACHE_VERSION,
        "annotation_id": annotation_id,
        "dataset_id": dataset_id,
        "user_id": user_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_key": _build_draft_cache_key(annotation_id, draft_updated_at, wsi_key),
        "summary": _aggregate_slide_summaries(slide_summaries),
        "slides": slide_summaries,
    }


def build_effective_summary_from_cache(
    dataset_id: str,
    gt_cache: Optional[dict[str, Any]],
    draft_slide_summaries: Optional[Dict[str, dict[str, Any]]],
    annotation_id: Optional[str] = None,
) -> dict[str, Any]:
    if not gt_cache:
        gt_cache = build_dataset_annotation_summary_cache(dataset_id, {}, [])

    slide_summaries = deepcopy(gt_cache.get("slides") or {})
    for wsi_id, slide_summary in (draft_slide_summaries or {}).items():
        slide_summaries[wsi_id] = deepcopy(slide_summary)

    return {
        "dataset_id": dataset_id,
        **_aggregate_slide_summaries(slide_summaries),
        "source": "effective_dataset",
        "annotation_id": annotation_id,
    }


async def rebuild_dataset_annotation_summary_cache(
    db: Any, dataset_id: str
) -> dict[str, Any]:
    from backend.database.repositories import (
        SegmentationAnnotationRepository,
        WSIRepository,
    )

    wsis = await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)
    merged_annotations: Dict[str, list[dict[str, Any]]] = {}

    gt_records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db, dataset_id, include_drafts=False
    )
    if gt_records and wsis:
        dataset_level_record: Any = None
        target_annotation_id = f"label_{dataset_id}"
        for record in gt_records:
            record_annotation_id = getattr(record, "annotation_id", None)
            if (
                isinstance(record_annotation_id, str)
                and record_annotation_id == target_annotation_id
            ):
                dataset_level_record = record
                break
        records_to_use = [dataset_level_record] if dataset_level_record else gt_records
        exact_lookup, stem_lookup = _build_dataset_wsi_lookups(wsis)

        for record in records_to_use:
            record_annotations = getattr(record, "annotations", {})
            if not isinstance(record_annotations, dict):
                continue
            roi_map = coco_to_roi_annotations(
                record_annotations,
                file_name_to_wsi_id=exact_lookup,
                file_stem_to_wsi_id=stem_lookup,
            )
            for wsi_id, regions in roi_map.items():
                merged_annotations.setdefault(wsi_id, []).extend(regions)

    finalized_annotations_key = {
        "count": len(gt_records),
        "latest_updated_at": _latest_updated_at_iso(gt_records),
    }
    wsi_key = {
        "count": len(wsis),
        "latest_updated_at": _latest_updated_at_iso(wsis),
    }

    cache_data = build_dataset_annotation_summary_cache(
        dataset_id,
        merged_annotations,
        wsis,
        finalized_annotations_key=finalized_annotations_key,
        wsi_key=wsi_key,
    )
    save_dataset_annotation_summary_cache(dataset_id, cache_data)
    return cache_data


async def rebuild_draft_annotation_summary_cache(
    db: Any,
    annotation_id: str,
    user_id: str,
    dataset_id: str,
) -> Optional[dict[str, Any]]:
    from backend.database.repositories import (
        SegmentationAnnotationRepository,
        WSIRepository,
    )

    draft_annotation = await SegmentationAnnotationRepository.get(
        db, annotation_id, user_id
    )
    if not draft_annotation:
        return None

    wsis = await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)
    cache_data = build_draft_annotation_summary_cache(
        annotation_id=annotation_id,
        dataset_id=dataset_id,
        user_id=user_id,
        annotations=draft_annotation.annotations
        if isinstance(draft_annotation.annotations, dict)
        else {},
        wsis=wsis,
        draft_updated_at=_to_isoformat(draft_annotation.updated_at),
    )
    save_draft_annotation_summary_cache(annotation_id, cache_data)
    return cache_data
