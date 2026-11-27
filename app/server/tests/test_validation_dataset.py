"""GET /results/validation-datasets/{dataset_id}: one dataset's external-validation metadata."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from helpers import _make_user


def _dataset(**overrides) -> MagicMock:
    task = MagicMock(task_type="patch_classification", classes=None)
    dataset = MagicMock(
        dataset_id="ds-1",
        user_id="another-user",
        is_public=False,
        data_type="patch",
        aggregation_level="wsi",
        tasks=[task],
    )
    dataset.name = "Target"
    for key, value in overrides.items():
        setattr(dataset, key, value)
    return dataset


def _db_returning(dataset) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = dataset
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def _call(user, dataset, *, wsi_ids=("w1", "w2")):
    from gateway.routes.results import get_validation_dataset

    with (
        patch("backend.services.workspaces.resolve_scope", new=AsyncMock(return_value=MagicMock(workspace_id=None))),
        patch("gateway.routes.results.DatasetRepository.get_wsi_ids", new=AsyncMock(return_value=list(wsi_ids))),
        patch("gateway.routes.results.DatasetRepository.get_distinct_labels", new=AsyncMock(return_value=["b", "a"])),
    ):
        return await get_validation_dataset("ds-1", user=user, db=_db_returning(dataset), workspace_id=None)


@pytest.mark.asyncio
async def test_returns_the_requested_dataset_with_wsi_ids_for_overlap_checks():
    item = await _call(_make_user("admin"), _dataset())

    assert item["dataset_id"] == "ds-1"
    assert item["wsi_ids"] == ["w1", "w2"]
    assert item["distinct_labels"] == ["a", "b"]
    assert item["total_wsi_count"] == item["display_count"] == 2
    assert item["available_feature_extractors"] == []


@pytest.mark.asyncio
async def test_hides_datasets_the_user_cannot_access():
    with pytest.raises(HTTPException) as exc:
        await _call(_make_user("pathologist"), _dataset())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_public_dataset_is_visible_to_gpu_users():
    item = await _call(_make_user("pathologist"), _dataset(is_public=True))
    assert item["name"] == "Target"


@pytest.mark.asyncio
async def test_empty_dataset_is_not_a_validation_target():
    with pytest.raises(HTTPException) as exc:
        await _call(_make_user("admin"), _dataset(), wsi_ids=())
    assert exc.value.status_code == 404
