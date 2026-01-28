"""
Heatmap and Visualization Proxy Routes

Proxies heatmap-related requests to the Preprocessing Service.
This maintains a unified API interface through the Gateway.
"""
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import logger, PREPROCESSING_SERVICE_URL
from backend.database import get_db
from backend.database.repositories import WSIRepository
from backend.auth import current_active_user, User, get_user_from_header_or_param
from backend.auth.dependencies import check_wsi_access_permission

router = APIRouter(prefix="/heatmap", tags=["Heatmap & Visualization"])


async def _check_wsi_access(wsi_id: str, user: User, db: AsyncSession):
    """Helper to check WSI access permission (ownership or elevated dataset permission)"""
    wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    if wsi:
        has_access = await check_wsi_access_permission(user, wsi.dataset_id, wsi.user_id, db)
        if not has_access:
            raise HTTPException(status_code=403, detail="You don't have permission to view this WSI's heatmap")


@router.get("/wsi/{wsi_id}/available")
async def get_available_heatmaps(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available heatmaps (attention data) for a WSI.
    Users can only view their own WSI's heatmaps.

    Proxies to: GET /wsi/{wsi_id}/available_heatmaps
    """
    await _check_wsi_access(wsi_id, user, db)
    logger.info(f"Proxying available_heatmaps request for WSI: {wsi_id}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/available_heatmaps"
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get available heatmaps: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/data")
async def get_heatmap_data(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get attention heatmap data for visualization overlay.
    Users can only view their own WSI's heatmaps.

    Proxies to: GET /wsi/{wsi_id}/heatmap
    """
    await _check_wsi_access(wsi_id, user, db)
    logger.info(f"Proxying heatmap data request for WSI: {wsi_id}, fold_key={fold_key}")

    try:
        params = {"patch_size": patch_size}
        if task_id:
            params["task_id"] = task_id
        if fold_key:
            params["fold_key"] = fold_key

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/heatmap",
                params=params
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/patch_image")
async def get_patch_image(
    wsi_id: str,
    x: int = Query(..., description="X coordinate of patch"),
    y: int = Query(..., description="Y coordinate of patch"),
    size: int = Query(256, description="Patch size"),
    level: int = Query(0, description="Pyramid level"),
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a patch image at the specified coordinates.
    Users can only view their own WSI's patches.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/patch_image
    """
    await _check_wsi_access(wsi_id, user, db)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/patch_image",
                params={"x": x, "y": y, "size": size, "level": level}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )
            
            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/jpeg")
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/patch_cam")
async def get_patch_cam(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    format: str = Query("image", description="Output format: 'image' or 'json'"),
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get patch-level CAM (Class Activation Map) for visualization.
    Users can only view their own WSI's CAM.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/patch_cam
    """
    await _check_wsi_access(wsi_id, user, db)
    try:
        params = {"format": format}
        if task_id:
            params["task_id"] = task_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/patch_cam",
                params=params
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            if format == "json":
                return response.json()
            else:
                return Response(
                    content=response.content,
                    media_type=response.headers.get("content-type", "image/png")
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch CAM: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/image")
async def get_patch_file_image(
    wsi_id: str,
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the entire patch image for patch classification tasks.
    Users can only view their own WSI's images.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/image
    """
    await _check_wsi_access(wsi_id, user, db)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/image"
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/jpeg")
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch file image: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/heatmap_thumbnail")
async def get_heatmap_thumbnail(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    class_idx: Optional[int] = Query(None, description="Class index for multi-class attention"),
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a rendered heatmap thumbnail image for a WSI.
    Users can only view their own WSI's heatmaps.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/heatmap_thumbnail
    """
    await _check_wsi_access(wsi_id, user, db)
    try:
        params = {"patch_size": patch_size, "size": size}
        if task_id:
            params["task_id"] = task_id
        if fold_key:
            params["fold_key"] = fold_key
        if class_idx is not None:
            params["class_idx"] = class_idx

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/heatmap_thumbnail",
                params=params
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/png")
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap thumbnail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wsi/{wsi_id}/thumbnail")
async def get_thumbnail(
    wsi_id: str,
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get thumbnail image for a WSI or patch file.
    Users can only view their own WSI's thumbnails.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/thumbnail
    """
    await _check_wsi_access(wsi_id, user, db)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/thumbnail",
                params={"size": size}
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/jpeg")
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Preprocessing service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get thumbnail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

