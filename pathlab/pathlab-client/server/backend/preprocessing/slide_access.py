from __future__ import annotations

import logging
from collections import OrderedDict
from importlib import import_module
from pathlib import Path
from typing import Any, Optional, cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

Config = import_module("backend.common.config").Config
WSIRepository = import_module("backend.database.repositories").WSIRepository

logger = logging.getLogger(__name__)

slide_cache: OrderedDict[str, Any] = OrderedDict()
dzg_cache: OrderedDict[str, Any] = OrderedDict()

_ADeepZoomGenerator = None


def _get_deepzoom_generator():
    global _ADeepZoomGenerator
    if _ADeepZoomGenerator is None:
        from Aslide.deepzoom import ADeepZoomGenerator

        _ADeepZoomGenerator = ADeepZoomGenerator
    return _ADeepZoomGenerator


def _load_slide(file_path: str):
    load_slide = import_module("backend.common.slide_utils").load_slide

    slide = load_slide(file_path)
    logger.info(f"Opened WSI with Aslide: {file_path}")
    return slide


async def get_wsi_path_from_db(wsi_id: str, db: AsyncSession) -> Optional[Path]:
    try:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        wsi_path = cast(str | None, getattr(wsi, "wsi_path", None)) if wsi else None
        if wsi and wsi_path:
            file_path = Path(wsi_path)
            if file_path.exists():
                return file_path
            logger.warning(f"WSI path in database does not exist: {wsi_path}")
    except Exception as e:
        logger.error(f"Failed to get WSI from database: {e}")
    return None


async def _resolve_slide_path(wsi_id: str, db: AsyncSession) -> str:
    file_path = await get_wsi_path_from_db(wsi_id, db)
    if not file_path:
        raise HTTPException(
            status_code=404, detail=f"WSI not found in database: {wsi_id}"
        )
    return str(file_path)


async def get_slide(wsi_id: str, db: AsyncSession):
    if wsi_id in slide_cache:
        slide = slide_cache.pop(wsi_id)
        slide_cache[wsi_id] = slide
        return slide

    try:
        slide = _load_slide(await _resolve_slide_path(wsi_id, db))
        slide_cache[wsi_id] = slide

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


def evict_slide(wsi_id: str) -> None:
    if wsi_id in slide_cache:
        try:
            evicted = slide_cache.pop(wsi_id)
            evicted.close()
        except Exception:
            pass


async def get_deepzoom_generator(
    wsi_id: str, db: AsyncSession, tile_size: int = 254, overlap: int = 1
):
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
        raise HTTPException(
            status_code=500, detail=f"Failed to create DeepZoom generator: {str(e)}"
        )


def clear_caches() -> None:
    logger.info(f"Shutting down: closing {len(slide_cache)} cached slides")
    for _wsi_id, slide in list(slide_cache.items()):
        try:
            slide.close()
        except Exception:
            pass
    slide_cache.clear()
    dzg_cache.clear()
    logger.info("All cached slides closed")
