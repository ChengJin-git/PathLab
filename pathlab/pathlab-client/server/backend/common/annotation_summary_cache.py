"""Dataset annotation summary cache helpers."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from backend.common.config import Config
from backend.common.coco_utils import coco_to_roi_annotations
from backend.common.file_types import is_patch_file


CACHE_VERSION = 2


def _to_isoformat(value) -> Optional[str]:
    return value.isoformat() if value else None


def _latest_updated_at_iso(items: Iterable) -> Optional[str]:
    latest_value = max((getattr(item, "updated_at", None) for item in items), default=None)
    return _to_isoformat(latest_value)


def _build_cache_key(finalized_annotations_key: dict, wsi_key: dict) -> dict:
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


def load_dataset_annotation_summary_cache(dataset_id: str) -> Optional[dict]:
    path = get_dataset_annotation_summary_cache_path(dataset_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_draft_annotation_summary_cache(annotation_id: str) -> Optional[dict]:
    path = get_draft_annotation_summary_cache_path(annotation_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_dataset_annotation_summary_cache(dataset_id: str, cache_data: dict) -> None:
    path = get_dataset_annotation_summary_cache_path(dataset_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def save_draft_annotation_summary_cache(annotation_id: str, cache_data: dict) -> None:
    path = get_draft_annotation_summary_cache_path(annotation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def is_dataset_annotation_summary_cache_valid(
    cache_data: Optional[dict],
    finalized_annotations_key: dict,
    wsi_key: dict,
) -> bool:
    if not cache_data or not isinstance(cache_data, dict):
        return False
    return cache_data.get("cache_key") == _build_cache_key(finalized_annotations_key, wsi_key)


def _build_draft_cache_key(annotation_id: str, draft_updated_at: Optional[str], wsi_key: dict) -> dict:
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
    cache_data: Optional[dict],
    annotation_id: str,
    draft_updated_at: Optional[str],
    wsi_key: dict,
) -> bool:
    if not cache_data or not isinstance(cache_data, dict):
        return False
    return cache_data.get("cache_key") == _build_draft_cache_key(annotation_id, draft_updated_at, wsi_key)


def _build_dataset_wsi_lookups(wsis: Iterable) -> tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_lookup: Dict[str, str] = {}
    for wsi in wsis:
        file_name = Path(str(getattr(wsi, "wsi_path", "") or "")).name
        if not file_name:
            continue
        exact_lookup[file_name] = wsi.wsi_id
        stem_lookup[Path(file_name).stem] = wsi.wsi_id
    return exact_lookup, stem_lookup


def _build_slide_summary_from_regions(regions, is_wsi_source: bool) -> dict:
    labels = {}
    total_regions = 0
    for region in regions if isinstance(regions, list) else []:
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


def _aggregate_slide_summaries(slide_summaries: Dict[str, dict]) -> dict:
    labels = {}
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

        for label, data in (slide.get("labels") or {}).items():
            entry = labels.setdefault(label, {"total_regions": 0, "total_slides": 0, "color": data.get("color")})
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
    annotations: Dict[str, list],
    wsis: Iterable,
    finalized_annotations_key: Optional[dict] = None,
    wsi_key: Optional[dict] = None,
) -> dict:
    wsis = list(wsis)
    wsi_source_map = {
        wsi.wsi_id: not is_patch_file(str(getattr(wsi, "wsi_path", "") or ""), getattr(wsi, "file_size", 0) or 0)
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
    annotations: Dict[str, list],
    wsis: Iterable,
    draft_updated_at: Optional[str] = None,
    wsi_key: Optional[dict] = None,
) -> dict:
    wsis = list(wsis)
    wsi_source_map = {
        wsi.wsi_id: not is_patch_file(str(getattr(wsi, "wsi_path", "") or ""), getattr(wsi, "file_size", 0) or 0)
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
    gt_cache: Optional[dict],
    draft_slide_summaries: Optional[Dict[str, dict]],
    annotation_id: Optional[str] = None,
) -> dict:
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


async def rebuild_dataset_annotation_summary_cache(db, dataset_id: str) -> dict:
    from backend.database.repositories import SegmentationAnnotationRepository, WSIRepository

    wsis = await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)
    merged_annotations = {}

    gt_records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db, dataset_id, include_drafts=False
    )
    if gt_records and wsis:
        dataset_level_record = next(
            (record for record in gt_records if record.annotation_id == f"annot_{dataset_id}"),
            None,
        )
        records_to_use = [dataset_level_record] if dataset_level_record else gt_records
        exact_lookup, stem_lookup = _build_dataset_wsi_lookups(wsis)

        for record in records_to_use:
            roi_map = coco_to_roi_annotations(
                record.annotations,
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
    db,
    annotation_id: str,
    user_id: str,
    dataset_id: str,
) -> Optional[dict]:
    from backend.database.repositories import SegmentationAnnotationRepository, WSIRepository

    draft_annotation = await SegmentationAnnotationRepository.get(db, annotation_id, user_id)
    if not draft_annotation:
        return None

    wsis = await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)
    cache_data = build_draft_annotation_summary_cache(
        annotation_id=annotation_id,
        dataset_id=dataset_id,
        user_id=user_id,
        annotations=draft_annotation.annotations if isinstance(draft_annotation.annotations, dict) else {},
        wsis=wsis,
        draft_updated_at=_to_isoformat(draft_annotation.updated_at),
    )
    save_draft_annotation_summary_cache(annotation_id, cache_data)
    return cache_data