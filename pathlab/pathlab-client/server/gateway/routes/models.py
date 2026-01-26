"""
Trained model management routes
Handles listing, retrieving, and managing trained models
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import TrainedModelRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership

router = APIRouter(prefix="/models", tags=["Trained Models"])


class ModelUpdateRequest(BaseModel):
    """Request body for updating model properties"""
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_trained_models(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List all trained models. Users see only their own models, admin sees all."""
    user_id_filter = None if user.is_admin() else str(user.id)
    models = await TrainedModelRepository.get_all(db, limit, skip, user_id=user_id_filter)
    total = await TrainedModelRepository.count(db, user_id=user_id_filter)
    return {"items": [model.to_dict() for model in models], "total": total}


@router.get("/{model_id}")
async def get_trained_model(
    model_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get trained model details. Users can only view their own models, admin can view all."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this model")

    return model.to_dict()


@router.patch("/{model_id}")
async def update_trained_model(
    model_id: str,
    req: ModelUpdateRequest,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update trained model properties (set default, activate/deactivate).
    Requires pathologist or admin role. Users can only update their own models."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to update this model")

    # Handle is_default update
    if req.is_default is True:
        model = await TrainedModelRepository.set_default(db, model_id)
        await db.commit()
        return model.to_dict()

    # Handle is_active update
    if req.is_active is not None:
        model = await TrainedModelRepository.set_active(db, model_id, req.is_active)
        await db.commit()
        return model.to_dict()

    return model.to_dict()


@router.delete("/{model_id}")
async def delete_trained_model(
    model_id: str,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete a trained model. Requires pathologist or admin role.
    Users can only delete their own models, admin can delete any."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this model")

    deleted = await TrainedModelRepository.delete(db, model_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete model")

    await db.commit()
    return {"message": "Model deleted successfully", "model_id": model_id}

