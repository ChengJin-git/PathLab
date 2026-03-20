"""
WSI upload routes
Handles file upload, path registration, CSV batch upload, and CSV template download.
"""

import os
import uuid
import shutil
import asyncio
import csv
import io
from pathlib import Path
from typing import Optional, List, Any
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
    DatasetStatsRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership
from ..dependencies import logger, storage_manager, UPLOADS_DIR
from ..models import UploadByPathRequest
from ..utils import (
    align_dataset_data_type_for_file,
    ensure_segmentation_contract,
    ensure_dataset_segmentation_contract,
    find_matching_segmentation_annotation_path,
    get_wsi_effective_file_size,
    load_coco_annotation_bytes,
    load_coco_annotation_file,
    resolve_file_data_type_and_properties,
)
from backend.common.annotation_summary_cache import (
    rebuild_dataset_annotation_summary_cache,
)
from backend.common.annotation_pubsub import publish as publish_annotation_event

router = APIRouter(prefix="/wsi/upload", tags=["WSI Upload"])

ALLOWED_TASK_TYPES = {"classification", "survival", "segmentation"}


def _resolve_task_type(
    requested_task_type: Optional[str], dataset_task_type: Optional[str] = None
) -> str:
    resolved_task_type = requested_task_type or dataset_task_type or "classification"
    if resolved_task_type not in ALLOWED_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail="task_type must be 'classification', 'survival', or 'segmentation'",
        )
    return resolved_task_type


def _find_matching_uploaded_segmentation_annotation(
    associated_files: List[UploadFile],
    image_name: str,
) -> Optional[UploadFile]:
    target_stem = Path(image_name).stem.lower()
    for associated_file in associated_files or []:
        associated_name = Path(associated_file.filename or "").name
        if Path(associated_name).suffix.lower() != ".json":
            continue
        if Path(associated_name).stem.lower() == target_stem:
            return associated_file
    return None


async def _save_upload_file(upload_file, dest_path: Path) -> None:
    chunk_size = 1024 * 1024
    with open(dest_path, "wb") as f:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)


def _build_dataset_segmentation_wsi_lookup(
    dataset_wsis: List[object],
) -> dict[str, object]:
    stem_lookup: dict[str, Optional[object]] = {}
    duplicate_stems: set[str] = set()

    for dataset_wsi in dataset_wsis:
        candidate_name = Path(
            getattr(dataset_wsi, "original_filename", None)
            or getattr(dataset_wsi, "wsi_path", "")
        ).name
        candidate_stem = Path(candidate_name).stem.lower()
        if not candidate_stem:
            continue

        if candidate_stem in stem_lookup:
            duplicate_stems.add(candidate_stem)
            stem_lookup[candidate_stem] = None
        else:
            stem_lookup[candidate_stem] = dataset_wsi

    return {
        stem: dataset_wsi
        for stem, dataset_wsi in stem_lookup.items()
        if stem not in duplicate_stems and dataset_wsi is not None
    }


async def _append_segmentation_annotation_to_existing_dataset(
    db: AsyncSession,
    *,
    dataset_id: str,
    annotation_name: str,
    annotation_payload: dict[str, Any],
    user_id: str,
    source: str,
):
    dataset_wsis = await WSIRepository.get_by_dataset(db, dataset_id)
    stem_lookup = _build_dataset_segmentation_wsi_lookup(dataset_wsis)
    matched_wsi = stem_lookup.get(Path(annotation_name).stem.lower())

    if matched_wsi is None:
        raise HTTPException(
            status_code=400,
            detail=f"No existing segmentation image found in dataset for annotation '{annotation_name}'",
        )

    await SegmentationAnnotationRepository.upsert(
        db,
        annotation_id=f"annot_{matched_wsi.wsi_id}",
        user_id=user_id,
        annotations=annotation_payload,
        source_dataset_id=dataset_id,
        status="finalized",
        visibility_mode="inherit",
        source=source,
    )
    return matched_wsi


@router.post("/csv")
async def upload_wsi_by_csv(
    file: UploadFile = File(...),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch register WSI files by uploading a CSV file.

    CSV format (with header):
    wsi_path,label,case_id,age,gender,wsi_id,event_time,event_status
    /path/to/slide1.svs,Benign,case_001,45,Female,slide_001,,
    /path/to/slide2.svs,,case_002,52,Male,slide_002,365,1

    Notes:
    - wsi_path is required
    - label, case_id, age, gender, wsi_id are optional
    - If wsi_id is not provided, it will be auto-generated
    - If case_id is not provided, it will be auto-generated as "case_{wsi_id}"
    - If label is not provided, it will remain empty
    - age should be an integer (patient age in years)
    - gender should be a string (e.g., Male, Female, Other)
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
        csv_text = content.decode("utf-8")
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        results = []
        success_count = 0
        failed_count = 0

        for row in csv_reader:
            wsi_path = row.get("wsi_path", "").strip()
            if not wsi_path:
                results.append(
                    {
                        "wsi_path": wsi_path,
                        "status": "failed",
                        "message": "wsi_path is required",
                    }
                )
                failed_count += 1
                continue

            # Get optional fields
            label = row.get("label", "").strip() or None
            case_id = row.get("case_id", "").strip() or None
            age_str = row.get("age", "").strip()
            age = int(age_str) if age_str and age_str.isdigit() else None
            gender = row.get("gender", "").strip() or None
            wsi_id = row.get("wsi_id", "").strip() or None
            # Survival analysis fields
            event_time_str = row.get("event_time", "").strip()
            event_time = float(event_time_str) if event_time_str else None
            event_status_str = row.get("event_status", "").strip()
            event_status = (
                int(event_status_str)
                if event_status_str and event_status_str.isdigit()
                else None
            )

            try:
                # Validate file exists
                if not os.path.exists(wsi_path):
                    results.append(
                        {
                            "wsi_path": wsi_path,
                            "status": "failed",
                            "message": f"File not found: {wsi_path}",
                        }
                    )
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
                    results.append(
                        {
                            "wsi_id": wsi_id,
                            "wsi_path": wsi_path,
                            "status": "failed",
                            "message": f"WSI already exists: {wsi_id}",
                        }
                    )
                    failed_count += 1
                    continue

                file_size = os.path.getsize(wsi_path)
                _file_data_type, wsi_props = resolve_file_data_type_and_properties(
                    wsi_path,
                    file_size=file_size,
                )
                file_size = wsi_props.get("file_size", file_size)

                # Generate case_id if not provided
                if not case_id:
                    case_id = f"case_{wsi_id[:8]}"

                logger.info(
                    f"Registering WSI from CSV: {original_filename} -> UUID: {wsi_id}"
                )

                # Create WSI in database with original_filename for internal reference
                wsi_data = {
                    "wsi_id": wsi_id,
                    "original_filename": original_filename,
                    "label": label,
                    "case_id": case_id,
                    "wsi_path": wsi_path,
                    "data_type": _file_data_type,
                    "file_size": file_size,
                    "age": age,
                    "gender": gender,
                    "event_time": event_time,
                    "event_status": event_status,
                    "mpp": wsi_props["mpp"],
                    "vendor": wsi_props["vendor"],
                    "width": wsi_props["width"],
                    "height": wsi_props["height"],
                    "magnification": wsi_props["magnification"],
                    "user_id": str(user.id),
                }

                wsi = await WSIRepository.create(db, wsi_data)
                await db.commit()

                # Save metadata to JSON file for persistence
                try:
                    storage_manager.save_wsi_metadata(wsi_id, wsi_data)
                except Exception as meta_err:
                    logger.warning(
                        f"Failed to save metadata file for {wsi_id}: {meta_err}"
                    )

                results.append(
                    {
                        "wsi_id": wsi_id,
                        "wsi_path": wsi_path,
                        "label": wsi.label,
                        "case_id": case_id,
                        "status": "success",
                        "message": "WSI registered successfully",
                    }
                )
                success_count += 1

                logger.info(f"Registered WSI from CSV: {wsi_id}")

            except Exception as e:
                results.append(
                    {
                        "wsi_path": wsi_path,
                        "wsi_id": wsi_id if wsi_id else "N/A",
                        "status": "failed",
                        "message": str(e),
                    }
                )
                failed_count += 1
                logger.error(f"Failed to register WSI from CSV: {wsi_path}, error: {e}")

        logger.info(
            f"CSV batch upload completed: {success_count} success, {failed_count} failed"
        )

        return {
            "total": success_count + failed_count,
            "success": success_count,
            "failed": failed_count,
            "results": results,
        }

    except Exception as e:
        logger.error(f"Failed to process CSV file: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to process CSV file: {str(e)}"
        )


@router.post("/file")
async def upload_wsi_file(
    file: UploadFile = File(...),
    associated_files: List[UploadFile] = File(default=[]),
    dataset_id: Optional[str] = Form(None),  # Existing dataset UUID
    dataset_name: Optional[str] = Form(None),  # Display name for new dataset
    source_organ: Optional[str] = Form(None),  # Source organ/tissue for new dataset
    aggregation_level: Optional[str] = Form(
        None
    ),  # Aggregation level for new dataset: "case" or "file"
    task_type: Optional[str] = Form(None),
    is_public: bool = Form(False),
    label: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    wsi_id: Optional[str] = Form(None),
    # Survival analysis fields
    event_time: Optional[float] = Form(None),
    event_status: Optional[int] = Form(None),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
        resolved_task_type = _resolve_task_type(task_type)
        is_json_annotation_upload = file_extension == ".json"
        segmentation_annotation = None
        wsi_path: Optional[Path] = None
        file_size = 0
        file_data_type: Optional[str] = None
        props: dict[str, Any] = {}

        if dataset_id and not is_json_annotation_upload:
            existing_with_name = await WSIRepository.get_by_filename_in_dataset(
                db, dataset_id, original_filename
            )
            if existing_with_name:
                raise HTTPException(
                    status_code=409,
                    detail=f"A file with filename '{original_filename}' already exists in this dataset",
                )

        if is_json_annotation_upload:
            segmentation_annotation = load_coco_annotation_bytes(
                await file.read(),
                source_name=original_filename,
            )
        else:
            # Generate UUID-based wsi_id if not provided (for privacy protection)
            if not wsi_id:
                wsi_id = str(uuid.uuid4())

            # Check if wsi_id already exists
            existing = await WSIRepository.get_by_id(db, wsi_id)
            if existing:
                raise HTTPException(
                    status_code=400, detail=f"WSI ID already exists: {wsi_id}"
                )

            # Save file to uploads directory using UUID-based filename
            wsi_files_dir = Path(UPLOADS_DIR) / "wsi_files"
            wsi_files_dir.mkdir(exist_ok=True, parents=True)

            wsi_path = wsi_files_dir / f"{wsi_id}{file_extension}"

            await _save_upload_file(file, wsi_path)

            file_size = wsi_path.stat().st_size
            logger.info(f"Saved WSI file: {wsi_path} ({file_size / (1024**2):.2f} MB)")
            logger.info(f"Original filename: {original_filename} -> UUID: {wsi_id}")

            file_data_type, props = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: resolve_file_data_type_and_properties(
                    wsi_path,
                    cached_file_data_type=file_data_type,
                    file_size=file_size,
                ),
            )
            file_size = props.get("file_size", file_size)

        # Handle associated files for special formats (MRXS, TMAP)
        associated_count = 0
        if associated_files and resolved_task_type != "segmentation":
            if file_extension == ".mrxs":
                # MRXS: Create data folder with same name as UUID
                data_folder = wsi_files_dir / wsi_id
                data_folder.mkdir(exist_ok=True, parents=True)

                for assoc_file in associated_files:
                    if assoc_file.filename:
                        assoc_path = data_folder / Path(assoc_file.filename).name
                        await _save_upload_file(assoc_file, assoc_path)
                        associated_count += 1

                logger.info(
                    f"Saved MRXS data folder with {associated_count} files: {data_folder}"
                )

            elif file_extension == ".tmap":
                # TMAP: Save DT files with same UUID base name
                for assoc_file in associated_files:
                    if assoc_file.filename:
                        dt_ext = Path(assoc_file.filename).suffix
                        dt_path = wsi_files_dir / f"{wsi_id}{dt_ext}"
                        await _save_upload_file(assoc_file, dt_path)
                        associated_count += 1

                logger.info(f"Saved {associated_count} TMAP DT files for: {wsi_id}")

        # Recalculate file_size now that associated data is on disk
        if file_extension in (".mrxs", ".tmap") and wsi_path is not None:
            file_size = get_wsi_effective_file_size(str(wsi_path))

        # Resolve dataset_id: use provided dataset_id, or create new dataset from dataset_name
        resolved_dataset_id = None
        resolved_aggregation_level = aggregation_level or "file"
        if dataset_id:
            # Validate provided dataset_id exists
            existing_dataset = await DatasetRepository.get_by_id(db, dataset_id)
            if not existing_dataset:
                raise HTTPException(
                    status_code=400, detail=f"Dataset not found: {dataset_id}"
                )
            if not check_data_ownership(str(existing_dataset.user_id or ""), user):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to upload to this dataset",
                )
            data_group = existing_dataset.data_group
            if not data_group:
                raise HTTPException(
                    status_code=400, detail="Dataset has no associated DataGroup"
                )
            resolved_task_type = _resolve_task_type(task_type, data_group.task_type)
            if task_type and data_group.task_type != task_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset task_type is '{data_group.task_type}', expected '{task_type}'",
                )
            if is_json_annotation_upload:
                if resolved_task_type != "segmentation":
                    raise HTTPException(
                        status_code=400,
                        detail="JSON uploads are only supported when appending to an existing segmentation dataset",
                    )
            else:
                existing_dataset = await align_dataset_data_type_for_file(
                    db,
                    existing_dataset,
                    file_path=str(wsi_path),
                    file_data_type=file_data_type,
                    task_type=resolved_task_type,
                    action="upload",
                    context="WSI upload",
                )
                data_group = existing_dataset.data_group
            ensure_dataset_segmentation_contract(
                existing_dataset,
                context="WSI upload",
                expected_task_type=resolved_task_type,
            )
            resolved_aggregation_level = data_group.aggregation_level
            resolved_dataset_id = dataset_id
        elif dataset_name:
            if is_json_annotation_upload:
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation JSON-only upload is only supported when appending to an existing dataset",
                )
            resolved_aggregation_level = aggregation_level or "file"
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context="WSI upload",
            )

            # Get or create DataGroup first
            data_group = await DataGroupRepository.get_or_create(
                db,
                data_type=file_data_type,
                aggregation_level=resolved_aggregation_level,
                task_type=resolved_task_type,
            )

            # Create or get dataset by name with group_id
            dataset = await DatasetRepository.get_or_create(
                db,
                dataset_name,
                group_id=data_group.group_id,
                user_id=str(user.id),
                source_organ=source_organ or None,
                is_public=is_public,
            )
            dataset = await align_dataset_data_type_for_file(
                db,
                dataset,
                file_path=str(wsi_path),
                file_data_type=file_data_type,
                task_type=resolved_task_type,
                action="upload",
                context="WSI upload",
            )
            resolved_dataset_id = dataset.dataset_id

        if is_json_annotation_upload:
            if resolved_dataset_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation JSON-only upload requires an existing dataset",
                )

            matched_wsi = await _append_segmentation_annotation_to_existing_dataset(
                db,
                dataset_id=resolved_dataset_id,
                annotation_name=original_filename,
                annotation_payload=segmentation_annotation,
                user_id=str(user.id),
                source="upload_json",
            )
            await db.commit()

            if resolved_dataset_id:
                try:
                    await rebuild_dataset_annotation_summary_cache(
                        db, resolved_dataset_id
                    )
                    await db.commit()
                except Exception as cache_err:
                    await db.rollback()
                    logger.warning(
                        f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}"
                    )
                try:
                    await publish_annotation_event(
                        resolved_dataset_id, {"type": "gt_updated"}
                    )
                except Exception:
                    pass

            return {
                "message": "Segmentation annotation appended successfully",
                "wsi_id": matched_wsi.wsi_id,
                "wsi_path": matched_wsi.wsi_path,
                "file_size": matched_wsi.file_size,
                "associated_files_count": 0,
            }

        if resolved_task_type == "segmentation" and segmentation_annotation is None:
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context="WSI upload",
            )
            annotation_upload = _find_matching_uploaded_segmentation_annotation(
                associated_files, original_filename
            )
            if annotation_upload is not None:
                annotation_name = Path(annotation_upload.filename or "").name
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
            "label": None if resolved_task_type == "segmentation" else label,
            "wsi_path": str(wsi_path),
            "data_type": data_group.data_type if data_group else file_data_type,
            "age": age,
            "gender": gender,
            "source": (existing_dataset.source_organ if dataset_id else source_organ)
            or None,
            "event_time": event_time,
            "event_status": event_status,
            "mpp": props.get("mpp"),
            "vendor": props.get("vendor"),
            "width": props.get("width"),
            "height": props.get("height"),
            "magnification": props.get("magnification"),
            "file_size": file_size,
            "user_id": str(user.id),
        }

        # Race-condition safe: catch IntegrityError if concurrent upload
        # with same wsi_id passes the existence check above (PostgreSQL READ COMMITTED)
        try:
            await WSIRepository.create(db, wsi_data)
            if (
                resolved_task_type == "segmentation"
                and segmentation_annotation is not None
            ):
                await SegmentationAnnotationRepository.upsert(
                    db,
                    annotation_id=f"annot_{wsi_id}",
                    user_id=str(user.id),
                    annotations=segmentation_annotation,
                    source_dataset_id=resolved_dataset_id,
                    status="finalized",
                    visibility_mode="inherit",
                    source="upload",
                )
            if resolved_dataset_id:
                await DatasetStatsRepository.recompute(db, resolved_dataset_id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=400, detail=f"WSI ID already exists: {wsi_id}"
            )

        logger.info(f"Created WSI record in database: {wsi_id}")

        if resolved_task_type == "segmentation" and resolved_dataset_id:
            try:
                await rebuild_dataset_annotation_summary_cache(db, resolved_dataset_id)
                await db.commit()
            except Exception as cache_err:
                await db.rollback()
                logger.warning(
                    f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}"
                )
            if segmentation_annotation is not None:
                try:
                    await publish_annotation_event(
                        resolved_dataset_id, {"type": "gt_updated"}
                    )
                except Exception:
                    pass

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
            "associated_files_count": associated_count,
        }

    except HTTPException:
        if wsi_path is not None and wsi_path.exists():
            try:
                wsi_path.unlink()
            except OSError:
                pass
        raise
    except Exception as e:
        logger.error(f"Failed to upload WSI file: {e}")
        if wsi_path is not None and wsi_path.exists():
            try:
                wsi_path.unlink()
            except OSError:
                pass
        raise HTTPException(
            status_code=500, detail=f"Failed to upload WSI file: {str(e)}"
        )


def _validate_mrxs_data_folder(wsi_path: str) -> Optional[str]:
    """
    Validate that MRXS file has its required data folder.
    MRXS format requires: <name>.mrxs + <name>/ folder (same name, no extension)

    Returns the data folder path if valid, None if missing.
    """
    wsi_file = Path(wsi_path)
    if wsi_file.suffix.lower() != ".mrxs":
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
    if wsi_file.suffix.lower() != ".tmap":
        return []

    base_name = wsi_file.stem
    parent_dir = wsi_file.parent
    dt_files = []

    # Look for .DT1, .DT2, ... files with same base name
    for file in parent_dir.iterdir():
        if file.stem == base_name and file.suffix.lower().startswith(".dt"):
            # Verify it's a DT file (e.g., .DT1, .DT2, etc.)
            suffix_num = file.suffix[3:]  # Remove '.DT' or '.dt'
            if suffix_num.isdigit():
                dt_files.append(str(file))

    return sorted(dt_files)


@router.post("/path")
async def upload_wsi_by_path(
    req: UploadByPathRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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
            raise HTTPException(
                status_code=404, detail=f"WSI file not found: {req.wsi_path}"
            )

        wsi_file = Path(req.wsi_path)
        file_extension = wsi_file.suffix.lower()
        is_json_annotation_path = file_extension == ".json"

        # Validate and detect associated files for special formats
        associated_data = {}

        if not is_json_annotation_path and file_extension == ".mrxs":
            data_folder = _validate_mrxs_data_folder(req.wsi_path)
            if not data_folder:
                raise HTTPException(
                    status_code=400,
                    detail=f"MRXS file requires a data folder with the same name. Expected: {wsi_file.stem}/",
                )
            associated_data["mrxs_data_folder"] = data_folder
            logger.info(f"Found MRXS data folder: {data_folder}")

        elif not is_json_annotation_path and file_extension == ".tmap":
            dt_files = _find_tmap_data_files(req.wsi_path)
            if dt_files:
                associated_data["tmap_dt_files"] = dt_files
                logger.info(f"Found {len(dt_files)} TMAP DT files: {dt_files}")

        # Store original filename for internal reference (including extension)
        original_filename = wsi_file.name
        resolved_task_type = _resolve_task_type(req.task_type)
        segmentation_annotation = None
        file_size = os.path.getsize(req.wsi_path)
        file_data_type: Optional[str] = None
        wsi_props = None
        wsi_id = req.wsi_id
        case_id = req.case_id

        if req.dataset_id and not is_json_annotation_path:
            existing_with_name = await WSIRepository.get_by_filename_in_dataset(
                db, req.dataset_id, original_filename
            )
            if existing_with_name:
                raise HTTPException(
                    status_code=409,
                    detail=f"A file with filename '{original_filename}' already exists in this dataset",
                )

        if is_json_annotation_path:
            segmentation_annotation = load_coco_annotation_file(req.wsi_path)
        else:
            if not wsi_id:
                wsi_id = str(uuid.uuid4())

            existing = await WSIRepository.get_by_id(db, wsi_id)
            if existing:
                raise HTTPException(
                    status_code=400, detail=f"WSI already exists: {wsi_id}"
                )

            file_data_type, wsi_props = resolve_file_data_type_and_properties(
                req.wsi_path
            )
            file_size = wsi_props.get("file_size", 0)
            case_id = req.case_id or f"case_{wsi_id[:8]}"

            logger.info(f"Registering WSI: {original_filename} -> UUID: {wsi_id}")

        # Resolve dataset_id: use provided dataset_id, or create new dataset from dataset_name
        resolved_dataset_id = None
        resolved_aggregation_level = req.aggregation_level or "file"
        if req.dataset_id:
            existing_dataset = await DatasetRepository.get_by_id(db, req.dataset_id)
            if not existing_dataset:
                raise HTTPException(
                    status_code=400, detail=f"Dataset not found: {req.dataset_id}"
                )
            if not check_data_ownership(str(existing_dataset.user_id or ""), user):
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to upload to this dataset",
                )
            data_group = existing_dataset.data_group
            if not data_group:
                raise HTTPException(
                    status_code=400, detail="Dataset has no associated DataGroup"
                )
            resolved_task_type = _resolve_task_type(req.task_type, data_group.task_type)
            if req.task_type and data_group.task_type != req.task_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset task_type is '{data_group.task_type}', expected '{req.task_type}'",
                )
            if is_json_annotation_path:
                if resolved_task_type != "segmentation":
                    raise HTTPException(
                        status_code=400,
                        detail="JSON uploads are only supported when appending to an existing segmentation dataset",
                    )
            else:
                existing_dataset = await align_dataset_data_type_for_file(
                    db,
                    existing_dataset,
                    file_path=req.wsi_path,
                    file_data_type=file_data_type,
                    task_type=resolved_task_type,
                    action="register",
                    context="WSI path registration",
                )
                data_group = existing_dataset.data_group
            ensure_dataset_segmentation_contract(
                existing_dataset,
                context="WSI path registration",
                expected_task_type=resolved_task_type,
            )
            resolved_aggregation_level = data_group.aggregation_level
            resolved_dataset_id = req.dataset_id
        elif req.dataset_name:
            if is_json_annotation_path:
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation JSON-only upload is only supported when appending to an existing dataset",
                )
            resolved_aggregation_level = req.aggregation_level or "file"
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context="WSI path registration",
            )

            # Get or create DataGroup first
            data_group = await DataGroupRepository.get_or_create(
                db,
                data_type=file_data_type,
                aggregation_level=resolved_aggregation_level,
                task_type=resolved_task_type,
            )

            # Create or get dataset by name with group_id
            dataset = await DatasetRepository.get_or_create(
                db,
                req.dataset_name,
                group_id=data_group.group_id,
                user_id=str(user.id),
                source_organ=req.source_organ or None,
                is_public=req.is_public,
            )
            dataset = await align_dataset_data_type_for_file(
                db,
                dataset,
                file_path=req.wsi_path,
                file_data_type=file_data_type,
                task_type=resolved_task_type,
                action="register",
                context="WSI path registration",
            )
            resolved_dataset_id = dataset.dataset_id

        if is_json_annotation_path:
            if resolved_dataset_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation JSON-only upload requires an existing dataset",
                )

            matched_wsi = await _append_segmentation_annotation_to_existing_dataset(
                db,
                dataset_id=resolved_dataset_id,
                annotation_name=original_filename,
                annotation_payload=segmentation_annotation,
                user_id=str(user.id),
                source="upload_path_json",
            )
            await db.commit()

            if resolved_dataset_id:
                try:
                    await rebuild_dataset_annotation_summary_cache(
                        db, resolved_dataset_id
                    )
                    await db.commit()
                except Exception as cache_err:
                    await db.rollback()
                    logger.warning(
                        f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}"
                    )
                try:
                    await publish_annotation_event(
                        resolved_dataset_id, {"type": "gt_updated"}
                    )
                except Exception:
                    pass

            return {
                "wsi_id": matched_wsi.wsi_id,
                "wsi_path": matched_wsi.wsi_path,
                "label": matched_wsi.label,
                "case_id": matched_wsi.case_id,
                "file_size": matched_wsi.file_size,
                "message": "Segmentation annotation appended successfully",
            }

        if resolved_task_type == "segmentation" and segmentation_annotation is None:
            ensure_segmentation_contract(
                resolved_task_type,
                file_data_type,
                resolved_aggregation_level,
                context="WSI path registration",
            )
            annotation_path = find_matching_segmentation_annotation_path(req.wsi_path)
            if annotation_path is not None:
                segmentation_annotation = load_coco_annotation_file(annotation_path)

        # Create WSI in database with original_filename for internal reference
        wsi_data = {
            "wsi_id": wsi_id,
            "original_filename": original_filename,
            "dataset_id": resolved_dataset_id,
            "label": None if resolved_task_type == "segmentation" else req.label,
            "case_id": case_id,
            "wsi_path": req.wsi_path,
            "data_type": data_group.data_type if data_group else file_data_type,
            "file_size": file_size,
            "age": req.age,
            "gender": req.gender,
            "source": (
                existing_dataset.source_organ if req.dataset_id else req.source_organ
            )
            or None,
            "event_time": req.event_time,
            "event_status": req.event_status,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
            "user_id": str(user.id),
        }

        # Race-condition safe: catch IntegrityError if concurrent register
        # with same wsi_id passes the existence check above (PostgreSQL READ COMMITTED)
        try:
            wsi = await WSIRepository.create(db, wsi_data)
            if (
                resolved_task_type == "segmentation"
                and segmentation_annotation is not None
            ):
                await SegmentationAnnotationRepository.upsert(
                    db,
                    annotation_id=f"annot_{wsi_id}",
                    user_id=str(user.id),
                    annotations=segmentation_annotation,
                    source_dataset_id=resolved_dataset_id,
                    status="finalized",
                    visibility_mode="inherit",
                    source="upload_path",
                )
            if resolved_dataset_id:
                await DatasetStatsRepository.recompute(db, resolved_dataset_id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"WSI already exists: {wsi_id}")

        logger.info(f"Registered WSI by path in database: {wsi_id}")

        if resolved_task_type == "segmentation" and resolved_dataset_id:
            try:
                await rebuild_dataset_annotation_summary_cache(db, resolved_dataset_id)
                await db.commit()
            except Exception as cache_err:
                await db.rollback()
                logger.warning(
                    f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}"
                )
            if segmentation_annotation is not None:
                try:
                    await publish_annotation_event(
                        resolved_dataset_id, {"type": "gt_updated"}
                    )
                except Exception:
                    pass

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
            "message": "WSI registered successfully",
        }

        # Check association but don't return full object to keep response clean
        if associated_data:
            response["associated_data_count"] = len(associated_data)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register WSI by path: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to register WSI by path: {str(e)}"
        )


@router.get("/csv/template")
async def get_csv_template(
    task_type: str = Query(
        "classification",
        description="Task type: 'classification', 'survival', or 'segmentation'",
    ),
    user: User = Depends(current_active_user),
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
    - split (train, val, test), case_id, age, gender

    Note: If no 'val' split is provided, 10% of 'train' samples will be
    automatically assigned to 'val' during upload.
    """
    if task_type == "survival":
        # Survival analysis template
        headers = [
            "filename",
            "split",
            "event_time",
            "event_status",
            "case_id",
            "age",
            "gender",
        ]
        examples = [
            {
                "filename": "slide1.svs",
                "split": "train",
                "event_time": "24.5",
                "event_status": "1",
                "case_id": "CASE001",
                "age": "65",
                "gender": "Male",
            },
            {
                "filename": "slide2.svs",
                "split": "val",
                "event_time": "36.0",
                "event_status": "0",
                "case_id": "CASE002",
                "age": "50",
                "gender": "Female",
            },
            {
                "filename": "slide3.svs",
                "split": "test",
                "event_time": "48.0",
                "event_status": "1",
                "case_id": "CASE003",
                "age": "70",
                "gender": "Male",
            },
        ]
        filename = "wsi_survival_metadata_template.csv"
    elif task_type == "segmentation":
        # Segmentation template — no label column; masks are provided via COCO JSON separately
        headers = ["filename", "split", "case_id", "age", "gender"]
        examples = [
            {
                "filename": "image_001.png",
                "split": "train",
                "case_id": "CASE001",
                "age": "",
                "gender": "",
            },
            {
                "filename": "image_002.png",
                "split": "val",
                "case_id": "CASE002",
                "age": "",
                "gender": "",
            },
            {
                "filename": "image_003.png",
                "split": "test",
                "case_id": "CASE003",
                "age": "",
                "gender": "",
            },
        ]
        filename = "segmentation_metadata_template.csv"
    else:
        # Classification template (default)
        headers = ["filename", "split", "label", "case_id", "age", "gender"]
        examples = [
            {
                "filename": "slide1.svs",
                "split": "train",
                "label": "Tumor",
                "case_id": "CASE001",
                "age": "65",
                "gender": "Male",
            },
            {
                "filename": "slide2.svs",
                "split": "val",
                "label": "Normal",
                "case_id": "CASE002",
                "age": "50",
                "gender": "Female",
            },
            {
                "filename": "slide3.svs",
                "split": "test",
                "label": "Tumor",
                "case_id": "CASE003",
                "age": "70",
                "gender": "Male",
            },
        ]
        filename = "wsi_classification_metadata_template.csv"

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(examples)

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/coco/template")
async def get_coco_annotation_template(user: User = Depends(current_active_user)):
    """
    Download COCO annotation JSON template for segmentation datasets.
    Requires authentication.
    """
    import json

    template_path = (
        Path(__file__).parent.parent.parent
        / "backend"
        / "ai"
        / "utils"
        / "dataset_template"
        / "segmentation_annotation.json"
    )

    if not template_path.exists():
        raise HTTPException(
            status_code=404, detail="COCO annotation template not found"
        )

    with open(template_path, "r") as f:
        content = f.read()

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=segmentation_annotation_template.json"
        },
    )
