# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false
import types
from dataclasses import dataclass
from io import BytesIO
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User
from backend.database.repositories import DatasetStatsRepository, WSIRepository
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


@pytest.mark.asyncio
async def test_upload_dataset_splits_matches_case_insensitive_extensionless_filenames(
    monkeypatch: pytest.MonkeyPatch,
):
    user = types.SimpleNamespace(id="user-1")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
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
async def test_upload_dataset_splits_reports_ambiguous_extensionless_matches(
    monkeypatch: pytest.MonkeyPatch,
):
    user = types.SimpleNamespace(id="user-1")
    db = _DummyDB()
    dataset = types.SimpleNamespace(
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
