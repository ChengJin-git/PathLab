from typing import Any

"""
Storage scan and external file management routes.

Extracted from storage.py for maintainability.
Includes:
- Directory scanning for WSI files (_scan_directory_for_wsi)
- External file availability checking (_check_path_exists_with_timeout, _check_wsi_file_availability, _check_external_files_sync)
- Endpoints: POST /scan-directory, GET /external-datasets-summary, POST /tasks/unbind-dataset,
             POST /check-external-files, POST /delete-unavailable-files
"""
import os
import asyncio
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sql_delete
import importlib

_backend_database = importlib.import_module("backend.database")
_backend_repositories = importlib.import_module("backend.database.repositories")
_backend_models = importlib.import_module("backend.database.models")
_backend_auth_dependencies = importlib.import_module("backend.auth.dependencies")
_backend_common_config = importlib.import_module("backend.common.config")
_backend_common_file_types = importlib.import_module("backend.common.file_types")
external_availability = importlib.import_module("backend.storage.external_availability")

get_db = _backend_database.get_db
async_session = _backend_database.async_session
WSIRepository = _backend_repositories.WSIRepository
DatasetRepository = _backend_repositories.DatasetRepository
StorageTaskRepository = _backend_repositories.StorageTaskRepository
DatasetStatsRepository = _backend_repositories.DatasetStatsRepository
TrainingTaskWSI = _backend_models.TrainingTaskWSI
AIResult = _backend_models.AIResult
AITask = _backend_models.AITask
require_admin = _backend_auth_dependencies.require_admin
Config = _backend_common_config.Config
PATCH_EXTENSIONS = _backend_common_file_types.PATCH_EXTENSIONS
WSI_EXTENSIONS = _backend_common_file_types.WSI_EXTENSIONS

from .access_control import User
from ..dependencies import logger
from ..models import (
    ScanDirectoryRequest,
    StartScanDirectoryTaskRequest,
    CheckExternalFilesRequest,
    DeleteUnavailableFilesRequest,
)
from ..scan_sessions import build_scan_response, create_scan_session, get_scan_session
from . import storage_tasks
from ..utils import (
    build_segmentation_annotation_index,
    get_scan_file_data_type,
    is_tiff_family,
    resolve_segmentation_annotation_match,
)


router = APIRouter()


def _validate_scan_directory_path(directory: str) -> None:
    if not os.path.exists(directory):
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {directory}")

    if not os.path.isdir(directory):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {directory}")

    if not os.access(directory, os.R_OK):
        raise HTTPException(status_code=400, detail=f"Directory is not readable: {directory}")


def _build_scan_task_results(
    *,
    session: dict[str, Any],
    page_size: int,
) -> dict[str, Any]:
    files = session["files"]
    return {
        "scan_id": session["scan_id"],
        "directory": session["directory"],
        "total_count": len(files),
        "valid_count": session["valid_count"],
        "wsi_count": session["wsi_count"],
        "patch_count": session["patch_count"],
        "page_size": page_size,
        "annotation_scan_enabled": session.get("annotation_scan_enabled", False),
    }


async def _mark_scan_directory_task_cancelled(
    task_id: str,
    *,
    processed_items: int = 0,
    success_count: int = 0,
) -> None:
    storage_tasks.clear_storage_task_cancellation(task_id)
    async with async_session() as db:
        await StorageTaskRepository.update_status(
            db,
            task_id,
            "cancelled",
            processed_items=processed_items,
            success_count=success_count,
            failed_count=0,
        )
        await db.commit()


# ==============================================================================
# Directory Scanning
# ==============================================================================


def _scan_directory_for_wsi(
    directory: str, *, include_annotation_json: bool = False, progress=None
) -> list[Any]:
    """
    Scan a directory for WSI and patch files (non-recursive).
    Handles special formats: MRXS (requires data folder), TMAP (may have DT files).

    Supports:
    - WSI files: .svs, .ndpi, .mrxs, .tmap, etc.
    - Patch files: .jpg, .jpeg, .png, .bmp
    - TIF/TIFF files: first use slide inspection, then fallback heuristics

    External import applies the TIFF/TIFF dataset rule at scan time as well:
    if any scanned TIFF/TIFF is classified as WSI, all scanned TIFF/TIFF files
    are displayed as WSI for this batch preview.

    Returns list of dicts with file info including data_type ('wsi' or 'patch').
    """

    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    results = []
    pending_tiff_items = []
    seen_stems = set()  # Track processed file stems to avoid duplicates

    entries = list(dir_path.iterdir())
    all_items = {item.name: item for item in entries}
    annotation_index = (
        build_segmentation_annotation_index(dir_path) if include_annotation_json else {}
    )

    def _build_file_info(
        item: Path, *, file_size: int, data_type: str
    ) -> dict[str, Any]:
        total_size = file_size
        ext = item.suffix.lower()

        file_info: dict[str, Any] = {
            "path": str(item),
            "filename": item.name,
            "size": file_size,
            "extension": ext,
            "format_type": "standard",
            "data_type": data_type,
            "valid": True,
            "validation_message": None,
            "has_annotation_json": False,
        }

        if ext == ".mrxs":
            file_info["format_type"] = "mrxs"
            data_folder_name = item.stem
            if data_folder_name in all_items and all_items[data_folder_name].is_dir():
                data_folder_path = all_items[data_folder_name]
                file_info["associated_data"] = str(data_folder_path)
                try:
                    for root, dirs, files in os.walk(data_folder_path):
                        for f in files:
                            total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
            else:
                file_info["valid"] = False
                file_info["validation_message"] = (
                    f"Missing required data folder: {data_folder_name}/"
                )
        elif ext == ".tmap":
            file_info["format_type"] = "tmap"
            dt_files = []
            for other_item in all_items.values():
                if other_item.is_file() and other_item.stem == item.stem:
                    other_ext = other_item.suffix.lower()
                    if other_ext.startswith(".dt") and len(other_ext) > 3:
                        suffix_num = other_ext[3:]
                        if suffix_num.isdigit():
                            dt_files.append(str(other_item))
                            try:
                                total_size += other_item.stat().st_size
                            except OSError:
                                pass
            if dt_files:
                file_info["associated_data"] = sorted(dt_files)

        if include_annotation_json:
            matched_annotation_path, _annotation_error = (
                resolve_segmentation_annotation_match(
                    item,
                    annotation_index=annotation_index,
                )
            )
            file_info["has_annotation_json"] = matched_annotation_path is not None

        file_info["size"] = total_size
        return file_info

    for index,item in enumerate(entries):
        if progress:progress(index,len(entries))
        if not item.is_file():
            continue

        ext = item.suffix.lower()
        if (
            ext not in WSI_EXTENSIONS
            and ext not in PATCH_EXTENSIONS
            and not is_tiff_family(item)
        ):
            continue

        if item.stem in seen_stems:
            continue
        seen_stems.add(item.stem)

        try:
            file_size = item.stat().st_size
        except OSError:
            file_size = 0

        if ext in WSI_EXTENSIONS:
            results.append(_build_file_info(item, file_size=file_size, data_type="wsi"))
        elif ext in PATCH_EXTENSIONS:
            results.append(
                _build_file_info(item, file_size=file_size, data_type="patch")
            )
        else:
            pending_tiff_items.append((item, file_size))

    if pending_tiff_items:
        sorted_tiff_items = sorted(
            pending_tiff_items, key=lambda entry: entry[1], reverse=True
        )
        checked_tiff_items: list[tuple[Path, int, str]] = []
        tiff_batch_has_wsi = False

        for item, file_size in sorted_tiff_items:
            data_type = get_scan_file_data_type(item, file_size)
            checked_tiff_items.append((item, file_size, data_type))
            if data_type == "wsi":
                tiff_batch_has_wsi = True
                break

        if tiff_batch_has_wsi:
            for item, file_size, _data_type in checked_tiff_items:
                results.append(
                    _build_file_info(item, file_size=file_size, data_type="wsi")
                )
            for item, file_size in sorted_tiff_items[len(checked_tiff_items) :]:
                results.append(
                    _build_file_info(item, file_size=file_size, data_type="wsi")
                )
        else:
            for item, file_size, data_type in checked_tiff_items:
                results.append(
                    _build_file_info(item, file_size=file_size, data_type=data_type)
                )

    # Sort by filename for consistent ordering
    results.sort(key=lambda x: x["filename"].lower())
    if progress:progress(len(entries),len(entries),force=True)
    return results


async def _run_scan_directory_task(task_id: str, user_id: str, params: dict[str, Any]):
    directory = params["directory_path"]
    task_type = params.get("task_type")
    page_size = min(max(1, int(params.get("page_size") or 100)), 500)
    include_annotation_json = task_type in {"patch_segmentation", "patch_detection"}

    try:
        async with async_session() as db:
            await StorageTaskRepository.update_status(
                db,
                task_id,
                "processing",
                progress=0,
                processed_items=0,
            )
            await db.commit()

        if storage_tasks.is_storage_task_cancelled(task_id):
            await _mark_scan_directory_task_cancelled(task_id)
            return

        from backend.storage import inspection_jobs
        import time
        from backend.common import file_lock as fcntl
        loop=asyncio.get_running_loop();last_progress=[0.0]
        async def persist(done,total):
            async with async_session() as progress_db:
                await StorageTaskRepository.update_status(progress_db,task_id,'processing',progress=int(100*done/max(1,total)),processed_items=done,total_items=total)
                await progress_db.commit()
        def progress(done,total,force=False):
            if storage_tasks.is_storage_task_cancelled(task_id):raise InterruptedError('Directory scan cancelled')
            if force or time.monotonic()-last_progress[0]>.5:
                last_progress[0]=time.monotonic()
                asyncio.run_coroutine_threadsafe(persist(done,total),loop).result(timeout=15)
        def scan():
            with (inspection_jobs.directory()/'heavy-scan.lock').open('a') as scan_lock:
                while True:
                    if storage_tasks.is_storage_task_cancelled(task_id):raise InterruptedError('Directory scan cancelled')
                    try:fcntl.flock(scan_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:time.sleep(.2)
                _validate_scan_directory_path(directory)
                return _scan_directory_for_wsi(directory,include_annotation_json=include_annotation_json,progress=progress)
        files = await inspection_jobs.thread_work(scan)
        valid_count = sum(1 for file in files if file.get("valid"))

        if storage_tasks.is_storage_task_cancelled(task_id):
            await _mark_scan_directory_task_cancelled(
                task_id,
                processed_items=len(files),
                success_count=valid_count,
            )
            return

        session = create_scan_session(
            directory=directory,
            files=files,
            user_id=user_id,
            annotation_scan_enabled=include_annotation_json,
        )
        results = _build_scan_task_results(session=session, page_size=page_size)

        async with async_session() as db:
            await StorageTaskRepository.update_status(
                db,
                task_id,
                "completed",
                progress=100,
                processed_items=len(files),
                success_count=valid_count,
                failed_count=0,
                results=results,
            )
            await db.commit()
    except InterruptedError:
        await _mark_scan_directory_task_cancelled(task_id)
    except Exception as e:
        logger.error(f"Directory scan task {task_id} failed: {e}")
        async with async_session() as db:
            await StorageTaskRepository.update_status(
                db,
                task_id,
                "failed",
                error_message=str(e),
            )
            await db.commit()


@router.post("/tasks/scan-directory")
async def start_scan_directory_task(
    request: StartScanDirectoryTaskRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Start a directory scan background task and return immediately."""
    try:
        directory = os.path.abspath(request.directory_path)

        page_size = min(max(1, request.page_size), 500)
        task_id = f"scan_{uuid.uuid4().hex[:16]}"
        params = {
            "directory_path": directory,
            "task_type": request.task_type,
            "page_size": page_size,
        }

        from sqlalchemy import select,func,text
        from datetime import timedelta
        from backend.database.models import StorageTask,utc_now
        if db.bind.dialect.name=='postgresql':
            await db.execute(text('SELECT pg_advisory_xact_lock(2026110103)'))
        import psutil
        active_rows=(await db.scalars(select(StorageTask).where(StorageTask.task_type=='scan_directory',StorageTask.status.in_(['pending','processing'])))).all()
        for existing in active_rows:
            owner=(existing.params or {}).get('scan_worker')
            try:alive=bool(owner) and psutil.Process(owner[0]).create_time()==owner[1]
            except (psutil.NoSuchProcess,psutil.AccessDenied):alive=False
            if not alive:
                existing.status='failed';existing.error_message='Directory scan interrupted; start again to retry'
        await db.flush()
        recent=(await db.scalars(select(StorageTask).where(StorageTask.task_type=='scan_directory',StorageTask.user_id==str(user.id),StorageTask.status.in_(['pending','processing','completed'])).order_by(StorageTask.created_at.desc()).limit(20))).all()
        for task in recent:
            if all((task.params or {}).get(key)==value for key,value in params.items()):
                if task.status in {'pending','processing'} or (task.completed_at and task.completed_at>utc_now()-timedelta(seconds=30) and task.results and get_scan_session(task.results.get('scan_id',''),str(user.id))):
                    return {'task_id':task.task_id,'message':'Using existing directory scan','directory':directory,'reused':True}
        active=await db.scalar(select(func.count()).select_from(StorageTask).where(StorageTask.task_type=='scan_directory',StorageTask.status.in_(['pending','processing'])))
        if active>=2:raise HTTPException(429,'Directory scans are busy; wait for the existing scan to finish')
        params['scan_worker']=[os.getpid(),psutil.Process().create_time()]

        await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type="scan_directory",
            total_items=0,
            params=params,
        )
        await db.commit()

        background_tasks.add_task(_run_scan_directory_task, task_id, str(user.id), params)

        return {
            "task_id": task_id,
            "message": "Directory scan task started",
            "directory": directory,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start directory scan task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start directory scan: {str(e)}"
        )


@router.post("/scan-directory")
async def scan_directory(
    request: ScanDirectoryRequest,
    user: User = Depends(require_admin),
):
    """
    Scan a directory for WSI files.
    Admin only operation.

    Returns a bounded page from a completed directory-scan task. A scan_id is
    required; this read never starts filesystem work.

    Returns:
        {
            "directory": str,
            "files": [
                {
                    "path": str,
                    "filename": str,
                    "size": int,
                    "extension": str,
                    "format_type": "standard" | "mrxs" | "tmap",
                    "valid": bool,
                    "validation_message": str | null,
                    "associated_data": str | list | null
                }
            ],
            "total_count": int,
            "valid_count": int,
            "total_size": int
        }
    """
    try:
        directory = request.directory_path
        page = max(1, request.page)
        page_size = min(max(1, request.page_size), 500)
        include_annotation_json = request.task_type in {"patch_segmentation", "patch_detection"}

        if request.scan_id:
            session = get_scan_session(request.scan_id, str(user.id))
            if session is None:
                raise HTTPException(
                    status_code=404, detail="Scan session not found or expired"
                )
            if session["directory"] != directory:
                raise HTTPException(
                    status_code=400,
                    detail="Scan session does not match requested directory",
                )
            if not include_annotation_json or session.get("annotation_scan_enabled"):
                return build_scan_response(session, page=page, page_size=page_size)

        raise HTTPException(409,'Start a directory scan task first, then request pages with its scan_id')

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan directory: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to scan directory: {str(e)}"
        )


# ==============================================================================
# External File Availability Checking
# ==============================================================================


def _check_path_exists_with_timeout(path: str, timeout: float = 5.0) -> bool:
    """
    Check if a path exists with a timeout to handle unreachable NAS/network storage.
    Uses a thread with join timeout since os.path.exists is blocking and cannot be interrupted.

    Args:
        path: File or directory path to check
        timeout: Maximum seconds to wait (default 5s)

    Returns:
        True if path exists and responded within timeout, False otherwise.

    Raises:
        TimeoutError: If the check did not complete within the timeout.
    """
    import threading

    result: list[bool | None] = [None]  # Use list to allow mutation from thread

    def _check():
        result[0] = os.path.exists(path)

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        # Thread is still running - path check is hanging (likely NAS unreachable)
        raise TimeoutError(
            f"File accessibility check timed out after {timeout}s for: {path}"
        )

    return bool(result[0])


def _check_wsi_file_availability(
    wsi_path: str,
    associated_files: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """
    Check if a WSI file and its associated data are available.

    Uses stored associated_files info to check for required data:
    - MRXS: Requires data folder (stored in associated_files["data_folder"])
    - TMAP: Checks DT files if they were registered (stored in associated_files["dt_files"])

    Args:
        wsi_path: Path to the main WSI file
        associated_files: Dict with format_type and associated data paths (from DB)
        timeout: Maximum seconds to wait for each file check (default 5s)

    Returns:
        (is_available, message)

    Raises:
        TimeoutError: If the file check timed out (likely NAS unreachable)
    """
    file_path = Path(wsi_path)

    # Check if main file exists (with timeout for NAS paths)
    try:
        if not _check_path_exists_with_timeout(str(file_path), timeout=timeout):
            return False, "File not found"
    except TimeoutError:
        raise  # Let caller handle NAS timeout

    # If we have associated_files info, use it for validation
    if associated_files:
        format_type = associated_files.get("format_type", "standard")

        # Check MRXS data folder
        if format_type == "mrxs":
            data_folder = associated_files.get("data_folder")
            if data_folder:
                if (
                    not _check_path_exists_with_timeout(data_folder, timeout=timeout)
                    or not Path(data_folder).is_dir()
                ):
                    return (
                        False,
                        f"Missing required data folder: {Path(data_folder).name}/",
                    )
            else:
                # Fallback: check for data folder with same name as file
                data_folder = str(file_path.parent / file_path.stem)
                if (
                    not _check_path_exists_with_timeout(data_folder, timeout=timeout)
                    or not Path(data_folder).is_dir()
                ):
                    return False, f"Missing required data folder: {file_path.stem}/"

        # Check TMAP DT files (only if they were registered)
        elif format_type == "tmap":
            dt_files = associated_files.get("dt_files", [])
            missing_dt = []
            for dt_file in dt_files:
                if not _check_path_exists_with_timeout(dt_file, timeout=timeout):
                    missing_dt.append(Path(dt_file).name)
            if missing_dt:
                return False, f"Missing DT files: {', '.join(missing_dt)}"

    else:
        # Fallback for files registered before this feature: check by extension
        ext = file_path.suffix.lower()
        if ext == ".mrxs":
            data_folder = str(file_path.parent / file_path.stem)
            if (
                not _check_path_exists_with_timeout(data_folder, timeout=timeout)
                or not Path(data_folder).is_dir()
            ):
                return False, f"Missing required data folder: {file_path.stem}/"

    return True, "Available"


def _is_under_uploads_dir(path: str, uploads_dir: str) -> bool:
    abs_path = os.path.abspath(path)
    abs_uploads = os.path.abspath(uploads_dir)
    return abs_path == abs_uploads or abs_path.startswith(abs_uploads + os.sep)


def _check_external_files_sync(
    wsi_data: list[dict[str, Any]], uploads_dir: str
) -> dict[str, Any]:
    """
    Check external files availability synchronously.
    Designed to run in a thread pool via asyncio.to_thread() to avoid blocking the event loop.

    Handles TimeoutError from _check_wsi_file_availability when NAS is unreachable.
    On first timeout, immediately marks all remaining external files as unavailable
    with a storage connectivity error instead of checking each one (which would all timeout).

    Args:
        wsi_data: List of dicts with keys: wsi_id, original_filename, wsi_path,
                  dataset_id, dataset_name, label, associated_files
        uploads_dir: The system uploads directory path
    """
    available = []
    unavailable = []
    storage_timeout = False
    timeout_path = None

    for item in wsi_data:
        wsi_path = item["wsi_path"]

        if not _is_under_uploads_dir(wsi_path, uploads_dir):
            file_info = {
                "wsi_id": item["wsi_id"],
                "original_filename": item["original_filename"],
                "wsi_path": wsi_path,
                "dataset_id": item["dataset_id"],
                "dataset_name": item["dataset_name"],
                "label": item["label"],
            }

            # If we already detected a timeout, skip checking remaining files
            if storage_timeout:
                file_info["status"] = "unavailable"
                file_info["reason"] = "Storage not responding (skipped after timeout)"
                unavailable.append(file_info)
                continue

            try:
                is_available, message = _check_wsi_file_availability(
                    wsi_path, item["associated_files"]
                )
            except TimeoutError:
                storage_timeout = True
                timeout_path = wsi_path
                file_info["status"] = "unavailable"
                file_info["reason"] = (
                    "External storage not responding (connection timed out)"
                )
                unavailable.append(file_info)
                continue

            if is_available:
                file_info["status"] = "available"
                available.append(file_info)
            else:
                file_info["status"] = "unavailable"
                file_info["reason"] = message
                unavailable.append(file_info)

    result: dict[str, Any] = {
        "total_external": len(available) + len(unavailable),
        "available_count": len(available),
        "unavailable_count": len(unavailable),
        "available": available,
        "unavailable": unavailable,
    }

    if storage_timeout:
        path_root = "/".join(timeout_path.split("/")[:3]) if timeout_path else "unknown"
        result["storage_timeout"] = True
        result["storage_timeout_message"] = (
            f"External storage at {path_root} is not responding. "
            f"Please check your network storage connection."
        )

    return result


def _record_external_availability_result(result: dict[str, Any]) -> None:
    try:
        external_availability.record_many_from_scan(result)
    except Exception as exc:
        logger.warning(f"Failed to record external availability scan result: {exc}")


# ==============================================================================
# External File Endpoints
# ==============================================================================


@router.get("/external-datasets-summary")
async def get_external_datasets_summary(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """
    Get a lightweight summary of datasets containing externally imported WSI files.

    Only returns dataset names and file counts - NO file availability checks.
    This is a pure database query with no file I/O operations, making it
    much faster than the full /external-datasets endpoint.

    Admin only operation.

    Returns:
        List of datasets with external file counts (no availability status).
    """
    try:
        from .storage_inspections import external_summary
        return await external_summary(db)

    except Exception as e:
        logger.error(f"Failed to get external datasets summary: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get external datasets summary: {str(e)}"
        )


@router.post("/tasks/unbind-dataset")
async def start_unbind_dataset_task(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a background task to unbind (delete records of) all external files in a dataset.

    This removes the database records for externally imported WSI files but does NOT
    delete the actual files on the external drive.

    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        external_refs = await DatasetRepository.get_external_wsi_path_refs_batch(
            db, [dataset_id]
        )
        external_wsi_ids = [str(ref["wsi_id"]) for ref in external_refs[dataset_id]]

        if not external_wsi_ids:
            raise HTTPException(
                status_code=400, detail="No external files found in this dataset"
            )

        # Generate task ID
        task_id = f"unbind_{uuid.uuid4().hex[:16]}"

        # Get dataset name for display
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        dataset_name = dataset.name if dataset else "Unknown"

        # Create task record
        await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type="unbind_dataset",
            total_items=len(external_wsi_ids),
            params={
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "wsi_ids": external_wsi_ids,
            },
        )
        await db.commit()

        # Start background task (reuse the delete external task logic)
        # Lazy import to avoid circular dependency
        from .storage_tasks import _run_delete_external_task

        background_tasks.add_task(
            _run_delete_external_task, task_id, str(user.id), external_wsi_ids
        )

        return {
            "task_id": task_id,
            "message": f"Unbind dataset task started for '{dataset_name}'",
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "total_files": len(external_wsi_ids),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start unbind dataset task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start unbind dataset task: {str(e)}"
        )


@router.post("/check-external-files")
async def check_external_files(
    request: CheckExternalFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Check availability of externally imported WSI files.

    External files are those whose wsi_path is outside the system's uploads directory.
    This is useful for detecting files that were imported from external drives that
    may have been disconnected.

    Handles special formats:
    - MRXS: Also checks for required data folder
    - TMAP: Checks main file (DT files are optional)

    Admin only operation.

    Returns:
        - available: List of WSI that are still accessible
        - unavailable: List of WSI that are no longer accessible (file not found)
    """
    try:
        from .storage_inspections import begin
        return await begin('external-health',request.dataset_id or '')

    except Exception as e:
        logger.error(f"Failed to check external files: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to check external files: {str(e)}"
        )


@router.post("/delete-unavailable-files")
async def delete_unavailable_files(
    request: DeleteUnavailableFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete WSI records for files that are no longer available.

    This removes the database records for WSI files that cannot be accessed
    (e.g., external drive disconnected). It does NOT delete any actual files.

    Admin only operation.

    Returns:
        - deleted: Number of records deleted
        - failed: Number of records that failed to delete
        - results: Details for each WSI ID
    """
    try:
        deleted_count = 0
        failed_count = 0
        results = []

        for wsi_id in request.wsi_ids:
            try:
                # Get WSI to verify it exists
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if not wsi:
                    results.append(
                        {
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "WSI not found",
                        }
                    )
                    failed_count += 1
                    continue

                # Delete all associated child records before deleting the WSI
                # (PostgreSQL enforces FK constraints strictly)
                try:
                    await db.execute(
                        sql_delete(TrainingTaskWSI).where(
                            TrainingTaskWSI.wsi_id == wsi_id
                        )
                    )
                    await db.execute(
                        sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
                    )
                    await db.execute(sql_delete(AITask).where(AITask.wsi_id == wsi_id))
                except Exception as assoc_error:
                    logger.warning(
                        f"Failed to delete associated data for {wsi_id}: {assoc_error}"
                    )

                # Delete the WSI record
                dataset_id = wsi.dataset_id
                success = await WSIRepository.delete(db, wsi_id)
                if success:
                    if dataset_id:
                        await DatasetStatsRepository.recompute(db, str(dataset_id))
                    await db.commit()
                    results.append(
                        {
                            "wsi_id": wsi_id,
                            "status": "deleted",
                            "message": "Record deleted successfully",
                        }
                    )
                    deleted_count += 1
                    logger.info(f"Deleted unavailable WSI record: {wsi_id}")
                else:
                    results.append(
                        {
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "Failed to delete record",
                        }
                    )
                    failed_count += 1

            except Exception as e:
                results.append(
                    {"wsi_id": wsi_id, "status": "failed", "message": str(e)}
                )
                failed_count += 1
                logger.error(f"Failed to delete WSI record {wsi_id}: {e}")

        return {"deleted": deleted_count, "failed": failed_count, "results": results}

    except Exception as e:
        logger.error(f"Failed to delete unavailable files: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete unavailable files: {str(e)}"
        )
