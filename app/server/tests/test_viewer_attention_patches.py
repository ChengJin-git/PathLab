"""Attention rankings must use stored scores, never the contrast-clipped color."""

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from PIL import Image

from backend.ai.result_store import AIResultStore
from backend.preprocessing import heatmap_routes, main as preprocessing
from gateway.routes import heatmap as gateway


@pytest.mark.parametrize("probabilities", [False, True])
async def test_top_bottom_ten_keep_unclipped_order_for_each_fold(
    tmp_path, monkeypatch, probabilities
):
    values = np.random.default_rng(24).permutation(np.linspace(-4, 4, 400))
    if probabilities:
        values = np.exp(values) / np.exp(values).sum()
    coords = np.column_stack((np.arange(400) * 64, np.zeros(400)))
    store = AIResultStore(tmp_path)
    for fold, attention in [("fold_0", values), ("fold_1", values[::-1])]:
        store.write_wsi_result(
            "task", "slide", fold_key=fold, result={}, arrays={"attention": attention}
        )
    monkeypatch.setattr(heatmap_routes, "_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        heatmap_routes,
        "find_any_cached_coords_for_wsi",
        lambda *args: tmp_path / "coords.h5",
    )
    monkeypatch.setattr(
        heatmap_routes,
        "safe_load_h5_coords",
        lambda *args, **kwargs: (
            coords,
            {"read_size": 256, "level_downsample": 2},
            None,
        ),
    )
    monkeypatch.setattr(
        heatmap_routes,
        "get_slide",
        AsyncMock(return_value=SimpleNamespace(level_dimensions=[(30000, 1000)])),
    )
    for fold, attention in [("fold_0", values), ("fold_1", values[::-1])]:
        result = await heatmap_routes.get_heatmap_data(
            "slide",
            task_id="task",
            fold_key=fold,
            patch_size=128,
            class_idx=None,
            db=object(),
        )
        assert result["task_id"] == "task" and result["fold_key"] == fold
        assert result["patch_size"] == 512
        assert [p["index"] for p in result["top_patches"]] == np.argsort(-attention)[
            :10
        ].tolist()
        assert [p["index"] for p in result["bottom_patches"]] == np.argsort(attention)[
            :10
        ].tolist()
        assert len({p["raw_weight"] for p in result["top_patches"]}) == 10
        assert len({p["weight"] for p in result["top_patches"]}) == 1
        assert [p["raw_weight"] for p in result["top_patches"]] == attention[
            np.argsort(-attention)[:10]
        ].tolist()


async def test_thumbnail_resizes_the_full_patch_instead_of_cropping_a_smaller_area(
    monkeypatch,
):
    slide = SimpleNamespace(
        read_region=Mock(return_value=Image.new("RGBA", (1024, 1024), "#805890"))
    )
    monkeypatch.setattr(preprocessing, "get_slide", AsyncMock(return_value=slide))
    response = await preprocessing.get_patch_image_at_coords(
        "slide", x=1024, y=2048, size=1024, level=0, thumbnail_size=160, db=object()
    )
    slide.read_region.assert_called_once_with((1024, 2048), 0, (1024, 1024))
    with Image.open(io.BytesIO(response.body)) as image:
        assert image.size == (160, 160)
    check = AsyncMock()
    proxy = AsyncMock(return_value=response)
    monkeypatch.setattr(gateway, "_check_wsi_access", check)
    monkeypatch.setattr(gateway, "proxy_preprocessing_binary", proxy)
    await gateway.get_patch_image(
        "slide",
        x=1024,
        y=2048,
        size=1024,
        level=0,
        thumbnail_size=160,
        user=object(),
        db=object(),
    )
    check.assert_awaited_once()
    assert proxy.await_args.kwargs["params"] == {
        "x": 1024,
        "y": 2048,
        "size": 1024,
        "level": 0,
        "thumbnail_size": 160,
    }
