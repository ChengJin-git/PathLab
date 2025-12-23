from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Depends
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

from .tiling import get_or_compute_coordinates, WSITiler, TissueSegmenter, visualize_segmentation

# Database imports
import sys
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR))

from backend.database import get_db
from backend.database.repositories import WSIRepository

# Preprocessing service: WSI processing, tissue segmentation, patch extraction
app = FastAPI(title="PathStudio Preprocessing Service")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable CORS for dev and on-prem SPA
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

# Get uploads directory
ROOT = Path(__file__).resolve().parents[3]
UPLOADS_DIR = ROOT / "uploads"
COORDS_DIR = UPLOADS_DIR / "coordinates"
MASKS_DIR = UPLOADS_DIR / "masks"
UPLOADS_DIR.mkdir(exist_ok=True, parents=True)
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
async def get_dzi(wsi_id: str, db: AsyncSession = Depends(get_db)):
    """Return DZI descriptor for OpenSeadragon"""
    logger.info(f"Requesting DZI for: {wsi_id}")

    try:
        dzg = await get_deepzoom_generator(wsi_id, db)
        dzi_xml = dzg.get_dzi("jpeg")

        # Add tile URL to DZI
        tile_root = f"/wsi/{wsi_id}/tiles/"
        try:
            xml_str = dzi_xml.decode("utf-8") if isinstance(dzi_xml, (bytes, bytearray)) else str(dzi_xml)
        except Exception:
            xml_str = str(dzi_xml)

        if ' Url=' not in xml_str and '<Image ' in xml_str:
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
        slide = await get_slide(wsi_id, db)

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

        # First, perform tissue segmentation to get contours
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

        coords_file = COORDS_DIR / f"{wsi_id}_coords.json"

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

                mask_path = MASKS_DIR / f"{wsi_id}_mask.png"
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
            "coords_file": str(coords_file)
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

