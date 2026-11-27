"""Derived dataset extraction preserves image bytes, labels, holes and access lineage."""

from unittest.mock import AsyncMock
from sqlalchemy import select
from backend.preprocessing import main as preprocessing
from backend.database.models import Dataset, SegmentationAnnotation, WSISlide
from backend.database.repositories import DatasetStatsRepository
from test_viewer_workspace import workspace


async def test_spatial_extraction_copies_source_and_persists_holes(
    workspace, monkeypatch
):
    w = workspace
    monkeypatch.setattr(preprocessing, "_uploads_dir", lambda: w.root)
    monkeypatch.setattr("backend.common.progress_store.set_progress", AsyncMock())
    monkeypatch.setattr(
        "backend.annotation.summary_cache.rebuild_dataset_annotation_summary_cache",
        AsyncMock(),
    )
    monkeypatch.setattr(DatasetStatsRepository, "recompute", AsyncMock())
    region = preprocessing.RegionSpec(
        type="polygon",
        x=1.5,
        y=1.5,
        width=60,
        height=60,
        label="T",
        points=[[1.5, 1.5], [61.5, 1.5], [61.5, 61.5], [1.5, 61.5]],
        holes=[[[10, 10], [20, 10], [20, 20], [10, 20]]],
    )
    async with w.db() as db:
        count = await preprocessing._extract_segmentation_dataset(
            db, {"slide": [region]}, "child", str(w.people[0].id), "test-extraction", 1
        )
        assert count == 1
        image = await db.scalar(select(WSISlide).where(WSISlide.dataset_id == "child"))
        assert image and image.parent_wsi_id == "slide" and image.data_type == "patch"
        from pathlib import Path

        assert Path(image.wsi_path).read_bytes() == (w.root / "image.png").read_bytes()
        labels = await db.scalar(
            select(SegmentationAnnotation).where(
                SegmentationAnnotation.source_dataset_id == "child"
            )
        )
        assert (
            labels.annotations["annotations"][0]["viewer_geometry"]["holes"]
            == region.model_dump()["holes"]
        )


async def test_classification_crop_accepts_fractional_coordinates(
    workspace, monkeypatch
):
    w = workspace
    monkeypatch.setattr(preprocessing, "_uploads_dir", lambda: w.root)
    async with w.db() as db:
        await preprocessing._extract_single_region(
            db,
            "slide",
            w.root / "image.png",
            True,
            preprocessing.RegionSpec(
                type="rect", x=10.2, y=10.8, width=20.5, height=30.2, label="T"
            ),
            "child",
            str(w.people[0].id),
        )
        await db.commit()
        image = await db.scalar(select(WSISlide).where(WSISlide.dataset_id == "child"))
        assert (image.width, image.height) == (21, 31)
