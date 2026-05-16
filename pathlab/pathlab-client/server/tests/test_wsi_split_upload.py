# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false
import types
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User
from backend.database.repositories import DatasetStatsRepository, WSIRepository
from backend.services.dataset_splits import DatasetSplitService
from gateway.routes import wsi as wsi_routes


@dataclass
class _Slide:
    wsi_id: str
    original_filename: str
    wsi_path: str
    split: str | None = None


class _DummyDB:
    def __init__(self):
        self.committed: bool = False

    async def commit(self):
        self.committed = True


def _user(user_id: str, *, is_admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, is_admin=lambda: is_admin)


class _FakeResult:
    _rows: list[SimpleNamespace]

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _FakeOneResult:
    _row: SimpleNamespace

    def __init__(self, row: SimpleNamespace) -> None:
        self._row = row

    def one(self) -> SimpleNamespace:
        return self._row


class _DatasetSummaryDB:
    execute_count: int

    def __init__(self) -> None:
        self.execute_count = 0

    async def execute(self, _query: object) -> _FakeResult:
        self.execute_count += 1
        if self.execute_count == 1:
            return _FakeResult(
                [
                    SimpleNamespace(
                        _total_count=1,
                        dataset_id="dataset-1",
                        dataset_name="All-IDB",
                        dataset_user_id="user-1",
                        group_id="group-1",
                        data_type="wsi",
                        aggregation_level="file",
                        task_type="wsi_classification",
                        source_organ=None,
                        is_public=False,
                        parent_dataset_id=None,
                        parent_dataset_name=None,
                        file_count=260,
                        total_size=1024,
                        split_train_count=0,
                        split_val_count=0,
                        split_test_count=0,
                    )
                ]
            )
        return _FakeResult(
            [
                SimpleNamespace(
                    dataset_id="dataset-1",
                    split_train_count=180,
                    split_val_count=40,
                    split_test_count=40,
                )
            ]
        )


class _ChatContextStatsDB:
    execute_count: int

    def __init__(self) -> None:
        self.execute_count = 0

    async def execute(self, _query: object) -> _FakeResult | _FakeOneResult:
        self.execute_count += 1
        if self.execute_count == 1:
            return _FakeOneResult(
                SimpleNamespace(total_count=260, wsi_count=260, patch_count=0)
            )
        if self.execute_count == 2:
            return _FakeResult([])
        if self.execute_count == 3:
            return _FakeResult(
                [
                    SimpleNamespace(
                        dataset_id="dataset-1",
                        dataset_name="All-IDB",
                        dataset_owner_id="user-1",
                        is_public=False,
                        source_organ=None,
                        group_data_type="wsi",
                        group_task_type="wsi_classification",
                        aggregation_level="file",
                        file_count=260,
                        wsi_count=260,
                        patch_count=0,
                    )
                ]
            )
        return _FakeResult([])


@pytest.mark.asyncio
async def test_upload_dataset_splits_matches_case_insensitive_extensionless_filenames(
    monkeypatch: pytest.MonkeyPatch,
):
    user = _user("user-1")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
        user_id="user-1",
        is_public=False,
        data_group=types.SimpleNamespace(
            aggregation_level="file",
            task_type="wsi_classification",
        )
    )
    slides = [
        _Slide(
            wsi_id="wsi-1",
            original_filename="Tumor_A.SVS",
            wsi_path="/uploads/wsi_files/Tumor_A.SVS",
        ),
        _Slide(
            wsi_id="wsi-2",
            original_filename="control_b.svs",
            wsi_path="/uploads/wsi_files/control_b.svs",
        ),
        _Slide(
            wsi_id="wsi-3",
            original_filename="normal_c.svs",
            wsi_path="/uploads/wsi_files/normal_c.svs",
        ),
    ]

    monkeypatch.setattr(
        wsi_routes,
        "get_dataset_with_access",
        AsyncMock(return_value=dataset),
    )
    monkeypatch.setattr(
        WSIRepository,
        "get_by_dataset",
        AsyncMock(return_value=slides),
    )
    monkeypatch.setattr(
        wsi_routes,
        "invalidate_chat_context",
        AsyncMock(),
    )
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)

    file = UploadFile(
        filename="splits.csv",
        file=BytesIO(b"filename,split\ntumor_a,train\nCONTROL_B,test\nnormal_c,val\n"),
    )

    response = await wsi_routes.upload_dataset_splits(
        dataset_id="dataset-1",
        file=file,
        user=cast(User, user),
        user_id_filter="user-1",
        db=cast(AsyncSession, cast(object, db)),
    )

    assert response["updated_count"] == 3
    assert response["not_found_count"] == 0
    assert slides[0].split == "train"
    assert slides[1].split == "test"
    assert slides[2].split == "val"
    recompute_mock.assert_awaited_once_with(db, "dataset-1")
    assert db.committed is True


@pytest.mark.asyncio
async def test_public_non_owner_upload_writes_user_override_without_changing_baseline(
    monkeypatch: pytest.MonkeyPatch,
):
    user = _user("user-2")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
        user_id="user-1",
        is_public=True,
        parent_dataset_id=None,
        data_group=types.SimpleNamespace(
            aggregation_level="file",
            task_type="wsi_classification",
        ),
    )
    slides = [
        _Slide(
            wsi_id="wsi-1",
            original_filename="tumor_a.svs",
            wsi_path="/uploads/wsi_files/tumor_a.svs",
            split="train",
        )
    ]

    monkeypatch.setattr(
        wsi_routes,
        "get_dataset_with_access",
        AsyncMock(return_value=dataset),
    )
    monkeypatch.setattr(
        WSIRepository,
        "get_by_dataset",
        AsyncMock(return_value=slides),
    )
    monkeypatch.setattr(wsi_routes, "invalidate_chat_context", AsyncMock())
    recompute_mock = AsyncMock()
    monkeypatch.setattr(DatasetStatsRepository, "recompute", recompute_mock)
    apply_mock = AsyncMock(
        return_value=SimpleNamespace(
            updated_count=1,
            auto_val_count=0,
            not_found_files=[],
        )
    )
    monkeypatch.setattr(DatasetSplitService, "apply_csv_splits", apply_mock)

    file = UploadFile(
        filename="splits.csv",
        file=BytesIO(b"filename,split\ntumor_a.svs,test\n"),
    )

    response = await wsi_routes.upload_dataset_splits(
        dataset_id="dataset-1",
        file=file,
        user=cast(User, user),
        user_id_filter="user-2",
        db=cast(AsyncSession, cast(object, db)),
    )

    assert response["updated_count"] == 1
    assert slides[0].split == "train"
    wsi_routes.get_dataset_with_access.assert_awaited_once_with(
        "dataset-1",
        user,
        db,
        require_owner=False,
        not_found_detail="Dataset not found: dataset-1",
        forbidden_detail="You don't have permission to modify this dataset",
    )
    WSIRepository.get_by_dataset.assert_awaited_once_with(db, "dataset-1", user_id=None)
    apply_mock.assert_awaited_once_with(
        db=db,
        dataset_id="dataset-1",
        slides=slides,
        csv_text="filename,split\ntumor_a.svs,test\n",
        task_type="wsi_classification",
        target_user_id="user-2",
    )
    recompute_mock.assert_not_awaited()
    assert db.committed is True


@pytest.mark.asyncio
async def test_private_non_owner_upload_is_rejected_even_with_read_access(
    monkeypatch: pytest.MonkeyPatch,
):
    user = _user("user-2")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
        user_id="user-1",
        is_public=False,
        parent_dataset_id=None,
        data_group=types.SimpleNamespace(
            aggregation_level="file",
            task_type="wsi_classification",
        ),
    )
    apply_mock = AsyncMock()

    monkeypatch.setattr(
        wsi_routes,
        "get_dataset_with_access",
        AsyncMock(return_value=dataset),
    )
    monkeypatch.setattr(WSIRepository, "get_by_dataset", AsyncMock(return_value=[]))
    monkeypatch.setattr(DatasetSplitService, "apply_csv_splits", apply_mock)

    file = UploadFile(
        filename="splits.csv",
        file=BytesIO(b"filename,split\ntumor_a.svs,test\n"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await wsi_routes.upload_dataset_splits(
            dataset_id="dataset-1",
            file=file,
            user=cast(User, user),
            user_id_filter="user-2",
            db=cast(AsyncSession, cast(object, db)),
        )

    assert exc_info.value.status_code == 403
    apply_mock.assert_not_awaited()
    assert db.committed is False


@pytest.mark.asyncio
async def test_owner_upload_updates_baseline_split_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    user = _user("user-1")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
        user_id="user-1",
        is_public=True,
        parent_dataset_id=None,
        data_group=types.SimpleNamespace(
            aggregation_level="file",
            task_type="wsi_classification",
        ),
    )
    slides = [
        _Slide(
            wsi_id="wsi-1",
            original_filename="tumor_a.svs",
            wsi_path="/uploads/wsi_files/tumor_a.svs",
            split="train",
        )
    ]
    apply_mock = AsyncMock(
        return_value=SimpleNamespace(
            updated_count=1,
            auto_val_count=0,
            not_found_files=[],
        )
    )

    monkeypatch.setattr(
        wsi_routes,
        "get_dataset_with_access",
        AsyncMock(return_value=dataset),
    )
    monkeypatch.setattr(WSIRepository, "get_by_dataset", AsyncMock(return_value=slides))
    monkeypatch.setattr(wsi_routes, "invalidate_chat_context", AsyncMock())
    monkeypatch.setattr(DatasetSplitService, "apply_csv_splits", apply_mock)

    file = UploadFile(
        filename="splits.csv",
        file=BytesIO(b"filename,split\ntumor_a.svs,test\n"),
    )

    await wsi_routes.upload_dataset_splits(
        dataset_id="dataset-1",
        file=file,
        user=cast(User, user),
        user_id_filter="user-1",
        db=cast(AsyncSession, cast(object, db)),
    )

    WSIRepository.get_by_dataset.assert_awaited_once_with(db, "dataset-1", user_id="user-1")
    apply_mock.assert_awaited_once_with(
        db=db,
        dataset_id="dataset-1",
        slides=slides,
        csv_text="filename,split\ntumor_a.svs,test\n",
        task_type="wsi_classification",
        target_user_id=None,
    )
    assert db.committed is True


@pytest.mark.asyncio
async def test_upload_dataset_splits_reports_ambiguous_extensionless_matches(
    monkeypatch: pytest.MonkeyPatch,
):
    user = _user("user-1")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
        user_id="user-1",
        is_public=False,
        data_group=types.SimpleNamespace(
            aggregation_level="file",
            task_type="wsi_classification",
        )
    )
    slides = [
        _Slide(
            wsi_id="wsi-1",
            original_filename="sample.svs",
            wsi_path="/uploads/wsi_files/sample.svs",
        ),
        _Slide(
            wsi_id="wsi-2",
            original_filename="sample.tiff",
            wsi_path="/uploads/wsi_files/sample.tiff",
        ),
    ]

    monkeypatch.setattr(
        wsi_routes,
        "get_dataset_with_access",
        AsyncMock(return_value=dataset),
    )
    monkeypatch.setattr(
        WSIRepository,
        "get_by_dataset",
        AsyncMock(return_value=slides),
    )

    file = UploadFile(
        filename="splits.csv",
        file=BytesIO(b"filename,split\nsample,train\n"),
    )

    with pytest.raises(HTTPException) as exc_info:
        response = await wsi_routes.upload_dataset_splits(
            dataset_id="dataset-1",
            file=file,
            user=cast(User, user),
            user_id_filter="user-1",
            db=cast(AsyncSession, cast(object, db)),
        )
        assert response is not None

    assert exc_info.value.status_code == 400
    assert "ambiguous" in str(exc_info.value.detail).lower()
    assert db.committed is False


@pytest.mark.asyncio
async def test_dataset_summary_uses_live_split_counts_when_cached_stats_are_stale(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        WSIRepository,
        "_get_coco_categories_batch",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        DatasetSplitService,
        "summarize_many",
        AsyncMock(
            return_value={
                "dataset-1": SimpleNamespace(
                    has_predefined_splits=True,
                    predefined_split_counts={"train": 180, "val": 40, "test": 40},
                    predefined_split_unit="files",
                )
            }
        ),
    )

    datasets, total = await WSIRepository.get_datasets_with_total(
        db=cast(AsyncSession, cast(object, _DatasetSummaryDB())),
        dataset_id="dataset-1",
    )

    assert total == 1
    assert datasets[0]["has_predefined_splits"] is True
    assert datasets[0]["predefined_split_counts"] == {
        "train": 180,
        "val": 40,
        "test": 40,
    }


@pytest.mark.asyncio
async def test_get_datasets_with_total_uses_split_service_for_stale_stats(
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: repository must delegate stale split resolution to DatasetSplitService."""
    monkeypatch.setattr(
        WSIRepository,
        "_get_coco_categories_batch",
        AsyncMock(return_value={}),
    )

    service_mock = AsyncMock(
        return_value={
            "dataset-1": SimpleNamespace(
                has_predefined_splits=True,
                predefined_split_counts={"train": 99, "val": 1, "test": 0},
                predefined_split_unit="files",
            )
        }
    )
    monkeypatch.setattr(DatasetSplitService, "summarize_many", service_mock)

    db = cast(AsyncSession, cast(object, _DatasetSummaryDB()))
    datasets, total = await WSIRepository.get_datasets_with_total(
        db=db,
        dataset_id="dataset-1",
    )

    assert total == 1
    service_mock.assert_awaited_once_with(db, ["dataset-1"])
    assert datasets[0]["has_predefined_splits"] is True
    assert datasets[0]["predefined_split_counts"] == {
        "train": 99,
        "val": 1,
        "test": 0,
    }
    assert datasets[0]["predefined_split_unit"] == "files"


@pytest.mark.asyncio
async def test_chat_context_stats_use_split_service_for_predefined_splits(
    monkeypatch: pytest.MonkeyPatch,
):
    service_mock = AsyncMock(
        return_value={
            "dataset-1": SimpleNamespace(
                has_predefined_splits=True,
                predefined_split_counts={"train": 12, "val": 3, "test": 5},
                predefined_split_unit="files",
            )
        }
    )
    monkeypatch.setattr(DatasetSplitService, "summarize_many", service_mock)

    db = cast(AsyncSession, cast(object, _ChatContextStatsDB()))
    stats = await WSIRepository.get_chat_context_stats(db=db, user_id="user-1")

    service_mock.assert_awaited_once_with(db, ["dataset-1"])
    assert stats["datasets"][0]["has_predefined_splits"] is True
    assert stats["datasets"][0]["predefined_split_counts"] == {
        "train": 12,
        "val": 3,
        "test": 5,
    }
    assert stats["datasets"][0]["predefined_split_unit"] == "files"
