"""
Utility functions for Gateway service
"""

import asyncio
from collections import defaultdict
import inspect
import json
import os
from pathlib import Path
import httpx
from typing import Any, Callable, Iterable, Mapping, Optional

from Aslide import Slide
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.coords_cache import compute_params_hash
from backend.ai.task_taxonomy import normalize_task_type, validate_task_axes
from backend.ai.tasks.patch_cache import (
    acquire_coords_lock,
    find_valid_cached_coords_summary,
)
from backend.common.config import Config
from sqlalchemy import text as sa_text
from backend.database.repositories import (
    DataGroupRepository,
    DatasetRepository,
    StorageTaskRepository,
)
from backend.common.file_types import (
    PATCH_EXTENSIONS,
    TIF_EXTENSIONS,
    WSI_EXTENSIONS,
    is_patch_file,
    is_patch_file_for_scan,
)
from .dependencies import logger, AI_SERVICE_URL, PREPROCESSING_SERVICE_URL


SEGMENTATION_TASK_TYPE = "patch_segmentation"
SEGMENTATION_DATA_TYPE = "patch"
SEGMENTATION_AGGREGATION_LEVEL = "file"
PROXY_BINARY_CACHE_HEADER_NAMES = (
    "cache-control",
    "etag",
    "last-modified",
    "expires",
    "content-disposition",
)
PREPROCESSING_COMPUTE_PATCHES_DEFAULTS = {
    "level": 0,
    "force_recompute": False,
    "seg_level": -1,
    "sthresh": 8,
    "mthresh": 7,
    "close": 4,
    "use_otsu": False,
    "contour_fn": "four_pt",
    "use_padding": True,
    "a_t": 5,
    "a_h": 16,
    "max_n_holes": 8,
    "save_mask": True,
}
PREPROCESSING_RETRYABLE_REQUEST_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
)
_PREPROCESSING_COMPUTE_PATCHES_SEMAPHORE = asyncio.Semaphore(
    max(1, Config.PREPROCESSING_MAX_CONCURRENT_COMPUTE_PATCHES)
)


def is_tiff_family(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() in TIF_EXTENSIONS


def get_file_data_type(file_path: str | Path, file_size: int = 0) -> str:
    return "patch" if is_patch_file(str(file_path), file_size) else "wsi"


def get_scan_file_data_type(file_path: str | Path, file_size: int = 0) -> str:
    return "patch" if is_patch_file_for_scan(str(file_path), file_size) else "wsi"


def get_file_size_safe(file_path: str | Path) -> int:
    try:
        return os.path.getsize(file_path)
    except Exception:
        return 0


def get_wsi_effective_file_size(file_path: str | Path) -> int:
    """
    Return the effective on-disk size of a WSI, including associated data:
    - .mrxs : main file + all files inside the same-stem data directory (always present)
    - .tmap : main file + any same-stem .DT<n> sibling files (may or may not exist)
    - others: main file only
    """
    path = Path(file_path)
    try:
        total = path.stat().st_size
    except OSError:
        return 0

    ext = path.suffix.lower()

    if ext == ".mrxs":
        data_folder = path.parent / path.stem
        if data_folder.is_dir():
            try:
                for root, _dirs, files in os.walk(data_folder):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            except OSError:
                pass

    elif ext == ".tmap":
        try:
            for sibling in path.parent.iterdir():
                if not sibling.is_file() or sibling.stem != path.stem:
                    continue
                sext = sibling.suffix.lower()
                if sext.startswith(".dt") and len(sext) > 3 and sext[3:].isdigit():
                    try:
                        total += sibling.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass

    return total


def build_default_wsi_properties(
    file_path: str | Path, file_size: Optional[int] = None
) -> dict[str, Any]:
    if file_size is None:
        file_size = get_file_size_safe(file_path)
    return {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
        "file_size": file_size,
    }


def resolve_file_data_type(
    file_path: str | Path,
    *,
    cached_file_data_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> str:
    suffix = Path(file_path).suffix.lower()

    if suffix in PATCH_EXTENSIONS:
        return "patch"
    if suffix in WSI_EXTENSIONS:
        return "wsi"

    if cached_file_data_type in {"wsi", "patch"} and suffix not in TIF_EXTENSIONS:
        return cached_file_data_type

    if file_size is None:
        file_size = get_file_size_safe(file_path)
    return get_file_data_type(file_path, file_size)


def should_extract_wsi_properties(
    file_path: str | Path, *, file_data_type: Optional[str] = None
) -> bool:
    suffix = Path(file_path).suffix.lower()

    if suffix in PATCH_EXTENSIONS:
        return False
    if suffix in WSI_EXTENSIONS or suffix in TIF_EXTENSIONS:
        return True
    return file_data_type != "patch"


def resolve_file_data_type_and_properties(
    file_path: str | Path,
    *,
    cached_file_data_type: Optional[str] = None,
    file_size: Optional[int] = None,
) -> tuple[str, dict[str, Any]]:
    if file_size is None:
        file_size = get_file_size_safe(file_path)

    file_data_type = resolve_file_data_type(
        file_path,
        cached_file_data_type=cached_file_data_type,
        file_size=file_size,
    )

    if should_extract_wsi_properties(file_path, file_data_type=file_data_type):
        props = extract_wsi_properties(str(file_path))
        if props.get("file_size", 0) <= 0:
            props["file_size"] = file_size
        return file_data_type, props

    return file_data_type, build_default_wsi_properties(file_path, file_size)


def infer_dataset_data_type_from_paths(file_paths: Iterable[str | Path]) -> str:
    for file_path in file_paths:
        path_obj = Path(file_path)
        file_size = path_obj.stat().st_size if path_obj.exists() else 0
        if get_file_data_type(path_obj, file_size) == "wsi":
            return "wsi"
    return "patch"


def find_first_path_for_data_type(
    file_paths: Iterable[str | Path], target_data_type: str
) -> Optional[str]:
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
        raise HTTPException(
            status_code=400, detail=f"{context}: dataset has no associated DataGroup"
        )

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
        await db.execute(
            sa_text(
                "UPDATE wsi_slides SET data_type = 'wsi', updated_at = NOW()"
                " WHERE dataset_id = :did AND data_type = 'patch'"
                " AND (LOWER(wsi_path) LIKE '%.tif' OR LOWER(wsi_path) LIKE '%.tiff')"
            ),
            {"did": dataset.dataset_id},
        )
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
    return get_file_data_type(
        getattr(wsi, "wsi_path", ""), getattr(wsi, "file_size", 0) or 0
    )


def ensure_segmentation_contract(
    task_type: Optional[str],
    data_type: Optional[str],
    aggregation_level: Optional[str],
    *,
    context: str,
) -> None:
    """Raise HTTP 400 when a segmentation combination violates the patch/file contract."""
    if task_type is None:
        return

    raw_task_type = task_type.strip().lower()
    is_segmentation_family_input = raw_task_type in {
        "segmentation",
        SEGMENTATION_TASK_TYPE,
    }

    normalized_task_type = raw_task_type
    normalized_data_type = data_type.strip().lower() if data_type else None
    normalized_aggregation = aggregation_level.strip().lower() if aggregation_level else None

    try:
        normalized_task_type = normalize_task_type(
            task_type=normalized_task_type,
            data_type=normalized_data_type,
            aggregation_level=normalized_aggregation or "file",
        )
    except ValueError:
        # Preserve legacy segmentation contract checks even when task-axis normalization fails.
        if not is_segmentation_family_input:
            return

    if normalized_task_type != SEGMENTATION_TASK_TYPE:
        if not is_segmentation_family_input:
            return
        normalized_task_type = SEGMENTATION_TASK_TYPE

    if normalized_data_type is not None and normalized_aggregation is not None:
        try:
            validate_task_axes(
                task_type=normalized_task_type,
                data_type=normalized_data_type,
                aggregation_level=normalized_aggregation,
            )
            return
        except ValueError:
            pass

    if (
        normalized_data_type != SEGMENTATION_DATA_TYPE
        or normalized_aggregation != SEGMENTATION_AGGREGATION_LEVEL
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{context}: segmentation datasets must use "
                f"data_type='{SEGMENTATION_DATA_TYPE}' and aggregation_level='{SEGMENTATION_AGGREGATION_LEVEL}'"
            ),
        )


def ensure_dataset_segmentation_contract(
    dataset: Any, *, context: str, expected_task_type: Optional[str] = None
) -> Any:
    """Validate a dataset's loaded data_group against the segmentation contract."""
    data_group = getattr(dataset, "data_group", None)
    if data_group is None:
        raise HTTPException(
            status_code=400, detail=f"{context}: dataset has no associated DataGroup"
        )

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


def build_segmentation_annotation_index(
    search_root: str | Path,
) -> dict[str, list[Path]]:
    """Build a case-insensitive stem -> COCO JSON paths index under a directory tree."""
    root_path = Path(search_root)
    index: dict[str, list[Path]] = defaultdict(list)

    if not root_path.exists():
        return {}

    try:
        if root_path.is_file():
            candidates = [root_path] if root_path.suffix.lower() == ".json" else []
        else:
            candidates = []
            for current_root, _dirs, files in os.walk(root_path):
                for filename in files:
                    candidate = Path(current_root) / filename
                    if candidate.suffix.lower() == ".json":
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
                if sibling.is_file()
                and sibling.suffix.lower() == ".json"
                and sibling.stem.lower() == image_stem
            )
        except Exception:
            return None, None

    unique_candidates: dict[str, Path] = {}
    for candidate in raw_candidates:
        candidate_path = Path(candidate)
        if not candidate_path.exists() or not candidate_path.is_file():
            continue
        if (
            candidate_path.suffix.lower() != ".json"
            or candidate_path.stem.lower() != image_stem
        ):
            continue
        unique_candidates.setdefault(str(candidate_path).lower(), candidate_path)

    ordered_candidates = sorted(
        unique_candidates.values(), key=lambda path: str(path).lower()
    )
    if not ordered_candidates:
        return None, None
    if len(ordered_candidates) > 1:
        return None, (
            f"Multiple same-name COCO JSON annotations found for '{path_obj.name}'. "
            "Keep exactly one matching annotation per image stem."
        )
    return ordered_candidates[0], None


def find_matching_segmentation_annotation_path(
    image_path: str | Path,
) -> Optional[Path]:
    """Find a same-stem COCO JSON annotation beside an image path."""
    match_path, _error = resolve_segmentation_annotation_match(image_path)
    return match_path


def validate_coco_annotation_payload(
    payload: Any, *, source_name: str
) -> dict[str, Any]:
    """Validate the minimum COCO structure required by PathLab segmentation."""
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400, detail=f"{source_name}: annotation must be a JSON object"
        )

    missing_keys = [
        key for key in ("images", "annotations", "categories") if key not in payload
    ]
    if missing_keys:
        raise HTTPException(
            status_code=400,
            detail=f"{source_name}: COCO annotation is missing required keys: {', '.join(missing_keys)}",
        )

    return payload


def load_coco_annotation_bytes(raw_bytes: bytes, *, source_name: str) -> dict[str, Any]:
    """Parse and validate uploaded COCO JSON bytes."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"{source_name}: annotation must be UTF-8 JSON"
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"{source_name}: invalid JSON annotation"
        ) from exc

    return validate_coco_annotation_payload(payload, source_name=source_name)


def load_coco_annotation_file(annotation_path: str | Path) -> dict[str, Any]:
    """Load and validate a COCO JSON annotation from disk."""
    path_obj = Path(annotation_path)
    try:
        payload = json.loads(path_obj.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"{path_obj.name}: annotation must be UTF-8 JSON"
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"{path_obj.name}: invalid JSON annotation"
        ) from exc

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
        logger.info(
            f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)"
        )
    except Exception as e:
        logger.warning(
            f"Failed to send cancellation to AI service for task {task_id}: {e}"
        )


async def request_preprocessing_service(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: float = 30.0,
    passthrough_request_errors: tuple[type[Exception], ...] = (),
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
        if passthrough_request_errors and isinstance(e, passthrough_request_errors):
            raise
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
    proxied_headers = {
        header_name: header_value
        for header_name in PROXY_BINARY_CACHE_HEADER_NAMES
        if (header_value := response.headers.get(header_name)) is not None
    }
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", default_media_type),
        headers=proxied_headers,
    )


def normalize_compute_patches_params(
    params: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Normalize compute_patches params to preprocessing-service defaults."""
    normalized = dict(PREPROCESSING_COMPUTE_PATCHES_DEFAULTS)
    if params:
        normalized.update(
            {key: value for key, value in params.items() if value is not None}
        )
    return normalized


def build_cached_compute_patches_response(
    wsi_id: str,
    *,
    level: int,
    coords_file: Path,
    num_patches: int,
    uploads_root: Path,
) -> dict[str, Any]:
    """Build a response payload matching preprocessing-service cache-hit semantics."""
    response_data: dict[str, Any] = {
        "wsi_id": wsi_id,
        "num_patches": num_patches,
        "num_contours": -1,
        "level": level,
        "coords_file": str(coords_file),
        "cached": True,
    }
    mask_path = uploads_root / "masks" / f"{wsi_id}_mask.png"
    if mask_path.exists():
        response_data["mask_file"] = str(mask_path)
    return response_data


async def _maybe_call(callback: Optional[Callable[..., Any]], *args: Any) -> None:
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result


async def ensure_coords_ready(
    wsi_id: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    timeout: float = 600.0,
    uploads_root: Optional[Path] = None,
    max_retries: int = 3,
    retry_backoff_seconds: int = 3,
    on_retry: Optional[Callable[[int, int, Exception, int], Any]] = None,
    on_lock_wait: Optional[Callable[[float], Any]] = None,
) -> Any:
    """Ensure coords are ready while avoiding redundant preprocessing requests."""
    normalized_params = normalize_compute_patches_params(params)
    uploads_root = uploads_root or Config.get_uploads_dir()

    seg_params = {
        "sthresh": normalized_params["sthresh"],
        "mthresh": normalized_params["mthresh"],
        "close": normalized_params["close"],
        "use_otsu": normalized_params["use_otsu"],
    }
    filter_params = {
        "a_t": normalized_params["a_t"],
        "a_h": normalized_params["a_h"],
        "max_n_holes": normalized_params["max_n_holes"],
    }
    params_hash = compute_params_hash(
        level=normalized_params["level"],
        seg_params=seg_params,
        filter_params=filter_params,
        contour_fn=normalized_params["contour_fn"],
        use_padding=normalized_params["use_padding"],
        seg_level=normalized_params["seg_level"],
    )

    def _lookup_cached_summary() -> Optional[dict[str, Any]]:
        return find_valid_cached_coords_summary(
            uploads_root,
            params_hash,
            wsi_id,
            level=normalized_params["level"],
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=normalized_params["contour_fn"],
            use_padding=normalized_params["use_padding"],
            seg_level=normalized_params["seg_level"],
        )

    async def _cached_response_if_available() -> Optional[dict[str, Any]]:
        if normalized_params["force_recompute"]:
            return None
        cached_summary = await asyncio.to_thread(_lookup_cached_summary)
        if cached_summary is None:
            return None
        return build_cached_compute_patches_response(
            wsi_id,
            level=normalized_params["level"],
            coords_file=cached_summary["coords_file"],
            num_patches=int(cached_summary["num_patches"]),
            uploads_root=uploads_root,
        )

    cached_response = await _cached_response_if_available()
    if cached_response is not None:
        return cached_response

    def _lock_wait_callback(wait_seconds: float) -> None:
        if on_lock_wait is None:
            return
        try:
            asyncio.get_running_loop().create_task(
                _maybe_call(on_lock_wait, wait_seconds)
            )
        except RuntimeError:
            logger.warning(
                "Unable to schedule preprocessing lock-wait callback for WSI %s",
                wsi_id,
            )

    async with acquire_coords_lock(
        uploads_root,
        params_hash,
        wsi_id,
        wait_callback=_lock_wait_callback,
    ):
        cached_response = await _cached_response_if_available()
        if cached_response is not None:
            return cached_response

        async with _PREPROCESSING_COMPUTE_PATCHES_SEMAPHORE:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await request_preprocessing_service(
                        "POST",
                        f"/wsi/{wsi_id}/compute_patches",
                        params=normalized_params,
                        timeout=timeout,
                        passthrough_request_errors=PREPROCESSING_RETRYABLE_REQUEST_ERRORS,
                    )
                    return response.json()
                except PREPROCESSING_RETRYABLE_REQUEST_ERRORS as retry_err:
                    if attempt >= max_retries:
                        raise
                    wait_secs = attempt * retry_backoff_seconds
                    await _maybe_call(
                        on_retry, attempt, max_retries, retry_err, wait_secs
                    )
                    await asyncio.sleep(wait_secs)


def extract_wsi_properties(wsi_path: str) -> dict[str, Any]:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification, file_size.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = build_default_wsi_properties(wsi_path, 0)

    if not wsi_path or not os.path.exists(wsi_path):
        logger.warning(f"WSI file not found: {wsi_path}")
        return default_props

    # Get effective file size (includes associated data dir for .mrxs, .DT* for .tmap)
    file_size = get_wsi_effective_file_size(wsi_path)

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
                vendor = slide.properties.get("openslide.vendor", "Unknown")
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
                mag = slide.properties.get("openslide.objective-power")
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except Exception:
                props["magnification"] = default_props["magnification"]

            logger.info(
                f"✓ Extracted properties from {os.path.basename(wsi_path)}: "
                f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                f"size={props['width']}x{props['height']}, mag={props['magnification']}x, "
                f"file_size={props['file_size']} bytes"
            )

            return props

    except Exception as e:
        logger.error(f"Failed to read WSI properties from {wsi_path}: {e}")
        # Still return file_size even if slide reading failed
        default_props["file_size"] = file_size
        return default_props
