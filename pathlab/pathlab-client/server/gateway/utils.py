"""
Utility functions for Gateway service
"""
from collections import defaultdict
import json
import os
from pathlib import Path
import httpx
from typing import Any, Iterable, Mapping, Optional

from Aslide import Slide
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories import DataGroupRepository, DatasetRepository, StorageTaskRepository
from backend.common.file_types import TIF_EXTENSIONS, is_patch_file, is_patch_file_for_scan
from .dependencies import logger, AI_SERVICE_URL, PREPROCESSING_SERVICE_URL


SEGMENTATION_TASK_TYPE = "segmentation"
SEGMENTATION_DATA_TYPE = "patch"
SEGMENTATION_AGGREGATION_LEVEL = "file"


def is_tiff_family(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() in TIF_EXTENSIONS


def get_file_data_type(file_path: str | Path, file_size: int = 0) -> str:
    return "patch" if is_patch_file(str(file_path), file_size) else "wsi"


def get_scan_file_data_type(file_path: str | Path, file_size: int = 0) -> str:
    return "patch" if is_patch_file_for_scan(str(file_path), file_size) else "wsi"


def infer_dataset_data_type_from_paths(file_paths: Iterable[str | Path]) -> str:
    for file_path in file_paths:
        path_obj = Path(file_path)
        file_size = path_obj.stat().st_size if path_obj.exists() else 0
        if get_file_data_type(path_obj, file_size) == "wsi":
            return "wsi"
    return "patch"


def find_first_path_for_data_type(file_paths: Iterable[str | Path], target_data_type: str) -> Optional[str]:
    for file_path in file_paths:
        path_obj = Path(file_path)
        file_size = path_obj.stat().st_size if path_obj.exists() else 0
        if get_file_data_type(path_obj, file_size) == target_data_type:
            return str(path_obj)
    return None


async def align_dataset_data_type_for_file(
    db: AsyncSession,
    dataset: Any,
    *,
    file_path: str | Path,
    file_data_type: str,
    task_type: str,
    action: str,
    context: str,
) -> Any:
    data_group = getattr(dataset, "data_group", None)
    if data_group is None:
        raise HTTPException(status_code=400, detail=f"{context}: dataset has no associated DataGroup")

    if data_group.data_type == file_data_type:
        return dataset

    if task_type == SEGMENTATION_TASK_TYPE:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset data_type is '{data_group.data_type}', cannot {action} '{file_data_type}' file",
        )

    if not is_tiff_family(file_path):
        raise HTTPException(
            status_code=400,
            detail=f"Dataset data_type is '{data_group.data_type}', cannot {action} '{file_data_type}' file",
        )

    if data_group.data_type == "patch" and file_data_type == "wsi":
        target_group = await DataGroupRepository.get_or_create(
            db,
            data_type="wsi",
            aggregation_level=data_group.aggregation_level,
            task_type=data_group.task_type,
        )
        dataset.group_id = target_group.group_id
        await db.flush()
        logger.info(
            "Promoted dataset %s to wsi during %s because TIFF/TIFF files contained a WSI",
            dataset.dataset_id,
            context,
        )
        refreshed = await DatasetRepository.get_by_id(db, dataset.dataset_id)
        return refreshed or dataset

    if data_group.data_type == "wsi" and file_data_type == "patch":
        return dataset

    raise HTTPException(
        status_code=400,
        detail=f"Dataset data_type is '{data_group.data_type}', cannot {action} '{file_data_type}' file",
    )


def get_effective_wsi_data_type(wsi: Any) -> str:
    dataset = getattr(wsi, "dataset", None)
    data_group = getattr(dataset, "data_group", None) if dataset else None
    if data_group and data_group.data_type in {"wsi", "patch"}:
        return data_group.data_type
    return get_file_data_type(getattr(wsi, "wsi_path", ""), getattr(wsi, "file_size", 0) or 0)


def ensure_segmentation_contract(
    task_type: Optional[str],
    data_type: Optional[str],
    aggregation_level: Optional[str],
    *,
    context: str,
) -> None:
    """Raise HTTP 400 when a segmentation combination violates the patch/file contract."""
    if task_type != SEGMENTATION_TASK_TYPE:
        return

    if data_type != SEGMENTATION_DATA_TYPE or aggregation_level != SEGMENTATION_AGGREGATION_LEVEL:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{context}: segmentation datasets must use "
                f"data_type='{SEGMENTATION_DATA_TYPE}' and aggregation_level='{SEGMENTATION_AGGREGATION_LEVEL}'"
            ),
        )


def ensure_dataset_segmentation_contract(dataset: Any, *, context: str, expected_task_type: Optional[str] = None) -> Any:
    """Validate a dataset's loaded data_group against the segmentation contract."""
    data_group = getattr(dataset, "data_group", None)
    if data_group is None:
        raise HTTPException(status_code=400, detail=f"{context}: dataset has no associated DataGroup")

    if expected_task_type and data_group.task_type != expected_task_type:
        raise HTTPException(
            status_code=400,
            detail=f"{context}: dataset task_type is '{data_group.task_type}', expected '{expected_task_type}'",
        )

    ensure_segmentation_contract(
        data_group.task_type,
        data_group.data_type,
        data_group.aggregation_level,
        context=context,
    )
    return data_group


def build_segmentation_annotation_index(search_root: str | Path) -> dict[str, list[Path]]:
    """Build a case-insensitive stem -> COCO JSON paths index under a directory tree."""
    root_path = Path(search_root)
    index: dict[str, list[Path]] = defaultdict(list)

    if not root_path.exists():
        return {}

    try:
        if root_path.is_file():
            candidates = [root_path] if root_path.suffix.lower() == '.json' else []
        else:
            candidates = []
            for current_root, _dirs, files in os.walk(root_path):
                for filename in files:
                    candidate = Path(current_root) / filename
                    if candidate.suffix.lower() == '.json':
                        candidates.append(candidate)
    except Exception:
        return {}

    for candidate in candidates:
        index[candidate.stem.lower()].append(candidate)

    return {
        stem: sorted(paths, key=lambda path: str(path).lower())
        for stem, paths in index.items()
    }


def resolve_segmentation_annotation_match(
    image_path: str | Path,
    *,
    annotation_index: Optional[Mapping[str, list[Path]]] = None,
) -> tuple[Optional[Path], Optional[str]]:
    """Resolve a segmentation COCO JSON match for an image, reporting ambiguity when needed."""
    path_obj = Path(image_path)
    image_stem = path_obj.stem.lower()

    if annotation_index is not None:
        raw_candidates = annotation_index.get(image_stem, [])
    else:
        raw_candidates = [
            path_obj.parent / f"{path_obj.stem}.json",
            path_obj.parent / f"{path_obj.stem.lower()}.json",
        ]
        try:
            raw_candidates.extend(
                sibling
                for sibling in path_obj.parent.iterdir()
                if sibling.is_file() and sibling.suffix.lower() == '.json' and sibling.stem.lower() == image_stem
            )
        except Exception:
            return None, None

    unique_candidates: dict[str, Path] = {}
    for candidate in raw_candidates:
        candidate_path = Path(candidate)
        if not candidate_path.exists() or not candidate_path.is_file():
            continue
        if candidate_path.suffix.lower() != '.json' or candidate_path.stem.lower() != image_stem:
            continue
        unique_candidates.setdefault(str(candidate_path).lower(), candidate_path)

    ordered_candidates = sorted(unique_candidates.values(), key=lambda path: str(path).lower())
    if not ordered_candidates:
        return None, None
    if len(ordered_candidates) > 1:
        return None, (
            f"Multiple same-name COCO JSON annotations found for '{path_obj.name}'. "
            "Keep exactly one matching annotation per image stem."
        )
    return ordered_candidates[0], None


def find_matching_segmentation_annotation_path(image_path: str | Path) -> Optional[Path]:
    """Find a same-stem COCO JSON annotation beside an image path."""
    match_path, _error = resolve_segmentation_annotation_match(image_path)
    return match_path


def validate_coco_annotation_payload(payload: Any, *, source_name: str) -> dict:
    """Validate the minimum COCO structure required by PathLab segmentation."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"{source_name}: annotation must be a JSON object")

    missing_keys = [key for key in ("images", "annotations", "categories") if key not in payload]
    if missing_keys:
        raise HTTPException(
            status_code=400,
            detail=f"{source_name}: COCO annotation is missing required keys: {', '.join(missing_keys)}",
        )

    return payload


def load_coco_annotation_bytes(raw_bytes: bytes, *, source_name: str) -> dict:
    """Parse and validate uploaded COCO JSON bytes."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{source_name}: annotation must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{source_name}: invalid JSON annotation") from exc

    return validate_coco_annotation_payload(payload, source_name=source_name)


def load_coco_annotation_file(annotation_path: str | Path) -> dict:
    """Load and validate a COCO JSON annotation from disk."""
    path_obj = Path(annotation_path)
    try:
        payload = json.loads(path_obj.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{path_obj.name}: annotation must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{path_obj.name}: invalid JSON annotation") from exc

    return validate_coco_annotation_payload(payload, source_name=path_obj.name)


async def require_no_active_batch_imports(db: AsyncSession, *, detail: str) -> None:
    """Raise HTTP 400 when a batch import storage task is still running."""
    active_storage_tasks = await StorageTaskRepository.get_active_tasks(db)
    if any(task.task_type == "batch_import" for task in active_storage_tasks):
        raise HTTPException(status_code=400, detail=detail)


async def cancel_ai_service_training(task_id: str) -> None:
    """
    Request AI service to cancel a training task and release GPU.

    Uses fire-and-forget pattern: sends the request and returns immediately
    without waiting for response, since AI service may be blocked by GPU training.
    The cancellation flag is set immediately when the request is received.
    """
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.delete(f"{AI_SERVICE_URL}/api/ai/training/{task_id}")
            logger.info(f"Sent cancellation request to AI service for task {task_id}")
    except httpx.TimeoutException:
        logger.info(f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)")
    except Exception as e:
        logger.warning(f"Failed to send cancellation to AI service for task {task_id}: {e}")


async def request_preprocessing_service(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Send a request to the preprocessing service with shared error handling."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=f"{PREPROCESSING_SERVICE_URL}{path}",
                params=params,
                json=json_body,
            )

        if response.status_code != 200:
            logger.error(
                f"Preprocessing service error for {method.upper()} {path}: {response.text}"
            )
            raise HTTPException(status_code=response.status_code, detail=response.text)

        return response
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.error(
            f"Failed to connect to preprocessing service for {method.upper()} {path}: {e}"
        )
        raise HTTPException(
            status_code=503,
            detail=f"Preprocessing service unavailable: {str(e)}",
        )


async def proxy_preprocessing_json(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: float = 30.0,
) -> Any:
    """Proxy a preprocessing-service request and return parsed JSON."""
    response = await request_preprocessing_service(
        method,
        path,
        params=params,
        json_body=json_body,
        timeout=timeout,
    )
    return response.json()


async def proxy_preprocessing_binary(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: float = 30.0,
    default_media_type: str = "application/octet-stream",
) -> Response:
    """Proxy a preprocessing-service request and return a binary response."""
    response = await request_preprocessing_service(
        method,
        path,
        params=params,
        json_body=json_body,
        timeout=timeout,
    )
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", default_media_type),
    )


def extract_wsi_properties(wsi_path: str) -> dict:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification, file_size.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
        "file_size": 0,
    }

    if not wsi_path or not os.path.exists(wsi_path):
        logger.warning(f"WSI file not found: {wsi_path}")
        return default_props

    # Get file size first - this works even if slide reading fails
    try:
        file_size = os.path.getsize(wsi_path)
    except Exception:
        file_size = 0

    try:
        with Slide(wsi_path) as slide:
            # Extract properties - start with file_size which is already retrieved
            props = {
                "file_size": file_size,
            }

            # 1. MPP (microns per pixel)
            try:
                mpp_value = slide.mpp
                if isinstance(mpp_value, (int, float)):
                    props["mpp"] = float(mpp_value)
                elif isinstance(mpp_value, tuple) and len(mpp_value) >= 2:
                    # If mpp is a tuple (mpp_x, mpp_y), take average
                    props["mpp"] = (float(mpp_value[0]) + float(mpp_value[1])) / 2
                else:
                    props["mpp"] = default_props["mpp"]
            except Exception:
                props["mpp"] = default_props["mpp"]

            # 2. Vendor
            try:
                vendor = slide.properties.get('openslide.vendor', 'Unknown')
                props["vendor"] = vendor if vendor else "Unknown"
            except Exception:
                props["vendor"] = default_props["vendor"]

            # 3. Width and Height (from level 0 dimensions)
            try:
                width, height = slide.dimensions
                props["width"] = int(width)
                props["height"] = int(height)
            except Exception:
                props["width"] = default_props["width"]
                props["height"] = default_props["height"]

            # 4. Magnification (objective power)
            try:
                mag = slide.properties.get('openslide.objective-power')
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except Exception:
                props["magnification"] = default_props["magnification"]

            logger.info(f"✓ Extracted properties from {os.path.basename(wsi_path)}: "
                       f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                       f"size={props['width']}x{props['height']}, mag={props['magnification']}x, "
                       f"file_size={props['file_size']} bytes")

            return props

    except Exception as e:
        logger.error(f"Failed to read WSI properties from {wsi_path}: {e}")
        # Still return file_size even if slide reading failed
        default_props["file_size"] = file_size
        return default_props

