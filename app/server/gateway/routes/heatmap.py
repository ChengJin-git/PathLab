"""
Heatmap and Visualization Proxy Routes

Proxies heatmap-related requests to the Preprocessing Service.
This maintains a unified API interface through the Gateway.
"""
from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import Response
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import logger
from ..utils import proxy_preprocessing_binary, proxy_preprocessing_json
from backend.database import get_db
from backend.auth import current_active_user, User, get_user_from_header_or_param
from backend.auth.dependencies import get_wsi_with_access
from backend.services.result_access import authorized_task_ids, require_result_task, select_result_artifact

router = APIRouter(prefix="/heatmap", tags=["Heatmap & Visualization"])

RECOMMENDATION_PRESET = "recommendation"
DEFAULT_PROXY_TIMEOUT_SECONDS = 30.0
PATCH_RECOMMENDATION_PROXY_TIMEOUT_SECONDS = 60.0


def _get_patch_overlay_proxy_timeout(preset: Optional[str]) -> float:
    if preset == RECOMMENDATION_PRESET:
        return PATCH_RECOMMENDATION_PROXY_TIMEOUT_SECONDS
    return DEFAULT_PROXY_TIMEOUT_SECONDS


async def _check_wsi_access(wsi_id: str, user: User, db: AsyncSession):
    """Helper to check WSI access permission (ownership or elevated dataset grant)."""
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
    """List authorized result summaries from the indexed artifact catalog."""
    await _check_wsi_access(wsi_id, user, db)
    from backend.services.viewer_results import result_entries
    return {'wsi_id':wsi_id,'heatmaps':await result_entries(db,user,wsi_id)}


@router.get("/wsi/{wsi_id}/data")
async def get_heatmap_data(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    class_idx: Optional[int] = Query(None, ge=0),
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
    task_id = await select_result_artifact(db, user, wsi_id, task_id, 'attention', fold_key)
    params = {"patch_size": patch_size}
    if class_idx is not None: params['class_idx'] = class_idx
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


async def _prediction_access(wsi_id, task_id, user, db):
    await _check_wsi_access(wsi_id, user, db)
    await require_result_task(db, user, task_id)


@router.get("/wsi/{wsi_id}/prediction")
async def get_prediction(wsi_id: str, task_id: str, fold_key: str | None = None,
                         threshold: float = Query(0.5, ge=0, le=1),
                         user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)):
    await _prediction_access(wsi_id, task_id, user, db)
    from backend.ai.result_store import AIResultStore
    from backend.common.config import Config
    from backend.services.result_analysis.segmentation_thresholds import metrics_at_threshold
    try:
        result = await asyncio.to_thread(AIResultStore(Config.get_uploads_dir()).read_result, task_id, wsi_id, fold_key)
    except (FileNotFoundError, KeyError):
        raise HTTPException(404, "Saved prediction unavailable") from None
    if result is None:
        raise HTTPException(404, "Saved prediction unavailable")
    if result.get("task_type") == "patch_segmentation":
        try:
            result = {**result, "metrics": metrics_at_threshold(result, threshold)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    from backend.services.result_analysis.visuals import class_colors
    payload = {key: result.get(key) for key in ("task_type", "pred", "probs", "classes", "class_names", "image_size", "detection", "metrics", "segmentation_preview", "has_ground_truth")}
    payload['class_colors'] = class_colors(result.get('class_names') or result.get('classes'))
    return payload


@router.get("/wsi/{wsi_id}/prediction_mask")
async def get_prediction_mask(wsi_id: str, task_id: str,
                              threshold: float = Query(0.5, ge=0, le=1),
                              class_index: int = Query(0, ge=0, le=1023),
                              layer: str = Query("pred", pattern="^(gt|pred)$"),
                              fold_key: str | None = None,
                              user: User = Depends(get_user_from_header_or_param), db: AsyncSession = Depends(get_db)):
    await _prediction_access(wsi_id, task_id, user, db)
    if abs(threshold * 100 - round(threshold * 100)) > 1e-6:
        raise HTTPException(422, "Pixel thresholds use increments of 0.01")
    from backend.services.result_analysis.previews import render_mask
    from backend.common.config import Config
    try:
        content = await asyncio.to_thread(render_mask, Config.get_uploads_dir(), task_id, wsi_id, layer, class_index, threshold, fold_key)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/wsi/{wsi_id}/patch_image")
async def get_patch_image(
    wsi_id: str,
    x: int = Query(..., description="X coordinate of patch"),
    y: int = Query(..., description="Y coordinate of patch"),
    size: int = Query(256, description="Patch size"),
    level: int = Query(0, description="Pyramid level"),
    thumbnail_size: int | None = Query(None, ge=32, le=512),
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
    params = {"x": x, "y": y, "size": size, "level": level}
    if thumbnail_size is not None:
        params["thumbnail_size"] = thumbnail_size
    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/patch_image",
        params=params,
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
    task_id = await select_result_artifact(db, user, wsi_id, task_id, 'cam', fold_key)
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
            timeout=_get_patch_overlay_proxy_timeout(preset),
        )

    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/patch_cam",
        params=params,
        timeout=_get_patch_overlay_proxy_timeout(preset),
        default_media_type="image/png",
    )


@router.get("/wsi/{wsi_id}/seg_mask")
async def get_seg_mask(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
    preset: Optional[str] = Query(None, description="Optional rendering preset for lightweight previews"),
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
    task_id = await select_result_artifact(db, user, wsi_id, task_id, 'pred_mask', fold_key)
    if task_id:
        params["task_id"] = task_id
    if fold_key:
        params["fold_key"] = fold_key
    if preset:
        params["preset"] = preset
    if size is not None:
        params["size"] = size

    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/seg_mask",
        params=params,
        timeout=_get_patch_overlay_proxy_timeout(preset),
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
    task_id = await select_result_artifact(db, user, wsi_id, task_id, 'attention', fold_key)
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
    preset: Optional[str] = Query(None, description="Optional rendering preset for lightweight previews"),
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
    params = {"size": size}
    if preset:
        params["preset"] = preset
    return await proxy_preprocessing_binary(
        "GET",
        f"/wsi/{wsi_id}/thumbnail",
        params=params,
        timeout=30.0,
        default_media_type="image/jpeg",
    )
