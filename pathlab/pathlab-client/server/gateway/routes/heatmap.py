"""
Heatmap and Visualization Proxy Routes

Proxies heatmap-related requests to the Preprocessing Service.
This maintains a unified API interface through the Gateway.
"""
from typing import Optional
from fastapi import APIRouter, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import logger
from ..utils import proxy_preprocessing_binary, proxy_preprocessing_json
from backend.database import get_db
from backend.auth import current_active_user, User, get_user_from_header_or_param
from backend.auth.dependencies import get_wsi_with_access

router = APIRouter(prefix="/heatmap", tags=["Heatmap & Visualization"])


async def _check_wsi_access(wsi_id: str, user: User, db: AsyncSession):
    """Helper to check WSI access permission (ownership or elevated dataset permission)."""
    await get_wsi_with_access(
        wsi_id,
        user,
        db,
        with_dataset=True,
        forbidden_detail="You don't have permission to view this WSI's heatmap",
    )


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
    return await proxy_preprocessing_json(
        "GET",
        f"/wsi/{wsi_id}/available_heatmaps",
        timeout=30.0,
    )


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
    params = {"patch_size": patch_size}
    if task_id:
        params["task_id"] = task_id
    if fold_key:
        params["fold_key"] = fold_key

    return await proxy_preprocessing_json(
        "GET",
        f"/wsi/{wsi_id}/heatmap",
        params=params,
        timeout=60.0,
    )


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
    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/patch_image",
        params={"x": x, "y": y, "size": size, "level": level},
        timeout=30.0,
        default_media_type="image/jpeg",
    )


@router.get("/wsi/{wsi_id}/patch_cam")
async def get_patch_cam(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    format: str = Query("image", description="Output format: 'image' or 'json'"),
    preset: Optional[str] = Query(None, description="Optional rendering preset for lightweight previews"),
    size: Optional[int] = Query(None, description="Optional max thumbnail size for preview rendering"),
    opacity: Optional[float] = Query(None, description="Optional overlay opacity for preview rendering"),
    blur_scale: Optional[float] = Query(None, description="Optional blur scale multiplier for preview rendering"),
    contrast_boost: Optional[float] = Query(None, description="Optional contrast boost for preview rendering"),
    saturation_boost: Optional[float] = Query(None, description="Optional saturation boost for preview rendering"),
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
    params = {"format": format}
    if task_id:
        params["task_id"] = task_id
    if fold_key:
        params["fold_key"] = fold_key
    if preset:
        params["preset"] = preset
        if size is not None:
            params["size"] = size
        if opacity is not None:
            params["opacity"] = opacity
        if blur_scale is not None:
            params["blur_scale"] = blur_scale
        if contrast_boost is not None:
            params["contrast_boost"] = contrast_boost
        if saturation_boost is not None:
            params["saturation_boost"] = saturation_boost

    if format == "json":
        return await proxy_preprocessing_json(
            "GET",
            f"/wsi/{wsi_id}/patch_cam",
            params=params,
            timeout=30.0,
        )

    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/patch_cam",
        params=params,
        timeout=30.0,
        default_media_type="image/png",
    )


@router.get("/wsi/{wsi_id}/seg_mask")
async def get_seg_mask(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
    size: Optional[int] = Query(None, description="Optional max thumbnail size for previews"),
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get patch segmentation mask overlay image.
    Proxies to: GET /wsi/{wsi_id}/seg_mask
    """
    await _check_wsi_access(wsi_id, user, db)
    params = {}
    if task_id:
        params["task_id"] = task_id
    if fold_key:
        params["fold_key"] = fold_key
    if size is not None:
        params["size"] = size

    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/seg_mask",
        params=params,
        timeout=30.0,
        default_media_type="image/png",
    )


@router.get("/wsi/{wsi_id}/info")
async def get_wsi_info(
    wsi_id: str,
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db)
):
    """
    Get WSI info including whether it's a patch or WSI.
    Used by frontend to determine display mode.

    Supports authentication via:
    - Authorization header: Bearer <token>
    - Query parameter: ?token=<token> (for <img> tags)

    Proxies to: GET /wsi/{wsi_id}/info
    """
    await _check_wsi_access(wsi_id, user, db)
    return await proxy_preprocessing_json(
        "GET",
        f"/wsi/{wsi_id}/info",
        timeout=30.0,
    )


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
    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/image",
        timeout=30.0,
        default_media_type="image/jpeg",
    )


@router.get("/wsi/{wsi_id}/heatmap_thumbnail")
async def get_heatmap_thumbnail(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    class_idx: Optional[int] = Query(None, description="Class index for multi-class attention"),
    preset: Optional[str] = Query(None, description="Optional rendering preset for lightweight previews"),
    opacity: Optional[float] = Query(None, description="Optional overlay opacity for preview rendering"),
    blur_scale: Optional[float] = Query(None, description="Optional blur scale multiplier for preview rendering"),
    contrast_boost: Optional[float] = Query(None, description="Optional contrast boost for preview rendering"),
    saturation_boost: Optional[float] = Query(None, description="Optional saturation boost for preview rendering"),
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
    params = {"patch_size": patch_size, "size": size}
    if task_id:
        params["task_id"] = task_id
    if fold_key:
        params["fold_key"] = fold_key
    if class_idx is not None:
        params["class_idx"] = class_idx
    if preset:
        params["preset"] = preset
        if opacity is not None:
            params["opacity"] = opacity
        if blur_scale is not None:
            params["blur_scale"] = blur_scale
        if contrast_boost is not None:
            params["contrast_boost"] = contrast_boost
        if saturation_boost is not None:
            params["saturation_boost"] = saturation_boost

    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/heatmap_thumbnail",
        params=params,
        timeout=60.0,
        default_media_type="image/png",
    )


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
    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/thumbnail",
        params={"size": size},
        timeout=30.0,
        default_media_type="image/jpeg",
    )

