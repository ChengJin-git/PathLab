import types

import pytest

from backend.auth.dependencies import (
    check_dataset_access_permission,
    check_wsi_access_permission,
)
from backend.database.repositories.annotation import (
    AnnotationOwnershipConflictError,
    SegmentationAnnotationRepository,
)
from backend.database.repositories.dataset import DatasetRepository
from backend.database.repositories.dataset_grant import DatasetGrantRepository


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _DB:
    def __init__(self, value):
        self._value = value
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        return _Result(self._value)


def _user(user_id: str = "u-1"):
    return types.SimpleNamespace(id=user_id, is_admin=lambda: False)


@pytest.mark.asyncio
async def test_dataset_access_uses_read_access_check(monkeypatch):
    async def _read_access(_db, _dataset_id, _user_id):
        return True

    async def _legacy_permission(*_args, **_kwargs):
        raise AssertionError("legacy permission check should not be used")

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_read_access",
        staticmethod(_read_access),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_permission",
        staticmethod(_legacy_permission),
    )

    allowed = await check_dataset_access_permission(
        _user(),
        "ds-1",
        dataset_user_id="owner-1",
        db=object(),
        is_public=False,
        parent_dataset_id=None,
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_dataset_access_checks_all_ancestors_for_collaborator(monkeypatch):
    calls = []

    async def _read_access(_db, _dataset_id, _user_id):
        return False

    async def _ancestors(_db, _dataset_id, _max_depth=8):
        return ["parent-a", "parent-b"]

    async def _collab(_db, dataset_id, _user_id):
        calls.append(dataset_id)
        return dataset_id == "parent-b"

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_read_access",
        staticmethod(_read_access),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_ancestor_dataset_ids",
        staticmethod(_ancestors),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_collaborate",
        staticmethod(_collab),
    )

    allowed = await check_dataset_access_permission(
        _user(),
        "ds-2",
        dataset_user_id="owner-1",
        db=object(),
        is_public=False,
        parent_dataset_id="parent-a",
    )

    assert allowed is True
    assert calls == ["parent-a", "parent-b"]


@pytest.mark.asyncio
async def test_wsi_access_checks_all_ancestors_for_collaborator(monkeypatch):
    calls = []

    async def _read_access(_db, _dataset_id, _user_id):
        return False

    async def _ancestors(_db, _dataset_id, _max_depth=8):
        return ["ancestor-1", "ancestor-2"]

    async def _collab(_db, dataset_id, _user_id):
        calls.append(dataset_id)
        return dataset_id == "ancestor-2"

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_read_access",
        staticmethod(_read_access),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_ancestor_dataset_ids",
        staticmethod(_ancestors),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_collaborate",
        staticmethod(_collab),
    )

    allowed = await check_wsi_access_permission(
        _user(),
        wsi_dataset_id="ds-3",
        wsi_user_id="another-user",
        db=object(),
        dataset_is_public=False,
        parent_dataset_id="ancestor-1",
    )

    assert allowed is True
    assert calls == ["ancestor-1", "ancestor-2"]


@pytest.mark.asyncio
async def test_get_with_permission_blocks_personal_draft_for_non_owner():
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="draft",
        visibility_mode="personal",
        source_dataset_id="ds-1",
    )
    db = _DB(annotation)

    result = await SegmentationAnnotationRepository.get_with_permission(
        db,
        annotation_id="annot-1",
        user_id="viewer-1",
        is_admin=False,
        elevated_dataset_ids={"ds-1"},
    )

    assert result is None


@pytest.mark.asyncio
async def test_upsert_raises_on_cross_user_draft_conflict():
    db = _DB("owner-1")

    with pytest.raises(AnnotationOwnershipConflictError):
        await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id="draft-1",
            user_id="owner-2",
            annotations={},
            source_dataset_id="ds-1",
            status="draft",
        )
