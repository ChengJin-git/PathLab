"""
WSI management routes
Handles WSI CRUD operations, file uploads, and metadata management
"""
import os
import uuid
import shutil
import csv
import io
import httpx
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sql_delete

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)
from backend.database.models import AIResult, AITask, TrainingTaskWSI
from ..dependencies import logger, storage_manager, UPLOADS_DIR, PREPROCESSING_SERVICE_URL
from ..models import UploadByPathRequest, DeletionMode, WSIMetadataUpdateRequest, DatasetRenameRequest
from ..utils import extract_wsi_properties

router = APIRouter(prefix="/wsi", tags=["WSI Management"])


@router.get("")
async def list_wsi(
    skip: int = 0,
    limit: int = 0,
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name"),
    db: AsyncSession = Depends(get_db)
):
    """List all WSI slides with pagination. If limit=0, return all records.
    If dataset_name is provided, filter by dataset."""
    if dataset_name is not None:
        wsi_slides = await WSIRepository.get_by_dataset(db, dataset_name, skip=skip, limit=limit)
        total = await WSIRepository.count_by_dataset(db, dataset_name)
    else:
        wsi_slides = await WSIRepository.get_all(db, skip=skip, limit=limit)
        total = await WSIRepository.count(db)
    items = [wsi.to_dict() for wsi in wsi_slides]
    return {"items": items, "total": total}


@router.get("/datasets")
async def list_datasets(
    data_level: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List all unique dataset names with file count and total size.

    Args:
        data_level: Optional filter - "wsi" for WSI files, "patch" for image files

    Returns:
        {
            "datasets": [
                {"dataset_name": str, "file_count": int, "total_size": int},
                ...
            ]
        }
    """
    datasets = await WSIRepository.get_datasets(db, data_level=data_level)
    return {"datasets": datasets}


@router.put("/datasets")
async def rename_dataset(
    req: DatasetRenameRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Rename a dataset.
    Updates all WSI files belonging to 'old_name' to have 'new_name'.
    """
    try:
        count = await WSIRepository.rename_dataset(db, req.old_name, req.new_name)
        return {"message": "Dataset renamed successfully", "updated_count": count}
    except Exception as e:
        logger.error(f"Failed to rename dataset: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rename dataset: {str(e)}")


@router.post("/check-duplicates")
async def check_duplicate_filenames(
    filenames: List[str],
    db: AsyncSession = Depends(get_db)
):
    """
    Check which filenames already exist in the database.

    This endpoint is used by the frontend to skip uploading files
    that already exist (based on original_filename).

    For special formats:
    - MRXS: Check by the .mrxs filename (e.g., "slide.mrxs")
    - TMAP: Check by the .tmap filename (e.g., "slide.tmap")
    - Standard: Check by the full filename (e.g., "slide.svs")

    Args:
        filenames: List of filenames to check

    Returns:
        {
            "duplicates": ["slide1.svs", "slide2.mrxs"],  # filenames that exist
            "new": ["slide3.ndpi"]  # filenames that don't exist
        }
    """
    if not filenames:
        return {"duplicates": [], "new": []}

    existing = await WSIRepository.get_existing_original_filenames(db, filenames)
    existing_set = set(existing)

    duplicates = [f for f in filenames if f in existing_set]
    new_files = [f for f in filenames if f not in existing_set]

    return {"duplicates": duplicates, "new": new_files}


@router.get("/{wsi_id}")
async def get_wsi(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """Get WSI metadata and latest result"""
    wsi = await WSIRepository.get_by_id(db, wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Get latest result
    last_result = await AIResultRepository.get_by_wsi_id(db, wsi_id)

    return {
        "wsi_id": wsi_id,
        "meta": wsi.to_dict(),
        "last_run": last_result.to_dict() if last_result else None
    }


@router.delete("/{wsi_id}")
async def delete_wsi(
    wsi_id: str,
    mode: DeletionMode = DeletionMode.STANDARD,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a WSI and its associated data.

    This will:
    1. Delete training task associations (TrainingTaskWSI)
    2. Delete all AI results associated with this WSI
    3. Delete all AI tasks associated with this WSI
    4. Delete the WSI record from database
    5. Delete WSI files using StorageManager (mode-dependent):

    Standard mode (recommended):
       - WSI file itself
       - Coordinates cache
       - Thumbnail
       - Mask
       - AI results directory
       - Keep training features (valuable for research)

    Complete mode:
       - All files from standard mode
       - Feature files from all training tasks

    Args:
        wsi_id: The WSI ID to delete
        mode: Deletion mode (DeletionMode.STANDARD or DeletionMode.COMPLETE)

    Returns:
        {
            "message": "WSI deleted successfully",
            "wsi_id": str,
            "storage_cleanup": dict  # Storage cleanup results
        }
    """
    try:
        # Get WSI from database
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        wsi_path = wsi.wsi_path

        # Delete all associated data before deleting the WSI
        # Using raw SQL for efficiency
        try:
            # Delete training task associations first (foreign key constraint)
            await db.execute(
                sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
            )

            # Delete AI results
            await db.execute(
                sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
            )

            # Delete AI tasks
            await db.execute(
                sql_delete(AITask).where(AITask.wsi_id == wsi_id)
            )
        except Exception as e:
            logger.warning(f"Failed to delete associated data for {wsi_id}: {e}")

        # Delete WSI from database
        await WSIRepository.delete(db, wsi_id)
        await db.commit()

        # Delete all files using StorageManager with specified mode
        storage_cleanup = storage_manager.delete_wsi_files(wsi_id, wsi_path, mode=mode.value)
        logger.info(storage_cleanup['summary'])

        return {
            "message": "WSI deleted successfully",
            "wsi_id": wsi_id,
            "storage_cleanup": storage_cleanup
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete WSI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete WSI: {str(e)}")


@router.patch("/{wsi_id}")
async def update_wsi_metadata(
    wsi_id: str,
    req: WSIMetadataUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Update WSI metadata (label, case_id, age, gender, source).

    Args:
        wsi_id: The WSI ID to update
        req: WSIMetadataUpdateRequest containing fields to update

    Returns:
        Updated WSI metadata
    """
    try:
        # Get WSI from database
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Update fields if provided
        if req.label is not None:
            wsi.label = req.label
        if req.case_id is not None:
            wsi.case_id = req.case_id
        if req.age is not None:
            wsi.age = req.age
        if req.gender is not None:
            wsi.gender = req.gender
        if req.source is not None:
            wsi.source = req.source
        # Survival analysis fields
        if req.event_time is not None:
            wsi.event_time = req.event_time
        if req.event_status is not None:
            wsi.event_status = req.event_status

        await db.commit()
        await db.refresh(wsi)

        logger.info(f"Updated WSI metadata: {wsi_id}")

        return {
            "message": "WSI metadata updated successfully",
            "wsi": wsi.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update WSI metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update WSI metadata: {str(e)}")


@router.post("/upload/file")
async def upload_wsi_file(
    file: UploadFile = File(...),
    associated_files: List[UploadFile] = File(default=[]),
    dataset_name: Optional[str] = Form(None),
    label: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    wsi_id: Optional[str] = Form(None),
    # Survival analysis fields
    event_time: Optional[float] = Form(None),
    event_status: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a WSI file with optional associated files.

    For special formats:
    - MRXS: Upload .mrxs file + data folder contents as associated_files
    - TMAP: Upload .TMAP file + .DT1, .DT2, etc. as associated_files

    The files will be saved to uploads directory and metadata will be created in database.

    Args:
        file: Main WSI file to upload
        associated_files: Associated data files (MRXS folder contents or TMAP DT files)
        label: Diagnosis label (optional)
        case_id: Case identifier (optional)
        age: Patient age (optional)
        gender: Patient gender (optional)
        source: Tissue source/organ (optional)
        wsi_id: Custom WSI ID (optional, UUID auto-generated if not provided)

    Returns:
        {
            "message": "WSI uploaded successfully",
            "wsi_id": str (UUID),
            "wsi_path": str,
            "file_size": int,
            "associated_files_count": int
        }

    Note: For privacy protection, wsi_id is now a UUID instead of the original filename.
    The original filename is stored internally but not exposed to the frontend.
    """
    try:
        # Store original filename for internal reference (including extension)
        original_filename = Path(file.filename).name
        file_extension = Path(file.filename).suffix.lower()

        # Generate UUID-based wsi_id if not provided (for privacy protection)
        if not wsi_id:
            wsi_id = str(uuid.uuid4())

        # Check if wsi_id already exists
        existing = await WSIRepository.get_by_id(db, wsi_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"WSI ID already exists: {wsi_id}")

        # Save file to uploads directory using UUID-based filename
        wsi_files_dir = Path(UPLOADS_DIR) / "wsi_files"
        wsi_files_dir.mkdir(exist_ok=True, parents=True)

        wsi_path = wsi_files_dir / f"{wsi_id}{file_extension}"

        # Save main WSI file
        with open(wsi_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = wsi_path.stat().st_size
        logger.info(f"Saved WSI file: {wsi_path} ({file_size / (1024**2):.2f} MB)")
        logger.info(f"Original filename: {original_filename} -> UUID: {wsi_id}")

        # Handle associated files for special formats (MRXS, TMAP)
        associated_count = 0
        if associated_files:
            if file_extension == '.mrxs':
                # MRXS: Create data folder with same name as UUID
                data_folder = wsi_files_dir / wsi_id
                data_folder.mkdir(exist_ok=True, parents=True)

                for assoc_file in associated_files:
                    if assoc_file.filename:
                        # Preserve relative path structure from original folder
                        assoc_path = data_folder / Path(assoc_file.filename).name
                        with open(assoc_path, "wb") as buffer:
                            shutil.copyfileobj(assoc_file.file, buffer)
                        associated_count += 1

                logger.info(f"Saved MRXS data folder with {associated_count} files: {data_folder}")

            elif file_extension == '.tmap':
                # TMAP: Save DT files with same UUID base name
                for assoc_file in associated_files:
                    if assoc_file.filename:
                        # Get the DT extension (e.g., .DT1, .DT2)
                        dt_ext = Path(assoc_file.filename).suffix
                        dt_path = wsi_files_dir / f"{wsi_id}{dt_ext}"
                        with open(dt_path, "wb") as buffer:
                            shutil.copyfileobj(assoc_file.file, buffer)
                        associated_count += 1

                logger.info(f"Saved {associated_count} TMAP DT files for: {wsi_id}")

        # Extract WSI properties
        props = extract_wsi_properties(str(wsi_path))

        # Create database record with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "dataset_name": dataset_name,
            "case_id": case_id,
            "label": label,
            "wsi_path": str(wsi_path),
            "age": age,
            "gender": gender,
            "source": source,
            "event_time": event_time,
            "event_status": event_status,
            "mpp": props.get("mpp"),
            "vendor": props.get("vendor"),
            "width": props.get("width"),
            "height": props.get("height"),
            "magnification": props.get("magnification"),
            "file_size": file_size,
        }

        await WSIRepository.create(db, wsi_data)
        await db.commit()

        logger.info(f"Created WSI record in database: {wsi_id}")

        # Save metadata to JSON file for persistence
        try:
            storage_manager.save_wsi_metadata(wsi_id, wsi_data)
        except Exception as e:
            logger.warning(f"Failed to save metadata file for {wsi_id}: {e}")

        return {
            "message": "WSI uploaded successfully",
            "wsi_id": wsi_id,
            "wsi_path": str(wsi_path),
            "file_size": file_size,
            "associated_files_count": associated_count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload WSI file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload WSI file: {str(e)}")


def _validate_mrxs_data_folder(wsi_path: str) -> Optional[str]:
    """
    Validate that MRXS file has its required data folder.
    MRXS format requires: <name>.mrxs + <name>/ folder (same name, no extension)

    Returns the data folder path if valid, None if missing.
    """
    wsi_file = Path(wsi_path)
    if wsi_file.suffix.lower() != '.mrxs':
        return None

    # Data folder should be same name without extension
    data_folder = wsi_file.parent / wsi_file.stem
    if data_folder.exists() and data_folder.is_dir():
        return str(data_folder)
    return None


def _find_tmap_data_files(wsi_path: str) -> List[str]:
    """
    Find associated DT files for TMAP format.
    TMAP format may have: <name>.TMAP + <name>.DT1 + <name>.DT2 + ... (optional)

    Returns list of DT file paths.
    """
    wsi_file = Path(wsi_path)
    if wsi_file.suffix.lower() != '.tmap':
        return []

    base_name = wsi_file.stem
    parent_dir = wsi_file.parent
    dt_files = []

    # Look for .DT1, .DT2, ... files with same base name
    for file in parent_dir.iterdir():
        if file.stem == base_name and file.suffix.lower().startswith('.dt'):
            # Verify it's a DT file (e.g., .DT1, .DT2, etc.)
            suffix_num = file.suffix[3:]  # Remove '.DT' or '.dt'
            if suffix_num.isdigit():
                dt_files.append(str(file))

    return sorted(dt_files)


@router.post("/upload/path")
async def upload_wsi_by_path(req: UploadByPathRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a WSI by file path (without copying the file).
    This is useful when WSI files are already on the server.

    For special formats:
    - MRXS: Automatically validates that the data folder exists
    - TMAP: Automatically detects associated DT files

    Args:
        req: UploadByPathRequest containing wsi_path and optional metadata

    Returns:
        {
            "wsi_id": str (UUID),
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str,
            "associated_data": dict (for MRXS/TMAP)
        }

    Note: For privacy protection, wsi_id is now a UUID instead of the original filename.
    The original filename is stored internally but not exposed to the frontend.
    """
    try:
        # Validate file exists
        if not os.path.exists(req.wsi_path):
            raise HTTPException(status_code=404, detail=f"WSI file not found: {req.wsi_path}")

        wsi_file = Path(req.wsi_path)
        file_extension = wsi_file.suffix.lower()

        # Validate and detect associated files for special formats
        associated_data = {}

        if file_extension == '.mrxs':
            data_folder = _validate_mrxs_data_folder(req.wsi_path)
            if not data_folder:
                raise HTTPException(
                    status_code=400,
                    detail=f"MRXS file requires a data folder with the same name. Expected: {wsi_file.stem}/"
                )
            associated_data['mrxs_data_folder'] = data_folder
            logger.info(f"Found MRXS data folder: {data_folder}")

        elif file_extension == '.tmap':
            dt_files = _find_tmap_data_files(req.wsi_path)
            if dt_files:
                associated_data['tmap_dt_files'] = dt_files
                logger.info(f"Found {len(dt_files)} TMAP DT files: {dt_files}")

        # Store original filename for internal reference (including extension)
        original_filename = wsi_file.name

        # Generate UUID-based wsi_id if not provided (for privacy protection)
        if not req.wsi_id:
            wsi_id = str(uuid.uuid4())
        else:
            wsi_id = req.wsi_id

        # Check if WSI already exists in database
        existing = await WSIRepository.get_by_id(db, wsi_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"WSI already exists: {wsi_id}")

        # Get file size
        file_size = os.path.getsize(req.wsi_path)

        # Extract WSI properties
        wsi_props = extract_wsi_properties(req.wsi_path)

        # Generate case_id if not provided
        case_id = req.case_id or f"case_{wsi_id[:8]}"

        logger.info(f"Registering WSI: {original_filename} -> UUID: {wsi_id}")

        # Create WSI in database with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "dataset_name": req.dataset_name,
            "label": req.label or "Unknown",
            "case_id": case_id,
            "wsi_path": req.wsi_path,
            "file_size": file_size,
            "age": req.age,
            "gender": req.gender,
            "source": req.source,
            "event_time": req.event_time,
            "event_status": req.event_status,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
        }

        wsi = await WSIRepository.create(db, wsi_data)
        await db.commit()

        logger.info(f"Registered WSI by path in database: {wsi_id}")

        # Save metadata to JSON file for persistence
        try:
            storage_manager.save_wsi_metadata(wsi_id, wsi_data)
        except Exception as e:
            logger.warning(f"Failed to save metadata file for {wsi_id}: {e}")

        response = {
            "wsi_id": wsi_id,
            "wsi_path": req.wsi_path,
            "label": wsi.label,
            "case_id": case_id,
            "message": "WSI registered successfully"
        }

        # Include associated data info for special formats
        if associated_data:
            response["associated_data"] = associated_data

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register WSI by path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to register WSI by path: {str(e)}")


@router.get("/upload/csv/template")
async def download_csv_template():
    """
    Download CSV template for batch WSI upload.

    Returns a CSV file with headers and example rows.
    """
    # Create CSV content with headers and example rows
    csv_content = """wsi_path,label,case_id,age,gender,source,wsi_id
/path/to/slide1.svs,Benign,case_001,45,Female,Cervix,slide_001
/path/to/slide2.svs,Malignant,case_002,52,Male,Lung,slide_002
/path/to/slide3.svs,Normal,case_003,38,Female,Breast,slide_003"""

    # Create a file-like object
    csv_file = io.StringIO(csv_content)

    # Return as downloadable file
    return StreamingResponse(
        iter([csv_file.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=wsi_upload_template.csv"
        }
    )


@router.post("/{wsi_id}/compute_patches")
async def compute_patches(
    wsi_id: str,
    patch_size: int = Query(512, description="Patch size (e.g., 256, 512)"),
    stride: int = Query(0, description="Stride between patches (0 = no overlap)"),
    level: int = Query(0, description="Pyramid level (0 = highest resolution)"),
    force_recompute: bool = Query(False, description="Force recompute even if patches exist"),
    sthresh: int = Query(5, description="Saturation threshold (0-255, low threshold for maximum tissue detection)"),
    mthresh: int = Query(7, description="Median filter kernel size (must be odd, default: 7)"),
    close: int = Query(4, description="Morphological closing kernel size (default: 4)"),
    use_otsu: bool = Query(False, description="Use Otsu auto-thresholding"),
    contour_fn: str = Query("four_pt", description="Contour check function (four_pt, center, basic)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Proxy endpoint to compute patches via preprocessing service.

    This endpoint forwards the request to the preprocessing service
    to maintain a unified API interface through the Gateway.
    """
    logger.info(f"Proxying compute_patches request for WSI: {wsi_id}")

    # Verify WSI exists in database
    wsi = await WSIRepository.get_by_id(db, wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="WSI not found")

    # Build query parameters
    params = {
        "patch_size": patch_size,
        "stride": stride,
        "level": level,
        "force_recompute": force_recompute,
        "sthresh": sthresh,
        "mthresh": mthresh,
        "close": close,
        "use_otsu": use_otsu,
        "contour_fn": contour_fn
    }

    # Forward request to preprocessing service
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Preprocessing service error: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Preprocessing service error: {response.text}"
                )

            result = response.json()
            logger.info(f"Successfully computed patches for WSI: {wsi_id}")
            return result

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from preprocessing service: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Preprocessing service error: {e.response.text}"
        )
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to preprocessing service: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Preprocessing service unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to compute patches: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compute patches: {str(e)}"
        )

