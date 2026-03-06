from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Depends, Request
from fastapi.responses import Response, JSONResponse
from PIL import Image
import io
import os
import gc
import ctypes

import logging
from pathlib import Path
from collections import OrderedDict
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

# Load libc for malloc_trim() - returns freed C-heap memory to OS.
# This is critical for long-running workers that use C libraries (SdpcSlide SDK)
# which may accumulate fragmented heap memory that gc.collect() alone won't release.
_libc = None
try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:
    pass


def _force_release_memory():
    """Force Python GC and return freed C-heap memory to OS."""
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:
            pass

from .tiling import (
    get_or_compute_coordinates,
    check_coords_cache_valid,
    WSITiler,
    TissueSegmenter,
    visualize_segmentation,
)

# Database imports
import sys
ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR))

from backend.database import get_db
from backend.database.repositories import WSIRepository
from backend.common.config import Config
from backend.common.file_types import is_patch_file

# Preprocessing service: WSI processing, tissue segmentation, patch extraction
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(_app):
    # Startup: nothing extra needed
    yield
    # Shutdown: close all cached slides to release file handles and memory
    logger.info(f"Shutting down: closing {len(slide_cache)} cached slides")
    for _wsi_id, slide in list(slide_cache.items()):
        try:
            slide.close()
        except Exception:
            pass
    slide_cache.clear()
    dzg_cache.clear()
    logger.info("All cached slides closed")

app = FastAPI(title="PathLab Preprocessing Service", lifespan=lifespan)

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

# Cache configuration - use centralized Config values
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
    """Load WSI file using Aslide (delegates to shared slide_utils)"""
    try:
        from backend.common.slide_utils import load_slide
        slide = load_slide(file_path)
        logger.info(f"Opened WSI with Aslide: {file_path}")
        return slide
    except Exception as e:
        logger.error(f"Failed to open WSI: {e}")
        raise


def _mask_visualization_worker(wsi_file_path: str, tissue_contours, hole_contours, mask_save_path: str):
    """
    Worker function for mask visualization subprocess.

    Runs in a separate process to isolate C library crashes (segfaults).
    Opens the slide independently (C handles can't cross process boundaries),
    generates the mask visualization, and saves it to disk.
    """
    try:
        from backend.common.slide_utils import load_slide
        slide = load_slide(wsi_file_path)
        mask_img = visualize_segmentation(
            slide,
            tissue_contours,
            hole_contours,
            -1,  # vis_level: Auto-select ~64x downsample
            3,   # line_thickness
            (0, 255, 0),  # color: Green for tissue
            (255, 0, 0),  # hole_color: Red for holes
        )
        mask_img.save(mask_save_path, format='PNG', optimize=True)
        del mask_img
        try:
            slide.close()
        except Exception:
            pass
    except Exception as e:
        # Log to stderr (subprocess stdout/stderr is not captured by parent logger)
        import sys
        print(f"[mask_worker] Failed to generate mask: {e}", file=sys.stderr)
        sys.exit(1)


def _run_mask_visualization_subprocess(
    wsi_file_path: str,
    tissue_contours,
    hole_contours,
    mask_save_path: str,
    timeout: int = 120,
) -> int:
    """
    Run mask visualization in a subprocess to isolate C library segfaults.

    Returns:
        Exit code: 0 = success, non-zero = failure (including segfault = -11)
    """
    import multiprocessing
    ctx = multiprocessing.get_context('fork')  # fork is fastest on Linux (COW for contour arrays)
    p = ctx.Process(
        target=_mask_visualization_worker,
        args=(wsi_file_path, tissue_contours, hole_contours, mask_save_path),
    )
    p.start()
    p.join(timeout=timeout)

    if p.is_alive():
        # Timeout: kill the subprocess
        logger.warning(f"Mask visualization subprocess timed out after {timeout}s, killing it")
        p.kill()
        p.join(timeout=5)
        return -1

    exit_code = p.exitcode
    if exit_code != 0:
        logger.warning(f"Mask visualization subprocess exited with code {exit_code}")
    return exit_code

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
        if len(slide_cache) > Config.SLIDE_CACHE_SIZE:
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
        if len(dzg_cache) > Config.DZG_CACHE_SIZE:
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


# File type classification: is_patch_file imported from backend.common.file_types


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
            slide = None
            try:
                # Use _load_slide to ensure color correction is applied
                slide = _load_slide(str(file_path))

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
            finally:
                if slide is not None:
                    try:
                        slide.close()
                    except Exception:
                        pass
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

        # Run blocking tile I/O in thread pool to avoid blocking the event loop
        fmt_lower = format.lower()

        def _generate_tile_bytes() -> bytes:
            """Blocking: read tile from disk + encode to image bytes"""
            tile = dzg.get_tile(level, (col, row))
            buf = io.BytesIO()
            save_format = "JPEG" if fmt_lower in ("jpeg", "jpg") else "PNG"
            if save_format == "JPEG":
                tile.save(buf, format=save_format, quality=85, optimize=True)
            else:
                tile.save(buf, format=save_format, optimize=True)
            return buf.getvalue()

        tile_bytes = await asyncio.to_thread(_generate_tile_bytes)

        content_type = f"image/{fmt_lower}"
        return Response(content=tile_bytes, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tile: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tile: {str(e)}")


@app.post("/wsi/{wsi_id}/compute_patches")
async def compute_patches(
    wsi_id: str,
    level: int = Query(0, description="Pyramid level"),
    force_recompute: bool = Query(False, description="Force recomputation"),
    # Tissue segmentation parameters
    seg_level: int = Query(-1, description="Pyramid level for tissue segmentation (-1 = auto)"),
    sthresh: int = Query(8, description="Saturation threshold (0-255, low threshold for maximum tissue detection)"),
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

    Note: patch_size and stride are auto-determined based on WSI magnification
    to ensure consistent physical coverage (~128μm) across different resolution WSIs.
    - 20x (mpp≈0.5): patch_size=256
    - 40x (mpp≈0.25): patch_size=512
    - 80x (mpp≈0.125): patch_size=1024

    Returns:
        {
            "wsi_id": str,
            "num_patches": int,
            "patch_size": int (auto-determined),
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

        # Load slide to get native MPP (needed for cache validation and coordinate computation)
        # Check if valid cache exists (skip tissue segmentation if not needed)
        mask_path = MASKS_DIR / f"{wsi_id}_mask.png"
        mask_exists = mask_path.exists()

        if not force_recompute:
            # Note: patch_size and stride are auto-determined by PrePATH-style tiling
            cache_result = check_coords_cache_valid(
                wsi_id=wsi_id,
                coords_dir=COORDS_DIR,
                level=level,
                seg_params=seg_params,
                filter_params=filter_params,
                contour_fn=contour_fn,
                use_padding=use_padding,
                seg_level=seg_level,
            )

            if cache_result is not None:
                coordinates, coords_file = cache_result
                logger.info(f"[Coords cache hit] {wsi_id}: {len(coordinates)} patches from {coords_file}")

                # Return cached result (mask already exists or not needed)
                response_data = {
                    "wsi_id": wsi_id,
                    "num_patches": len(coordinates),
                    "num_contours": -1,  # Not available from cache
                    "level": level,
                    "coords_file": str(coords_file),
                    "cached": True,
                }

                if mask_exists:
                    response_data["mask_file"] = str(mask_path)

                return JSONResponse(response_data)

        # Cache miss or force_recompute - need to compute coordinates
        # import time as _time
        # _t0 = _time.monotonic()
        slide = await get_slide(wsi_id, db)
        # _t1 = _time.monotonic()
        # logger.info(f"[Timing] get_slide took {_t1 - _t0:.1f}s for {wsi_id}")

        # Perform tissue segmentation to get contours
        # NOTE: segment_tissue() is CPU-intensive (OpenCV operations).
        # Run in thread pool to avoid blocking the event loop (which also serves tiles).
        logger.info(f"Segmenting tissue with params: {seg_params}, filter: {filter_params}, seg_level: {seg_level}")
        segmenter = TissueSegmenter(**seg_params, seg_level=seg_level, filter_params=filter_params)
        tissue_contours, hole_contours = await asyncio.to_thread(
            segmenter.segment_tissue, slide
        )
        del segmenter  # Release segmenter (holds references to filter params, etc.)
        _force_release_memory()  # GC + malloc_trim after heavy image processing
        # _t2 = _time.monotonic()
        # logger.info(f"[Timing] segment_tissue took {_t2 - _t1:.1f}s, found {len(tissue_contours)} tissue contours")

        # Compute coordinates with PrePATH-style tiling (patch_size auto-determined by MPP)
        # Returns (coordinates, coords_file_path) tuple
        # NOTE: get_or_compute_coordinates() is CPU-intensive (tiling computation).
        # Run in thread pool to avoid blocking the event loop.
        coordinates, coords_file = await asyncio.to_thread(
            get_or_compute_coordinates,
            wsi_id=wsi_id,
            slide=slide,
            coords_dir=COORDS_DIR,
            level=level,
            force_recompute=force_recompute,
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=contour_fn,
            use_padding=use_padding,
            seg_level=seg_level,
            tissue_contours=tissue_contours,
            hole_contours=hole_contours,
        )
        _force_release_memory()  # GC + malloc_trim after coordinate computation
        # _t3 = _time.monotonic()
        # logger.info(f"[Timing] get_or_compute_coordinates took {_t3 - _t2:.1f}s, {len(coordinates)} coords for {wsi_id}")

        # Generate and save mask visualization
        # IMPORTANT: Run in a **subprocess** to isolate C library crashes (segfaults).
        # The Aslide/SdpcSlide C SDK can segfault on certain slides (e.g., large .sdpc files),
        # which would kill the entire uvicorn worker process. By running in a subprocess,
        # a segfault only kills the child process; the worker survives and returns normally.
        mask_file = None
        if save_mask:
            try:
                logger.info(f"Generating tissue segmentation mask visualization")
                wsi_file_path = slide.filepath  # Get path before passing to subprocess
                mask_path.parent.mkdir(parents=True, exist_ok=True)

                # Run in subprocess to isolate potential C library segfaults
                exit_code = await asyncio.to_thread(
                    _run_mask_visualization_subprocess,
                    wsi_file_path,
                    tissue_contours,
                    hole_contours,
                    str(mask_path),
                    timeout=120,  # 2 min timeout for mask generation
                )

                if exit_code == 0 and mask_path.exists():
                    mask_file = str(mask_path)
                    logger.info(f"Mask visualization saved: {mask_path}")
                else:
                    logger.warning(
                        f"Mask visualization subprocess failed (exit_code={exit_code}) for {wsi_id}. "
                        f"Skipping mask - this does not affect patch coordinates."
                    )
            except Exception as e:
                logger.warning(f"Failed to generate mask visualization: {e}. Skipping mask.")

        # Prepare response before releasing resources
        num_patches = len(coordinates)
        num_contours = len(tissue_contours)

        # Release heavy objects no longer needed
        del tissue_contours, hole_contours, coordinates

        # Close and evict slide from cache to release C library resources.
        # During batch processing (e.g., training pipeline), slides are processed
        # sequentially and won't be reused immediately. Keeping them in cache
        # accumulates memory from the underlying C libraries (e.g., SdpcSlide SDK).
        if wsi_id in slide_cache:
            try:
                evicted = slide_cache.pop(wsi_id)
                evicted.close()
            except Exception:
                pass
        del slide
        _force_release_memory()  # GC + malloc_trim: return C-heap to OS after slide processing

        response_data = {
            "wsi_id": wsi_id,
            "num_patches": num_patches,
            "num_contours": num_contours,
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
    level: int = Query(0, description="Pyramid level"),
    seg_level: int = Query(-1, description="Pyramid level for tissue segmentation (-1 = auto)"),
    max_patches: Optional[int] = Query(None, description="Maximum number of patches to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get patch coordinates (compute if not cached)

    Note: patch_size and stride are auto-determined by PrePATH-style tiling
    based on WSI magnification to ensure consistent physical coverage (~128μm).

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

        # Returns (coordinates, coords_file_path) tuple
        # Note: patch_size and stride are auto-determined by PrePATH-style tiling
        # NOTE: get_or_compute_coordinates() is CPU-intensive on cache miss.
        # Run in thread pool to avoid blocking the event loop.
        coordinates, _coords_file = await asyncio.to_thread(
            get_or_compute_coordinates,
            wsi_id=wsi_id,
            slide=slide,
            coords_dir=COORDS_DIR,
            level=level,
            seg_level=seg_level,
        )

        # Limit number of patches if requested
        if max_patches and len(coordinates) > max_patches:
            coordinates = coordinates[:max_patches]

        return JSONResponse({
            "wsi_id": wsi_id,
            "num_patches": len(coordinates),
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


# --- Heatmap & CAM routes (extracted to heatmap_routes.py) ---
from .heatmap_routes import router as heatmap_router
app.include_router(heatmap_router)


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



# --- Annotation Region Extraction ---
from pydantic import BaseModel, Field
from typing import Any


class RegionSpec(BaseModel):
    """Specification for a single annotation region."""
    type: str = Field(..., description="Region type: 'rect' or 'polygon'")
    x: int = Field(..., description="Bounding box x (level-0 pixel)")
    y: int = Field(..., description="Bounding box y (level-0 pixel)")
    width: int = Field(..., description="Bounding box width (level-0 pixel)")
    height: int = Field(..., description="Bounding box height (level-0 pixel)")
    label: str = Field(..., description="Region label")
    # Polygon-only: original polygon points stored as metadata
    points: Optional[List[List[int]]] = Field(None, description="Polygon vertices [[x,y], ...]")


class ExtractRegionsRequest(BaseModel):
    """Request body for region extraction."""
    regions: Dict[str, List[RegionSpec]] = Field(
        ..., description="Map of wsi_id -> list of region specs"
    )
    dataset_name: str = Field(..., description="Name for the new dataset")
    task_type: str = Field(..., description="Task type (classification, segmentation, etc.)")
    user_id: str = Field(..., description="User ID who initiated the extraction")
    task_id: str = Field(..., description="Task ID for progress tracking")
    source_dataset_id: Optional[str] = Field(None, description="For segmentation: reuse existing dataset instead of creating a new one")


@app.post("/annotation/extract_regions")
async def extract_regions(req: ExtractRegionsRequest, db: AsyncSession = Depends(get_db)):
    """
    Extract annotation regions from WSI/patch images and create a new dataset.

    This endpoint is called by the Gateway after auth/access checks are done.
    Runs extraction in a background task and tracks progress via Redis.
    Returns immediately with the task_id.
    """
    # Validate all WSIs exist before starting
    for wsi_id in req.regions:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

    # Start background extraction
    asyncio.create_task(
        _extract_regions_background(
            regions=req.regions,
            dataset_name=req.dataset_name,
            task_type=req.task_type,
            user_id=req.user_id,
            task_id=req.task_id,
            source_dataset_id=req.source_dataset_id,
        )
    )

    return {"task_id": req.task_id, "status": "started"}


async def _extract_regions_background(
    regions: Dict[str, List[RegionSpec]],
    dataset_name: str,
    task_type: str,
    user_id: str,
    task_id: str,
    source_dataset_id: Optional[str] = None,
):
    """
    Background task: extract ROI regions from WSI/patch files and create a new dataset.

    Steps:
    1. Create DataGroup + Dataset for the new annotated patches
       (or reuse existing dataset for segmentation if source_dataset_id provided)
    2. For each WSI and its regions:
       a. Open the slide (WSI) or image (patch)
       b. Read the bounding-box region
       c. Save as JPEG to uploads/wsi_files/
       d. Create WSISlide record with parent_wsi_id
    3. Update progress via Redis
    """
    import uuid
    from backend.database import async_session_maker
    from backend.database.repositories import (
        DataGroupRepository,
        DatasetRepository,
        WSIRepository,
    )
    from backend.common.progress_store import set_progress, clear_progress

    total_regions = sum(len(r) for r in regions.values())
    completed = 0

    try:
        await set_progress(task_id, 0)

        async with async_session_maker() as db:
            # Segmentation + source_dataset_id: reuse existing dataset, only generate COCO JSON
            if task_type == "segmentation" and source_dataset_id:
                logger.info(
                    f"Segmentation reuse mode: adding COCO JSON to existing dataset {source_dataset_id}"
                )
                completed = await _extract_segmentation_dataset(
                    db=db,
                    regions=regions,
                    dataset_id=source_dataset_id,
                    user_id=user_id,
                    task_id=task_id,
                    total_regions=total_regions,
                    reuse_existing=True,
                )
                await db.commit()
            else:
                # Create new DataGroup + Dataset
                data_group = await DataGroupRepository.get_or_create(
                    db,
                    data_type="patch",
                    aggregation_level="file",
                    task_type=task_type,
                )

                dataset = await DatasetRepository.get_or_create(
                    db,
                    name=dataset_name,
                    group_id=data_group.group_id,
                    user_id=user_id,
                )
                dataset_id = dataset.dataset_id
                await db.commit()

                # 2. Extract regions — segmentation vs classification have different flows
                if task_type == "segmentation":
                    # Segmentation on patches: copy original images + generate COCO JSON
                    completed = await _extract_segmentation_dataset(
                        db=db,
                        regions=regions,
                        dataset_id=dataset_id,
                        user_id=user_id,
                        task_id=task_id,
                        total_regions=total_regions,
                        reuse_existing=False,
                    )
                else:
                    # Classification/other: crop each annotation region as a new image
                    for source_wsi_id, region_list in regions.items():
                        # Load source WSI info
                        source_wsi = await WSIRepository.get_by_id(db, source_wsi_id)
                        if not source_wsi:
                            logger.warning(f"Source WSI not found during extraction: {source_wsi_id}")
                            completed += len(region_list)
                            continue

                        source_path = Path(source_wsi.wsi_path)
                        source_is_patch = is_patch_file(str(source_path), source_wsi.file_size or 0)

                        for region in region_list:
                            try:
                                await _extract_single_region(
                                    db=db,
                                    source_wsi_id=source_wsi_id,
                                    source_path=source_path,
                                    source_is_patch=source_is_patch,
                                    region=region,
                                    dataset_id=dataset_id,
                                    user_id=user_id,
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to extract region from {source_wsi_id}: {e}",
                                    exc_info=True,
                                )

                            completed += 1
                            progress = int(completed / total_regions * 100)
                            await set_progress(task_id, progress)

                await db.commit()

        logger.info(f"Annotation extraction completed: task_id={task_id}, {completed}/{total_regions} regions")
        await set_progress(task_id, 100)

    except Exception as e:
        logger.error(f"Annotation extraction failed: task_id={task_id}, error={e}", exc_info=True)
        await set_progress(task_id, -1)  # -1 signals error

    finally:
        # Don't clear progress immediately — let SSE client read the final state
        await asyncio.sleep(5)
        await clear_progress(task_id)


async def _extract_single_region(
    db: AsyncSession,
    source_wsi_id: str,
    source_path: Path,
    source_is_patch: bool,
    region: RegionSpec,
    dataset_id: str,
    user_id: str,
):
    """
    Extract a single annotation region from a WSI or patch image.

    For WSI files: uses ASlide read_region at level 0.
    For patch files: uses PIL Image.crop.

    Saves the cropped image as JPEG and creates a WSI database record.
    """
    import uuid
    from backend.database.repositories import WSIRepository

    new_wsi_id = str(uuid.uuid4())

    # Ensure output directory exists
    output_dir = UPLOADS_DIR / "wsi_files"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{new_wsi_id}.jpg"

    # Extract region image
    if source_is_patch:
        # Patch file: crop with PIL
        cropped = await asyncio.to_thread(
            _crop_patch_image, source_path, region.x, region.y, region.width, region.height
        )
    else:
        # WSI file: read_region via ASlide
        slide = await get_slide(source_wsi_id, db)
        cropped = await asyncio.to_thread(
            _read_wsi_region, slide, region.x, region.y, region.width, region.height
        )

    # Save as JPEG
    await asyncio.to_thread(_save_image_jpeg, cropped, output_path)

    file_size = output_path.stat().st_size

    # Create WSI record for the extracted patch
    wsi_data = {
        "wsi_id": new_wsi_id,
        "original_filename": f"{source_wsi_id}_roi_{region.label}.jpg",
        "dataset_id": dataset_id,
        "label": region.label,
        "wsi_path": str(output_path),
        "file_size": file_size,
        "width": region.width,
        "height": region.height,
        "user_id": user_id,
        "parent_wsi_id": source_wsi_id,
    }
    await WSIRepository.create(db, wsi_data)

    logger.info(f"Extracted region: {new_wsi_id} from {source_wsi_id} ({region.label})")


def _crop_patch_image(file_path: Path, x: int, y: int, w: int, h: int) -> Image.Image:
    """Crop a region from a patch image file (runs in thread)."""
    with Image.open(file_path) as img:
        img = img.convert("RGB")
        cropped = img.crop((x, y, x + w, y + h))
        return cropped.copy()  # Copy to detach from source file


def _read_wsi_region(slide, x: int, y: int, w: int, h: int) -> Image.Image:
    """Read a region from a WSI slide at level 0 (runs in thread)."""
    region = slide.read_region((x, y), 0, (w, h))
    # Convert RGBA to RGB (ASlide returns RGBA)
    if region.mode == "RGBA":
        background = Image.new("RGB", region.size, (255, 255, 255))
        background.paste(region, mask=region.split()[3])
        return background
    return region.convert("RGB")


def _save_image_jpeg(img: Image.Image, output_path: Path):
    """Save a PIL Image as JPEG (runs in thread)."""
    img.save(output_path, format="JPEG", quality=90)



async def _extract_segmentation_dataset(
    db,
    regions: Dict[str, List["RegionSpec"]],
    dataset_id: str,
    user_id: str,
    task_id: str,
    total_regions: int,
    reuse_existing: bool = False,
) -> int:
    """
    Segmentation-specific dataset creation from viewer annotations on patch images.

    When reuse_existing=False (new dataset):
    1. Copies each source patch image once to the dataset directory
    2. Aggregates all annotations into a single COCO JSON file
    3. Creates one WSISlide record per source patch (not per annotation)

    When reuse_existing=True (source_dataset_id provided):
    1. Uses existing images in the dataset (no copy, no new WSISlide records)
    2. Only generates/updates the COCO JSON with annotations

    The COCO JSON is saved to uploads/annotations/<dataset_id>_coco.json
    and follows the format expected by SegmentationDataset.

    Returns:
        Number of annotation regions processed (for progress tracking).
    """
    import uuid
    import json
    import shutil
    from backend.database.repositories import WSIRepository
    from backend.common.progress_store import set_progress

    output_dir = UPLOADS_DIR / "wsi_files"
    output_dir.mkdir(parents=True, exist_ok=True)
    annotations_dir = UPLOADS_DIR / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)

    # COCO JSON structure
    coco_images = []
    coco_annotations = []
    label_to_category_id: Dict[str, int] = {}
    image_id_counter = 0
    annotation_id_counter = 0
    completed = 0

    for source_wsi_id, region_list in regions.items():
        # Load source WSI info
        source_wsi = await WSIRepository.get_by_id(db, source_wsi_id)
        if not source_wsi:
            logger.warning(f"Source WSI not found during extraction: {source_wsi_id}")
            completed += len(region_list)
            continue

        source_path = Path(source_wsi.wsi_path)
        source_is_patch = is_patch_file(str(source_path), source_wsi.file_size or 0)

        if not source_is_patch:
            # WSI segmentation dataset creation is not supported (frontend blocks this)
            logger.warning(f"Skipping WSI source for segmentation: {source_wsi_id}")
            completed += len(region_list)
            continue

        if reuse_existing:
            # Reuse mode: no file copy, no new DB record.
            # Use the existing file path for COCO JSON file_name reference.
            file_name = Path(source_wsi.wsi_path).name
            img_width = source_wsi.width
            img_height = source_wsi.height
            if not img_width or not img_height:
                with Image.open(source_path) as img:
                    img_width, img_height = img.size
        else:
            # New dataset mode: copy source patch image once (keep original format)
            new_wsi_id = str(uuid.uuid4())
            ext = source_path.suffix or ".jpg"
            output_path = output_dir / f"{new_wsi_id}{ext}"
            await asyncio.to_thread(shutil.copy2, str(source_path), str(output_path))

            file_size = output_path.stat().st_size
            file_name = f"{new_wsi_id}{ext}"

            # Get source image dimensions
            img_width = source_wsi.width
            img_height = source_wsi.height
            if not img_width or not img_height:
                with Image.open(output_path) as img:
                    img_width, img_height = img.size

        # Add COCO image entry
        image_id_counter += 1
        coco_images.append({
            "id": image_id_counter,
            "width": img_width,
            "height": img_height,
            "file_name": file_name,
        })

        # Convert each annotation region to COCO annotation
        for region in region_list:
            # Map label to category ID
            if region.label not in label_to_category_id:
                label_to_category_id[region.label] = len(label_to_category_id)
            cat_id = label_to_category_id[region.label]

            annotation_id_counter += 1

            # Build segmentation polygon
            if region.type == "polygon" and region.points:
                # Polygon: flatten [[x,y], [x,y], ...] → [x,y,x,y,...]
                flat_points = []
                for pt in region.points:
                    flat_points.extend(pt)
                segmentation = [flat_points]
            else:
                # Rectangle: convert bbox to 4-corner polygon
                x, y, w, h = region.x, region.y, region.width, region.height
                segmentation = [[x, y, x + w, y, x + w, y + h, x, y + h]]

            # Compute area
            area = region.width * region.height

            coco_annotations.append({
                "id": annotation_id_counter,
                "image_id": image_id_counter,
                "category_id": cat_id,
                "segmentation": segmentation,
                "bbox": [region.x, region.y, region.width, region.height],
                "area": area,
                "iscrowd": 0,
            })

            completed += 1
            progress = int(completed / total_regions * 100)
            await set_progress(task_id, progress)

        if not reuse_existing:
            # Create WSI record for the copied patch (one per source, not per annotation)
            wsi_data = {
                "wsi_id": new_wsi_id,
                "original_filename": source_wsi.original_filename or source_path.name,
                "dataset_id": dataset_id,
                "label": None,  # Segmentation labels are in COCO JSON, not per-slide
                "wsi_path": str(output_path),
                "file_size": file_size,
                "width": img_width,
                "height": img_height,
                "user_id": user_id,
                "parent_wsi_id": source_wsi_id,
            }
            await WSIRepository.create(db, wsi_data)

    # Build categories dict (matches the format used by SegmentationDataset)
    categories = {str(cat_id): label for label, cat_id in label_to_category_id.items()}

    # Assemble full COCO JSON
    coco_json = {
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": categories,
    }

    # Save COCO JSON to disk (cache for training)
    coco_path = annotations_dir / f"{dataset_id}_coco.json"
    await asyncio.to_thread(_save_coco_json, coco_json, coco_path)

    # Also save to DB as source of truth
    try:
        from backend.common.annotation_summary_cache import rebuild_dataset_annotation_summary_cache
        from backend.database.repositories import SegmentationAnnotationRepository
        await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id=f"annot_{dataset_id}",
            user_id=user_id,
            annotations=coco_json,
            source_dataset_id=dataset_id,
            status="finalized",
            source="extraction",
        )
        await db.commit()
        await rebuild_dataset_annotation_summary_cache(db, dataset_id)
    except Exception as e:
        logger.warning(f"Failed to save COCO annotation to DB for dataset {dataset_id}: {e}")

    logger.info(
        f"Segmentation dataset created: dataset_id={dataset_id}, "
        f"{len(coco_images)} images, {len(coco_annotations)} annotations, "
        f"{len(categories)} categories, COCO JSON: {coco_path}"
    )

    return completed


def _save_coco_json(coco_data: dict, output_path: Path):
    """Save COCO JSON to file (runs in thread)."""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(coco_data, f, indent=2, ensure_ascii=False)