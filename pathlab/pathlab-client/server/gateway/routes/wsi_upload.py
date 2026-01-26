"""
WSI CSV batch upload functionality
Separated due to length
"""
import os
import uuid
import csv
import io
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import WSIRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin
from ..dependencies import logger, storage_manager
from ..utils import extract_wsi_properties

router = APIRouter(prefix="/wsi/upload", tags=["WSI Upload"])


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

                # Store original filename for internal reference
                original_filename = Path(wsi_path).stem

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

