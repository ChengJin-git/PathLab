from collections import OrderedDict

import pytest


@pytest.mark.asyncio
async def test_get_slide_uses_cache_and_evict_slide(monkeypatch):
    from backend.preprocessing import slide_access

    class _FakeSlide:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake_slide = _FakeSlide()
    slide_access.slide_cache = OrderedDict()

    async def _fake_get_wsi_path(_wsi_id, _db):
        return None

    monkeypatch.setattr(slide_access, "get_wsi_path_from_db", _fake_get_wsi_path)
    monkeypatch.setattr(slide_access, "_load_slide", lambda _path: fake_slide)

    async def _resolve_slide_path(_wsi_id, _db):
        return "/tmp/test.svs"

    monkeypatch.setattr(slide_access, "_resolve_slide_path", _resolve_slide_path)

    slide_1 = await slide_access.get_slide("wsi-1", object())
    slide_2 = await slide_access.get_slide("wsi-1", object())

    assert slide_1 is fake_slide
    assert slide_2 is fake_slide

    slide_access.evict_slide("wsi-1")

    assert fake_slide.closed is True
    assert "wsi-1" not in slide_access.slide_cache
