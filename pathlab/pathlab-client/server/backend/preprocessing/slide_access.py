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

_ADeepZoomGenerator = None


class SlideCacheManager:
    def __init__(self, slide_cache_size: int, dzg_cache_size: int):
        self.slide_cache_size = slide_cache_size
        self.dzg_cache_size = dzg_cache_size
        self.slide_cache: OrderedDict[str, Any] = OrderedDict()
        self.dzg_cache: OrderedDict[str, Any] = OrderedDict()

    def get_slide(self, wsi_id: str) -> Any | None:
        if wsi_id not in self.slide_cache:
            return None
        slide = self.slide_cache.pop(wsi_id)
        self.slide_cache[wsi_id] = slide
        return slide

    def put_slide(self, wsi_id: str, slide: Any) -> None:
        self.slide_cache[wsi_id] = slide
        if len(self.slide_cache) <= self.slide_cache_size:
            return
        evicted_key, evicted_slide = self.slide_cache.popitem(last=False)
        self._close_slide(evicted_slide)
        logger.debug(f"Evicted old slide from cache: {evicted_key}")

    def evict_slide(self, wsi_id: str) -> None:
        if wsi_id not in self.slide_cache:
            return
        evicted = self.slide_cache.pop(wsi_id)
        self._close_slide(evicted)

    def get_dzg(self, cache_key: str) -> Any | None:
        if cache_key not in self.dzg_cache:
            return None
        dzg = self.dzg_cache.pop(cache_key)
        self.dzg_cache[cache_key] = dzg
        return dzg

    def put_dzg(self, cache_key: str, dzg: Any) -> None:
        self.dzg_cache[cache_key] = dzg
        if len(self.dzg_cache) <= self.dzg_cache_size:
            return
        evicted_key, _ = self.dzg_cache.popitem(last=False)
        logger.debug(f"Evicted old DZG from cache: {evicted_key}")

    def clear(self) -> None:
        logger.info(
            "Shutting down: closing %s cached slides and clearing %s DZG entries",
            len(self.slide_cache),
            len(self.dzg_cache),
        )
        for _wsi_id, slide in list(self.slide_cache.items()):
            self._close_slide(slide)
        self.slide_cache.clear()
        self.dzg_cache.clear()
        logger.info("All cached slides closed")

    @staticmethod
    def _close_slide(slide: Any) -> None:
        try:
            slide.close()
        except Exception as exc:
            logger.warning("Failed to close cached slide: %s", exc)


_cache_manager = SlideCacheManager(Config.SLIDE_CACHE_SIZE, Config.DZG_CACHE_SIZE)


def set_cache_manager(manager: SlideCacheManager) -> None:
    global _cache_manager
    _cache_manager = manager


def get_cache_manager() -> SlideCacheManager:
    return _cache_manager


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
    manager = get_cache_manager()
    slide = manager.get_slide(wsi_id)
    if slide is not None:
        return slide

    try:
        slide = _load_slide(await _resolve_slide_path(wsi_id, db))
        manager.put_slide(wsi_id, slide)
        return slide
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open slide: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open slide: {str(e)}")


def evict_slide(wsi_id: str) -> None:
    get_cache_manager().evict_slide(wsi_id)


async def get_deepzoom_generator(
    wsi_id: str, db: AsyncSession, tile_size: int = 254, overlap: int = 1
):
    cache_key = f"{wsi_id}_{tile_size}_{overlap}"
    manager = get_cache_manager()
    dzg = manager.get_dzg(cache_key)
    if dzg is not None:
        return dzg

    try:
        slide = await get_slide(wsi_id, db)
        ADeepZoomGenerator = _get_deepzoom_generator()
        dzg = ADeepZoomGenerator(slide, tile_size=tile_size, overlap=overlap)
        manager.put_dzg(cache_key, dzg)
        return dzg
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create DeepZoom generator: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create DeepZoom generator: {str(e)}"
        )


def clear_caches() -> None:
    get_cache_manager().clear()
