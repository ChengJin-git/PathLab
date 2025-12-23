"""
Trained model management routes
Handles listing and retrieving trained models
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pathstudio.services.backend.database import get_db
from pathstudio.services.backend.database.repositories import TrainedModelRepository

router = APIRouter(prefix="/models", tags=["Trained Models"])


@router.get("")
async def list_trained_models(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all trained models"""
    models = await TrainedModelRepository.get_all(db, limit, skip)
    return {"items": [model.to_dict() for model in models]}


@router.get("/{model_id}")
async def get_trained_model(
    model_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get trained model details"""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")
    return model.to_dict()

