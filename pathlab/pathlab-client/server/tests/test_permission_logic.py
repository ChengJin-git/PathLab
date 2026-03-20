import types

import pytest

from backend.auth.dependencies import (
    check_dataset_write_permission,
    check_dataset_access_permission,
    get_permitted_dataset_ids,
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


@pytest.mark.asyncio
async def test_dataset_access_allows_public_without_grant(monkeypatch):
    async def _read_access(*_args, **_kwargs):
        raise AssertionError(
            "read-access grant check should not run for public datasets"
        )

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_read_access",
        staticmethod(_read_access),
    )

    allowed = await check_dataset_access_permission(
        _user(),
        "ds-public",
        dataset_user_id="owner-1",
        db=object(),
        is_public=True,
        parent_dataset_id=None,
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_wsi_access_denies_when_no_public_owner_or_grant(monkeypatch):
    async def _read_access(_db, _dataset_id, _user_id):
        return False

    async def _collab(_db, _dataset_id, _user_id):
        return False

    async def _ancestors(_db, _dataset_id, _max_depth=8):
        return ["parent-only"]

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_read_access",
        staticmethod(_read_access),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_collaborate",
        staticmethod(_collab),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_ancestor_dataset_ids",
        staticmethod(_ancestors),
    )

    allowed = await check_wsi_access_permission(
        _user(),
        wsi_dataset_id="ds-private",
        wsi_user_id="owner-2",
        db=object(),
        dataset_is_public=False,
        parent_dataset_id="parent-only",
    )

    assert allowed is False


@pytest.mark.asyncio
async def test_dataset_write_access_checks_direct_collaborate(monkeypatch):
    async def _collab(_db, dataset_id, _user_id):
        return dataset_id == "ds-write"

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_collaborate",
        staticmethod(_collab),
    )

    allowed = await check_dataset_write_permission(
        _user(),
        "ds-write",
        dataset_user_id="owner-1",
        db=object(),
        parent_dataset_id=None,
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_dataset_write_access_checks_ancestors_for_collaborator(monkeypatch):
    calls = []

    async def _ancestors(_db, _dataset_id, _max_depth=8):
        return ["parent-a", "parent-b"]

    async def _collab(_db, dataset_id, _user_id):
        calls.append(dataset_id)
        return dataset_id == "parent-b"

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

    allowed = await check_dataset_write_permission(
        _user(),
        "ds-child",
        dataset_user_id="owner-1",
        db=object(),
        parent_dataset_id="parent-a",
    )

    assert allowed is True
    assert calls == ["ds-child", "parent-a", "parent-b"]


@pytest.mark.asyncio
async def test_get_permitted_dataset_ids_uses_read_ids(monkeypatch):
    async def _public_ids(_db):
        return ["ds-public"]

    async def _read_ids(_db, _user_id):
        return ["ds-read"]

    async def _collab_ids(_db, _user_id):
        return ["ds-collab"]

    async def _children(_db, _ids):
        return ["ds-child"]

    async def _gpu_ids(*_args, **_kwargs):
        raise AssertionError("GPU-only dataset IDs should not drive read visibility")

    monkeypatch.setattr(
        DatasetRepository,
        "get_public_dataset_ids",
        staticmethod(_public_ids),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "list_read_dataset_ids_for_user",
        staticmethod(_read_ids),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "list_collaborate_dataset_ids_for_user",
        staticmethod(_collab_ids),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_child_dataset_ids",
        staticmethod(_children),
    )
    monkeypatch.setattr(
        DatasetGrantRepository,
        "list_gpu_dataset_ids_for_user",
        staticmethod(_gpu_ids),
    )

    dataset_ids = await get_permitted_dataset_ids(_user(), object())

    assert set(dataset_ids) == {"ds-public", "ds-read", "ds-collab", "ds-child"}


@pytest.mark.asyncio
async def test_get_with_permission_allows_inherit_draft_for_dataset_access():
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="draft",
        visibility_mode="inherit",
        source_dataset_id="ds-2",
    )
    db = _DB(annotation)

    result = await SegmentationAnnotationRepository.get_with_permission(
        db,
        annotation_id="annot-2",
        user_id="viewer-2",
        is_admin=False,
        elevated_dataset_ids={"ds-2"},
    )

    assert result is annotation


@pytest.mark.asyncio
async def test_get_with_permission_allows_inherit_on_public_dataset(monkeypatch):
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="draft",
        visibility_mode="inherit",
        source_dataset_id="ds-public",
    )

    async def _get_by_id(_db, dataset_id):
        return types.SimpleNamespace(
            dataset_id=dataset_id,
            is_public=True,
            is_open_collaboration=False,
        )

    monkeypatch.setattr(DatasetRepository, "get_by_id", staticmethod(_get_by_id))

    db = _DB(annotation)
    result = await SegmentationAnnotationRepository.get_with_permission(
        db,
        annotation_id="annot-public",
        user_id="viewer-any",
        is_admin=False,
        elevated_dataset_ids=None,
    )

    assert result is annotation


@pytest.mark.asyncio
async def test_get_with_permission_blocks_inherit_on_private_dataset(monkeypatch):
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="draft",
        visibility_mode="inherit",
        source_dataset_id="ds-private",
    )

    async def _get_by_id(_db, dataset_id):
        return types.SimpleNamespace(
            dataset_id=dataset_id,
            is_public=False,
            is_open_collaboration=False,
        )

    monkeypatch.setattr(DatasetRepository, "get_by_id", staticmethod(_get_by_id))

    db = _DB(annotation)
    result = await SegmentationAnnotationRepository.get_with_permission(
        db,
        annotation_id="annot-private",
        user_id="viewer-any",
        is_admin=False,
        elevated_dataset_ids=None,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_with_permission_allows_shared_draft_for_dataset_access():
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="shared_draft",
        visibility_mode="shared",
        source_dataset_id="ds-3",
    )
    db = _DB(annotation)

    result = await SegmentationAnnotationRepository.get_with_permission(
        db,
        annotation_id="shared_ds-3",
        user_id="viewer-3",
        is_admin=False,
        elevated_dataset_ids={"ds-3"},
    )

    assert result is annotation
