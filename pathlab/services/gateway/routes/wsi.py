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
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sql_delete

from pathlab.services.backend.database import get_db
from pathlab.services.backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)
from pathlab.services.backend.database.models import AIResult, AITask, TrainingTaskWSI
from ..dependencies import logger, storage_manager, UPLOADS_DIR, PREPROCESSING_SERVICE_URL
from ..models import UploadByPathRequest, DeletionMode
from ..utils import extract_wsi_properties

router = APIRouter(prefix="/wsi", tags=["WSI Management"])


@router.get("")
async def list_wsi(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all WSI slides with pagination"""
    wsi_slides = await WSIRepository.get_all(db, skip=skip, limit=limit)
    items = [wsi.to_dict() for wsi in wsi_slides]
    return {"items": items}


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
    label: Optional[str] = None,
    case_id: Optional[str] = None,
    age: Optional[int] = None,
    gender: Optional[str] = None,
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Update WSI metadata (label, case_id, age, gender, source).

    Args:
        wsi_id: The WSI ID to update
        label: New label (optional)
        case_id: New case_id (optional)
        age: New age (optional)
        gender: New gender (optional)
        source: New source/organ (optional)

    Returns:
        Updated WSI metadata
    """
    try:
        # Get WSI from database
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Update fields if provided
        if label is not None:
            wsi.label = label
        if case_id is not None:
            wsi.case_id = case_id
        if age is not None:
            wsi.age = age
        if gender is not None:
            wsi.gender = gender
        if source is not None:
            wsi.source = source

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
    label: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    wsi_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a WSI file.
    The file will be saved to uploads directory and metadata will be created in database.

    Args:
        file: WSI file to upload
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
            "file_size": int
        }

    Note: For privacy protection, wsi_id is now a UUID instead of the original filename.
    The original filename is stored internally but not exposed to the frontend.
    """
    try:
        # Store original filename for internal reference
        original_filename = Path(file.filename).stem

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

        file_extension = Path(file.filename).suffix
        wsi_path = wsi_files_dir / f"{wsi_id}{file_extension}"

        # Save uploaded file
        with open(wsi_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = wsi_path.stat().st_size
        logger.info(f"Saved WSI file: {wsi_path} ({file_size / (1024**2):.2f} MB)")
        logger.info(f"Original filename: {original_filename} -> UUID: {wsi_id}")

        # Extract WSI properties
        props = extract_wsi_properties(str(wsi_path))

        # Create database record with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "case_id": case_id,
            "label": label,
            "wsi_path": str(wsi_path),
            "age": age,
            "gender": gender,
            "source": source,
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

        return {
            "message": "WSI uploaded successfully",
            "wsi_id": wsi_id,
            "wsi_path": str(wsi_path),
            "file_size": file_size
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload WSI file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload WSI file: {str(e)}")


@router.post("/upload/path")
async def upload_wsi_by_path(req: UploadByPathRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a WSI by file path (without copying the file).
    This is useful when WSI files are already on the server.

    Args:
        req: UploadByPathRequest containing wsi_path and optional metadata

    Returns:
        {
            "wsi_id": str (UUID),
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str
        }

    Note: For privacy protection, wsi_id is now a UUID instead of the original filename.
    The original filename is stored internally but not exposed to the frontend.
    """
    try:
        # Validate file exists
        if not os.path.exists(req.wsi_path):
            raise HTTPException(status_code=404, detail=f"WSI file not found: {req.wsi_path}")

        # Store original filename for internal reference
        original_filename = Path(req.wsi_path).stem

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
            "label": req.label or "Unknown",
            "case_id": case_id,
            "wsi_path": req.wsi_path,
            "file_size": file_size,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
        }

        wsi = await WSIRepository.create(db, wsi_data)
        await db.commit()

        logger.info(f"Registered WSI by path in database: {wsi_id}")

        return {
            "wsi_id": wsi_id,
            "wsi_path": req.wsi_path,
            "label": wsi.label,
            "case_id": case_id,
            "message": "WSI registered successfully"
        }

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

