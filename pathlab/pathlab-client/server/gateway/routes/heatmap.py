"""
Heatmap and Visualization Proxy Routes

Proxies heatmap-related requests to the Preprocessing Service.
This maintains a unified API interface through the Gateway.
"""
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..dependencies import logger, PREPROCESSING_SERVICE_URL

router = APIRouter(prefix="/heatmap", tags=["Heatmap & Visualization"])


@router.get("/wsi/{wsi_id}/available")
async def get_available_heatmaps(wsi_id: str):
    """
    Get list of available heatmaps (attention data) for a WSI.
    
    Proxies to: GET /wsi/{wsi_id}/available_heatmaps
    """
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
    patch_size: int = Query(512, description="Patch size used during inference")
):
    """
    Get attention heatmap data for visualization overlay.
    
    Proxies to: GET /wsi/{wsi_id}/heatmap
    """
    logger.info(f"Proxying heatmap data request for WSI: {wsi_id}")
    
    try:
        params = {"patch_size": patch_size}
        if task_id:
            params["task_id"] = task_id
            
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
    level: int = Query(0, description="Pyramid level")
):
    """
    Get a patch image at the specified coordinates.
    
    Proxies to: GET /wsi/{wsi_id}/patch_image
    """
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
    format: str = Query("image", description="Output format: 'image' or 'json'")
):
    """
    Get patch-level CAM (Class Activation Map) for visualization.

    Proxies to: GET /wsi/{wsi_id}/patch_cam
    """
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
async def get_patch_file_image(wsi_id: str):
    """
    Get the entire patch image for patch classification tasks.

    Proxies to: GET /wsi/{wsi_id}/image
    """
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

