# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories.training import TrainingTaskRepository
from backend.services.dataset_splits import DatasetSplitService


class _FakeScalarResult:
    def scalar_one(self):
        return SimpleNamespace(task_id="task-1")


class _FakeDB:
    def __init__(self) -> None:
        self.executed: list[object] = []
        self.bulk_records: list[dict[str, object]] = []
        self.added: list[object] = []
        self.flushed = False
        self.committed = False

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, statement: object, records: list[dict[str, object]] | None = None) -> _FakeScalarResult:
        self.executed.append(statement)
        if records:
            self.bulk_records.extend(records)
        return _FakeScalarResult()


@pytest.mark.asyncio
async def test_manual_training_uses_submitter_split_overrides(monkeypatch: pytest.MonkeyPatch):
    slides = [
        SimpleNamespace(wsi_id="wsi-1", label="A", split="train", dataset_id="dataset-1"),
        SimpleNamespace(wsi_id="wsi-2", label="B", split="val", dataset_id="dataset-1"),
    ]
    resolve_mock = AsyncMock(return_value={"wsi-1": "test", "wsi-2": "val"})
    monkeypatch.setattr(DatasetSplitService, "resolve_effective_splits", resolve_mock)

    db = _FakeDB()
    await TrainingTaskRepository.create(
        db=cast(AsyncSession, cast(object, db)),
        task_data={
            "task_id": "task-1",
            "task_name": "Manual split task",
            "group_id": "group-1",
            "user_id": "user-2",
            "preprocessing_config": {},
            "model_config": {},
            "task_type": "wsi_classification",
        },
        wsi_ids=["wsi-1", "wsi-2"],
        split_config={"strategy": "manual"},
        prefetched_wsis=slides,
    )

    resolve_mock.assert_awaited_once_with(
        cast(AsyncSession, cast(object, db)),
        slides,
        "user-2",
    )
    assert db.bulk_records[0]["split"] == "test"
    assert db.bulk_records[1]["split"] == "val"
    assert db.flushed is True
    assert db.committed is True
