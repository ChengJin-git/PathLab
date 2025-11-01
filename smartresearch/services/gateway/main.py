import json
import os
import shutil
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from Aslide import Slide
import asyncio

# Load environment variables from .env file
from dotenv import load_dotenv

# Database imports
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # smartresearch/
sys.path.insert(0, ROOT)

# Load .env file from smartresearch directory
env_path = os.path.join(ROOT, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"[Gateway] Loaded environment variables from {env_path}")
else:
    print(f"[Gateway] No .env file found at {env_path}, using system environment variables")

from smartresearch.services.backend.database import get_db, init_db, close_db
from smartresearch.services.backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
    ChatRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    TrainingLogRepository,
)

# Gateway - PostgreSQL-based implementation
UPLOADS_DIR = os.path.join(ROOT, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Service URLs (internal communication)
AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "http://127.0.0.1:6102")
PREPROCESSING_SERVICE_URL = os.environ.get("PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101")

def extract_wsi_properties(wsi_path: str) -> dict:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
    }

    if not wsi_path or not os.path.exists(wsi_path):
        print(f"[Gateway] WSI file not found: {wsi_path}")
        return default_props

    try:
        with Slide(wsi_path) as slide:
            # Extract properties
            props = {}

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
            except:
                props["mpp"] = default_props["mpp"]

            # 2. Vendor
            try:
                vendor = slide.properties.get('openslide.vendor', 'Unknown')
                props["vendor"] = vendor if vendor else "Unknown"
            except:
                props["vendor"] = default_props["vendor"]

            # 3. Width and Height (from level 0 dimensions)
            try:
                width, height = slide.dimensions
                props["width"] = int(width)
                props["height"] = int(height)
            except:
                props["width"] = default_props["width"]
                props["height"] = default_props["height"]

            # 4. Magnification (objective power)
            try:
                mag = slide.properties.get('openslide.objective-power')
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except:
                props["magnification"] = default_props["magnification"]

            print(f"[Gateway] ✓ Extracted properties from {os.path.basename(wsi_path)}: "
                  f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                  f"size={props['width']}x{props['height']}, mag={props['magnification']}x")

            return props

    except Exception as e:
        print(f"[Gateway] Failed to read WSI properties from {wsi_path}: {e}")
        return default_props


app = FastAPI(title="SmartResearch Gateway")

# Enable CORS for dev and on-prem SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    print("[Gateway] Initializing database...")
    await init_db()
    print("[Gateway] ✓ Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown"""
    print("[Gateway] Closing database connections...")
    await close_db()
    print("[Gateway] ✓ Database connections closed")

class WSIClassifyRequest(BaseModel):
    wsi_id: str
    classes: Optional[List[str]] = None  # Optional: classes for classification (auto-detected if not provided)
    model_id: Optional[str] = None  # Optional: specific model to use
    params: Optional[Dict] = None


class TrainingTaskRequest(BaseModel):
    """Request model for creating a training task"""
    task_name: str
    task_type: str  # "classification" or "segmentation"
    task_description: Optional[str] = None
    wsi_ids: List[str]
    preprocessing: Dict  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model: Dict  # {aggregator, learning_rate, epochs, optimizer, batch_size}

@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}

@app.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    Get system statistics including WSI count, task count, and results count.
    Returns:
        {
            "wsi_count": int,
            "task_count": int,
            "completed_count": int,
            "results_count": int,
            "labels": {label: count}
        }
    """
    # Get counts from database
    wsi_count = await WSIRepository.count(db)
    task_count = await AITaskRepository.count(db)
    completed_count = await AITaskRepository.count_completed(db)
    results_count = await AIResultRepository.count(db)
    labels_count = await WSIRepository.get_label_distribution(db)

    return {
        "wsi_count": wsi_count,
        "task_count": task_count,
        "completed_count": completed_count,
        "results_count": results_count,
        "labels": labels_count
    }

@app.get("/wsi")
async def list_wsi(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all WSI slides with pagination"""
    wsi_slides = await WSIRepository.get_all(db, skip=skip, limit=limit)
    items = [wsi.to_dict() for wsi in wsi_slides]
    return {"items": items}

@app.get("/wsi/{wsi_id}")
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

@app.delete("/wsi/{wsi_id}")
async def delete_wsi(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a WSI and its associated data.

    This will:
    1. Delete training task associations (TrainingTaskWSI)
    2. Delete all AI results associated with this WSI
    3. Delete all AI tasks associated with this WSI
    4. Delete the WSI record from database
    5. Delete the WSI file from disk (if it's in the uploads directory)

    Args:
        wsi_id: The WSI ID to delete

    Returns:
        {"message": "WSI deleted successfully", "wsi_id": str}
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
            from smartresearch.services.backend.database.models import AIResult, AITask, TrainingTaskWSI
            from sqlalchemy import delete as sql_delete

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
            print(f"[Gateway] Warning: Failed to delete associated data for {wsi_id}: {e}")

        # Delete WSI from database
        await WSIRepository.delete(db, wsi_id)
        await db.commit()

        # Delete file from disk if it's in the uploads directory
        if wsi_path and os.path.exists(wsi_path):
            # Only delete if the file is in our uploads directory (safety check)
            if wsi_path.startswith(UPLOADS_DIR):
                try:
                    os.remove(wsi_path)
                    print(f"[Gateway] Deleted WSI file: {wsi_path}")
                except Exception as e:
                    print(f"[Gateway] Failed to delete WSI file {wsi_path}: {e}")
                    # Don't raise error - database record is already deleted
            else:
                print(f"[Gateway] WSI file not in uploads directory, skipping deletion: {wsi_path}")

        print(f"[Gateway] Deleted WSI: {wsi_id}")

        return {
            "message": "WSI deleted successfully",
            "wsi_id": wsi_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to delete WSI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete WSI: {str(e)}")

@app.patch("/wsi/{wsi_id}")
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

        print(f"[Gateway] Updated WSI metadata: {wsi_id}")

        return {
            "message": "WSI metadata updated successfully",
            "wsi": wsi.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to update WSI metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update WSI metadata: {str(e)}")

# ============================================================================
# Training Task APIs (must be before /tasks/{task_id} to avoid route conflicts)
# ============================================================================

@app.post("/tasks/training")
async def create_training_task(
    req: TrainingTaskRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new training task.
    Automatically extracts classes from selected WSI labels.
    """
    try:
        # Validate WSI IDs exist
        if not req.wsi_ids or len(req.wsi_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one WSI must be selected")

        # Check all WSI IDs exist
        for wsi_id in req.wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Generate task ID
        task_id = f"train_{uuid.uuid4().hex[:16]}"

        # Prepare task data
        task_data = {
            "task_id": task_id,
            "task_name": req.task_name,
            "task_type": req.task_type,
            "task_description": req.task_description,
            "preprocessing_config": req.preprocessing,
            "model_config": req.model,
        }

        # Create training task (automatically extracts classes from WSI labels)
        task = await TrainingTaskRepository.create(db, task_data, req.wsi_ids)
        await db.commit()

        print(f"[Gateway] ✓ Created training task: {task_id}")
        print(f"[Gateway]   - Task name: {req.task_name}")
        print(f"[Gateway]   - Task type: {req.task_type}")
        print(f"[Gateway]   - WSI count: {len(req.wsi_ids)}")
        print(f"[Gateway]   - Classes: {task.classes}")

        # Start preprocessing pipeline asynchronously (with new DB session)
        asyncio.create_task(
            run_training_pipeline(task_id, req.wsi_ids, req.preprocessing, req.model)
        )

        # Return task info
        result = task.to_dict()
        result["wsi_count"] = len(req.wsi_ids)

        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to create training task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create training task: {str(e)}")


@app.get("/tasks/training")
async def list_training_tasks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all training tasks"""
    tasks = await TrainingTaskRepository.get_all(db, limit, skip)

    # Add WSI count to each task
    result_tasks = []
    for task in tasks:
        task_dict = task.to_dict()
        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
        task_dict["wsi_count"] = len(wsi_ids)
        result_tasks.append(task_dict)

    return {"items": result_tasks}


@app.get("/tasks/training/stream")
async def stream_training_tasks():
    """
    Server-Sent Events endpoint for real-time training task updates.
    Streams task status and progress updates to connected clients.
    """
    async def event_generator():
        """Generate SSE events with task updates"""
        try:
            while True:
                # Get database session
                async for db in get_db():
                    try:
                        # Fetch all training tasks
                        tasks = await TrainingTaskRepository.get_all(db, limit=100, offset=0)

                        # Add WSI count to each task
                        result_tasks = []
                        for task in tasks:
                            task_dict = task.to_dict()
                            wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
                            task_dict["wsi_count"] = len(wsi_ids)
                            result_tasks.append(task_dict)

                        # Send SSE event
                        data = json.dumps({"items": result_tasks})
                        yield f"data: {data}\n\n"

                    finally:
                        await db.close()

                # Wait 2 seconds before next update
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Client disconnected
            print("[Gateway] SSE client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@app.get("/tasks/training/{task_id}")
async def get_training_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get training task details"""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get associated WSI IDs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)

    result = task.to_dict()
    result["wsi_ids"] = wsi_ids
    result["wsi_count"] = len(wsi_ids)

    return result


@app.delete("/tasks/training/{task_id}")
async def delete_training_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a training task"""
    success = await TrainingTaskRepository.delete(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Training task not found")
    await db.commit()
    return {"message": "Training task deleted successfully"}


@app.get("/tasks/training/{task_id}/logs")
async def get_training_logs(
    task_id: str,
    level: Optional[str] = Query(None, description="Filter by log level (INFO, WARNING, ERROR, DEBUG)"),
    limit: int = Query(1000, description="Maximum number of logs to return"),
    offset: int = Query(0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get logs for a training task.

    Supports filtering by log level and pagination.
    Returns logs in chronological order.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get logs from database
    logs = await TrainingLogRepository.get_by_task_id(db, task_id, level, limit, offset)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset
    }


@app.get("/tasks/training/{task_id}/logs/stream")
async def stream_training_logs(
    task_id: str,
    after_sequence: int = Query(0, description="Get logs after this sequence number"),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream training logs using Server-Sent Events (SSE).

    This endpoint supports real-time log streaming by polling for new logs.
    Clients should track the last sequence number and request logs after that.

    For true real-time streaming, use WebSocket or implement SSE with async generators.
    This is a simplified polling-based approach.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get new logs after the specified sequence
    logs = await TrainingLogRepository.get_logs_after_sequence(db, task_id, after_sequence, limit=100)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
        "last_sequence": logs[-1].sequence if logs else after_sequence
    }


@app.get("/tasks/training/{task_id}/logs/recent")
async def get_recent_training_logs(
    task_id: str,
    count: int = Query(100, description="Number of recent logs to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the most recent N logs for a training task.

    Useful for quickly displaying the latest logs without pagination.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get recent logs
    logs = await TrainingLogRepository.get_recent(db, task_id, count)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs)
    }


# ============================================================================
# AI Task APIs (generic task endpoints)
# ============================================================================

@app.post("/tasks/wsi-classification")
async def create_wsi_classification(
    req: WSIClassifyRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a WSI classification task by calling AI Service.
    Gateway orchestrates the request to AI Service.

    If classes are not provided, they will be auto-detected from all WSI labels in the database.
    """
    # Validate WSI exists in database
    wsi = await WSIRepository.get_by_id(db, req.wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Auto-detect classes if not provided
    classes = req.classes
    if not classes:
        # Get all unique labels from database
        all_wsi = await WSIRepository.get_all(db, skip=0, limit=10000)
        unique_labels = set()
        for w in all_wsi:
            if w.label:
                unique_labels.add(w.label)

        if not unique_labels:
            raise HTTPException(
                status_code=400,
                detail="No classes provided and no labeled WSI found in database. Please provide classes parameter."
            )

        classes = sorted(list(unique_labels))
        print(f"[Gateway] Auto-detected classes from database: {classes}")

    # Call AI Service to create analysis task
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{AI_SERVICE_URL}/api/ai/analyze",
                json={
                    "task": "wsi_classification",
                    "wsi_id": req.wsi_id,
                    "classes": classes,
                    "model_id": req.model_id,
                    "params": req.params or {}
                }
            )
            response.raise_for_status()
            result = response.json()

            # Store task in database
            task_data = {
                "task_id": result.get("task_id"),
                "wsi_id": req.wsi_id,
                "task_type": "wsi-classification",
                "status": result.get("status", "pending"),
                "progress": 0,
                "params": {
                    "classes": classes,
                    "model_id": req.model_id,
                    **(req.params or {})
                },
            }
            await AITaskRepository.create(db, task_data)
            await db.commit()

            return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"AI Service error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"AI Service unavailable: {str(e)}")

@app.get("/tasks/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get task status from database.
    """
    # Try AI task first
    task = await AITaskRepository.get_by_id(db, task_id)
    if task:
        return task.to_dict()

    # Try training task
    training_task = await TrainingTaskRepository.get_by_id(db, task_id)
    if training_task:
        return training_task.to_dict()

    return {"task_id": task_id, "status": "not_found"}

@app.get("/results/{wsi_id}")
async def get_results(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get AI analysis results for a WSI from database.
    """
    # Get from database
    result = await AIResultRepository.get_by_wsi_id(db, wsi_id)
    if result:
        return result.to_dict()

    # No result found
    return {"wsi_id": wsi_id, "pred": None, "probs": None}


class UploadByPathRequest(BaseModel):
    """Request model for uploading WSI by file path"""
    wsi_path: str
    label: Optional[str] = None
    case_id: Optional[str] = None
    wsi_id: Optional[str] = None


@app.post("/wsi/upload/file")
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
        label: Optional label for the WSI
        case_id: Optional case ID
        wsi_id: Optional custom WSI ID (auto-generated if not provided)

    Returns:
        {
            "wsi_id": str,
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str
        }
    """
    try:
        # Generate wsi_id if not provided
        if not wsi_id:
            # Use original filename without extension as base
            base_name = Path(file.filename).stem if file.filename else "wsi"
            wsi_id = f"{base_name}_{uuid.uuid4().hex[:8]}"

        # Check if wsi_id already exists in database
        existing = await WSIRepository.get_by_id(db, wsi_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"WSI ID already exists: {wsi_id}")

        # Get file extension
        file_ext = Path(file.filename).suffix if file.filename else ".tif"
        if not file_ext:
            file_ext = ".tif"

        # Save file to uploads directory
        file_path = os.path.join(UPLOADS_DIR, f"{wsi_id}{file_ext}")

        # Check if file already exists
        if os.path.exists(file_path):
            raise HTTPException(status_code=400, detail=f"WSI file already exists: {wsi_id}")

        # Save uploaded file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"[Gateway] Saved uploaded file: {file_path}")

        # Extract WSI properties
        wsi_props = extract_wsi_properties(file_path)

        # Generate case_id if not provided
        if not case_id:
            case_id = f"case_{wsi_id}"

        # Create metadata in database
        wsi_data = {
            "wsi_id": wsi_id,
            "label": label or "Unknown",
            "case_id": case_id,
            "wsi_path": file_path,
            "age": age,
            "gender": gender,
            "source": source,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
        }

        wsi = await WSIRepository.create(db, wsi_data)
        await db.commit()

        print(f"[Gateway] Created WSI in database: {wsi_id}")

        return {
            "wsi_id": wsi_id,
            "wsi_path": file_path,
            "label": wsi.label,
            "case_id": case_id,
            "message": "WSI uploaded successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to upload WSI file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload WSI file: {str(e)}")


@app.post("/wsi/upload/path")
async def upload_wsi_by_path(req: UploadByPathRequest, db: AsyncSession = Depends(get_db)):
    """
    Register a WSI by file path (without copying the file).
    This is useful when WSI files are already on the server.

    Args:
        req: UploadByPathRequest containing wsi_path and optional metadata

    Returns:
        {
            "wsi_id": str,
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str
        }
    """
    try:
        # Validate file exists
        if not os.path.exists(req.wsi_path):
            raise HTTPException(status_code=404, detail=f"WSI file not found: {req.wsi_path}")

        # Generate wsi_id if not provided
        if not req.wsi_id:
            # Use filename without extension as base
            base_name = Path(req.wsi_path).stem
            wsi_id = f"{base_name}_{uuid.uuid4().hex[:8]}"
        else:
            wsi_id = req.wsi_id

        # Check if WSI already exists in database
        existing = await WSIRepository.get_by_id(db, wsi_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"WSI already exists: {wsi_id}")

        # Extract WSI properties
        wsi_props = extract_wsi_properties(req.wsi_path)

        # Generate case_id if not provided
        case_id = req.case_id or f"case_{wsi_id}"

        # Create WSI in database
        wsi_data = {
            "wsi_id": wsi_id,
            "label": req.label or "Unknown",
            "case_id": case_id,
            "wsi_path": req.wsi_path,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
        }

        wsi = await WSIRepository.create(db, wsi_data)
        await db.commit()

        print(f"[Gateway] Registered WSI by path in database: {wsi_id}")

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
        print(f"[Gateway] Failed to register WSI by path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to register WSI by path: {str(e)}")


@app.get("/wsi/upload/csv/template")
async def download_csv_template():
    """
    Download CSV template for batch WSI upload.

    Returns a CSV file with headers and example rows.
    """
    from fastapi.responses import StreamingResponse
    import io

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


@app.post("/wsi/upload/csv")
async def upload_wsi_by_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Batch register WSI files by uploading a CSV file.

    CSV format (with header):
    wsi_path,label,case_id,age,gender,source,wsi_id
    /path/to/slide1.svs,Benign,case_001,45,Female,Cervix,slide_001
    /path/to/slide2.svs,Malignant,case_002,52,Male,Lung,slide_002

    Notes:
    - wsi_path is required
    - label, case_id, age, gender, source, wsi_id are optional
    - If wsi_id is not provided, it will be auto-generated
    - If case_id is not provided, it will be auto-generated as "case_{wsi_id}"
    - If label is not provided, it will be set to "Unknown"
    - age should be an integer (patient age in years)
    - gender should be a string (e.g., Male, Female, Other)
    - source should be a string (organ/tissue source, e.g., Cervix, Lung, Breast)

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
    import csv
    import io

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

                # Generate wsi_id if not provided
                if not wsi_id:
                    base_name = Path(wsi_path).stem
                    wsi_id = f"{base_name}_{uuid.uuid4().hex[:8]}"

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

                # Extract WSI properties
                wsi_props = extract_wsi_properties(wsi_path)

                # Generate case_id if not provided
                if not case_id:
                    case_id = f"case_{wsi_id}"

                # Create WSI in database
                wsi_data = {
                    "wsi_id": wsi_id,
                    "label": label or "Unknown",
                    "case_id": case_id,
                    "wsi_path": wsi_path,
                    "age": age,
                    "gender": gender,
                    "source": source,
                    "mpp": wsi_props["mpp"],
                    "vendor": wsi_props["vendor"],
                    "width": wsi_props["width"],
                    "height": wsi_props["height"],
                    "magnification": wsi_props["magnification"],
                }

                wsi = await WSIRepository.create(db, wsi_data)
                await db.commit()

                results.append({
                    "wsi_id": wsi_id,
                    "wsi_path": wsi_path,
                    "label": wsi.label,
                    "case_id": case_id,
                    "status": "success",
                    "message": "WSI registered successfully"
                })
                success_count += 1

                print(f"[Gateway] Registered WSI from CSV: {wsi_id}")

            except Exception as e:
                results.append({
                    "wsi_path": wsi_path,
                    "wsi_id": wsi_id if wsi_id else "N/A",
                    "status": "failed",
                    "message": str(e)
                })
                failed_count += 1
                print(f"[Gateway] Failed to register WSI from CSV: {wsi_path}, error: {e}")

        return {
            "total": len(results),
            "success": success_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        print(f"[Gateway] Failed to process CSV file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process CSV file: {str(e)}")


# ============================================================================
# Training Pipeline
# ============================================================================

async def run_training_pipeline(
    task_id: str,
    wsi_ids: List[str],
    preprocessing_config: Dict,
    model_config: Dict
):
    """
    Run the complete training pipeline:
    1. Patch extraction for all WSI slides
    2. Feature extraction (TODO)
    3. Model training (TODO)
    """
    from smartresearch.services.backend.database.utils.training_logger import TrainingLogger

    # Create new database session for background task
    async for db in get_db():
        logger = None
        try:
            # Initialize training logger
            logger = TrainingLogger(task_id, db)

            # Update task status to running
            await TrainingTaskRepository.update_status(db, task_id, "running", progress=0)
            await db.commit()

            await logger.info(f"🚀 Starting training pipeline for task: {task_id}")
            await db.commit()  # Commit log entry

            # Step 1: Patch extraction for all WSI slides
            total_wsi = len(wsi_ids)
            patch_size = preprocessing_config.get('tile_size', 512)
            stride = preprocessing_config.get('stride', 512)
            level = preprocessing_config.get('level', 0)
            # If stride is 0, use patch_size (no overlap)
            if stride == 0:
                stride = patch_size

            # Tissue segmentation parameters
            sthresh = preprocessing_config.get('sthresh', 5)  # Very low threshold for maximum tissue detection
            mthresh = preprocessing_config.get('mthresh', 7)
            close = preprocessing_config.get('close', 4)
            use_otsu = preprocessing_config.get('use_otsu', False)
            contour_fn = preprocessing_config.get('contour_fn', 'four_pt')
            use_padding = preprocessing_config.get('use_padding', True)

            # Filter parameters - minimal filtering for maximum patch extraction
            a_t = preprocessing_config.get('a_t', 1)  # Minimal area threshold
            a_h = preprocessing_config.get('a_h', 256)  # Filter out small holes (larger = more filtering)
            max_n_holes = preprocessing_config.get('max_n_holes', 100)

            await logger.info(f"Step 1/3: Extracting patches from {total_wsi} WSI slides")
            await logger.info(f"Patch size: {patch_size}x{patch_size}, Stride: {stride}, Level: {level}",
                            metadata={"patch_size": patch_size, "stride": stride, "level": level})
            await logger.info(f"Tissue segmentation: sthresh={sthresh}, mthresh={mthresh}, close={close}",
                            metadata={"sthresh": sthresh, "mthresh": mthresh, "close": close})
            await db.commit()

            for idx, wsi_id in enumerate(wsi_ids, 1):
                try:
                    await logger.info(f"Processing WSI {idx}/{total_wsi}: {wsi_id}",
                                    metadata={"wsi_index": idx, "total_wsi": total_wsi, "wsi_id": wsi_id})
                    await db.commit()

                    # Call preprocessing service to compute patches
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        response = await client.post(
                            f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                            params={
                                "patch_size": patch_size,
                                "stride": stride,
                                "level": level,
                                "force_recompute": True,  # Always recompute to use latest parameters
                                "sthresh": sthresh,
                                "mthresh": mthresh,
                                "close": close,
                                "use_otsu": use_otsu,
                                "contour_fn": contour_fn,
                                "use_padding": use_padding,
                                "a_t": a_t,
                                "a_h": a_h,
                                "max_n_holes": max_n_holes,
                                "save_mask": True
                            }
                        )
                        response.raise_for_status()
                        result = response.json()

                        num_patches = result.get('num_patches', 0)
                        num_contours = result.get('num_contours', 0)
                        mask_file = result.get('mask_file')

                        await logger.info(f"✓ Extracted {num_patches} patches from {wsi_id}",
                                        metadata={"wsi_id": wsi_id, "num_patches": num_patches, "num_contours": num_contours})

                        if mask_file:
                            await logger.info(f"✓ Generated tissue segmentation mask",
                                            metadata={"wsi_id": wsi_id, "mask_file": mask_file})

                        await db.commit()

                    # Update progress
                    progress = int((idx / total_wsi) * 33)  # Patch extraction is 33% of total
                    await TrainingTaskRepository.update_status(db, task_id, "running", progress=progress)
                    await db.commit()

                except Exception as e:
                    await logger.error(f"✗ Failed to extract patches from {wsi_id}: {e}",
                                     metadata={"wsi_id": wsi_id, "error": str(e)})
                    await db.commit()
                    raise

            await logger.info(f"✓ Patch extraction completed for all {total_wsi} WSI slides")
            await db.commit()

            # Step 2: Feature extraction
            await logger.info("Step 2/3: Feature extraction")
            await TrainingTaskRepository.update_status(db, task_id, "running", progress=40)
            await db.commit()

            feature_extractor = model_config.get("feature_extractor", "resnet50")
            batch_size = model_config.get("batch_size", 256)  # Increased from 64 for faster processing
            device = model_config.get("device", "cuda")

            await logger.info(f"Extracting features using {feature_extractor}",
                            metadata={"feature_extractor": feature_extractor, "batch_size": batch_size})
            await db.commit()

            # Call AI service for feature extraction
            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    response = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/extract_features",
                        json={
                            "task_id": task_id,
                            "wsi_ids": wsi_ids,
                            "feature_extractor": feature_extractor,
                            "batch_size": batch_size,
                            "device": device
                        }
                    )
                    response.raise_for_status()
                    feature_result = response.json()

                    feature_paths = feature_result.get("feature_paths", {})
                    await logger.info(f"✓ Feature extraction completed for {len(feature_paths)} WSI slides",
                                    metadata={"num_wsi": len(feature_paths)})
                    await db.commit()

            except Exception as e:
                await logger.error(f"✗ Feature extraction failed: {e}", metadata={"error": str(e)})
                await db.commit()
                raise

            await TrainingTaskRepository.update_status(db, task_id, "running", progress=60)
            await db.commit()

            # Step 3: Model training
            await logger.info("Step 3/3: Model training")
            await db.commit()

            # Get WSI labels and prepare training data
            wsi_labels = {}
            train_split = []
            val_split = []

            for wsi_id in wsi_ids:
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if wsi and wsi.label:
                    wsi_labels[wsi_id] = wsi.label

            # Get training task to retrieve classes and splits
            training_task = await TrainingTaskRepository.get_by_id(db, task_id)
            classes = training_task.classes if training_task else []

            # Simple split: 80% train, 20% val
            import random
            random.seed(42)
            shuffled_ids = wsi_ids.copy()
            random.shuffle(shuffled_ids)
            split_idx = int(len(shuffled_ids) * 0.8)
            train_split = shuffled_ids[:split_idx]
            val_split = shuffled_ids[split_idx:]

            await logger.info(f"Training split: {len(train_split)} WSI, Validation split: {len(val_split)} WSI",
                            metadata={"train_count": len(train_split), "val_count": len(val_split)})
            await db.commit()

            # Prepare training config
            training_config = {
                "feature_extractor": feature_extractor,
                "aggregator": model_config.get("aggregator", "abmil"),
                "epochs": model_config.get("epochs", 10),
                "learning_rate": model_config.get("learning_rate", 1e-4),
                "batch_size": batch_size,
                "device": device,
                "train_split": train_split,
                "val_split": val_split,
            }

            # Call AI service for training
            try:
                async with httpx.AsyncClient(timeout=1800.0) as client:  # 30 min timeout
                    response = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/train",
                        json={
                            "task_id": task_id,
                            "feature_paths": feature_paths,
                            "wsi_labels": wsi_labels,
                            "classes": classes,
                            "config": training_config
                        }
                    )
                    response.raise_for_status()
                    training_result = response.json()

                    model_id = training_result.get("model_id")
                    train_metrics = training_result.get("train_metrics", {})
                    val_metrics = training_result.get("val_metrics", {})

                    await logger.info(f"✓ Model training completed",
                                    metadata={
                                        "model_id": model_id,
                                        "train_acc": train_metrics.get("accuracy"),
                                        "val_acc": val_metrics.get("accuracy")
                                    })
                    await db.commit()

            except Exception as e:
                await logger.error(f"✗ Model training failed: {e}", metadata={"error": str(e)})
                await db.commit()
                raise

            # Mark as completed
            await TrainingTaskRepository.update_status(
                db, task_id, "completed", progress=100
            )
            await logger.info(f"✅ Training pipeline completed successfully")
            await db.commit()

        except Exception as e:
            if logger:
                await logger.error(f"❌ Training pipeline failed: {e}", metadata={"error": str(e)})
            await TrainingTaskRepository.update_status(
                db, task_id, "failed", progress=0, error_message=str(e)
            )
            await db.commit()

        finally:
            # Close logger
            if logger:
                await logger.close()
            # Close database session
            await db.close()


# ============================================================================
# Trained Model APIs
# ============================================================================

@app.get("/models")
async def list_trained_models(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all trained models"""
    models = await TrainedModelRepository.get_all(db, limit, skip)
    return {"items": [model.to_dict() for model in models]}


@app.get("/models/{model_id}")
async def get_trained_model(
    model_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get trained model details"""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")
    return model.to_dict()


@app.get("/tasks/training/{task_id}/models")
async def get_task_models(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all models from a training task"""
    models = await TrainedModelRepository.get_by_task_id(db, task_id)
    return {"items": [model.to_dict() for model in models]}


# ============================================================================
# AI Chat & Task Parsing APIs
# ============================================================================

class ChatRequest(BaseModel):
    """Request model for AI chat"""
    conversation_id: Optional[str] = None  # Optional conversation ID for persistence
    messages: List[Dict[str, str]]


class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation"""
    user_id: Optional[str] = "default_user"
    title: Optional[str] = None


@app.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a new conversation"""
    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": req.user_id,
        "title": req.title or "New Conversation",
    }
    conversation = await ChatRepository.create_conversation(db, conversation_data)
    await db.commit()
    return conversation.to_dict()


@app.get("/conversations")
async def list_conversations(
    user_id: str = "default_user",
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List all conversations for a user"""
    conversations = await ChatRepository.get_user_conversations(db, user_id, skip, limit)
    return {"items": [conv.to_dict() for conv in conversations]}


@app.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a conversation with all messages"""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        **conversation.to_dict(),
        "messages": [msg.to_dict() for msg in conversation.messages]
    }


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a conversation"""
    success = await ChatRepository.delete_conversation(db, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"message": "Conversation deleted successfully"}


class ParseTaskRequest(BaseModel):
    """Request model for task parsing"""
    description: str


async def stream_ai_response(
    messages: List[Dict[str, str]],
    api_key: str = None,
    base_url: str = None,
    model: str = None
) -> AsyncIterator[str]:
    """
    Stream AI response using SiliconFlow API (OpenAI-compatible).

    Args:
        messages: Chat messages
        api_key: SiliconFlow API key (from request header or env)
        base_url: SiliconFlow base URL (from request header or env)
        model: Model name (from request header or env)
    """
    # Use provided config or fall back to environment variables
    siliconflow_api_key = api_key or os.environ.get("SILICONFLOW_API_KEY")
    siliconflow_base_url = base_url or os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    siliconflow_model = model or os.environ.get("SILICONFLOW_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct")

    if not siliconflow_api_key:
        # Return error message if no API key is configured
        error_msg = """**AI Configuration Required**

To use the AI assistant, please configure your SiliconFlow API key:

1. Click **Settings** in the left sidebar
2. Enter your **SiliconFlow API Key** in the configuration form
3. Click **Save Settings**

**Get your API key:** [SiliconFlow Console](https://cloud.siliconflow.cn/account/ak)

After saving, return here and start chatting!"""

        # Output error message instantly (no typing effect for errors)
        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Real SiliconFlow API call with streaming
    try:
        print(f"[Gateway] Using SiliconFlow API with model: {siliconflow_model}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{siliconflow_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {siliconflow_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": siliconflow_model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            parsed = json.loads(data)
                            if "choices" in parsed and len(parsed["choices"]) > 0:
                                delta = parsed["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        print(f"[Gateway] Error in AI streaming: {e}")
        error_msg = f"❌ Error: {str(e)}\n\nPlease check your API key and network connection."
        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Chat with AI assistant (streaming).
    Returns Server-Sent Events (SSE) stream.

    If conversation_id is provided, messages will be persisted to database.

    AI configuration is read from HTTP headers:
    - X-SiliconFlow-API-Key: SiliconFlow API key
    - X-SiliconFlow-Base-URL: SiliconFlow base URL
    - X-SiliconFlow-Model: Model name
    """
    # Get AI configuration from request headers
    api_key = request.headers.get("X-SiliconFlow-API-Key")
    base_url = request.headers.get("X-SiliconFlow-Base-URL")
    model = request.headers.get("X-SiliconFlow-Model")

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        system_prompt = {
            "role": "system",
            "content": """You are an AI assistant for SmartResearch, a pathology AI platform.
You help researchers set up and run WSI (Whole Slide Image) classification tasks.

Available models:
- ResNet50: Feature extractor (2048-dim features)
- ViT-Large: Vision Transformer (1024-dim features)

Available aggregators:
- ABMIL: Attention-based Multiple Instance Learning
- Mean: Simple mean pooling

When users describe a research task, help them:
1. Understand their requirements
2. Select appropriate models and parameters
3. Guide them through the task setup process

Be concise, helpful, and technical when appropriate."""
        }
        messages.insert(0, system_prompt)

    # If conversation_id is provided, save user message to database
    if req.conversation_id and len(req.messages) > 0:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": last_user_message.get("content", ""),
            }
            await ChatRepository.add_message(db, message_data)
            await db.commit()

    # Stream AI response
    async def stream_with_persistence():
        """Stream AI response and save to database if conversation_id is provided"""
        full_response = ""
        async for chunk in stream_ai_response(messages, api_key, base_url, model):
            yield chunk
            # Extract content from SSE chunk
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk[6:])
                    if "content" in data:
                        full_response += data["content"]
                except:
                    pass

        # Save assistant response to database
        if req.conversation_id and full_response:
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "assistant",
                "content": full_response,
            }
            await ChatRepository.add_message(db, message_data)
            await db.commit()

    return StreamingResponse(
        stream_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/parse-task")
async def parse_task(req: ParseTaskRequest, request: Request):
    """
    Parse natural language task description into structured parameters.
    Uses LLM to extract task type, models, and configuration.

    AI configuration is read from HTTP headers:
    - X-SiliconFlow-API-Key: SiliconFlow API key
    - X-SiliconFlow-Base-URL: SiliconFlow base URL
    - X-SiliconFlow-Model: Model name
    """
    # Get AI configuration from request headers
    api_key = request.headers.get("X-SiliconFlow-API-Key")
    base_url = request.headers.get("X-SiliconFlow-Base-URL", "https://api.siliconflow.cn/v1")
    model = request.headers.get("X-SiliconFlow-Model", "Qwen/Qwen3-VL-235B-A22B-Instruct")

    if not api_key:
        # Return error if no API key is provided
        raise HTTPException(
            status_code=400,
            detail="AI configuration required. Please configure your SiliconFlow API key in Settings."
        )

    # Real SiliconFlow API call
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": """You are a task parser for a pathology AI platform.
Extract structured information from natural language task descriptions.

Return JSON with:
- task_type: "wsi_classification" or "wsi_segmentation"
- models: array of model names (e.g., ["resnet50", "vit_large"])
- description: cleaned task description
- suggested_params: object with tile_size, stride, aggregator

Available models: resnet50, vit_large
Available aggregators: abmil, mean"""
                        },
                        {
                            "role": "user",
                            "content": f"Parse this task: {req.description}"
                        }
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"}
                }
            )
            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed

    except Exception as e:
        print(f"[Gateway] Error parsing task: {e}")
        # Fallback to mock response
        return {
            "task_type": "wsi_classification",
            "models": ["resnet50"],
            "description": req.description,
            "suggested_params": {
                "tile_size": 224,
                "stride": 224,
                "aggregator": "abmil"
            }
        }
