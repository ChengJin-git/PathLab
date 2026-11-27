"""
Heatmap and CAM visualization endpoints for the Preprocessing Service.

Extracted from main.py to reduce file size. Handles:
- WSI attention heatmap data (JSON)
- WSI attention heatmap thumbnail (rendered image)
- Available heatmaps listing
- Patch-level CAM visualization
"""

import logging
import math
from importlib import import_module
from pathlib import Path
from typing import Dict, Optional, Any, Mapping, cast

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

_result_store_mod = import_module("backend.ai.result_store")
AIResultStore = _result_store_mod.AIResultStore
ATTENTION_ARTIFACT = _result_store_mod.ATTENTION_ARTIFACT
CAM_ARTIFACT = _result_store_mod.CAM_ARTIFACT
PRED_MASK_ARTIFACT = _result_store_mod.PRED_MASK_ARTIFACT
get_db = import_module("backend.database").get_db
WSIRepository = import_module("backend.database.repositories").WSIRepository
Config = import_module("backend.common.config").Config
is_patch_file = import_module("backend.common.file_types").is_patch_file
find_any_cached_coords_for_wsi = import_module(
    "backend.ai.tasks.patch_cache"
).find_any_cached_coords_for_wsi
from .coords_utils import safe_load_h5_coords
from .heatmap_utils import (
    handle_multi_class_attention,
    normalize_attention,
    find_best_fold,
)
from .slide_access import get_slide

logger = logging.getLogger(__name__)

from backend.common.internal_requests import require_internal_request
router = APIRouter(dependencies=[Depends(require_internal_request)])


def _uploads_dir() -> Path:
    return Config.get_uploads_dir()


def _result_store() -> AIResultStore:
    return AIResultStore(_uploads_dir())


def _probe_fold_candidates(task_id: str) -> list[str | None]:
    candidates: list[str | None] = [None]
    best_fold = find_best_fold(task_id, _uploads_dir())
    if best_fold:
        candidates.append(best_fold)
    for idx in range(10):
        fold = f"fold_{idx}"
        if fold not in candidates:
            candidates.append(fold)
    return candidates


def _select_artifact_target(
    store: AIResultStore,
    wsi_id: str,
    artifact: str,
    task_id: str | None,
    fold_key: str | None,
) -> tuple[str, str | None] | None:
    if task_id:
        if fold_key is not None:
            if store.artifact_exists(
                task_id, wsi_id, artifact, fold_key=fold_key, strict=True
            ):
                return task_id, fold_key
            return None
        if store.artifact_exists(
            task_id, wsi_id, artifact, fold_key=None, strict=True
        ):
            return task_id, None
        for candidate_fold in _probe_fold_candidates(task_id):
            if candidate_fold is None:
                continue
            if store.artifact_exists(
                task_id, wsi_id, artifact, fold_key=candidate_fold, strict=True
            ):
                return task_id, candidate_fold
        for item in store.list_task_wsi_artifacts(task_id, wsi_id):
            if item.get("artifact") != artifact:
                continue
            discovered_fold = item.get("fold_key")
            if discovered_fold and store.artifact_exists(
                task_id, wsi_id, artifact, fold_key=discovered_fold, strict=True
            ):
                return task_id, discovered_fold
        return None

    task_ids = sorted(
        {
            item["task_id"]
            for item in store.list_wsi_artifacts(wsi_id)
            if item.get("artifact") == artifact
        }
    )
    for current_task_id in task_ids:
        if fold_key is not None:
            if store.artifact_exists(
                current_task_id, wsi_id, artifact, fold_key=fold_key, strict=True
            ):
                return current_task_id, fold_key
            continue
        if store.artifact_exists(
            current_task_id, wsi_id, artifact, fold_key=None, strict=True
        ):
            return current_task_id, None
        for candidate_fold in _probe_fold_candidates(current_task_id):
            if candidate_fold is None:
                continue
            if store.artifact_exists(
                current_task_id,
                wsi_id,
                artifact,
                fold_key=candidate_fold,
                strict=True,
            ):
                return current_task_id, candidate_fold
    return None


RECOMMENDATION_PRESET = "recommendation"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _get_render_settings(
    preset: Optional[str],
    opacity: Optional[float],
    blur_scale: Optional[float],
    contrast_boost: Optional[float],
    saturation_boost: Optional[float],
) -> Dict[str, Any]:
    is_recommendation = preset == RECOMMENDATION_PRESET
    return {
        "opacity": _clamp(
            opacity if opacity is not None else (0.68 if is_recommendation else 0.5),
            0.05,
            0.95,
        ),
        "blur_scale": _clamp(
            blur_scale
            if blur_scale is not None
            else (0.6 if is_recommendation else 1.0),
            0.1,
            3.0,
        ),
        "contrast_boost": _clamp(
            contrast_boost
            if contrast_boost is not None
            else (1.18 if is_recommendation else 1.0),
            0.5,
            3.0,
        ),
        "saturation_boost": _clamp(
            saturation_boost
            if saturation_boost is not None
            else (1.25 if is_recommendation else 1.0),
            0.5,
            3.0,
        ),
        "cache_headers": {"Cache-Control": "private, max-age=600"}
        if is_recommendation
        else {},
    }


def _cache_headers(render_settings: Mapping[str, Any]) -> Mapping[str, str]:
    return cast(Mapping[str, str], render_settings["cache_headers"])


def _coerce_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp_value(value: Any) -> float:
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except Exception:
            return 0.0
    return _coerce_float(value, 0.0)


def _enhance_overlay_image(image, contrast_boost: float, saturation_boost: float):
    from PIL import ImageEnhance

    if contrast_boost == 1.0 and saturation_boost == 1.0:
        return image

    if image.mode == "RGBA":
        alpha_channel = image.getchannel("A")
        rgb_image = image.convert("RGB")
        if saturation_boost != 1.0:
            rgb_image = ImageEnhance.Color(rgb_image).enhance(saturation_boost)
        if contrast_boost != 1.0:
            rgb_image = ImageEnhance.Contrast(rgb_image).enhance(contrast_boost)
        enhanced = rgb_image.convert("RGBA")
        enhanced.putalpha(alpha_channel)
        return enhanced

    enhanced = image
    if saturation_boost != 1.0:
        enhanced = ImageEnhance.Color(enhanced).enhance(saturation_boost)
    if contrast_boost != 1.0:
        enhanced = ImageEnhance.Contrast(enhanced).enhance(contrast_boost)
    return enhanced


def _get_thumbnail_blur_radius(
    patch_w: float,
    patch_h: float,
    blur_scale: float,
    preset: Optional[str],
) -> float:
    """
    Compute thumbnail blur radius.

    Recommendation cards use a more conservative blur when each patch collapses to
    only a couple of pixels in the thumbnail, which helps preserve local hotspots
    without increasing thumbnail resolution or payload size.
    """
    patch_extent = max(1.0, min(float(patch_w), float(patch_h)))
    base_radius = (patch_extent / 2.0) * blur_scale

    if preset == RECOMMENDATION_PRESET:
        if patch_extent <= 1.0:
            return 0.0
        if patch_extent <= 2.0:
            return min(0.35, base_radius)
        return max(0.45, base_radius * 0.7)

    return max(1.0, base_radius)


@router.get("/wsi/{wsi_id}/heatmap")
async def get_heatmap_data(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(
        None, description="Fold key for k-fold results (e.g., 'fold_0')"
    ),
    patch_size: int = Query(512, description="Patch size used during inference"),
    class_idx: Optional[int] = Query(
        None, description="Class index for multi-class attention (e.g., CLAM_MB)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get attention heatmap data for visualization overlay.

    For multi-class attention models (e.g., CLAM_MB), use class_idx to select which class's attention to visualize.
    If class_idx is not provided for multi-class attention, defaults to the predicted class.

    Returns:
        JSON with coordinates, attention weights, and metadata for rendering heatmap
    """
    logger.info(
        f"Getting heatmap data for {wsi_id}, task_id={task_id}, fold_key={fold_key}"
    )

    # Helper function to return empty heatmap response
    def empty_heatmap_response(message: str = "No heatmap data available"):
        return {
            "wsi_id": wsi_id,
            "task_id": task_id,
            "fold_key": fold_key,
            "task_name": None,
            "patch_size": patch_size,
            "slide_width": 0,
            "slide_height": 0,
            "num_patches": 0,
            "attention_min": 0,
            "attention_max": 0,
            "prediction": None,
            "probs": None,
            "heatmap": [],
            "top_patches": [],
            "bottom_patches": [],
            "message": message,
        }

    try:
        store = _result_store()
        selected = _select_artifact_target(
            store, wsi_id, ATTENTION_ARTIFACT, task_id, fold_key
        )
        if selected is None:
            logger.info(
                f"No attention data found for task {task_id}, fold_key={fold_key}"
            )
            return empty_heatmap_response(
                f"No attention data for task {task_id}"
                + (f" fold {fold_key}" if fold_key else "")
            )

        selected_task_id, selected_fold_key = selected
        attention = store.read_array(
            selected_task_id,
            wsi_id,
            ATTENTION_ARTIFACT,
            fold_key=selected_fold_key,
            strict=True,
        )
        logger.info(
            f"Loaded attention: shape={attention.shape}, min={attention.min()}, max={attention.max()}"
        )
        result_meta = store.read_result(
            selected_task_id,
            wsi_id,
            fold_key=selected_fold_key,
            strict=True,
        )

        # Load coordinates from coords.h5 (search across all params_hash directories)
        coords_file = find_any_cached_coords_for_wsi(_uploads_dir(), wsi_id)
        if coords_file is None:
            raise HTTPException(
                status_code=404,
                detail=f"Coordinates not found for {wsi_id}. Run compute_patches first.",
            )

        # Use safe loading to handle corrupted files
        coords, coords_attrs, load_error = safe_load_h5_coords(
            coords_file, delete_if_corrupted=False
        )
        if coords is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load coordinates for {wsi_id}: {load_error}. Please rerun compute_patches.",
            )

        logger.info(f"Loaded coordinates: shape={coords.shape}")
        # Coordinates are level-zero pixels; use the actual tile footprint for
        # thumbnails and click-to-focus, rather than the request's default size.
        attrs = coords_attrs or {}
        read_size = attrs.get("read_size", attrs.get("patch_size"))
        if read_size is not None:
            downsample = attrs.get("level_downsample", attrs.get("downsample", 1))
            if isinstance(downsample, (list, tuple)) or getattr(downsample, "ndim", 0) > 0:
                downsample = downsample[0]
            extent = float(read_size) * float(downsample)
            if math.isfinite(extent) and extent > 0:
                patch_size = max(1, round(extent))

        # Handle multi-class attention (e.g., CLAM_MB returns shape (num_classes, N))
        attention_type = result_meta.get("attention_type", "single")
        classes = result_meta.get("classes", [])
        num_attention_classes = attention.shape[0] if attention.ndim == 2 else None
        attention, selected_class_idx = handle_multi_class_attention(
            attention, result_meta, class_idx
        )

        # Verify shapes match
        num_patches = len(coords)
        if len(attention) != num_patches:
            logger.warning(
                f"Shape mismatch: attention={len(attention)}, coords={num_patches}"
            )
            # Truncate to smaller size
            min_len = min(len(attention), num_patches)
            attention = attention[:min_len]
            coords = coords[:min_len]

        # Contrast clipping is for colors only. Preserve the saved scores for
        # ranking: the highest/lowest 5% can all have the same clipped color.
        if len(attention) == 0:
            return empty_heatmap_response()
        attention_normalized, _ = normalize_attention(attention)

        # Build heatmap data with index for sorting
        heatmap_data = []
        for i, (coord, weight) in enumerate(zip(coords, attention_normalized)):
            heatmap_data.append(
                {
                    "index": i,
                    "x": int(coord[0]),
                    "y": int(coord[1]),
                    "weight": float(weight),
                    "raw_weight": float(attention[i]),
                }
            )

        top_patches = sorted(
            heatmap_data, key=lambda p: (-p["raw_weight"], p["index"])
        )[:10]
        bottom_patches = sorted(
            heatmap_data, key=lambda p: (p["raw_weight"], p["index"])
        )[:10]

        # Get slide dimensions
        slide = await get_slide(wsi_id, db)
        width, height = slide.level_dimensions[0]

        # Determine task type from result_meta or file prefix
        task_type = result_meta.get("task_type")
        if not task_type:
            task_type = "survival" if "risk_score" in result_meta else "train"

        return {
            "wsi_id": wsi_id,
            "task_id": selected_task_id,
            "task_type": task_type,
            "fold_key": selected_fold_key,
            "task_name": result_meta.get("task_name"),
            "patch_size": patch_size,
            "slide_width": width,
            "slide_height": height,
            "num_patches": len(heatmap_data),
            "attention_min": float(attention.min()),
            "attention_max": float(attention.max()),
            "prediction": result_meta.get("pred"),
            "probs": result_meta.get("probs"),
            "heatmap": heatmap_data,
            "top_patches": top_patches,
            "bottom_patches": bottom_patches,
            # Multi-class attention info
            "aggregator": result_meta.get("aggregator"),
            "attention_type": attention_type,
            "num_attention_classes": num_attention_classes,
            "selected_class_idx": selected_class_idx,
            "classes": classes,
            # Survival prediction fields
            "risk_score": result_meta.get("risk_score"),
            "risk_group": result_meta.get("risk_group"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap data: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to get heatmap data: {str(e)}"
        )


@router.get("/wsi/{wsi_id}/heatmap_thumbnail")
async def get_heatmap_thumbnail(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(
        None, description="Fold key for k-fold results (e.g., 'fold_0')"
    ),
    patch_size: int = Query(512, description="Patch size used during inference"),
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    class_idx: Optional[int] = Query(
        None, description="Class index for multi-class attention"
    ),
    preset: Optional[str] = Query(
        None, description="Optional rendering preset for lightweight previews"
    ),
    opacity: Optional[float] = Query(
        None, description="Optional overlay opacity for preview rendering"
    ),
    blur_scale: Optional[float] = Query(
        None, description="Optional blur scale multiplier for preview rendering"
    ),
    contrast_boost: Optional[float] = Query(
        None, description="Optional contrast boost for preview rendering"
    ),
    saturation_boost: Optional[float] = Query(
        None, description="Optional saturation boost for preview rendering"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a rendered heatmap thumbnail image for a WSI.

    This endpoint generates a thumbnail-sized heatmap overlay image by:
    1. Getting the WSI thumbnail
    2. Rendering the attention heatmap on top
    3. Returning the blended image

    Returns:
        PNG image with heatmap overlay
    """
    from PIL import Image
    import io
    import numpy as np

    _load_slide = import_module("backend.common.slide_utils").load_slide

    render_settings = _get_render_settings(
        preset, opacity, blur_scale, contrast_boost, saturation_boost
    )

    logger.info(
        f"Getting heatmap thumbnail for {wsi_id}, task_id={task_id}, size={size}"
    )

    try:
        store = _result_store()
        selected = _select_artifact_target(
            store, wsi_id, ATTENTION_ARTIFACT, task_id, fold_key
        )
        if selected is None:
            raise HTTPException(
                status_code=404, detail=f"No attention data for task {task_id}"
            )
        selected_task_id, selected_fold_key = selected

        wsi = None

        attention = store.read_array(
            selected_task_id,
            wsi_id,
            ATTENTION_ARTIFACT,
            fold_key=selected_fold_key,
            strict=True,
        )
        result_meta = store.read_result(
            selected_task_id,
            wsi_id,
            fold_key=selected_fold_key,
            strict=True,
        )

        # Load coordinates (search across all params_hash directories)
        coords_file = find_any_cached_coords_for_wsi(_uploads_dir(), wsi_id)
        if coords_file is None:
            raise HTTPException(status_code=404, detail="Coordinates not found")

        # Use safe loading to handle corrupted files
        coords, _, load_error = safe_load_h5_coords(
            coords_file, delete_if_corrupted=False
        )
        if coords is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load coordinates: {load_error}. Please rerun compute_patches.",
            )

        # Handle multi-class attention
        attention, _ = handle_multi_class_attention(attention, result_meta, class_idx)

        # Verify shapes match
        num_patches = len(coords)
        if len(attention) != num_patches:
            min_len = min(len(attention), num_patches)
            attention = attention[:min_len]
            coords = coords[:min_len]

        # Normalize attention for visualization
        attention_normalized, _ = normalize_attention(attention)

        # Get slide dimensions
        slide = await get_slide(wsi_id, db)
        slide_width, slide_height = slide.level_dimensions[0]

        # Calculate thumbnail dimensions maintaining aspect ratio
        aspect_ratio = slide_width / slide_height
        if aspect_ratio > 1:
            thumb_width = size
            thumb_height = int(size / aspect_ratio)
        else:
            thumb_height = size
            thumb_width = int(size * aspect_ratio)

        # Get WSI thumbnail
        if wsi is None:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        wsi_path = _coerce_str(wsi.wsi_path)
        if wsi_path is None:
            raise HTTPException(status_code=500, detail="WSI path missing")
        file_path = Path(wsi_path)
        file_size = _coerce_int(wsi.file_size) or file_path.stat().st_size

        if is_patch_file(str(file_path), file_size):
            # Patch file
            with Image.open(file_path) as img:
                try:
                    img.draft("RGB", (thumb_width, thumb_height))
                except Exception:
                    pass

                img.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                thumbnail = img.convert("RGB")
        else:
            # WSI file
            aslide = _load_slide(str(file_path))
            try:
                lowest_level = len(aslide.level_dimensions) - 1
                level_dims = aslide.level_dimensions[lowest_level]
                region = aslide.read_region((0, 0), lowest_level, level_dims)
                thumbnail = region.convert("RGB")
                thumbnail.thumbnail(
                    (thumb_width, thumb_height), Image.Resampling.LANCZOS
                )
            finally:
                try:
                    aslide.close()
                except Exception:
                    pass

        # Get actual thumbnail dimensions after resize (may differ from calculated)
        actual_thumb_width, actual_thumb_height = thumbnail.size

        # Create heatmap overlay using coolwarm colormap (matching WSI Viewer)
        # Coolwarm: blue (low) -> white (mid) -> red (high)
        def weight_to_rgb(w: float) -> tuple[Any, ...]:
            """Convert attention weight to RGB using coolwarm colormap"""
            w = max(0, min(1, w))
            if w < 0.5:
                # Blue to White
                t = w / 0.5
                r = int(59 + (255 - 59) * t)
                g = int(76 + (255 - 76) * t)
                b = int(192 + (255 - 192) * t)
            else:
                # White to Red
                t = (w - 0.5) / 0.5
                r = 255
                g = int(255 * (1 - t))
                b = int(255 * (1 - t * 0.8))
            return (r, g, b)

        # Scale factor from slide coordinates to actual thumbnail size
        scale_x = actual_thumb_width / slide_width
        scale_y = actual_thumb_height / slide_height
        patch_w = max(1e-6, patch_size * scale_x)
        patch_h = max(1e-6, patch_size * scale_y)

        # Create transparent RGBA overlay so empty areas do not darken the whole slide.
        heatmap_rgba = np.zeros(
            (actual_thumb_height, actual_thumb_width, 4), dtype=np.uint8
        )

        # Draw patches on heatmap as opaque color blocks; opacity is applied after blur.
        # Use floor/ceil bounds instead of int(start) + int(width) to avoid seams and
        # preserve more consistent patch coverage at tiny thumbnail scales.
        for coord, weight in zip(coords, attention_normalized):
            x = max(0, int(math.floor(coord[0] * scale_x)))
            y = max(0, int(math.floor(coord[1] * scale_y)))
            x_end = min(
                actual_thumb_width, int(math.ceil((coord[0] + patch_size) * scale_x))
            )
            y_end = min(
                actual_thumb_height, int(math.ceil((coord[1] + patch_size) * scale_y))
            )

            if x_end <= x:
                x_end = min(actual_thumb_width, x + 1)
            if y_end <= y:
                y_end = min(actual_thumb_height, y + 1)

            if x < x_end and y < y_end:
                rgb = weight_to_rgb(weight)
                heatmap_rgba[y:y_end, x:x_end, 0] = rgb[0]  # R
                heatmap_rgba[y:y_end, x:x_end, 1] = rgb[1]  # G
                heatmap_rgba[y:y_end, x:x_end, 2] = rgb[2]  # B
                heatmap_rgba[y:y_end, x:x_end, 3] = 255

        # Apply Gaussian blur to the transparent overlay, then boost visibility for
        # recommendation-card previews when requested.
        from PIL import ImageFilter

        heatmap_image = Image.fromarray(heatmap_rgba, mode="RGBA")
        blur_radius = _get_thumbnail_blur_radius(
            patch_w,
            patch_h,
            float(render_settings["blur_scale"]),
            preset,
        )
        heatmap_blurred = (
            heatmap_image
            if blur_radius <= 0
            else heatmap_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        )
        heatmap_blurred = _enhance_overlay_image(
            heatmap_blurred,
            render_settings["contrast_boost"],
            render_settings["saturation_boost"],
        )

        alpha_channel = heatmap_blurred.getchannel("A").point(
            lambda value: int(value * render_settings["opacity"])
        )
        heatmap_overlay = heatmap_blurred.copy()
        heatmap_overlay.putalpha(alpha_channel)

        blended = Image.alpha_composite(thumbnail.convert("RGBA"), heatmap_overlay)
        blended_rgb = blended.convert("RGB")

        # Convert to bytes
        buf = io.BytesIO()
        blended_rgb.save(buf, format="PNG")
        buf.seek(0)

        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers=_cache_headers(render_settings),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap thumbnail: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to get heatmap thumbnail: {str(e)}"
        )


@router.get("/wsi/{wsi_id}/patch_cam")
async def get_patch_cam(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(
        None, description="Fold key for k-fold results (e.g., 'fold_0')"
    ),
    format: str = Query(
        "image",
        description="Output format: 'image' for colored PNG, 'json' for raw data",
    ),
    size: Optional[int] = Query(
        None, description="Optional max thumbnail size for previews"
    ),
    preset: Optional[str] = Query(
        None, description="Optional rendering preset for lightweight previews"
    ),
    opacity: Optional[float] = Query(
        None, description="Optional overlay opacity for preview rendering"
    ),
    blur_scale: Optional[float] = Query(
        None, description="Optional blur scale multiplier for preview rendering"
    ),
    contrast_boost: Optional[float] = Query(
        None, description="Optional contrast boost for preview rendering"
    ),
    saturation_boost: Optional[float] = Query(
        None, description="Optional saturation boost for preview rendering"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get patch-level CAM (Class Activation Map) data for visualization overlay.

    For patch classification tasks, returns the CAM heatmap that can be overlaid
    on the patch image to show which regions contributed to the classification.

    Args:
        wsi_id: The WSI/patch ID
        task_id: Optional specific task ID
        fold_key: Optional fold key for k-fold results (e.g., 'fold_0')
        format: 'image' returns colored heatmap PNG with transparency,
                'json' returns raw CAM data

    Returns:
        PNG image (format=image) or JSON with CAM data (format=json)
    """
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import colormaps

    render_settings = _get_render_settings(
        preset, opacity, blur_scale, contrast_boost, saturation_boost
    )

    logger.info(
        f"Getting patch CAM for {wsi_id}, task_id={task_id}, fold_key={fold_key}, format={format}, size={size}"
    )

    # Helper function to return empty CAM response
    def empty_cam_response(message: str = "No CAM data available"):
        if format == "json":
            return {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "task_name": None,
                "cam": [],
                "cam_size": [0, 0],
                "prediction": None,
                "probs": None,
                "message": message,
            }
        else:
            # Return a 1x1 transparent PNG for image format
            import io
            from PIL import Image

            img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers=render_settings["cache_headers"],
            )

    try:
        store = _result_store()
        selected = _select_artifact_target(
            store, wsi_id, CAM_ARTIFACT, task_id, fold_key
        )
        if selected is None:
            logger.info(f"No CAM data found for {wsi_id}, task={task_id}")
            return empty_cam_response("No CAM data available")
        selected_task_id, selected_fold_key = selected
        cam = store.read_array(
            selected_task_id,
            wsi_id,
            CAM_ARTIFACT,
            fold_key=selected_fold_key,
            strict=True,
        )
        logger.info(
            f"Loaded CAM: shape={cam.shape}, min={cam.min():.4f}, max={cam.max():.4f}"
        )
        result_meta = store.read_result(
            selected_task_id,
            wsi_id,
            fold_key=selected_fold_key,
            strict=True,
        )

        if format == "json":
            return {
                "wsi_id": wsi_id,
                "task_id": result_meta.get("task_id"),
                "prediction": result_meta.get("pred"),
                "probs": result_meta.get("probs"),
                "classes": result_meta.get("classes"),
                "cam_size": list(cam.shape),
                "cam_min": float(cam.min()),
                "cam_max": float(cam.max()),
                "cam_data": cam.tolist(),  # 2D array
            }
        else:
            # Return colored heatmap overlaid on original patch image
            from PIL import Image, ImageFilter
            import io

            # First, get the original patch image
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise HTTPException(
                    status_code=404, detail=f"Patch not found: {wsi_id}"
                )

            file_path = Path(wsi.wsi_path)
            with Image.open(file_path) as img:
                original_image = img.convert("RGB")

            source_width, source_height = original_image.size
            target_width, target_height = source_width, source_height

            if size is not None and size > 0:
                scale = min(size / max(source_width, source_height), 1.0)
                if scale < 1.0:
                    target_width = max(1, int(round(source_width * scale)))
                    target_height = max(1, int(round(source_height * scale)))
                    original_image = original_image.resize(
                        (target_width, target_height), Image.Resampling.LANCZOS
                    )

            # Normalize CAM to 0-1 if not already
            if cam.max() > cam.min():
                cam_normalized = (cam - cam.min()) / (cam.max() - cam.min())
            else:
                cam_normalized = np.zeros_like(cam)

            # Apply colormap (jet is commonly used for heatmaps)
            colormap = colormaps["jet"]
            colored_cam = colormap(cam_normalized)  # Returns RGBA (H, W, 4)

            # Convert to uint8
            colored_cam_uint8 = (colored_cam * 255).astype(np.uint8)

            # Set alpha using the requested opacity (defaults preserve current behavior).
            colored_cam_uint8[:, :, 3] = int(round(255 * render_settings["opacity"]))

            # Create PIL image and resize to match original
            cam_image = Image.fromarray(colored_cam_uint8, mode="RGBA")
            cam_image = cam_image.resize(
                (target_width, target_height), Image.Resampling.BILINEAR
            )

            # Apply Gaussian blur for smoother appearance
            blur_radius = max(
                1, (target_width / 50) * render_settings["blur_scale"]
            )  # Adaptive blur based on image size
            cam_image = cam_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            cam_image = _enhance_overlay_image(
                cam_image,
                render_settings["contrast_boost"],
                render_settings["saturation_boost"],
            )

            # Composite CAM over original image
            original_rgba = original_image.convert("RGBA")
            blended = Image.alpha_composite(original_rgba, cam_image)
            blended_rgb = blended.convert("RGB")

            # Convert to bytes
            buf = io.BytesIO()
            blended_rgb.save(buf, format="PNG")
            buf.seek(0)

            return Response(
                content=buf.getvalue(),
                media_type="image/png",
                headers=render_settings["cache_headers"],
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch CAM: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to get patch CAM: {str(e)}"
        )


# ============================================================================
# Segmentation Mask Visualization
# ============================================================================

# Distinct colors for segmentation classes (RGBA, alpha=160 for overlay)
_SEG_COLORS = [
    (255, 0, 0, 160),  # Red
    (0, 255, 0, 160),  # Green
    (0, 0, 255, 160),  # Blue
    (255, 255, 0, 160),  # Yellow
    (255, 0, 255, 160),  # Magenta
    (0, 255, 255, 160),  # Cyan
    (255, 128, 0, 160),  # Orange
    (128, 0, 255, 160),  # Purple
    (0, 128, 255, 160),  # Sky Blue
    (255, 0, 128, 160),  # Pink
]


@router.get("/wsi/{wsi_id}/seg_mask")
async def get_seg_mask(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
    preset: Optional[str] = Query(
        None, description="Optional rendering preset for lightweight previews"
    ),
    size: Optional[int] = Query(
        None, description="Optional max thumbnail size for previews"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get patch segmentation mask overlay image.

    Loads the pred_mask.npy (shape: (num_classes, H, W), binary), assigns
    a distinct colour per class, composites over the original patch image,
    and returns a PNG.
    """
    import numpy as np
    from PIL import Image
    import io

    try:
        render_settings = _get_render_settings(preset, None, None, None, None)
        store = _result_store()
        selected = _select_artifact_target(
            store, wsi_id, PRED_MASK_ARTIFACT, task_id, fold_key
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="No segmentation mask found")
        selected_task_id, selected_fold_key = selected

        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"Patch not found: {wsi_id}")

        # Load mask: shape (num_classes, H, W), values 0/1
        mask = store.read_array(
            selected_task_id,
            wsi_id,
            PRED_MASK_ARTIFACT,
            fold_key=selected_fold_key,
            strict=True,
        )
        # Normalize persisted masks across historical dtypes (bool/float/uint8)
        # so viewer/chat overlay rendering always consumes a binary uint8 array.
        mask = (mask > 0).astype(np.uint8, copy=False)
        logger.info(f"Loaded seg mask: shape={mask.shape}")

        file_path = Path(wsi.wsi_path)
        with Image.open(file_path) as img:
            original_image = img.convert("RGB")

        source_w, source_h = original_image.size
        target_w, target_h = source_w, source_h

        if size is not None and size > 0:
            scale = min(size / max(source_w, source_h), 1.0)
            if scale < 1.0:
                target_w = max(1, int(round(source_w * scale)))
                target_h = max(1, int(round(source_h * scale)))
                original_image = original_image.resize(
                    (target_w, target_h), Image.Resampling.LANCZOS
                )

        # Build RGBA overlay
        overlay = np.zeros((target_h, target_w, 4), dtype=np.uint8)

        if mask.ndim == 3:
            num_classes = mask.shape[0]
            for c in range(num_classes):
                color = _SEG_COLORS[c % len(_SEG_COLORS)]
                # Resize class mask to original size
                class_mask = Image.fromarray((mask[c] * 255).astype(np.uint8), mode="L")
                class_mask = class_mask.resize(
                    (target_w, target_h), Image.Resampling.NEAREST
                )
                class_arr = np.array(class_mask) > 127  # binary
                for ch in range(4):
                    overlay[:, :, ch][class_arr] = color[ch]
        elif mask.ndim == 2:
            # Single-class mask
            color = _SEG_COLORS[0]
            class_mask = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
            class_mask = class_mask.resize(
                (target_w, target_h), Image.Resampling.NEAREST
            )
            class_arr = np.array(class_mask) > 127
            for ch in range(4):
                overlay[:, :, ch][class_arr] = color[ch]

        overlay_img = Image.fromarray(overlay, mode="RGBA")

        # Composite
        original_rgba = original_image.convert("RGBA")
        blended = Image.alpha_composite(original_rgba, overlay_img)
        blended_rgb = blended.convert("RGB")

        buf = io.BytesIO()
        blended_rgb.save(buf, format="PNG")
        buf.seek(0)

        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers=render_settings["cache_headers"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get seg mask: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get seg mask: {str(e)}")
