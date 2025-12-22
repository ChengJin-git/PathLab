"""
AI Results API Routes

Handles retrieval of AI analysis results.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab.services.backend.database import get_db
from pathlab.services.backend.database.repositories import AIResultRepository

router = APIRouter(prefix="/results", tags=["AI Results"])


@router.get("/{wsi_id}")
async def get_results(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get AI analysis results for a WSI from database.
    
    Args:
        wsi_id: The WSI ID to get results for
        
    Returns:
        AI result data including predictions and probabilities
    """
    # Get from database
    result = await AIResultRepository.get_by_wsi_id(db, wsi_id)
    if result:
        return result.to_dict()

    # No result found
    return {"wsi_id": wsi_id, "pred": None, "probs": None}

