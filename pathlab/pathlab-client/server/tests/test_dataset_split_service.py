# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories.dataset_stats import DatasetStatsRepository
from backend.services.dataset_splits import DatasetSplitService


class _DummyDB:
    pass


class _Slide:
    def __init__(
        self,
        wsi_id: str,
        original_filename: str,
        wsi_path: str,
        split: str | None = None,
    ) -> None:
        self.wsi_id: str = wsi_id
        self.original_filename: str = original_filename
        self.wsi_path: str = wsi_path
        self.split: str | None = split
        self.label: str | None = None
        self.case_id: str | None = None
        self.age: int | None = None
        self.gender: str | None = None
        self.event_time: float | None = None
        self.event_status: int | None = None


class _FakeResult:
    _rows: list[SimpleNamespace]

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _FakeDB:
    def __init__(self, results: list[list[SimpleNamespace]]) -> None:
        self._results: list[list[SimpleNamespace]] = results
        self._call_idx: int = 0
        self.recompute_calls: list[str] = []

    async def execute(self, _query: object) -> _FakeResult:
        rows = self._results[self._call_idx]
        self._call_idx += 1
        return _FakeResult(rows)


def fake_db_with_cached_counts(train: int, val: int, test: int) -> _FakeDB:
    return _FakeDB(
        [
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    aggregation_level="file",
                    split_train_count=train,
                    split_val_count=val,
                    split_test_count=test,
                )
            ]
        ]
    )


def fake_db_with_zero_cache_and_live_counts(
    train: int, val: int, test: int
) -> _FakeDB:
    return _FakeDB(
        [
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    aggregation_level="file",
                    split_train_count=0,
                    split_val_count=0,
                    split_test_count=0,
                )
            ],
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    split_train_count=train,
                    split_val_count=val,
                    split_test_count=test,
                )
            ],
        ]
    )


@pytest.mark.asyncio
async def test_summarize_many_uses_cached_counts_when_present():
    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, fake_db_with_cached_counts(3, 1, 1))),
        dataset_ids=["dataset-1"],
    )

    assert summaries["dataset-1"].has_predefined_splits is True
    assert summaries["dataset-1"].predefined_split_counts == {
        "train": 3,
        "val": 1,
        "test": 1,
    }
    assert summaries["dataset-1"].predefined_split_unit == "files"


@pytest.mark.asyncio
async def test_summarize_many_repairs_zero_cache_from_live_splits(
    monkeypatch: pytest.MonkeyPatch,
):
    db = fake_db_with_zero_cache_and_live_counts(train=180, val=40, test=40)
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, db)),
        dataset_ids=["dataset-1"],
    )

    assert summaries["dataset-1"].has_predefined_splits is True
    assert summaries["dataset-1"].predefined_split_counts == {
        "train": 180,
        "val": 40,
        "test": 40,
    }
    assert summaries["dataset-1"].predefined_split_unit == "files"
    recompute_mock.assert_awaited_once_with(db, "dataset-1")


@pytest.mark.asyncio
async def test_summarize_many_returns_empty_dict_for_empty_dataset_ids():
    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, _FakeDB([]))),
        dataset_ids=[],
    )
    assert summaries == {}


@pytest.mark.asyncio
async def test_summarize_many_repairs_missing_stats_row_from_live_splits(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _FakeDB(
        [
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    aggregation_level="case",
                    split_train_count=None,
                    split_val_count=None,
                    split_test_count=None,
                )
            ],
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    split_train_count=50,
                    split_val_count=10,
                    split_test_count=10,
                )
            ],
        ]
    )
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, db)),
        dataset_ids=["dataset-1"],
    )

    assert summaries["dataset-1"].has_predefined_splits is True
    assert summaries["dataset-1"].predefined_split_counts == {
        "train": 50,
        "val": 10,
        "test": 10,
    }
    assert summaries["dataset-1"].predefined_split_unit == "cases"
    recompute_mock.assert_awaited_once_with(db, "dataset-1")


@pytest.mark.asyncio
async def test_summarize_many_case_level_live_counts_use_cases_unit(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _FakeDB(
        [
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    aggregation_level="case",
                    split_train_count=0,
                    split_val_count=0,
                    split_test_count=0,
                )
            ],
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    split_train_count=120,
                    split_val_count=30,
                    split_test_count=30,
                )
            ],
        ]
    )
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, db)),
        dataset_ids=["dataset-1"],
    )

    assert summaries["dataset-1"].has_predefined_splits is True
    assert summaries["dataset-1"].predefined_split_counts == {
        "train": 120,
        "val": 30,
        "test": 30,
    }
    assert summaries["dataset-1"].predefined_split_unit == "cases"
    recompute_mock.assert_awaited_once_with(db, "dataset-1")


@pytest.mark.asyncio
async def test_summarize_many_mixed_datasets_returns_one_per_id(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _FakeDB(
        [
            [
                SimpleNamespace(
                    dataset_id="ds-cached",
                    aggregation_level="file",
                    split_train_count=10,
                    split_val_count=2,
                    split_test_count=2,
                ),
                SimpleNamespace(
                    dataset_id="ds-zero",
                    aggregation_level="file",
                    split_train_count=0,
                    split_val_count=0,
                    split_test_count=0,
                ),
                SimpleNamespace(
                    dataset_id="ds-case",
                    aggregation_level="case",
                    split_train_count=0,
                    split_val_count=0,
                    split_test_count=0,
                ),
            ],
            [
                SimpleNamespace(
                    dataset_id="ds-zero",
                    split_train_count=0,
                    split_val_count=0,
                    split_test_count=0,
                ),
                SimpleNamespace(
                    dataset_id="ds-case",
                    split_train_count=5,
                    split_val_count=1,
                    split_test_count=1,
                ),
            ],
        ]
    )
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    summaries = await DatasetSplitService.summarize_many(
        db=cast(AsyncSession, cast(object, db)),
        dataset_ids=["ds-cached", "ds-zero", "ds-case"],
    )

    assert len(summaries) == 3

    assert summaries["ds-cached"].has_predefined_splits is True
    assert summaries["ds-cached"].predefined_split_counts == {
        "train": 10,
        "val": 2,
        "test": 2,
    }
    assert summaries["ds-cached"].predefined_split_unit == "files"

    assert summaries["ds-zero"].has_predefined_splits is False
    assert summaries["ds-zero"].predefined_split_counts == {
        "train": 0,
        "val": 0,
        "test": 0,
    }
    assert summaries["ds-zero"].predefined_split_unit == "files"

    assert summaries["ds-case"].has_predefined_splits is True
    assert summaries["ds-case"].predefined_split_counts == {
        "train": 5,
        "val": 1,
        "test": 1,
    }
    assert summaries["ds-case"].predefined_split_unit == "cases"

    recompute_mock.assert_awaited_once_with(db, "ds-case")


@pytest.mark.asyncio
async def test_apply_csv_splits_matches_case_insensitive_extensionless_filenames(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _DummyDB()
    slides = [
        _Slide("wsi-1", "Tumor_A.SVS", "/uploads/wsi_files/Tumor_A.SVS"),
        _Slide("wsi-2", "control_b.svs", "/uploads/wsi_files/control_b.svs"),
        _Slide("wsi-3", "normal_c.svs", "/uploads/wsi_files/normal_c.svs"),
    ]
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    result = await DatasetSplitService.apply_csv_splits(
        db=cast(AsyncSession, cast(object, db)),
        dataset_id="dataset-1",
        slides=slides,
        csv_text="filename,split\ntumor_a,train\nCONTROL_B,test\nnormal_c,val\n",
        task_type="wsi_classification",
    )

    assert result.updated_count == 3
    assert result.auto_val_count == 0
    assert result.not_found_files == []
    assert slides[0].split == "train"
    assert slides[1].split == "test"
    assert slides[2].split == "val"
    recompute_mock.assert_awaited_once_with(db, "dataset-1")


@pytest.mark.asyncio
async def test_apply_csv_splits_reports_ambiguous_extensionless_matches():
    slides = [
        _Slide("wsi-1", "sample.svs", "/uploads/wsi_files/sample.svs"),
        _Slide("wsi-2", "sample.tiff", "/uploads/wsi_files/sample.tiff"),
    ]

    with pytest.raises(HTTPException) as exc_info:
        _ = await DatasetSplitService.apply_csv_splits(
            db=cast(AsyncSession, cast(object, _DummyDB())),
            dataset_id="dataset-1",
            slides=slides,
            csv_text="filename,split\nsample,train\n",
            task_type="wsi_classification",
        )

    assert exc_info.value.status_code == 400
    assert "ambiguous" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_apply_csv_splits_updates_metadata_and_normalizes_validation(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _DummyDB()
    slide = _Slide("wsi-1", "sample.svs", "/uploads/wsi_files/sample.svs")
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    result = await DatasetSplitService.apply_csv_splits(
        db=cast(AsyncSession, cast(object, db)),
        dataset_id="dataset-1",
        slides=[slide],
        csv_text=(
            "file_name,split,label,case_id,age,gender,event_time,event_status\n"
            "sample.svs,validation,tumor,case-1,42,F,13.5,1\n"
        ),
        task_type="wsi_classification",
    )

    assert result.updated_count == 1
    assert slide.split == "val"
    assert slide.label == "tumor"
    assert slide.case_id == "case-1"
    assert slide.age == 42
    assert slide.gender == "F"
    assert slide.event_time == 13.5
    assert slide.event_status == 1
    recompute_mock.assert_awaited_once_with(db, "dataset-1")
