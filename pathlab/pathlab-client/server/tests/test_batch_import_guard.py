from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from gateway import utils


FAKE_DB = cast(AsyncSession, object())


@pytest.mark.asyncio
async def test_active_batch_import_for_other_dataset_does_not_block_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _active_tasks(_db: AsyncSession):
        return [
            SimpleNamespace(
                task_type="batch_import",
                params={"dataset_id": "other-dataset"},
            )
        ]

    monkeypatch.setattr(
        "gateway.utils.StorageTaskRepository.get_active_tasks", _active_tasks
    )

    await utils.require_no_active_batch_imports(
        FAKE_DB,
        detail="blocked",
        dataset_ids={"training-dataset"},
    )


@pytest.mark.asyncio
async def test_active_batch_import_for_same_dataset_blocks_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _active_tasks(_db: AsyncSession):
        return [
            SimpleNamespace(
                task_type="batch_import",
                params={"dataset_id": "training-dataset"},
            )
        ]

    monkeypatch.setattr(
        "gateway.utils.StorageTaskRepository.get_active_tasks", _active_tasks
    )

    with pytest.raises(HTTPException) as exc_info:
        await utils.require_no_active_batch_imports(
            FAKE_DB,
            detail="blocked",
            dataset_ids={"training-dataset"},
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "blocked"


@pytest.mark.asyncio
async def test_unscoped_batch_import_does_not_block_dataset_scoped_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _active_tasks(_db: AsyncSession):
        return [
            SimpleNamespace(
                task_type="batch_import",
                params={"dataset_name": "Admin Only Import"},
            )
        ]

    monkeypatch.setattr(
        "gateway.utils.StorageTaskRepository.get_active_tasks", _active_tasks
    )

    await utils.require_no_active_batch_imports(
        FAKE_DB,
        detail="blocked",
        dataset_ids={"training-dataset"},
    )


@pytest.mark.asyncio
async def test_empty_dataset_scope_does_not_fall_back_to_global_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _active_tasks(_db: AsyncSession):
        return [
            SimpleNamespace(
                task_type="batch_import",
                params={"dataset_id": "other-dataset"},
            )
        ]

    monkeypatch.setattr(
        "gateway.utils.StorageTaskRepository.get_active_tasks", _active_tasks
    )

    await utils.require_no_active_batch_imports(
        FAKE_DB,
        detail="blocked",
        dataset_ids=set(),
    )


@pytest.mark.asyncio
async def test_legacy_unscoped_guard_still_blocks_any_active_batch_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _active_tasks(_db: AsyncSession):
        return [
            SimpleNamespace(
                task_type="batch_import",
                params={"dataset_id": "any-dataset"},
            )
        ]

    monkeypatch.setattr(
        "gateway.utils.StorageTaskRepository.get_active_tasks", _active_tasks
    )

    with pytest.raises(HTTPException):
        await utils.require_no_active_batch_imports(FAKE_DB, detail="blocked")
