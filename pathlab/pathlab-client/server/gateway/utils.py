"""
Utility functions for Gateway service
"""
import json
import os
from pathlib import Path
import httpx
from typing import Any, Mapping, Optional

from Aslide import Slide
from fastapi import HTTPException
from fastapi.responses import Response

from .dependencies import logger, AI_SERVICE_URL, PREPROCESSING_SERVICE_URL


SEGMENTATION_TASK_TYPE = "segmentation"
SEGMENTATION_DATA_TYPE = "patch"
SEGMENTATION_AGGREGATION_LEVEL = "file"


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


def find_matching_segmentation_annotation_path(image_path: str | Path) -> Optional[Path]:
    """Find a same-stem COCO JSON annotation beside an image path."""
    path_obj = Path(image_path)
    image_stem = path_obj.stem.lower()
    json_candidates = [
        path_obj.parent / f"{path_obj.stem}.json",
        path_obj.parent / f"{path_obj.stem.lower()}.json",
    ]
    for candidate in json_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    try:
        for sibling in path_obj.parent.iterdir():
            if sibling.is_file() and sibling.suffix.lower() == '.json' and sibling.stem.lower() == image_stem:
                return sibling
    except Exception:
        return None
    return None


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

