import types

import pytest

from backend.database.repositories.dataset import (
    DatasetNameConflictError,
    DatasetRepository,
)


class _AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyDB:
    def begin_nested(self):
        return _AsyncNullContext()


@pytest.mark.asyncio
async def test_get_or_create_scopes_lookup_to_user_namespace(monkeypatch):
    existing_other_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Shared Dataset",
    )
    created_for_target_user = types.SimpleNamespace(
        dataset_id="ds-b",
        user_id="user-b",
        name="Shared Dataset",
    )

    lookup_user_ids = []
    create_calls = []

    async def _fake_get_by_name(_db, _name, user_id=None):
        lookup_user_ids.append(user_id)
        if user_id is None:
            return existing_other_user
        return None

    async def _fake_create(
        _db,
        _dataset_id,
        _name,
        group_id,
        user_id,
        source_organ=None,
        parent_dataset_id=None,
        is_public=False,
    ):
        create_calls.append(
            {
                "group_id": group_id,
                "user_id": user_id,
                "source_organ": source_organ,
                "parent_dataset_id": parent_dataset_id,
                "is_public": is_public,
            }
        )
        return created_for_target_user

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "create",
        staticmethod(_fake_create),
    )

    result = await DatasetRepository.get_or_create(
        _DummyDB(),
        name="Shared Dataset",
        group_id="group-1",
        user_id="user-b",
    )

    assert lookup_user_ids == ["user-b"]
    assert len(create_calls) == 1
    assert result.user_id == "user-b"


@pytest.mark.asyncio
async def test_get_or_create_reuses_dataset_for_same_user(monkeypatch):
    existing_same_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Dataset A",
    )

    create_calls = []

    async def _fake_get_by_name(_db, _name, user_id=None):
        if user_id == "user-a":
            return existing_same_user
        return None

    async def _fake_create(*_args, **_kwargs):
        create_calls.append(True)
        return types.SimpleNamespace(dataset_id="new", user_id="user-a")

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "create",
        staticmethod(_fake_create),
    )

    result = await DatasetRepository.get_or_create(
        _DummyDB(),
        name="Dataset A",
        group_id="group-1",
        user_id="user-a",
    )

    assert result is existing_same_user
    assert create_calls == []


@pytest.mark.asyncio
async def test_get_or_create_raises_conflict_when_reuse_disabled(monkeypatch):
    existing_same_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Dataset A",
    )

    async def _fake_get_by_name(_db, _name, user_id=None):
        if user_id == "user-a":
            return existing_same_user
        return None

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )

    with pytest.raises(DatasetNameConflictError):
        await DatasetRepository.get_or_create(
            _DummyDB(),
            name="Dataset A",
            group_id="group-1",
            user_id="user-a",
            reuse_existing=False,
        )
