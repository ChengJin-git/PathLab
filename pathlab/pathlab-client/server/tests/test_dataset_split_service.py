# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories.dataset_stats import DatasetStatsRepository
from backend.services.dataset_splits import DatasetSplitService


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
