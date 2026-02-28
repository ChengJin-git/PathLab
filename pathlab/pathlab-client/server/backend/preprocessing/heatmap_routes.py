"""
Heatmap and CAM visualization endpoints for the Preprocessing Service.

Extracted from main.py to reduce file size. Handles:
- WSI attention heatmap data (JSON)
- WSI attention heatmap thumbnail (rendered image)
- Available heatmaps listing
- Patch-level CAM visualization
"""
import json
import logging
import re
import struct
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import WSIRepository
from backend.common.config import Config
from backend.common.file_types import is_patch_file
from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi
from .tiling import safe_load_h5_coords
from .heatmap_utils import (
    load_result_meta,
    select_attention_file,
    handle_multi_class_attention,
    normalize_attention,
    find_best_fold,
)

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOADS_DIR = Config.get_uploads_dir()
AI_RESULTS_DIR = UPLOADS_DIR / "ai_results"


def _get_npy_shape_fast(filepath: Path) -> Optional[tuple]:
    """
    Read numpy array shape from file header without loading the entire array.
    This is much faster than np.load() for large arrays.
    """
    try:
        with open(filepath, 'rb') as f:
            # Read magic string and version
            magic = f.read(6)
            if magic[:6] != b'\x93NUMPY':
                return None

            # Re-read properly
            f.seek(0)
            f.read(6)  # Skip magic
            version_major = struct.unpack('B', f.read(1))[0]
            f.read(1)  # Skip version_minor

            # Read header length
            if version_major == 1:
                header_len = struct.unpack('<H', f.read(2))[0]
            else:  # version 2 or 3
                header_len = struct.unpack('<I', f.read(4))[0]

            # Read and parse header
            header = f.read(header_len).decode('latin1')
            # Parse the dict-like string to extract shape using regex
            # Format: {'descr': '<f4', 'fortran_order': False, 'shape': (10, 20), }
            shape_match = re.search(r"'shape':\s*\((\d+),\s*(\d+)\)", header)
            if shape_match:
                return (int(shape_match.group(1)), int(shape_match.group(2)))
            return None
    except Exception:
        return None


@router.get("/wsi/{wsi_id}/heatmap")
async def get_heatmap_data(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    class_idx: Optional[int] = Query(None, description="Class index for multi-class attention (e.g., CLAM_MB)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get attention heatmap data for visualization overlay.

    For multi-class attention models (e.g., CLAM_MB), use class_idx to select which class's attention to visualize.
    If class_idx is not provided for multi-class attention, defaults to the predicted class.

    Returns:
        JSON with coordinates, attention weights, and metadata for rendering heatmap
    """
    import numpy as np
    from .main import get_slide

    logger.info(f"Getting heatmap data for {wsi_id}, task_id={task_id}, fold_key={fold_key}")

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
            "message": message
        }

    try:
        # Find result directory
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            # Return empty data instead of 404 when no inference results
            logger.info(f"No AI results directory for {wsi_id}")
            return empty_heatmap_response("No inference results available")

        # Find attention file (with or without task_id and fold_key)
        attention_files = list(result_dir.glob("*_attention.npy"))
        if not attention_files:
            # Return empty data instead of 404 when no attention files
            logger.info(f"No attention files found for {wsi_id}")
            return empty_heatmap_response("No attention data available")

        # Select the right attention file based on task_id and fold_key
        attention_file = select_attention_file(attention_files, task_id, fold_key, UPLOADS_DIR)
        if attention_file is None:
            logger.info(f"No attention data found for task {task_id}, fold_key={fold_key}")
            return empty_heatmap_response(f"No attention data for task {task_id}" + (f" fold {fold_key}" if fold_key else ""))

        # Load attention weights
        attention = np.load(str(attention_file), allow_pickle=True)
        logger.info(f"Loaded attention: shape={attention.shape}, min={attention.min()}, max={attention.max()}")

        # Load corresponding result.json for metadata
        result_meta = load_result_meta(attention_file, "_attention.npy")

        # Load coordinates from coords.h5 (search across all params_hash directories)
        coords_file = find_any_cached_coords_for_wsi(UPLOADS_DIR, wsi_id)
        if coords_file is None:
            raise HTTPException(
                status_code=404,
                detail=f"Coordinates not found for {wsi_id}. Run compute_patches first."
            )

        # Use safe loading to handle corrupted files
        coords, _, load_error = safe_load_h5_coords(coords_file, delete_if_corrupted=False)
        if coords is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load coordinates for {wsi_id}: {load_error}. Please rerun compute_patches."
            )

        logger.info(f"Loaded coordinates: shape={coords.shape}")

        # Handle multi-class attention (e.g., CLAM_MB returns shape (num_classes, N))
        attention_type = result_meta.get("attention_type", "single")
        classes = result_meta.get("classes", [])
        num_attention_classes = attention.shape[0] if attention.ndim == 2 else None
        attention, selected_class_idx = handle_multi_class_attention(attention, result_meta, class_idx)

        # Verify shapes match
        num_patches = len(coords)
        if len(attention) != num_patches:
            logger.warning(f"Shape mismatch: attention={len(attention)}, coords={num_patches}")
            # Truncate to smaller size
            min_len = min(len(attention), num_patches)
            attention = attention[:min_len]
            coords = coords[:min_len]

        # Normalize attention for visualization
        attention_normalized, attention = normalize_attention(attention)

        # Build heatmap data with index for sorting
        heatmap_data = []
        for i, (coord, weight) in enumerate(zip(coords, attention_normalized)):
            heatmap_data.append({
                "index": i,
                "x": int(coord[0]),
                "y": int(coord[1]),
                "weight": float(weight),
                "raw_weight": float(attention[i])
            })

        # Sort by weight to get top and bottom patches
        sorted_by_weight = sorted(heatmap_data, key=lambda p: p["weight"], reverse=True)
        top_patches = sorted_by_weight[:10]  # Top 10 highest attention
        bottom_patches = sorted_by_weight[-10:][::-1]  # Bottom 10 lowest attention (reversed for ascending order)

        # Get slide dimensions
        slide = await get_slide(wsi_id, db)
        width, height = slide.level_dimensions[0]

        # Determine task type from result_meta or file prefix
        task_type = result_meta.get("task_type")
        if not task_type:
            # Infer from file name (train_xxx for classification, survival_xxx for survival)
            if attention_file.stem.startswith("train_"):
                # Check if this is a survival task by looking for risk_score
                task_type = "survival" if "risk_score" in result_meta else "train"
            else:
                task_type = "unknown"

        return {
            "wsi_id": wsi_id,
            "task_id": result_meta.get("task_id"),
            "task_type": task_type,
            "fold_key": result_meta.get("fold_key"),  # K-fold: which fold this attention comes from
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
        raise HTTPException(status_code=500, detail=f"Failed to get heatmap data: {str(e)}")


@router.get("/wsi/{wsi_id}/heatmap_thumbnail")
async def get_heatmap_thumbnail(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    patch_size: int = Query(512, description="Patch size used during inference"),
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    class_idx: Optional[int] = Query(None, description="Class index for multi-class attention"),
    db: AsyncSession = Depends(get_db)
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
    import numpy as np
    from PIL import Image
    import io
    from .main import get_slide
    from backend.common.slide_utils import load_slide as _load_slide

    logger.info(f"Getting heatmap thumbnail for {wsi_id}, task_id={task_id}, size={size}")

    try:
        # Find result directory
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            raise HTTPException(status_code=404, detail="No inference results available")

        # Find attention file
        attention_files = list(result_dir.glob("*_attention.npy"))
        if not attention_files:
            raise HTTPException(status_code=404, detail="No attention data available")

        # Select the right attention file
        attention_file = select_attention_file(attention_files, task_id, fold_key, UPLOADS_DIR)
        if attention_file is None:
            raise HTTPException(status_code=404, detail=f"No attention data for task {task_id}")

        # Load attention weights
        attention = np.load(str(attention_file), allow_pickle=True)

        # Load result metadata
        result_meta = load_result_meta(attention_file, "_attention.npy")

        # Load coordinates (search across all params_hash directories)
        coords_file = find_any_cached_coords_for_wsi(UPLOADS_DIR, wsi_id)
        if coords_file is None:
            raise HTTPException(status_code=404, detail="Coordinates not found")

        # Use safe loading to handle corrupted files
        coords, _, load_error = safe_load_h5_coords(coords_file, delete_if_corrupted=False)
        if coords is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load coordinates: {load_error}. Please rerun compute_patches."
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
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        file_path = Path(wsi.wsi_path)
        file_size = wsi.file_size or file_path.stat().st_size

        if is_patch_file(str(file_path), file_size):
            # Patch file
            with Image.open(file_path) as img:
                thumbnail = img.convert('RGB')
                thumbnail.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        else:
            # WSI file
            aslide = _load_slide(str(file_path))
            try:
                lowest_level = len(aslide.level_dimensions) - 1
                level_dims = aslide.level_dimensions[lowest_level]
                region = aslide.read_region((0, 0), lowest_level, level_dims)
                thumbnail = region.convert('RGB')
                thumbnail.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
            finally:
                try:
                    aslide.close()
                except Exception:
                    pass

        # Get actual thumbnail dimensions after resize (may differ from calculated)
        actual_thumb_width, actual_thumb_height = thumbnail.size

        # Create heatmap overlay using coolwarm colormap (matching WSI Viewer)
        # Coolwarm: blue (low) -> white (mid) -> red (high)
        def weight_to_rgb(w: float) -> tuple:
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
        patch_w = max(1, int(patch_size * scale_x))
        patch_h = max(1, int(patch_size * scale_y))

        # Create RGB heatmap image (no alpha - matching WSI Viewer approach)
        heatmap_rgb = np.zeros((actual_thumb_height, actual_thumb_width, 3), dtype=np.uint8)

        # Draw patches on heatmap with coolwarm colors (opaque, no alpha)
        for coord, weight in zip(coords, attention_normalized):
            x = int(coord[0] * scale_x)
            y = int(coord[1] * scale_y)
            # Clamp to bounds
            x_end = min(x + patch_w, actual_thumb_width)
            y_end = min(y + patch_h, actual_thumb_height)
            x = max(0, x)
            y = max(0, y)
            if x < x_end and y < y_end:
                rgb = weight_to_rgb(weight)
                heatmap_rgb[y:y_end, x:x_end, 0] = rgb[0]  # R
                heatmap_rgb[y:y_end, x:x_end, 1] = rgb[1]  # G
                heatmap_rgb[y:y_end, x:x_end, 2] = rgb[2]  # B

        # Apply Gaussian blur to RGB image only (matching WSI Viewer)
        from PIL import ImageFilter
        heatmap_image = Image.fromarray(heatmap_rgb, mode='RGB')
        blur_radius = max(2, patch_w / 2)
        heatmap_blurred = heatmap_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # Blend heatmap with thumbnail using 50% opacity
        heatmap_opacity = 0.5
        blended_rgb = Image.blend(thumbnail, heatmap_blurred, alpha=heatmap_opacity)

        # Convert to bytes
        buf = io.BytesIO()
        blended_rgb.save(buf, format='PNG')
        buf.seek(0)

        return Response(content=buf.getvalue(), media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap thumbnail: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get heatmap thumbnail: {str(e)}")


@router.get("/wsi/{wsi_id}/available_heatmaps")
async def get_available_heatmaps(
    wsi_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available heatmaps (attention data) for a WSI.

    Returns:
        List of available tasks with attention data
    """
    import re
    from backend.database.repositories import TrainingTaskRepository

    logger.info(f"Getting available heatmaps for {wsi_id}")

    try:
        # Find result directory
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            return {"wsi_id": wsi_id, "heatmaps": []}

        # Find all attention files (WSI-level), CAM files (patch-level), and segmentation masks
        attention_files = list(result_dir.glob("*_attention.npy"))
        cam_files = list(result_dir.glob("*_cam.npy"))
        seg_mask_files = list(result_dir.glob("*_pred_mask.npy"))

        if not attention_files and not cam_files and not seg_mask_files:
            return {"wsi_id": wsi_id, "heatmaps": []}

        # Phase 1: Parse all files and collect task_ids that need DB lookup
        attention_data_list = []  # List of (file, task_type, task_id, fold_key, result_meta)
        cam_data_list = []  # List of (file, task_type, task_id, result_meta)
        seg_mask_data_list = []  # List of (file, task_type, task_id, fold_key, result_meta)
        task_ids_needing_db = set()

        # Process WSI-level attention files (parse only, no DB calls yet)
        for attention_file in attention_files:
            filename = attention_file.stem
            base_name = filename.replace("_attention", "")

            fold_key = None
            if "_fold_" in base_name:
                fold_match = re.search(r'(fold_\d+)$', base_name)
                if fold_match:
                    fold_key = fold_match.group(1)
                    base_name = base_name[:fold_match.start()].rstrip("_")

            parts = base_name.split("_", 1)
            task_type = parts[0] if parts else "unknown"
            task_id = parts[1] if len(parts) > 1 else None

            # Load result.json for metadata
            result_meta = load_result_meta(attention_file, "_attention.npy")

            effective_task_id = task_id or result_meta.get("task_id")
            effective_fold_key = fold_key or result_meta.get("fold_key")

            # Check if we need DB lookup for this task
            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            if effective_task_id and (not classes or not feature_extractor):
                task_ids_needing_db.add(effective_task_id)

            attention_data_list.append((
                attention_file, task_type, effective_task_id, effective_fold_key, result_meta
            ))

        # Process patch-level CAM files (parse only, no DB calls yet)
        for cam_file in cam_files:
            filename = cam_file.stem
            base_name = filename.replace("_cam", "")

            fold_key = None
            if "_fold_" in base_name:
                fold_match = re.search(r'(fold_\d+)$', base_name)
                if fold_match:
                    fold_key = fold_match.group(1)
                    base_name = base_name[:fold_match.start()].rstrip("_")

            parts = base_name.split("_", 1)
            task_type = parts[0] if parts else "unknown"
            task_id = parts[1] if len(parts) > 1 else None

            result_meta = load_result_meta(cam_file, "_cam.npy")

            effective_task_id = task_id or result_meta.get("task_id")
            effective_fold_key = fold_key or result_meta.get("fold_key")

            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            if effective_task_id and (not classes or not feature_extractor):
                task_ids_needing_db.add(effective_task_id)

            cam_data_list.append((cam_file, task_type, effective_task_id, effective_fold_key, result_meta))

        # Process patch-level segmentation mask files (parse only, no DB calls yet)
        for mask_file in seg_mask_files:
            filename = mask_file.stem
            base_name = filename.replace("_pred_mask", "")

            fold_key = None
            if "_fold_" in base_name:
                fold_match = re.search(r'(fold_\d+)$', base_name)
                if fold_match:
                    fold_key = fold_match.group(1)
                    base_name = base_name[:fold_match.start()].rstrip("_")

            parts = base_name.split("_", 1)
            task_type = parts[0] if parts else "unknown"
            task_id = parts[1] if len(parts) > 1 else None

            result_meta = load_result_meta(mask_file, "_pred_mask.npy")

            effective_task_id = task_id or result_meta.get("task_id")
            effective_fold_key = fold_key or result_meta.get("fold_key")

            if effective_task_id:
                task_ids_needing_db.add(effective_task_id)

            seg_mask_data_list.append((mask_file, task_type, effective_task_id, effective_fold_key, result_meta))

        # Phase 2: Batch fetch all needed training tasks from DB (single query)
        training_tasks_map: Dict[str, any] = {}
        if task_ids_needing_db:
            try:
                training_tasks_map = await TrainingTaskRepository.get_by_ids(db, list(task_ids_needing_db))
            except Exception as e:
                logger.warning(f"Failed to batch fetch training tasks: {e}")

        # Phase 3: Build heatmap entries with all data
        heatmaps = []

        for attention_file, task_type, effective_task_id, effective_fold_key, result_meta in attention_data_list:
            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            task_name = result_meta.get("task_name")
            aggregator = result_meta.get("aggregator")

            # Fill in missing data from DB if available
            if effective_task_id and effective_task_id in training_tasks_map:
                training_task = training_tasks_map[effective_task_id]
                if not classes and training_task.classes:
                    classes = training_task.classes
                if not feature_extractor and training_task.preprocessing_config:
                    feature_extractor = training_task.preprocessing_config.get("feature_extractor")
                if not task_name and training_task.task_name:
                    task_name = training_task.task_name
                if not aggregator and training_task.model_config:
                    aggregator = training_task.model_config.get("aggregator")

            # Detect multi-class attention using fast header read (no full array load)
            attention_type = result_meta.get("attention_type", "single")
            num_attention_classes = result_meta.get("num_attention_classes")

            # Only read from file if not in result_meta
            if "attention_type" not in result_meta:
                shape = _get_npy_shape_fast(attention_file)
                if shape and len(shape) == 2:
                    attention_type = "multi_class"
                    num_attention_classes = shape[0]

            # Determine if this is a survival task by checking for risk_score
            is_survival = "risk_score" in result_meta
            actual_task_type = "survival" if is_survival else task_type

            heatmaps.append({
                "task_id": effective_task_id,
                "fold_key": effective_fold_key,
                "task_type": actual_task_type,
                "task_name": task_name or actual_task_type,
                "prediction": result_meta.get("pred"),
                "probs": result_meta.get("probs"),
                "classes": classes,
                "feature_extractor": feature_extractor,
                "aggregator": aggregator,
                "created_at": attention_file.stat().st_mtime,
                "attention_file": str(attention_file.name),
                "data_type": "wsi",
                "attention_type": attention_type,
                "num_attention_classes": num_attention_classes,
                # Survival prediction fields
                "risk_score": result_meta.get("risk_score"),
                "risk_group": result_meta.get("risk_group"),
            })

        for cam_file, task_type, effective_task_id, effective_fold_key, result_meta in cam_data_list:
            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            task_name = result_meta.get("task_name")

            if effective_task_id and effective_task_id in training_tasks_map:
                training_task = training_tasks_map[effective_task_id]
                if not classes and training_task.classes:
                    classes = training_task.classes
                if not feature_extractor and training_task.preprocessing_config:
                    feature_extractor = training_task.preprocessing_config.get("feature_extractor")
                if not task_name and training_task.task_name:
                    task_name = training_task.task_name

            heatmaps.append({
                "task_id": effective_task_id,
                "task_type": task_type,
                "task_name": task_name or task_type,
                "fold_key": effective_fold_key,
                "prediction": result_meta.get("pred"),
                "probs": result_meta.get("probs"),
                "classes": classes,
                "feature_extractor": feature_extractor,
                "created_at": cam_file.stat().st_mtime,
                "attention_file": str(cam_file.name),
                "data_type": "patch",
                "cam_size": result_meta.get("cam_size"),
            })

        # Build heatmap entries for segmentation masks
        for mask_file, task_type, effective_task_id, effective_fold_key, result_meta in seg_mask_data_list:
            task_name = result_meta.get("task_name")

            if effective_task_id and effective_task_id in training_tasks_map:
                training_task = training_tasks_map[effective_task_id]
                if not task_name and training_task.task_name:
                    task_name = training_task.task_name

            num_classes = result_meta.get("num_classes", 1)
            class_names = result_meta.get("class_names", [])

            heatmaps.append({
                "task_id": effective_task_id,
                "task_type": "segmentation",
                "task_name": task_name or "segmentation",
                "fold_key": effective_fold_key,
                "prediction": "segmentation",
                "probs": result_meta.get("metrics"),
                "classes": class_names or None,
                "feature_extractor": None,
                "created_at": mask_file.stat().st_mtime,
                "attention_file": str(mask_file.name),
                "data_type": "patch_segmentation",
                "num_classes": num_classes,
                "image_size": result_meta.get("image_size"),
            })

        # Get best_fold info and validation performance for each model from metrics.json
        model_metrics: Dict[str, Dict] = {}
        task_best_folds: Dict[str, str] = {}

        possible_prefixes = [
            "patch_cls",  # Patch classification
            "patch_seg",  # Patch segmentation
            "abmil", "meanmil", "maxmil", "dsmil", "dtfdmil",  # WSI aggregators
            "clam_sb", "clam_mb", "transmil",
        ]

        # Collect all unique task_ids
        task_ids = set(h.get("task_id") for h in heatmaps if h.get("task_id"))

        for tid in task_ids:
            for model_prefix in possible_prefixes:
                model_id = f"{model_prefix}_{tid}"
                metrics_file = UPLOADS_DIR / "models" / model_id / "metrics.json"
                if metrics_file.exists():
                    try:
                        with open(metrics_file, 'r') as f:
                            metrics_data = json.load(f)
                            best_fold = metrics_data.get("best_fold")

                            # Get validation accuracy
                            val_accuracy = None
                            if metrics_data.get("is_kfold") and metrics_data.get("aggregated"):
                                val_accuracy = metrics_data["aggregated"].get("accuracy", {}).get("mean")
                            elif metrics_data.get("accuracy") is not None:
                                val_accuracy = metrics_data.get("accuracy")
                            elif metrics_data.get("val_accuracy") is not None:
                                val_accuracy = metrics_data.get("val_accuracy")

                            # Determine aggregator from model_prefix (None for patch_cls)
                            aggregator = model_prefix if model_prefix != "patch_cls" else None

                            # Get K-Fold info
                            is_kfold = metrics_data.get("is_kfold", False)
                            num_folds = metrics_data.get("num_folds")

                            model_metrics[(tid, aggregator)] = {
                                "best_fold": best_fold,
                                "val_accuracy": val_accuracy or 0.0,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds,
                            }

                            if best_fold and tid not in task_best_folds:
                                task_best_folds[tid] = best_fold
                    except Exception as e:
                        logger.warning(f"Failed to read metrics.json for {model_id}: {e}")

        # Mark is_best_fold and val_accuracy for each heatmap
        for heatmap in heatmaps:
            h_task_id = heatmap.get("task_id")
            h_fold_key = heatmap.get("fold_key")
            h_aggregator = heatmap.get("aggregator")

            # Get model metrics
            model_key = (h_task_id, h_aggregator)
            metrics = model_metrics.get(model_key, {})

            # Set val_accuracy for sorting
            heatmap["val_accuracy"] = metrics.get("val_accuracy", 0.0)

            # Set K-Fold info
            heatmap["is_kfold"] = metrics.get("is_kfold", False)
            heatmap["num_folds"] = metrics.get("num_folds")

            # Set is_best_fold
            if h_fold_key and h_task_id in task_best_folds:
                heatmap["is_best_fold"] = (h_fold_key == task_best_folds[h_task_id])
            else:
                heatmap["is_best_fold"] = None  # Not a k-fold task or no fold info

        # Sort by: val_accuracy desc, is_best_fold priority, creation time desc
        def heatmap_sort_key(h):
            val_acc = h.get("val_accuracy", 0.0)
            is_best = h.get("is_best_fold")
            best_priority = 0 if is_best is True else (1 if is_best is None else 2)
            return (-val_acc, best_priority, -h["created_at"])

        heatmaps.sort(key=heatmap_sort_key)

        return {"wsi_id": wsi_id, "heatmaps": heatmaps}

    except Exception as e:
        logger.error(f"Failed to get available heatmaps: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get available heatmaps: {str(e)}")


@router.get("/wsi/{wsi_id}/patch_cam")
async def get_patch_cam(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results (e.g., 'fold_0')"),
    format: str = Query("image", description="Output format: 'image' for colored PNG, 'json' for raw data"),
    db: AsyncSession = Depends(get_db)
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
    matplotlib.use('Agg')
    from matplotlib import cm

    logger.info(f"Getting patch CAM for {wsi_id}, task_id={task_id}, fold_key={fold_key}, format={format}")

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
                "message": message
            }
        else:
            # Return a 1x1 transparent PNG for image format
            import io
            from PIL import Image
            img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return Response(content=buf.getvalue(), media_type="image/png")

    try:
        # Find result directory
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            logger.info(f"No AI results directory for {wsi_id}")
            return empty_cam_response("No inference results available")

        # Find CAM file
        cam_files = list(result_dir.glob("*_cam.npy"))
        if not cam_files:
            logger.info(f"No CAM files found for {wsi_id}")
            return empty_cam_response("No CAM data available")

        # Select the right CAM file based on task_id and fold_key
        if task_id:
            matching = [f for f in cam_files if task_id in f.name]
            if not matching:
                logger.info(f"No CAM data found for task {task_id}")
                return empty_cam_response(f"No CAM data for task {task_id}")

            # Handle K-Fold selection
            if fold_key:
                # Explicit fold_key specified - use it
                fold_matching = [f for f in matching if fold_key in f.name]
                if fold_matching:
                    matching = fold_matching
                    logger.info(f"Using specified fold {fold_key} for patch CAM task {task_id}")
                else:
                    logger.warning(f"Fold {fold_key} not found for task {task_id}, using fallback")
            else:
                # No fold_key specified - prefer non-fold files, or use best_fold
                non_fold = [f for f in matching if "fold_" not in f.name]
                if non_fold:
                    matching = non_fold
                elif matching:
                    # All files are k-fold - try to find best fold from metrics.json
                    best_fold = find_best_fold(task_id, UPLOADS_DIR)
                    if best_fold:
                        best_matching = [f for f in matching if best_fold in f.name]
                        if best_matching:
                            matching = best_matching
                            logger.info(f"Using best fold {best_fold} for patch CAM task {task_id}")

            cam_file = matching[0]
        else:
            cam_file = sorted(cam_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]

        # Load CAM data
        cam = np.load(str(cam_file), allow_pickle=True)
        logger.info(f"Loaded CAM: shape={cam.shape}, min={cam.min():.4f}, max={cam.max():.4f}")

        # Load corresponding result.json for metadata
        result_meta = load_result_meta(cam_file, "_cam.npy")

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
                "cam_data": cam.tolist()  # 2D array
            }
        else:
            # Return colored heatmap overlaid on original patch image
            from PIL import Image, ImageFilter
            import io

            # First, get the original patch image
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise HTTPException(status_code=404, detail=f"Patch not found: {wsi_id}")

            file_path = Path(wsi.wsi_path)
            with Image.open(file_path) as img:
                original_image = img.convert('RGB')

            orig_width, orig_height = original_image.size

            # Normalize CAM to 0-1 if not already
            if cam.max() > cam.min():
                cam_normalized = (cam - cam.min()) / (cam.max() - cam.min())
            else:
                cam_normalized = np.zeros_like(cam)

            # Apply colormap (jet is commonly used for heatmaps)
            colormap = cm.get_cmap('jet')
            colored_cam = colormap(cam_normalized)  # Returns RGBA (H, W, 4)

            # Convert to uint8
            colored_cam_uint8 = (colored_cam * 255).astype(np.uint8)

            # Set alpha to 50% for overlay
            colored_cam_uint8[:, :, 3] = 128

            # Create PIL image and resize to match original
            cam_image = Image.fromarray(colored_cam_uint8, mode='RGBA')
            cam_image = cam_image.resize((orig_width, orig_height), Image.Resampling.BILINEAR)

            # Apply Gaussian blur for smoother appearance
            blur_radius = max(2, orig_width / 50)  # Adaptive blur based on image size
            cam_image = cam_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))

            # Composite CAM over original image
            original_rgba = original_image.convert('RGBA')
            blended = Image.alpha_composite(original_rgba, cam_image)
            blended_rgb = blended.convert('RGB')

            # Convert to bytes
            buf = io.BytesIO()
            blended_rgb.save(buf, format='PNG')
            buf.seek(0)

            return Response(content=buf.getvalue(), media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch CAM: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get patch CAM: {str(e)}")



# ============================================================================
# Segmentation Mask Visualization
# ============================================================================

# Distinct colors for segmentation classes (RGBA, alpha=160 for overlay)
_SEG_COLORS = [
    (255, 0, 0, 160),     # Red
    (0, 255, 0, 160),     # Green
    (0, 0, 255, 160),     # Blue
    (255, 255, 0, 160),   # Yellow
    (255, 0, 255, 160),   # Magenta
    (0, 255, 255, 160),   # Cyan
    (255, 128, 0, 160),   # Orange
    (128, 0, 255, 160),   # Purple
    (0, 128, 255, 160),   # Sky Blue
    (255, 0, 128, 160),   # Pink
]


@router.get("/wsi/{wsi_id}/seg_mask")
async def get_seg_mask(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID"),
    fold_key: Optional[str] = Query(None, description="Fold key for k-fold results"),
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
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            raise HTTPException(status_code=404, detail="No results for this WSI")

        mask_files = list(result_dir.glob("*_pred_mask.npy"))
        if not mask_files:
            raise HTTPException(status_code=404, detail="No segmentation mask found")

        # Select the right mask file
        if task_id:
            matching = [f for f in mask_files if task_id in f.name]
            if not matching:
                raise HTTPException(status_code=404, detail=f"No mask for task {task_id}")

            if fold_key:
                fold_matching = [f for f in matching if fold_key in f.name]
                if fold_matching:
                    matching = fold_matching
            else:
                non_fold = [f for f in matching if "fold_" not in f.name]
                if non_fold:
                    matching = non_fold
                elif matching:
                    best_fold = find_best_fold(task_id, UPLOADS_DIR)
                    if best_fold:
                        best_matching = [f for f in matching if best_fold in f.name]
                        if best_matching:
                            matching = best_matching

            mask_file = matching[0]
        else:
            mask_file = sorted(mask_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]

        # Load mask: shape (num_classes, H, W), values 0/1
        mask = np.load(str(mask_file), allow_pickle=True)
        logger.info(f"Loaded seg mask: shape={mask.shape}")

        # Load original image
        from backend.database.repositories import WSIRepository
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"Patch not found: {wsi_id}")

        file_path = Path(wsi.wsi_path)
        with Image.open(file_path) as img:
            original_image = img.convert('RGB')

        orig_w, orig_h = original_image.size

        # Build RGBA overlay
        overlay = np.zeros((orig_h, orig_w, 4), dtype=np.uint8)

        if mask.ndim == 3:
            num_classes = mask.shape[0]
            for c in range(num_classes):
                color = _SEG_COLORS[c % len(_SEG_COLORS)]
                # Resize class mask to original size
                class_mask = Image.fromarray((mask[c] * 255).astype(np.uint8), mode='L')
                class_mask = class_mask.resize((orig_w, orig_h), Image.Resampling.NEAREST)
                class_arr = np.array(class_mask) > 127  # binary
                for ch in range(4):
                    overlay[:, :, ch][class_arr] = color[ch]
        elif mask.ndim == 2:
            # Single-class mask
            color = _SEG_COLORS[0]
            class_mask = Image.fromarray((mask * 255).astype(np.uint8), mode='L')
            class_mask = class_mask.resize((orig_w, orig_h), Image.Resampling.NEAREST)
            class_arr = np.array(class_mask) > 127
            for ch in range(4):
                overlay[:, :, ch][class_arr] = color[ch]

        overlay_img = Image.fromarray(overlay, mode='RGBA')

        # Composite
        original_rgba = original_image.convert('RGBA')
        blended = Image.alpha_composite(original_rgba, overlay_img)
        blended_rgb = blended.convert('RGB')

        buf = io.BytesIO()
        blended_rgb.save(buf, format='PNG')
        buf.seek(0)

        return Response(content=buf.getvalue(), media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get seg mask: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get seg mask: {str(e)}")
