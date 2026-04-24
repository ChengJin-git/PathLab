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
    manager = slide_access.SlideCacheManager(slide_cache_size=1, dzg_cache_size=1)
    slide_access.set_cache_manager(manager)

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
    assert "wsi-1" not in manager.slide_cache


@pytest.mark.asyncio
async def test_slide_cache_manager_closes_lru_slide_on_capacity(monkeypatch):
    from backend.preprocessing import slide_access

    class _FakeSlide:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def close(self):
            self.closed = True

    first_slide = _FakeSlide("first")
    second_slide = _FakeSlide("second")
    manager = slide_access.SlideCacheManager(slide_cache_size=1, dzg_cache_size=1)
    slide_access.set_cache_manager(manager)

    slides_by_path = {
        "/tmp/first.svs": first_slide,
        "/tmp/second.svs": second_slide,
    }

    async def _resolve_slide_path(wsi_id, _db):
        return f"/tmp/{wsi_id}.svs"

    monkeypatch.setattr(slide_access, "_resolve_slide_path", _resolve_slide_path)
    monkeypatch.setattr(slide_access, "_load_slide", lambda path: slides_by_path[path])

    assert await slide_access.get_slide("first", object()) is first_slide
    assert await slide_access.get_slide("second", object()) is second_slide

    assert first_slide.closed is True
    assert second_slide.closed is False
    assert list(manager.slide_cache) == ["second"]
