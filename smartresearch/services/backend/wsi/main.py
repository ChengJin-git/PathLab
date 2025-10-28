from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from fastapi.responses import Response, JSONResponse
from PIL import Image
import io
import os
import json
import logging
from pathlib import Path
from collections import OrderedDict
from typing import List, Optional

from .tiling import get_or_compute_coordinates, WSITiler

# WSI service with ASlide support
app = FastAPI(title="SmartResearch WSI Service")

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
METADATA_DIR = UPLOADS_DIR / "metadata"
COORDS_DIR = UPLOADS_DIR / "coordinates"
UPLOADS_DIR.mkdir(exist_ok=True, parents=True)
METADATA_DIR.mkdir(exist_ok=True, parents=True)
COORDS_DIR.mkdir(exist_ok=True, parents=True)

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

def get_wsi_path(wsi_id: str) -> Path:
    """Get WSI file path from wsi_id"""
    # First check metadata
    metadata_path = METADATA_DIR / f"{wsi_id}.json"
    if metadata_path.exists():
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                # Try to get wsi_path from metadata
                wsi_path = metadata.get('wsi_path')
                if wsi_path:
                    file_path = Path(wsi_path)
                    if file_path.exists():
                        return file_path
        except Exception as e:
            logger.error(f"Failed to read metadata: {e}")

    # Try to find file in uploads directory
    for fp in UPLOADS_DIR.glob(f"{wsi_id}.*"):
        if fp.is_file():
            return fp

    # Try common extensions
    extensions = ['.svs', '.tif', '.tiff', '.ndpi', '.kfb', '.mrxs']
    for ext in extensions:
        file_path = UPLOADS_DIR / f"{wsi_id}{ext}"
        if file_path.exists():
            return file_path

    raise HTTPException(status_code=404, detail=f"WSI file not found: {wsi_id}")

def get_slide(wsi_id: str):
    """Get slide object with LRU cache"""
    if wsi_id in slide_cache:
        slide = slide_cache.pop(wsi_id)
        slide_cache[wsi_id] = slide
        return slide

    try:
        file_path = get_wsi_path(wsi_id)
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
    except Exception as e:
        logger.error(f"Failed to open slide: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open slide: {str(e)}")

def get_deepzoom_generator(wsi_id: str, tile_size: int = 254, overlap: int = 1):
    """Get DeepZoom generator with LRU cache"""
    cache_key = f"{wsi_id}_{tile_size}_{overlap}"
    if cache_key in dzg_cache:
        dzg = dzg_cache.pop(cache_key)
        dzg_cache[cache_key] = dzg
        return dzg

    try:
        slide = get_slide(wsi_id)
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
    except Exception as e:
        logger.error(f"Failed to create DeepZoom generator: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create DeepZoom generator: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok", "service": "wsi"}

@app.get("/api/wsi")
def list_wsi():
    """List all WSI files from metadata"""
    items = []
    try:
        for metadata_file in METADATA_DIR.glob("*.json"):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    wsi_id = metadata_file.stem
                    items.append({
                        "wsi_id": wsi_id,
                        "label": metadata.get("label"),
                        "wsi_path": metadata.get("wsi_path")
                    })
            except Exception as e:
                logger.error(f"Failed to read metadata {metadata_file}: {e}")
                continue
    except Exception as e:
        logger.error(f"Failed to list WSI: {e}")
    return {"items": items}

@app.get("/wsi/{wsi_id}/dzi")
def get_dzi(wsi_id: str):
    """Return DZI descriptor for OpenSeadragon"""
    logger.info(f"Requesting DZI for: {wsi_id}")

    try:
        dzg = get_deepzoom_generator(wsi_id)
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
def get_tile(
    wsi_id: str,
    level: int = PathParam(..., description="DeepZoom level"),
    col: int = PathParam(..., description="Tile column"),
    row: int = PathParam(..., description="Tile row"),
    format: str = PathParam(..., description="Tile format (jpeg or png)")
):
    """Return WSI tile image"""
    logger.debug(f"Requesting tile: {wsi_id}, level={level}, col={col}, row={row}, format={format}")

    try:
        dzg = get_deepzoom_generator(wsi_id)

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
def compute_patches(
    wsi_id: str,
    patch_size: int = Query(256, description="Patch size"),
    stride: int = Query(256, description="Stride between patches"),
    level: int = Query(0, description="Pyramid level"),
    force_recompute: bool = Query(False, description="Force recomputation")
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
            "coords_file": str
        }
    """
    logger.info(f"Computing patches for {wsi_id}")

    try:
        slide = get_slide(wsi_id)

        coordinates = get_or_compute_coordinates(
            wsi_id=wsi_id,
            slide=slide,
            coords_dir=COORDS_DIR,
            patch_size=patch_size,
            stride=stride,
            level=level,
            force_recompute=force_recompute
        )

        coords_file = COORDS_DIR / f"{wsi_id}_coords.json"

        return JSONResponse({
            "wsi_id": wsi_id,
            "num_patches": len(coordinates),
            "patch_size": patch_size,
            "stride": stride,
            "level": level,
            "coords_file": str(coords_file)
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compute patches: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to compute patches: {str(e)}")


@app.get("/wsi/{wsi_id}/patches")
def get_patches(
    wsi_id: str,
    patch_size: int = Query(256, description="Patch size"),
    stride: int = Query(256, description="Stride"),
    level: int = Query(0, description="Pyramid level"),
    max_patches: Optional[int] = Query(None, description="Maximum number of patches to return")
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
        slide = get_slide(wsi_id)

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

