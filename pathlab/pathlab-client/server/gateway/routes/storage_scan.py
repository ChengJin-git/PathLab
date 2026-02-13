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
from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    StorageTaskRepository,
)
from backend.database.models import TrainingTaskWSI, AIResult, AITask
from backend.auth import User
from backend.auth.dependencies import require_admin
from ..dependencies import logger
from ..models import ScanDirectoryRequest, CheckExternalFilesRequest, DeleteUnavailableFilesRequest
from backend.common.config import Config
from backend.common.file_types import WSI_EXTENSIONS, TIF_EXTENSIONS, SIZE_THRESHOLD

router = APIRouter()


# ==============================================================================
# Directory Scanning
# ==============================================================================

def _scan_directory_for_wsi(directory: str) -> list:
    """
    Scan a directory for WSI and patch files (non-recursive).
    Handles special formats: MRXS (requires data folder), TMAP (may have DT files).

    Supports:
    - WSI files: .svs, .ndpi, .mrxs, .tmap, etc.
    - Patch files: .jpg, .jpeg, .png, .bmp
    - TIF/TIFF files: classified by size (>= 100MB = WSI, < 100MB = patch)

    Returns list of dicts with file info including data_type ('wsi' or 'patch').
    """
    import uuid as uuid_module
    from backend.common.file_types import PATCH_EXTENSIONS

    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    results = []
    seen_stems = set()  # Track processed file stems to avoid duplicates

    # Build a set of all items in directory for quick lookup
    all_items = {item.name: item for item in dir_path.iterdir()}

    for item in dir_path.iterdir():
        if not item.is_file():
            continue

        ext = item.suffix.lower()
        file_size = item.stat().st_size

        # Determine file type: WSI, patch, or skip
        data_type = None
        if ext in WSI_EXTENSIONS:
            data_type = 'wsi'
        elif ext in PATCH_EXTENSIONS:
            data_type = 'patch'
        elif ext in TIF_EXTENSIONS:
            # TIF/TIFF: classify by size
            data_type = 'wsi' if file_size >= SIZE_THRESHOLD else 'patch'

        if data_type is None:
            continue

        # Skip if we've already processed this stem (for MRXS/TMAP handling)
        if item.stem in seen_stems:
            continue
        seen_stems.add(item.stem)

        # Total size includes main file + associated files
        total_size = file_size

        file_info = {
            "path": str(item),
            "filename": item.name,
            "size": file_size,  # Will be updated to include associated files
            "extension": ext,
            "format_type": "standard",
            "data_type": data_type,  # 'wsi' or 'patch'
            "valid": True,
            "validation_message": None,
        }

        # Handle MRXS format - requires data folder with same name
        if ext == '.mrxs':
            file_info["format_type"] = "mrxs"
            data_folder_name = item.stem
            if data_folder_name in all_items and all_items[data_folder_name].is_dir():
                data_folder_path = all_items[data_folder_name]
                file_info["associated_data"] = str(data_folder_path)
                # Calculate total size of data folder
                try:
                    for root, dirs, files in os.walk(data_folder_path):
                        for f in files:
                            total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass  # Ignore errors when calculating folder size
            else:
                file_info["valid"] = False
                file_info["validation_message"] = f"Missing required data folder: {data_folder_name}/"

        # Handle TMAP format - may have DT files
        elif ext == '.tmap':
            file_info["format_type"] = "tmap"
            dt_files = []
            for name, other_item in all_items.items():
                if other_item.is_file() and other_item.stem == item.stem:
                    other_ext = other_item.suffix.lower()
                    if other_ext.startswith('.dt') and len(other_ext) > 3:
                        suffix_num = other_ext[3:]
                        if suffix_num.isdigit():
                            dt_files.append(str(other_item))
                            # Add DT file size to total
                            try:
                                total_size += other_item.stat().st_size
                            except OSError:
                                pass
            if dt_files:
                file_info["associated_data"] = sorted(dt_files)

        # Update size to include associated files
        file_info["size"] = total_size

        results.append(file_info)

    # Sort by filename for consistent ordering
    results.sort(key=lambda x: x["filename"].lower())
    return results


@router.post("/scan-directory")
async def scan_directory(
    request: ScanDirectoryRequest,
    user: User = Depends(require_admin),
):
    """
    Scan a directory for WSI files.
    Admin only operation.

    This scans the specified directory (non-recursive) for WSI files,
    handling special formats like MRXS and TMAP.

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

        # Validate directory exists
        if not os.path.exists(directory):
            raise HTTPException(status_code=400, detail=f"Directory does not exist: {directory}")

        if not os.path.isdir(directory):
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {directory}")

        if not os.access(directory, os.R_OK):
            raise HTTPException(status_code=400, detail=f"Directory is not readable: {directory}")

        # Scan directory in thread pool to avoid blocking
        files = await asyncio.to_thread(_scan_directory_for_wsi, directory)

        valid_count = sum(1 for f in files if f["valid"])
        total_size = sum(f["size"] for f in files)

        return {
            "directory": directory,
            "files": files,
            "total_count": len(files),
            "valid_count": valid_count,
            "total_size": total_size,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scan directory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan directory: {str(e)}")


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

    result = [None]  # Use list to allow mutation from thread

    def _check():
        result[0] = os.path.exists(path)

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        # Thread is still running - path check is hanging (likely NAS unreachable)
        raise TimeoutError(f"File accessibility check timed out after {timeout}s for: {path}")

    return result[0]


def _check_wsi_file_availability(wsi_path: str, associated_files: dict = None, timeout: float = 5.0) -> tuple[bool, str]:
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
                if not _check_path_exists_with_timeout(data_folder, timeout=timeout) or not Path(data_folder).is_dir():
                    return False, f"Missing required data folder: {Path(data_folder).name}/"
            else:
                # Fallback: check for data folder with same name as file
                data_folder = str(file_path.parent / file_path.stem)
                if not _check_path_exists_with_timeout(data_folder, timeout=timeout) or not Path(data_folder).is_dir():
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
        if ext == '.mrxs':
            data_folder = str(file_path.parent / file_path.stem)
            if not _check_path_exists_with_timeout(data_folder, timeout=timeout) or not Path(data_folder).is_dir():
                return False, f"Missing required data folder: {file_path.stem}/"

    return True, "Available"


def _check_external_files_sync(
    wsi_data: list[dict],
    uploads_dir: str
) -> dict:
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

        if not wsi_path.startswith(uploads_dir):
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
                    wsi_path,
                    item["associated_files"]
                )
            except TimeoutError:
                storage_timeout = True
                timeout_path = wsi_path
                file_info["status"] = "unavailable"
                file_info["reason"] = "External storage not responding (connection timed out)"
                unavailable.append(file_info)
                continue

            if is_available:
                file_info["status"] = "available"
                available.append(file_info)
            else:
                file_info["status"] = "unavailable"
                file_info["reason"] = message
                unavailable.append(file_info)

    result = {
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


# ==============================================================================
# External File Endpoints
# ==============================================================================

@router.get("/external-datasets-summary")
async def get_external_datasets_summary(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records with dataset relationship loaded
        wsi_list = await WSIRepository.get_all_with_dataset(db, limit=0)

        # Filter external files and group by dataset (pure string comparison, no file I/O)
        dataset_stats: dict[str, dict] = {}
        for wsi in wsi_list:
            if not wsi.wsi_path.startswith(uploads_dir):
                ds_id = wsi.dataset_id or "uncategorized"
                if ds_id not in dataset_stats:
                    dataset_stats[ds_id] = {
                        "dataset_id": wsi.dataset_id,
                        "dataset_name": wsi.dataset.name if wsi.dataset else "Uncategorized",
                        "total_files": 0,
                    }
                dataset_stats[ds_id]["total_files"] += 1

        datasets = list(dataset_stats.values())
        return {
            "datasets": datasets,
            "total": sum(d["total_files"] for d in datasets)
        }

    except Exception as e:
        logger.error(f"Failed to get external datasets summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get external datasets summary: {str(e)}")


@router.post("/tasks/unbind-dataset")
async def start_unbind_dataset_task(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records in this dataset
        wsi_list = await WSIRepository.get_by_dataset(db, dataset_id, limit=0)

        # Filter to only external files (use wsi_id, not database id)
        external_wsi_ids = [
            wsi.wsi_id for wsi in wsi_list
            if not wsi.wsi_path.startswith(uploads_dir)
        ]

        if not external_wsi_ids:
            raise HTTPException(
                status_code=400,
                detail="No external files found in this dataset"
            )

        # Generate task ID
        task_id = f"unbind_{uuid.uuid4().hex[:16]}"

        # Get dataset name for display
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        dataset_name = dataset.name if dataset else "Unknown"

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='unbind_dataset',
            total_items=len(external_wsi_ids),
            params={
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "wsi_ids": external_wsi_ids
            }
        )
        await db.commit()

        # Start background task (reuse the delete external task logic)
        # Lazy import to avoid circular dependency
        from .storage_tasks import _run_delete_external_task
        background_tasks.add_task(
            _run_delete_external_task,
            task_id,
            str(user.id),
            external_wsi_ids
        )

        return {
            "task_id": task_id,
            "message": f"Unbind dataset task started for '{dataset_name}'",
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "total_files": len(external_wsi_ids)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start unbind dataset task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start unbind dataset task: {str(e)}")


@router.post("/check-external-files")
async def check_external_files(
    request: CheckExternalFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
        uploads_dir = str(Config.get_uploads_dir())

        # Get all WSI records with dataset relationship loaded, optionally filtered by dataset
        if request.dataset_id:
            wsi_list = await WSIRepository.get_by_dataset(db, request.dataset_id, limit=0)
        else:
            wsi_list = await WSIRepository.get_all_with_dataset(db, limit=0)

        # Extract plain data from ORM objects (ORM objects can't cross thread boundaries)
        wsi_data = [
            {
                "wsi_id": wsi.wsi_id,
                "original_filename": wsi.original_filename,
                "wsi_path": wsi.wsi_path,
                "dataset_id": wsi.dataset_id,
                "dataset_name": wsi.dataset.name if wsi.dataset else None,
                "label": wsi.label,
                "associated_files": wsi.associated_files,
            }
            for wsi in wsi_list
        ]

        # Run file availability checks in thread pool to avoid blocking event loop
        result = await asyncio.to_thread(_check_external_files_sync, wsi_data, uploads_dir)
        return result

    except Exception as e:
        logger.error(f"Failed to check external files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check external files: {str(e)}")


@router.post("/delete-unavailable-files")
async def delete_unavailable_files(
    request: DeleteUnavailableFilesRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
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
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": "WSI not found"
                    })
                    failed_count += 1
                    continue

                # Delete all associated child records before deleting the WSI
                # (PostgreSQL enforces FK constraints strictly)
                try:
                    await db.execute(
                        sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
                    )
                    await db.execute(
                        sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
                    )
                    await db.execute(
                        sql_delete(AITask).where(AITask.wsi_id == wsi_id)
                    )
                except Exception as assoc_error:
                    logger.warning(f"Failed to delete associated data for {wsi_id}: {assoc_error}")

                # Delete the WSI record
                success = await WSIRepository.delete(db, wsi_id)
                if success:
                    await db.commit()
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "deleted",
                        "message": "Record deleted successfully"
                    })
                    deleted_count += 1
                    logger.info(f"Deleted unavailable WSI record: {wsi_id}")
                else:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": "Failed to delete record"
                    })
                    failed_count += 1

            except Exception as e:
                results.append({
                    "wsi_id": wsi_id,
                    "status": "failed",
                    "message": str(e)
                })
                failed_count += 1
                logger.error(f"Failed to delete WSI record {wsi_id}: {e}")

        return {
            "deleted": deleted_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.error(f"Failed to delete unavailable files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete unavailable files: {str(e)}")