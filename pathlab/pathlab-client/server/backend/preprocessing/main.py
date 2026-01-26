from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Depends, Request
from fastapi.responses import Response, JSONResponse
from PIL import Image
import io
import os
import json
import logging
from pathlib import Path
from collections import OrderedDict
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from .tiling import (
    get_or_compute_coordinates,
    check_coords_cache_valid,
    WSITiler,
    TissueSegmenter,
    visualize_segmentation
)

# Database imports
import sys
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR))

from backend.database import get_db
from backend.database.repositories import WSIRepository
from backend.common.config import Config

# Preprocessing service: WSI processing, tissue segmentation, patch extraction
app = FastAPI(title="PathLab Preprocessing Service")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable CORS for dev and on-prem SPA - MUST be before routers
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get uploads directory
UPLOADS_DIR = Config.get_uploads_dir()
Config.ensure_directories()
COORDS_DIR = UPLOADS_DIR / "coordinates"
MASKS_DIR = UPLOADS_DIR / "masks"
COORDS_DIR.mkdir(exist_ok=True, parents=True)
MASKS_DIR.mkdir(exist_ok=True, parents=True)

# Cache configuration
SLIDE_CACHE_SIZE = int(os.environ.get("SLIDE_CACHE_SIZE", "8"))
DZG_CACHE_SIZE = int(os.environ.get("DZG_CACHE_SIZE", "16"))
slide_cache = OrderedDict()
dzg_cache = OrderedDict()

# Lazy import ASlide
_ADeepZoomGenerator = None

def _get_deepzoom_generator():
    """Lazy import ADeepZoomGenerator"""
    global _ADeepZoomGenerator
    if _ADeepZoomGenerator is None:
        from Aslide.deepzoom import ADeepZoomGenerator
        _ADeepZoomGenerator = ADeepZoomGenerator
    return _ADeepZoomGenerator

def _load_slide(file_path: str):
    """Load WSI file using Aslide"""
    try:
        from Aslide.aslide import Slide
        slide = Slide(str(file_path))
        logger.info(f"Opened WSI with Aslide: {file_path}")
        return slide
    except Exception as e:
        logger.error(f"Failed to open WSI: {e}")
        raise

async def get_wsi_path_from_db(wsi_id: str, db: AsyncSession) -> Optional[Path]:
    """Get WSI file path from database"""
    try:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi and wsi.wsi_path:
            file_path = Path(wsi.wsi_path)
            if file_path.exists():
                return file_path
            else:
                logger.warning(f"WSI path in database does not exist: {wsi.wsi_path}")
    except Exception as e:
        logger.error(f"Failed to get WSI from database: {e}")
    return None

async def get_slide(wsi_id: str, db: AsyncSession):
    """Get slide object with LRU cache"""
    if wsi_id in slide_cache:
        slide = slide_cache.pop(wsi_id)
        slide_cache[wsi_id] = slide
        return slide

    try:
        # Get file path from database
        file_path = await get_wsi_path_from_db(wsi_id, db)
        if not file_path:
            raise HTTPException(status_code=404, detail=f"WSI not found in database: {wsi_id}")

        slide = _load_slide(str(file_path))
        slide_cache[wsi_id] = slide

        # Enforce LRU cache size
        if len(slide_cache) > SLIDE_CACHE_SIZE:
            try:
                evicted_key, evicted_slide = slide_cache.popitem(last=False)
                try:
                    evicted_slide.close()
                except Exception:
                    pass
                logger.debug(f"Evicted old slide from cache: {evicted_key}")
            except Exception:
                pass
        return slide
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open slide: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open slide: {str(e)}")

async def get_deepzoom_generator(wsi_id: str, db: AsyncSession, tile_size: int = 254, overlap: int = 1):
    """Get DeepZoom generator with LRU cache"""
    cache_key = f"{wsi_id}_{tile_size}_{overlap}"
    if cache_key in dzg_cache:
        dzg = dzg_cache.pop(cache_key)
        dzg_cache[cache_key] = dzg
        return dzg

    try:
        slide = await get_slide(wsi_id, db)
        ADeepZoomGenerator = _get_deepzoom_generator()
        dzg = ADeepZoomGenerator(slide, tile_size=tile_size, overlap=overlap)
        dzg_cache[cache_key] = dzg

        # Enforce LRU cache size
        if len(dzg_cache) > DZG_CACHE_SIZE:
            try:
                evicted_key, _ = dzg_cache.popitem(last=False)
                logger.debug(f"Evicted old DZG from cache: {evicted_key}")
            except Exception:
                pass
        return dzg
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create DeepZoom generator: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create DeepZoom generator: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok", "service": "preprocessing"}


# File size threshold for determining WSI vs Patch (100 MB)
SIZE_THRESHOLD = 100 * 1024 * 1024

# WSI file extensions (excluding .tif/.tiff which need size check)
WSI_EXTENSIONS = {'.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif', '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap', '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax', '.dyj', '.dyqx', '.ibl', '.zyp'}

# Patch/image file extensions
PATCH_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp'}


def is_patch_file(file_path: str, file_size: int = 0) -> bool:
    """
    Determine if a file is a patch (simple image) or WSI.
    - .jpg, .jpeg, .png, .bmp are always patches
    - .tif/.tiff < 100MB are patches, >= 100MB are WSIs
    - Other WSI formats are always WSIs
    """
    ext = Path(file_path).suffix.lower()

    if ext in PATCH_EXTENSIONS:
        return True

    if ext in ('.tif', '.tiff'):
        return file_size < SIZE_THRESHOLD

    return False


@app.get("/wsi/{wsi_id}/info")
async def get_wsi_info(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get WSI info including whether it's a patch or WSI.
    Used by frontend to determine display mode.
    """
    try:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        file_path = wsi.wsi_path
        file_size = wsi.file_size or 0

        # If file_size not in DB, try to get it from file system
        if file_size == 0 and file_path and Path(file_path).exists():
            file_size = Path(file_path).stat().st_size

        is_patch = is_patch_file(file_path, file_size)

        return {
            "wsi_id": wsi_id,
            "is_patch": is_patch,
            "file_path": file_path,
            "file_size": file_size,
            "width": wsi.width,
            "height": wsi.height
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get WSI info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get WSI info: {str(e)}")


@app.get("/wsi/{wsi_id}/image")
async def get_patch_image(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the patch image directly for simple image files.
    Used for viewing patches without DZI/tile-based rendering.
    """
    try:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        file_path = Path(wsi.wsi_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {wsi.wsi_path}")

        file_size = wsi.file_size or file_path.stat().st_size

        # Only allow patch files
        if not is_patch_file(str(file_path), file_size):
            raise HTTPException(status_code=400, detail="This endpoint is only for patch images, use DZI for WSI files")

        # Read and return the image
        with open(file_path, "rb") as f:
            image_data = f.read()

        # Determine content type
        ext = file_path.suffix.lower()
        content_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.bmp': 'image/bmp',
            '.tif': 'image/tiff',
            '.tiff': 'image/tiff'
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')

        return Response(content=image_data, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get patch image: {str(e)}")


@app.get("/wsi/{wsi_id}/thumbnail")
async def get_thumbnail(
    wsi_id: str,
    size: int = Query(256, description="Max thumbnail size (width or height)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get thumbnail image for a WSI or patch file.
    - For patch files: returns the image resized to fit within size
    - For WSI files: uses ASlide to generate a thumbnail from the lowest pyramid level
    """
    import io
    from PIL import Image

    try:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        file_path = Path(wsi.wsi_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {wsi.wsi_path}")

        file_size = wsi.file_size or file_path.stat().st_size

        # Check if it's a patch file or WSI
        if is_patch_file(str(file_path), file_size):
            # Patch file: load directly with PIL and resize
            with Image.open(file_path) as img:
                img = img.convert('RGB')
                # Resize to fit within size while maintaining aspect ratio
                img.thumbnail((size, size), Image.Resampling.LANCZOS)

                img_bytes = io.BytesIO()
                img.save(img_bytes, format='JPEG', quality=85)
                img_bytes.seek(0)

                return Response(content=img_bytes.getvalue(), media_type='image/jpeg')
        else:
            # WSI file: use ASlide to get thumbnail
            try:
                from Aslide.aslide import Slide
                slide = Slide(str(file_path))

                # Get the thumbnail from the lowest resolution level
                # ASlide's Slide object should have get_thumbnail or similar
                if hasattr(slide, 'get_thumbnail'):
                    thumbnail = slide.get_thumbnail((size, size))
                else:
                    # Fallback: read from the highest level (lowest resolution)
                    levels = slide.level_count if hasattr(slide, 'level_count') else len(slide.level_dimensions)
                    lowest_level = levels - 1
                    level_dims = slide.level_dimensions[lowest_level]

                    # Read the entire lowest level
                    region = slide.read_region((0, 0), lowest_level, level_dims)
                    thumbnail = region.convert('RGB')

                    # Resize to fit within size
                    thumbnail.thumbnail((size, size), Image.Resampling.LANCZOS)

                img_bytes = io.BytesIO()
                thumbnail.save(img_bytes, format='JPEG', quality=85)
                img_bytes.seek(0)

                return Response(content=img_bytes.getvalue(), media_type='image/jpeg')
            except Exception as e:
                logger.error(f"Failed to generate WSI thumbnail: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to generate thumbnail: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get thumbnail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get thumbnail: {str(e)}")


@app.get("/api/wsi")
async def list_wsi(db: AsyncSession = Depends(get_db)):
    """List all WSI files from database"""
    try:
        wsi_list = await WSIRepository.get_all(db)
        items = [
            {
                "wsi_id": wsi.wsi_id,
                "label": wsi.label,
                "wsi_path": wsi.wsi_path
            }
            for wsi in wsi_list
        ]
        return {"items": items}
    except Exception as e:
        logger.error(f"Failed to list WSI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list WSI: {str(e)}")

@app.get("/wsi/{wsi_id}/dzi")
async def get_dzi(wsi_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Return DZI descriptor for OpenSeadragon"""
    logger.info(f"Requesting DZI for: {wsi_id}")

    try:
        dzg = await get_deepzoom_generator(wsi_id, db)
        dzi_xml = dzg.get_dzi("jpeg")

        # Build absolute tile URL using the actual request base URL
        base_url = str(request.base_url).rstrip("/")
        tile_root = f"{base_url}/wsi/{wsi_id}/tiles/"

        try:
            xml_str = dzi_xml.decode("utf-8") if isinstance(dzi_xml, (bytes, bytearray)) else str(dzi_xml)
        except Exception:
            xml_str = str(dzi_xml)

        # Always ensure absolute URL in DZI - replace existing Url or add new one
        import re
        if ' Url=' in xml_str:
            # Replace existing Url attribute with absolute URL
            xml_str = re.sub(r' Url="[^"]*"', f' Url="{tile_root}"', xml_str)
        elif '<Image ' in xml_str:
            # Add Url attribute if not present
            xml_str = xml_str.replace('<Image ', f'<Image Url="{tile_root}" ', 1)

        return Response(content=xml_str, media_type="application/xml")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get DZI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get DZI: {str(e)}")

@app.get("/wsi/{wsi_id}/tiles/{level}/{col}_{row}.{format}")
async def get_tile(
    wsi_id: str,
    level: int = PathParam(..., description="DeepZoom level"),
    col: int = PathParam(..., description="Tile column"),
    row: int = PathParam(..., description="Tile row"),
    format: str = PathParam(..., description="Tile format (jpeg or png)"),
    db: AsyncSession = Depends(get_db)
):
    """Return WSI tile image"""
    logger.debug(f"Requesting tile: {wsi_id}, level={level}, col={col}, row={row}, format={format}")

    try:
        dzg = await get_deepzoom_generator(wsi_id, db)

        # Validate level and coordinates
        if level < 0 or level >= dzg.level_count:
            raise HTTPException(
                status_code=404,
                detail=f"Invalid level: {level}, valid range: 0-{dzg.level_count-1}"
            )

        level_tiles = dzg.level_tiles[level]
        if col < 0 or col >= level_tiles[0] or row < 0 or row >= level_tiles[1]:
            raise HTTPException(
                status_code=404,
                detail=f"Invalid tile coordinates: ({col}, {row}), valid range: x: 0-{level_tiles[0]-1}, y: 0-{level_tiles[1]-1}"
            )

        # Get tile image
        tile = dzg.get_tile(level, (col, row))

        # Convert to bytes
        img_bytes = io.BytesIO()
        fmt_lower = format.lower()
        save_format = "JPEG" if fmt_lower in ("jpeg", "jpg") else "PNG"

        if save_format == "JPEG":
            tile.save(img_bytes, format=save_format, quality=85, optimize=True)
        else:
            tile.save(img_bytes, format=save_format, optimize=True)

        img_bytes.seek(0)

        content_type = f"image/{fmt_lower}"
        return Response(content=img_bytes.getvalue(), media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tile: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tile: {str(e)}")


@app.post("/wsi/{wsi_id}/compute_patches")
async def compute_patches(
    wsi_id: str,
    patch_size: int = Query(256, description="Patch size"),
    stride: int = Query(256, description="Stride between patches"),
    level: int = Query(0, description="Pyramid level"),
    force_recompute: bool = Query(False, description="Force recomputation"),
    # Tissue segmentation parameters
    sthresh: int = Query(5, description="Saturation threshold (0-255, low threshold for maximum tissue detection)"),
    mthresh: int = Query(7, description="Median filter kernel size"),
    close: int = Query(4, description="Morphological closing kernel size"),
    use_otsu: bool = Query(False, description="Use Otsu auto-thresholding"),
    contour_fn: str = Query('four_pt', description="Contour check function (four_pt, center, basic)"),
    use_padding: bool = Query(True, description="Allow patches at tissue boundary"),
    # Filter parameters
    a_t: int = Query(100, description="Minimum tissue area (in 512x512 patches)"),
    a_h: int = Query(16, description="Minimum hole area"),
    max_n_holes: int = Query(8, description="Maximum number of holes per contour"),
    # Visualization
    save_mask: bool = Query(True, description="Save tissue segmentation mask visualization"),
    db: AsyncSession = Depends(get_db)
):
    """
    Compute patch coordinates with tissue detection (PrePATH-style)

    Returns:
        {
            "wsi_id": str,
            "num_patches": int,
            "patch_size": int,
            "stride": int,
            "level": int,
            "coords_file": str,
            "mask_file": str (optional)
        }
    """
    logger.info(f"Computing patches for {wsi_id}")

    try:
        # Prepare segmentation parameters
        seg_params = {
            'sthresh': sthresh,
            'mthresh': mthresh,
            'close': close,
            'use_otsu': use_otsu
        }

        # Prepare filter parameters
        filter_params = {
            'a_t': a_t,
            'a_h': a_h,
            'max_n_holes': max_n_holes
        }

        # Check if valid cache exists (skip tissue segmentation if not needed)
        mask_path = MASKS_DIR / f"{wsi_id}_mask.png"
        mask_exists = mask_path.exists()

        if not force_recompute:
            cache_result = check_coords_cache_valid(
                wsi_id=wsi_id,
                coords_dir=COORDS_DIR,
                patch_size=patch_size,
                stride=stride,
                level=level,
                seg_params=seg_params,
                filter_params=filter_params,
                contour_fn=contour_fn,
                use_padding=use_padding
            )

            if cache_result is not None:
                coordinates, coords_file = cache_result
                logger.info(f"Using cached coordinates: {len(coordinates)} patches from {coords_file}")

                # Return cached result (mask already exists or not needed)
                response_data = {
                    "wsi_id": wsi_id,
                    "num_patches": len(coordinates),
                    "num_contours": -1,  # Not available from cache
                    "patch_size": patch_size,
                    "stride": stride,
                    "level": level,
                    "coords_file": str(coords_file),
                    "cached": True
                }

                if mask_exists:
                    response_data["mask_file"] = str(mask_path)

                return JSONResponse(response_data)

        # Cache miss or force_recompute - need to compute coordinates
        slide = await get_slide(wsi_id, db)

        # Perform tissue segmentation to get contours
        logger.info(f"Segmenting tissue with params: {seg_params}, filter: {filter_params}")
        segmenter = TissueSegmenter(**seg_params, filter_params=filter_params)
        tissue_contours, hole_contours = segmenter.segment_tissue(slide)
        logger.info(f"Found {len(tissue_contours)} tissue contours")

        # Compute coordinates
        coordinates = get_or_compute_coordinates(
            wsi_id=wsi_id,
            slide=slide,
            coords_dir=COORDS_DIR,
            patch_size=patch_size,
            stride=stride,
            level=level,
            force_recompute=force_recompute,
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=contour_fn,
            use_padding=use_padding
        )

        coords_file = COORDS_DIR / f"{wsi_id}_coords.h5"

        # Generate and save mask visualization
        mask_file = None
        if save_mask:
            try:
                logger.info(f"Generating tissue segmentation mask visualization")
                mask_img = visualize_segmentation(
                    slide,
                    tissue_contours,
                    hole_contours,
                    vis_level=-1,  # Auto-select ~64x downsample
                    line_thickness=3,
                    color=(0, 255, 0),  # Green for tissue
                    hole_color=(255, 0, 0)  # Red for holes
                )

                mask_path.parent.mkdir(parents=True, exist_ok=True)
                mask_img.save(mask_path, format='PNG', optimize=True)
                mask_file = str(mask_path)
                logger.info(f"Saved mask visualization to {mask_path}")
            except Exception as e:
                logger.warning(f"Failed to generate mask visualization: {e}")

        response_data = {
            "wsi_id": wsi_id,
            "num_patches": len(coordinates),
            "num_contours": len(tissue_contours),
            "patch_size": patch_size,
            "stride": stride,
            "level": level,
            "coords_file": str(coords_file),
            "cached": False
        }

        if mask_file:
            response_data["mask_file"] = mask_file

        return JSONResponse(response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compute patches: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to compute patches: {str(e)}")


@app.get("/wsi/{wsi_id}/patches")
async def get_patches(
    wsi_id: str,
    patch_size: int = Query(256, description="Patch size"),
    stride: int = Query(256, description="Stride"),
    level: int = Query(0, description="Pyramid level"),
    max_patches: Optional[int] = Query(None, description="Maximum number of patches to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get patch coordinates (compute if not cached)

    Returns:
        {
            "wsi_id": str,
            "num_patches": int,
            "coordinates": List[Tuple[int, int]]
        }
    """
    logger.info(f"Getting patches for {wsi_id}")

    try:
        slide = await get_slide(wsi_id, db)

        coordinates = get_or_compute_coordinates(
            wsi_id=wsi_id,
            slide=slide,
            coords_dir=COORDS_DIR,
            patch_size=patch_size,
            stride=stride,
            level=level
        )

        # Limit number of patches if requested
        if max_patches and len(coordinates) > max_patches:
            coordinates = coordinates[:max_patches]

        return JSONResponse({
            "wsi_id": wsi_id,
            "num_patches": len(coordinates),
            "patch_size": patch_size,
            "stride": stride,
            "level": level,
            "coordinates": coordinates
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patches: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get patches: {str(e)}")


@app.get("/wsi/{wsi_id}/mask")
def get_mask(wsi_id: str):
    """
    Get tissue segmentation mask visualization image

    Returns:
        PNG image of tissue segmentation mask
    """
    logger.info(f"Getting mask for {wsi_id}")

    try:
        mask_path = MASKS_DIR / f"{wsi_id}_mask.png"

        if not mask_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Mask not found for {wsi_id}. Run compute_patches first with save_mask=true"
            )

        # Read and return image
        with open(mask_path, 'rb') as f:
            img_bytes = f.read()

        return Response(content=img_bytes, media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get mask: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get mask: {str(e)}")


# AI Results directory
AI_RESULTS_DIR = UPLOADS_DIR / "ai_results"


@app.get("/wsi/{wsi_id}/heatmap")
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
    import h5py

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
        if task_id:
            if fold_key:
                # K-fold: look for train_{task_id}_{fold_key}_attention.npy
                matching = [f for f in attention_files if task_id in f.name and fold_key in f.name]
            else:
                # Regular or auto-select: match task_id but exclude fold files if there's a non-fold version
                matching = [f for f in attention_files if task_id in f.name]
                # If there are both fold and non-fold files, prefer non-fold (shouldn't happen but be safe)
                non_fold = [f for f in matching if "fold_" not in f.name]
                if non_fold:
                    matching = non_fold
            if not matching:
                # Return empty data when specific task not found
                logger.info(f"No attention data found for task {task_id}, fold_key={fold_key}")
                return empty_heatmap_response(f"No attention data for task {task_id}" + (f" fold {fold_key}" if fold_key else ""))
            attention_file = matching[0]
        else:
            # Use the most recent
            attention_file = sorted(attention_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]

        # Load attention weights
        attention = np.load(str(attention_file), allow_pickle=True)
        logger.info(f"Loaded attention: shape={attention.shape}, min={attention.min()}, max={attention.max()}")

        # Load corresponding result.json for metadata
        result_json_file = attention_file.with_name(
            attention_file.name.replace("_attention.npy", "_result.json")
        )
        result_meta = {}
        if result_json_file.exists():
            with open(result_json_file, 'r') as f:
                result_meta = json.load(f)

        # Load coordinates from coords.h5
        coords_file = COORDS_DIR / f"{wsi_id}_coords.h5"
        if not coords_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Coordinates not found for {wsi_id}. Run compute_patches first."
            )

        with h5py.File(str(coords_file), 'r') as f:
            coords = f['coords'][:]

        logger.info(f"Loaded coordinates: shape={coords.shape}")

        # Handle multi-class attention (e.g., CLAM_MB returns shape (num_classes, N))
        attention_type = result_meta.get("attention_type", "single")
        classes = result_meta.get("classes", [])
        num_attention_classes = None
        selected_class_idx = class_idx

        if attention.ndim == 2:
            # Multi-class attention: shape (num_classes, N)
            num_attention_classes = attention.shape[0]
            logger.info(f"Multi-class attention detected: {num_attention_classes} classes")

            # Select which class's attention to use
            if selected_class_idx is None:
                # Default to predicted class
                pred_label = result_meta.get("pred")
                if pred_label and pred_label in classes:
                    selected_class_idx = classes.index(pred_label)
                else:
                    selected_class_idx = 0  # Fallback to first class

            # Validate class_idx
            if selected_class_idx < 0 or selected_class_idx >= num_attention_classes:
                selected_class_idx = 0

            logger.info(f"Using attention for class {selected_class_idx}: {classes[selected_class_idx] if selected_class_idx < len(classes) else 'unknown'}")
            attention = attention[selected_class_idx]  # Now shape (N,)
        else:
            # Single-class attention: shape (N,)
            selected_class_idx = None

        # Verify shapes match
        num_patches = len(coords)
        if len(attention) != num_patches:
            logger.warning(f"Shape mismatch: attention={len(attention)}, coords={num_patches}")
            # Truncate to smaller size
            min_len = min(len(attention), num_patches)
            attention = attention[:min_len]
            coords = coords[:min_len]

        # Check if attention is already softmax-normalized (sums to ~1) or raw logits
        attention_sum = attention.sum()
        if abs(attention_sum - 1.0) < 0.01:
            # Already softmax normalized - use min-max with percentile clipping for visualization
            # This enhances contrast for visualization
            p_low, p_high = np.percentile(attention, [5, 95])
            attention_clipped = np.clip(attention, p_low, p_high)
            attention_normalized = (attention_clipped - p_low) / (p_high - p_low + 1e-8)
            logger.info(f"Using percentile normalization: p5={p_low:.6f}, p95={p_high:.6f}")
        else:
            # Raw logits - apply softmax first
            # Numerically stable softmax
            attention_shifted = attention - attention.max()
            exp_attention = np.exp(attention_shifted)
            attention_softmax = exp_attention / exp_attention.sum()
            # Then percentile normalization for visualization
            p_low, p_high = np.percentile(attention_softmax, [5, 95])
            attention_clipped = np.clip(attention_softmax, p_low, p_high)
            attention_normalized = (attention_clipped - p_low) / (p_high - p_low + 1e-8)
            attention = attention_softmax  # Use softmax values for raw_weight
            logger.info(f"Applied softmax, then percentile normalization: p5={p_low:.6f}, p95={p_high:.6f}")

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

        return {
            "wsi_id": wsi_id,
            "task_id": result_meta.get("task_id"),
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
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get heatmap data: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get heatmap data: {str(e)}")


@app.get("/wsi/{wsi_id}/available_heatmaps")
async def get_available_heatmaps(
    wsi_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get list of available heatmaps (attention data) for a WSI.

    Returns:
        List of available tasks with attention data
    """
    from backend.database.repositories import TrainingTaskRepository

    logger.info(f"Getting available heatmaps for {wsi_id}")

    try:
        # Find result directory
        result_dir = AI_RESULTS_DIR / wsi_id
        if not result_dir.exists():
            return {"wsi_id": wsi_id, "heatmaps": []}

        # Find all attention files (WSI-level) and CAM files (patch-level)
        attention_files = list(result_dir.glob("*_attention.npy"))
        cam_files = list(result_dir.glob("*_cam.npy"))

        if not attention_files and not cam_files:
            return {"wsi_id": wsi_id, "heatmaps": []}

        heatmaps = []

        # Process WSI-level attention files
        for attention_file in attention_files:
            # Extract task_id and fold_key from filename
            # Possible formats:
            # - train_{task_id}_attention.npy (regular training)
            # - train_{task_id}_{fold_key}_attention.npy (k-fold training, e.g., train_abc123_fold_0_attention.npy)
            filename = attention_file.stem  # e.g., "train_taskid_attention" or "train_taskid_fold_0_attention"
            base_name = filename.replace("_attention", "")  # e.g., "train_taskid" or "train_taskid_fold_0"

            # Check if this is a k-fold file (contains "fold_")
            fold_key = None
            if "_fold_" in base_name:
                # Extract fold_key: find the fold_X part
                import re
                fold_match = re.search(r'(fold_\d+)$', base_name)
                if fold_match:
                    fold_key = fold_match.group(1)
                    # Remove fold_key from base_name to get task_id
                    base_name = base_name[:fold_match.start()].rstrip("_")

            parts = base_name.split("_", 1)
            task_type = parts[0] if parts else "unknown"
            task_id = parts[1] if len(parts) > 1 else None

            # Load corresponding result.json for metadata
            result_json_file = attention_file.with_name(
                attention_file.name.replace("_attention.npy", "_result.json")
            )
            result_meta = {}
            if result_json_file.exists():
                with open(result_json_file, 'r') as f:
                    result_meta = json.load(f)

            # Get task_id and fold_key from result_meta if not from filename
            effective_task_id = task_id or result_meta.get("task_id")
            effective_fold_key = fold_key or result_meta.get("fold_key")

            # Get classes and feature_extractor: first try from result.json, then from database
            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            if effective_task_id and (not classes or not feature_extractor):
                try:
                    training_task = await TrainingTaskRepository.get_by_id(db, effective_task_id)
                    if training_task:
                        if not classes and training_task.classes:
                            classes = training_task.classes
                        if not feature_extractor and training_task.preprocessing_config:
                            feature_extractor = training_task.preprocessing_config.get("feature_extractor")
                except Exception as e:
                    logger.warning(f"Failed to fetch task info for {effective_task_id}: {e}")

            heatmaps.append({
                "task_id": effective_task_id,
                "fold_key": effective_fold_key,  # K-fold: which fold this attention comes from
                "task_type": task_type,
                "task_name": result_meta.get("task_name", task_type),
                "prediction": result_meta.get("pred"),
                "probs": result_meta.get("probs"),
                "classes": classes,
                "feature_extractor": feature_extractor,
                "aggregator": result_meta.get("aggregator"),  # MIL aggregator type
                "created_at": attention_file.stat().st_mtime,
                "attention_file": str(attention_file.name),
                "data_level": "wsi",  # WSI-level attention
            })

        # Process patch-level CAM files
        for cam_file in cam_files:
            # Extract task_id from filename (e.g., train_taskid_cam.npy)
            filename = cam_file.stem  # e.g., "train_taskid_cam"
            parts = filename.replace("_cam", "").split("_", 1)

            task_type = parts[0] if parts else "unknown"
            task_id = parts[1] if len(parts) > 1 else None

            # Load corresponding result.json for metadata
            result_json_file = cam_file.with_name(
                cam_file.name.replace("_cam.npy", "_result.json")
            )
            result_meta = {}
            if result_json_file.exists():
                with open(result_json_file, 'r') as f:
                    result_meta = json.load(f)

            # Get task_id from result_meta if not from filename
            effective_task_id = task_id or result_meta.get("task_id")

            # Get classes and feature_extractor: first try from result.json, then from database
            classes = result_meta.get("classes")
            feature_extractor = result_meta.get("feature_extractor")
            if effective_task_id and (not classes or not feature_extractor):
                try:
                    training_task = await TrainingTaskRepository.get_by_id(db, effective_task_id)
                    if training_task:
                        if not classes and training_task.classes:
                            classes = training_task.classes
                        if not feature_extractor and training_task.preprocessing_config:
                            feature_extractor = training_task.preprocessing_config.get("feature_extractor")
                except Exception as e:
                    logger.warning(f"Failed to fetch task info for {effective_task_id}: {e}")

            heatmaps.append({
                "task_id": effective_task_id,
                "task_type": task_type,
                "task_name": result_meta.get("task_name", task_type),
                "prediction": result_meta.get("pred"),
                "probs": result_meta.get("probs"),
                "classes": classes,
                "feature_extractor": feature_extractor,
                "created_at": cam_file.stat().st_mtime,
                "attention_file": str(cam_file.name),
                "data_level": "patch",  # Patch-level CAM
                "cam_size": result_meta.get("cam_size"),  # CAM spatial size
            })

        # Sort by creation time (newest first)
        heatmaps.sort(key=lambda x: x["created_at"], reverse=True)

        return {"wsi_id": wsi_id, "heatmaps": heatmaps}

    except Exception as e:
        logger.error(f"Failed to get available heatmaps: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get available heatmaps: {str(e)}")


@app.get("/wsi/{wsi_id}/patch_image")
async def get_patch_image(
    wsi_id: str,
    x: int = Query(..., description="X coordinate of patch"),
    y: int = Query(..., description="Y coordinate of patch"),
    size: int = Query(256, description="Patch size"),
    level: int = Query(0, description="Pyramid level"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a patch image at the specified coordinates.

    Returns:
        JPEG image of the patch
    """
    logger.debug(f"Getting patch image for {wsi_id} at ({x}, {y}), size={size}, level={level}")

    try:
        slide = await get_slide(wsi_id, db)

        # Read region from slide
        region = slide.read_region((x, y), level, (size, size))

        # Convert RGBA to RGB
        if region.mode == 'RGBA':
            background = Image.new('RGB', region.size, (255, 255, 255))
            background.paste(region, mask=region.split()[3])
            region = background

        # Convert to JPEG bytes
        buf = io.BytesIO()
        region.save(buf, format='JPEG', quality=90)
        buf.seek(0)

        return Response(content=buf.getvalue(), media_type="image/jpeg")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get patch image: {str(e)}")


@app.get("/wsi/{wsi_id}/patch_cam")
async def get_patch_cam(
    wsi_id: str,
    task_id: Optional[str] = Query(None, description="Specific task ID for the result"),
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
        format: 'image' returns colored heatmap PNG with transparency,
                'json' returns raw CAM data

    Returns:
        PNG image (format=image) or JSON with CAM data (format=json)
    """
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import cm

    logger.info(f"Getting patch CAM for {wsi_id}, task_id={task_id}, format={format}")

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
            # Return empty data instead of 404 when no inference results
            logger.info(f"No AI results directory for {wsi_id}")
            return empty_cam_response("No inference results available")

        # Find CAM file
        cam_files = list(result_dir.glob("*_cam.npy"))
        if not cam_files:
            # Return empty data instead of 404 when no CAM files
            logger.info(f"No CAM files found for {wsi_id}")
            return empty_cam_response("No CAM data available")

        # Select the right CAM file based on task_id
        if task_id:
            matching = [f for f in cam_files if task_id in f.name]
            if not matching:
                # Return empty data when specific task not found
                logger.info(f"No CAM data found for task {task_id}")
                return empty_cam_response(f"No CAM data for task {task_id}")
            cam_file = matching[0]
        else:
            # Use the most recent
            cam_file = sorted(cam_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]

        # Load CAM data
        cam = np.load(str(cam_file), allow_pickle=True)
        logger.info(f"Loaded CAM: shape={cam.shape}, min={cam.min():.4f}, max={cam.max():.4f}")

        # Load corresponding result.json for metadata
        result_json_file = cam_file.with_name(
            cam_file.name.replace("_cam.npy", "_result.json")
        )
        result_meta = {}
        if result_json_file.exists():
            with open(result_json_file, 'r') as f:
                result_meta = json.load(f)

        if format == "json":
            # Return raw CAM data as JSON
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
            # Return colored heatmap as PNG with transparency
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

            # Create PIL image
            cam_image = Image.fromarray(colored_cam_uint8, mode='RGBA')

            # Convert to bytes
            buf = io.BytesIO()
            cam_image.save(buf, format='PNG')
            buf.seek(0)

            return Response(content=buf.getvalue(), media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get patch CAM: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get patch CAM: {str(e)}")

