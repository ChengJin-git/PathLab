"""
WSI upload routes
Handles file upload, path registration, CSV batch upload, and CSV template download.
"""
import os
import uuid
import shutil
import csv
import io
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    DataGroupRepository,
    SegmentationAnnotationRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin
from ..dependencies import logger, storage_manager, UPLOADS_DIR
from ..models import UploadByPathRequest
from ..utils import (
    extract_wsi_properties,
    ensure_segmentation_contract,
    ensure_dataset_segmentation_contract,
    find_matching_segmentation_annotation_path,
    load_coco_annotation_bytes,
    load_coco_annotation_file,
)
from backend.common.file_types import is_patch_file
from backend.common.annotation_summary_cache import rebuild_dataset_annotation_summary_cache

router = APIRouter(prefix="/wsi/upload", tags=["WSI Upload"])

ALLOWED_TASK_TYPES = {"classification", "survival", "segmentation"}


def _resolve_task_type(requested_task_type: Optional[str], dataset_task_type: Optional[str] = None) -> str:
    resolved_task_type = requested_task_type or dataset_task_type or 'classification'
    if resolved_task_type not in ALLOWED_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail="task_type must be 'classification', 'survival', or 'segmentation'",
        )
    return resolved_task_type


@router.post("/csv")
async def upload_wsi_by_csv(
    file: UploadFile = File(...),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Batch register WSI files by uploading a CSV file.

    CSV format (with header):
    wsi_path,label,case_id,age,gender,source,wsi_id,event_time,event_status
    /path/to/slide1.svs,Benign,case_001,45,Female,Cervix,slide_001,,
    /path/to/slide2.svs,,case_002,52,Male,Lung,slide_002,365,1

    Notes:
    - wsi_path is required
    - label, case_id, age, gender, source, wsi_id are optional
    - If wsi_id is not provided, it will be auto-generated
    - If case_id is not provided, it will be auto-generated as "case_{wsi_id}"
    - If label is not provided, it will be set to "Unknown"
    - age should be an integer (patient age in years)
    - gender should be a string (e.g., Male, Female, Other)
    - source should be a string (organ/tissue source, e.g., Cervix, Lung, Breast)
    - event_time: time to event for survival analysis (float, days/months)
    - event_status: event status for survival analysis (1 = event occurred, 0 = censored)

    Returns:
        {
            "total": int,
            "success": int,
            "failed": int,
            "results": [
                {
                    "wsi_id": str,
                    "wsi_path": str,
                    "status": "success" | "failed",
                    "message": str
                }
            ]
        }
    """
    try:
        # Read CSV file
        content = await file.read()
        csv_text = content.decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        results = []
        success_count = 0
        failed_count = 0

        for row in csv_reader:
            wsi_path = row.get('wsi_path', '').strip()
            if not wsi_path:
                results.append({
                    "wsi_path": wsi_path,
                    "status": "failed",
                    "message": "wsi_path is required"
                })
                failed_count += 1
                continue

            # Get optional fields
            label = row.get('label', '').strip() or None
            case_id = row.get('case_id', '').strip() or None
            age_str = row.get('age', '').strip()
            age = int(age_str) if age_str and age_str.isdigit() else None
            gender = row.get('gender', '').strip() or None
            source = row.get('source', '').strip() or None
            wsi_id = row.get('wsi_id', '').strip() or None
            # Survival analysis fields
            event_time_str = row.get('event_time', '').strip()
            event_time = float(event_time_str) if event_time_str else None
            event_status_str = row.get('event_status', '').strip()
            event_status = int(event_status_str) if event_status_str and event_status_str.isdigit() else None

            try:
                # Validate file exists
                if not os.path.exists(wsi_path):
                    results.append({
                        "wsi_path": wsi_path,
                        "status": "failed",
                        "message": f"File not found: {wsi_path}"
                    })
                    failed_count += 1
                    continue

                # Store original filename for internal reference (including extension)
                original_filename = Path(wsi_path).name

                # Generate UUID-based wsi_id if not provided (for privacy protection)
                if not wsi_id:
                    wsi_id = str(uuid.uuid4())

                # Check if WSI already exists
                existing = await WSIRepository.get_by_id(db, wsi_id)
                if existing:
                    results.append({
                        "wsi_id": wsi_id,
                        "wsi_path": wsi_path,
                        "status": "failed",
                        "message": f"WSI already exists: {wsi_id}"
                    })
                    failed_count += 1
                    continue

                # Get file size
                file_size = os.path.getsize(wsi_path)

                # Extract WSI properties
                wsi_props = extract_wsi_properties(wsi_path)

                # Generate case_id if not provided
                if not case_id:
                    case_id = f"case_{wsi_id[:8]}"

                logger.info(f"Registering WSI from CSV: {original_filename} -> UUID: {wsi_id}")

                # Create WSI in database with original_filename for internal reference
                wsi_data = {
                    "wsi_id": wsi_id,
                    "original_filename": original_filename,
                    "label": label or "Unknown",
                    "case_id": case_id,
                    "wsi_path": wsi_path,
                    "file_size": file_size,
                    "age": age,
                    "gender": gender,
                    "source": source,
                    "event_time": event_time,
                    "event_status": event_status,
                    "mpp": wsi_props["mpp"],
                    "vendor": wsi_props["vendor"],
                    "width": wsi_props["width"],
                    "height": wsi_props["height"],
                    "magnification": wsi_props["magnification"],
                    "user_id": str(user.id),  # Associate with current user
                }

                wsi = await WSIRepository.create(db, wsi_data)
                await db.commit()

                # Save metadata to JSON file for persistence
                try:
                    storage_manager.save_wsi_metadata(wsi_id, wsi_data)
                except Exception as meta_err:
                    logger.warning(f"Failed to save metadata file for {wsi_id}: {meta_err}")

                results.append({
                    "wsi_id": wsi_id,
                    "wsi_path": wsi_path,
                    "label": wsi.label,
                    "case_id": case_id,
                    "status": "success",
                    "message": "WSI registered successfully"
                })
                success_count += 1

                logger.info(f"Registered WSI from CSV: {wsi_id}")

            except Exception as e:
                results.append({
                    "wsi_path": wsi_path,
                    "wsi_id": wsi_id if wsi_id else "N/A",
                    "status": "failed",
                    "message": str(e)
                })
                failed_count += 1
                logger.error(f"Failed to register WSI from CSV: {wsi_path}, error: {e}")

        logger.info(f"CSV batch upload completed: {success_count} success, {failed_count} failed")

        return {
            "total": success_count + failed_count,
            "success": success_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.error(f"Failed to process CSV file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process CSV file: {str(e)}")



@router.post("/file")
async def upload_wsi_file(
    file: UploadFile = File(...),
    associated_files: List[UploadFile] = File(default=[]),
    dataset_id: Optional[str] = Form(None),  # Existing dataset UUID
    dataset_name: Optional[str] = Form(None),  # Display name for new dataset
    aggregation_level: Optional[str] = Form(None),  # Aggregation level for new dataset: "case" or "file"
    task_type: Optional[str] = Form(None),
    label: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    wsi_id: Optional[str] = Form(None),
    # Survival analysis fields
    event_time: Optional[float] = Form(None),
    event_status: Optional[int] = Form(None),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a WSI file with optional associated files.
    All authenticated users can upload WSI files.

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

        file_data_type = 'patch' if is_patch_file(str(wsi_path)) else 'wsi'
        resolved_task_type = _resolve_task_type(task_type)
        segmentation_annotation = None

        if task_type == 'segmentation':
            ensure_segmentation_contract(
                task_type,
                file_data_type,
                aggregation_level or 'file',
                context='WSI upload',
            )

        # Handle associated files for special formats (MRXS, TMAP)
        associated_count = 0
        if associated_files and resolved_task_type != 'segmentation':
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

        props = extract_wsi_properties(str(wsi_path))

        # Resolve dataset_id: use provided dataset_id, or create new dataset from dataset_name
        resolved_dataset_id = None
        resolved_aggregation_level = aggregation_level or "file"
        if dataset_id:
            # Validate provided dataset_id exists
            existing_dataset = await DatasetRepository.get_by_id(db, dataset_id)
            if not existing_dataset:
                raise HTTPException(status_code=400, detail=f"Dataset not found: {dataset_id}")
            data_group = existing_dataset.data_group
            if not data_group:
                raise HTTPException(status_code=400, detail='Dataset has no associated DataGroup')
            resolved_task_type = _resolve_task_type(task_type, data_group.task_type)
            if task_type and data_group.task_type != task_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset task_type is '{data_group.task_type}', expected '{task_type}'",
                )
            if data_group.data_type != file_data_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset data_type is '{data_group.data_type}', cannot upload '{file_data_type}' file",
                )
            ensure_dataset_segmentation_contract(existing_dataset, context='WSI upload', expected_task_type=resolved_task_type)
            resolved_aggregation_level = data_group.aggregation_level
            resolved_dataset_id = dataset_id
        elif dataset_name:
            resolved_aggregation_level = aggregation_level or "file"
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context='WSI upload',
            )

            # Get or create DataGroup first
            data_group = await DataGroupRepository.get_or_create(
                db,
                data_type=file_data_type,
                aggregation_level=resolved_aggregation_level,
                task_type=resolved_task_type
            )

            # Create or get dataset by name with group_id
            dataset = await DatasetRepository.get_or_create(
                db, dataset_name, group_id=data_group.group_id, user_id=str(user.id)
            )
            resolved_dataset_id = dataset.dataset_id

        if resolved_task_type == 'segmentation' and segmentation_annotation is None:
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context='WSI upload',
            )
            if len(associated_files) != 1:
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation upload requires exactly one same-name COCO JSON annotation per image",
                )
            annotation_upload = associated_files[0]
            annotation_name = Path(annotation_upload.filename or '').name
            if Path(annotation_name).suffix.lower() != '.json':
                raise HTTPException(status_code=400, detail='Segmentation annotation must be a .json file')
            if Path(annotation_name).stem.lower() != Path(original_filename).stem.lower():
                raise HTTPException(
                    status_code=400,
                    detail='Segmentation annotation filename must match the image filename stem',
                )
            segmentation_annotation = load_coco_annotation_bytes(
                await annotation_upload.read(),
                source_name=annotation_name,
            )

        # Create database record with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "dataset_id": resolved_dataset_id,
            "case_id": case_id,
            "label": "Segmentation" if resolved_task_type == 'segmentation' else label,
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
            "user_id": str(user.id),  # Associate with current user
        }

        # Race-condition safe: catch IntegrityError if concurrent upload
        # with same wsi_id passes the existence check above (PostgreSQL READ COMMITTED)
        try:
            await WSIRepository.create(db, wsi_data)
            if resolved_task_type == 'segmentation':
                await SegmentationAnnotationRepository.upsert(
                    db,
                    annotation_id=f"annot_{wsi_id}",
                    user_id=str(user.id),
                    annotations=segmentation_annotation,
                    source_dataset_id=resolved_dataset_id,
                    status="finalized",
                    source="upload",
                )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"WSI ID already exists: {wsi_id}")

        logger.info(f"Created WSI record in database: {wsi_id}")

        if resolved_task_type == 'segmentation' and resolved_dataset_id:
            try:
                await rebuild_dataset_annotation_summary_cache(db, resolved_dataset_id)
                await db.commit()
            except Exception as cache_err:
                await db.rollback()
                logger.warning(f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}")

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


@router.post("/path")
async def upload_wsi_by_path(
    req: UploadByPathRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Register a WSI by file path (without copying the file).
    This is useful when WSI files are already on the server.
    All authenticated users can register WSI files.

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
        file_data_type = 'patch' if is_patch_file(req.wsi_path) else 'wsi'

        # Extract WSI properties
        wsi_props = extract_wsi_properties(req.wsi_path)

        # Generate case_id if not provided
        case_id = req.case_id or f"case_{wsi_id[:8]}"

        logger.info(f"Registering WSI: {original_filename} -> UUID: {wsi_id}")

        resolved_task_type = _resolve_task_type(req.task_type)
        segmentation_annotation = None
        if req.task_type == 'segmentation':
            annotation_path = find_matching_segmentation_annotation_path(req.wsi_path)
            if annotation_path is None:
                raise HTTPException(
                    status_code=400,
                    detail='Segmentation upload requires a same-name COCO JSON annotation beside the image file',
                )
            segmentation_annotation = load_coco_annotation_file(annotation_path)

        # Resolve dataset_id: use provided dataset_id, or create new dataset from dataset_name
        resolved_dataset_id = None
        resolved_aggregation_level = req.aggregation_level or "file"
        if req.dataset_id:
            existing_dataset = await DatasetRepository.get_by_id(db, req.dataset_id)
            if not existing_dataset:
                raise HTTPException(status_code=400, detail=f"Dataset not found: {req.dataset_id}")
            data_group = existing_dataset.data_group
            if not data_group:
                raise HTTPException(status_code=400, detail='Dataset has no associated DataGroup')
            resolved_task_type = _resolve_task_type(req.task_type, data_group.task_type)
            if req.task_type and data_group.task_type != req.task_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset task_type is '{data_group.task_type}', expected '{req.task_type}'",
                )
            if data_group.data_type != file_data_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset data_type is '{data_group.data_type}', cannot register '{file_data_type}' file",
                )
            ensure_dataset_segmentation_contract(existing_dataset, context='WSI path registration', expected_task_type=resolved_task_type)
            resolved_aggregation_level = data_group.aggregation_level
            resolved_dataset_id = req.dataset_id
        elif req.dataset_name:
            resolved_aggregation_level = req.aggregation_level or "file"
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context='WSI path registration',
            )

            # Get or create DataGroup first
            data_group = await DataGroupRepository.get_or_create(
                db,
                data_type=file_data_type,
                aggregation_level=resolved_aggregation_level,
                task_type=resolved_task_type
            )

            # Create or get dataset by name with group_id
            dataset = await DatasetRepository.get_or_create(
                db, req.dataset_name, group_id=data_group.group_id, user_id=str(user.id)
            )
            resolved_dataset_id = dataset.dataset_id

        if resolved_task_type == 'segmentation' and segmentation_annotation is None:
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context='WSI path registration',
            )
            annotation_path = find_matching_segmentation_annotation_path(req.wsi_path)
            if annotation_path is None:
                raise HTTPException(
                    status_code=400,
                    detail='Segmentation upload requires a same-name COCO JSON annotation beside the image file',
                )
            segmentation_annotation = load_coco_annotation_file(annotation_path)

        # Create WSI in database with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "dataset_id": resolved_dataset_id,
            "label": "Segmentation" if resolved_task_type == 'segmentation' else (req.label or "Unknown"),
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
            "user_id": str(user.id),  # Associate with current user
        }

        # Race-condition safe: catch IntegrityError if concurrent register
        # with same wsi_id passes the existence check above (PostgreSQL READ COMMITTED)
        try:
            wsi = await WSIRepository.create(db, wsi_data)
            if resolved_task_type == 'segmentation':
                await SegmentationAnnotationRepository.upsert(
                    db,
                    annotation_id=f"annot_{wsi_id}",
                    user_id=str(user.id),
                    annotations=segmentation_annotation,
                    source_dataset_id=resolved_dataset_id,
                    status="finalized",
                    source="upload_path",
                )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"WSI already exists: {wsi_id}")

        logger.info(f"Registered WSI by path in database: {wsi_id}")

        if resolved_task_type == 'segmentation' and resolved_dataset_id:
            try:
                await rebuild_dataset_annotation_summary_cache(db, resolved_dataset_id)
                await db.commit()
            except Exception as cache_err:
                await db.rollback()
                logger.warning(f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}")

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

        # Check association but don't return full object to keep response clean
        if associated_data:
            response["associated_data_count"] = len(associated_data)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register WSI by path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to register WSI by path: {str(e)}")


@router.get("/csv/template")
async def get_csv_template(
    task_type: str = Query("classification", description="Task type: 'classification', 'survival', or 'segmentation'"),
    user: User = Depends(current_active_user)
):
    """
    Download a CSV template for batch WSI metadata configuration.
    Requires authentication.

    Required columns:
    - filename: The original filename of the WSI slide
    - For classification: label (required)
    - For survival: event_time, event_status (required)
    - For segmentation: no label required — masks are provided via COCO JSON separately

    Optional columns:
    - split (train, val, test), case_id, age, gender, source

    Note: If no 'val' split is provided, 10% of 'train' samples will be
    automatically assigned to 'val' during upload.
    """
    if task_type == "survival":
        # Survival analysis template
        headers = ["filename", "split", "event_time", "event_status", "case_id", "age", "gender", "source"]
        examples = [
            {"filename": "slide1.svs", "split": "train", "event_time": "24.5", "event_status": "1",
             "case_id": "CASE001", "age": "65", "gender": "Male", "source": "Lung"},
            {"filename": "slide2.svs", "split": "val", "event_time": "36.0", "event_status": "0",
             "case_id": "CASE002", "age": "50", "gender": "Female", "source": "Lung"},
            {"filename": "slide3.svs", "split": "test", "event_time": "48.0", "event_status": "1",
             "case_id": "CASE003", "age": "70", "gender": "Male", "source": "Lung"}
        ]
        filename = "wsi_survival_metadata_template.csv"
    elif task_type == "segmentation":
        # Segmentation template — no label column; masks are provided via COCO JSON separately
        headers = ["filename", "split", "case_id", "age", "gender", "source"]
        examples = [
            {"filename": "image_001.png", "split": "train",
             "case_id": "CASE001", "age": "", "gender": "", "source": ""},
            {"filename": "image_002.png", "split": "val",
             "case_id": "CASE002", "age": "", "gender": "", "source": ""},
            {"filename": "image_003.png", "split": "test",
             "case_id": "CASE003", "age": "", "gender": "", "source": ""}
        ]
        filename = "segmentation_metadata_template.csv"
    else:
        # Classification template (default)
        headers = ["filename", "split", "label", "case_id", "age", "gender", "source"]
        examples = [
            {"filename": "slide1.svs", "split": "train", "label": "Tumor",
             "case_id": "CASE001", "age": "65", "gender": "Male", "source": "Lung"},
            {"filename": "slide2.svs", "split": "val", "label": "Normal",
             "case_id": "CASE002", "age": "50", "gender": "Female", "source": "Lung"},
            {"filename": "slide3.svs", "split": "test", "label": "Tumor",
             "case_id": "CASE003", "age": "70", "gender": "Male", "source": "Lung"}
        ]
        filename = "wsi_classification_metadata_template.csv"

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(examples)

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/coco/template")
async def get_coco_annotation_template(
    user: User = Depends(current_active_user)
):
    """
    Download COCO annotation JSON template for segmentation datasets.
    Requires authentication.
    """
    import json
    template_path = Path(__file__).parent.parent.parent / "backend" / "ai" / "utils" / "dataset_template" / "segmentation_annotation.json"

    if not template_path.exists():
        raise HTTPException(status_code=404, detail="COCO annotation template not found")

    with open(template_path, "r") as f:
        content = f.read()

    return StreamingResponse(
        io.BytesIO(content.encode('utf-8')),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=segmentation_annotation_template.json"}
    )