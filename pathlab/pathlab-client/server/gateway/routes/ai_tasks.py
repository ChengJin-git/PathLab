"""
AI inference task management routes
Handles WSI classification and other AI inference tasks
"""
import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    TrainingTaskRepository,
)
from ..dependencies import logger, AI_SERVICE_URL
from ..models import WSIClassifyRequest

router = APIRouter(prefix="/tasks", tags=["AI Inference"])


@router.post("/wsi_classification")
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
        logger.info(f"Auto-detected classes from database: {classes}")

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
                "task_type": "wsi_classification",
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


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get task status from database.
    Checks both AI inference tasks and training tasks.
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
