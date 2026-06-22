from importlib import import_module
import types
from typing import Any, cast

import pytest

DataGroupRepository = cast(
    Any,
    import_module("backend.database.repositories.data_group").DataGroupRepository,
)


class _AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any):
        return False


class _DummyDB:
    def begin_nested(self):
        return _AsyncNullContext()


class _CreateDB:
    def __init__(self):
        self.added: list[Any] = []

    def add(self, obj: Any):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


class _ScalarResult:
    def scalar_one_or_none(self):
        return None


class _LookupDB:
    async def execute(self, statement: Any):
        compiled = statement.compile()
        params = compiled.params
        assert params.get("data_type_1") == "patch"
        assert params.get("aggregation_level_1") == "file"
        assert params.get("task_type_1") == "patch_classification"
        return _ScalarResult()


@pytest.mark.asyncio
async def test_create_normalizes_task_type_and_preserves_data_axes():
    db = _CreateDB()

    created = await DataGroupRepository.create(
        db,
        group_id="group-1",
        name="WSI case classification",
        data_type="wsi",
        aggregation_level="case",
        task_type="wsi_classification",
    )

    assert getattr(created, "task_type") == "wsi_classification"
    assert getattr(created, "data_type") == "wsi"
    assert getattr(created, "aggregation_level") == "case"


@pytest.mark.asyncio
async def test_get_by_combination_normalizes_lookup_task_type():
    result = await DataGroupRepository.get_by_combination(
        _LookupDB(),
        data_type="patch",
        aggregation_level="file",
        task_type="patch_classification",
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_normalizes_before_lookup_and_create(monkeypatch):
    db = _DummyDB()
    lookup_calls = []
    create_calls = []

    async def _fake_get_by_combination(_db, data_type, aggregation_level, task_type):
        lookup_calls.append((data_type, aggregation_level, task_type))
        return None

    async def _fake_create(_db: Any, **kwargs: Any):
        group_id = kwargs["group_id"]
        name = kwargs["name"]
        data_type = kwargs["data_type"]
        aggregation_level = kwargs["aggregation_level"]
        task_type = kwargs["task_type"]
        description = kwargs.get("description")
        create_calls.append((data_type, aggregation_level, task_type, name, description))
        return types.SimpleNamespace(
            group_id=group_id,
            name=name,
            data_type=data_type,
            aggregation_level=aggregation_level,
            task_type=task_type,
        )

    monkeypatch.setattr(
        DataGroupRepository,
        "get_by_combination",
        staticmethod(_fake_get_by_combination),
    )
    monkeypatch.setattr(
        DataGroupRepository,
        "create",
        staticmethod(_fake_create),
    )

    created = await DataGroupRepository.get_or_create(
        db,
        data_type="wsi",
        aggregation_level="case",
        task_type="wsi_classification",
    )

    assert lookup_calls == [("wsi", "case", "wsi_classification")]
    assert len(create_calls) == 1
    assert create_calls[0][0] == "wsi"
    assert create_calls[0][1] == "case"
    assert create_calls[0][2] == "wsi_classification"
    assert getattr(created, "data_type") == "wsi"
    assert getattr(created, "aggregation_level") == "case"
    assert getattr(created, "task_type") == "wsi_classification"
    assert "WSI Classification" in getattr(created, "name")


@pytest.mark.asyncio
async def test_get_or_create_integrity_error_fallback_requeries_with_canonical_id(
    monkeypatch,
):
    from sqlalchemy.exc import IntegrityError

    existing = types.SimpleNamespace(
        group_id="existing-group",
        name="WSI Case-level Classification",
        data_type="wsi",
        aggregation_level="case",
        task_type="wsi_classification",
    )
    lookup_calls = []

    async def _fake_get_by_combination(_db, data_type, aggregation_level, task_type):
        lookup_calls.append((data_type, aggregation_level, task_type))
        if len(lookup_calls) == 1:
            return None
        return existing

    async def _fake_create(*_args, **_kwargs):
        raise IntegrityError("insert into data_groups", {}, Exception("duplicate key"))

    monkeypatch.setattr(
        DataGroupRepository,
        "get_by_combination",
        staticmethod(_fake_get_by_combination),
    )
    monkeypatch.setattr(
        DataGroupRepository,
        "create",
        staticmethod(_fake_create),
    )

    result = await DataGroupRepository.get_or_create(
        _DummyDB(),
        data_type="wsi",
        aggregation_level="case",
        task_type="wsi_classification",
    )

    assert result is existing
    assert lookup_calls == [
        ("wsi", "case", "wsi_classification"),
        ("wsi", "case", "wsi_classification"),
    ]


@pytest.mark.asyncio
async def test_get_or_create_rejects_invalid_axes_before_storing(monkeypatch):
    create_called = False

    async def _fake_create(*_args, **_kwargs):
        nonlocal create_called
        create_called = True
        return None

    monkeypatch.setattr(
        DataGroupRepository,
        "create",
        staticmethod(_fake_create),
    )

    with pytest.raises(ValueError, match="unsupported aggregation_level"):
        await DataGroupRepository.get_or_create(
            _DummyDB(),
            data_type="patch",
            aggregation_level="case",
            task_type="patch_segmentation",
        )

    assert create_called is False


@pytest.mark.asyncio
async def test_get_or_create_rejects_legacy_task_type_before_storing(monkeypatch):
    create_called = False

    async def _fake_create(*_args, **_kwargs):
        nonlocal create_called
        create_called = True
        return None

    monkeypatch.setattr(
        DataGroupRepository,
        "create",
        staticmethod(_fake_create),
    )

    with pytest.raises(ValueError, match="got: classification"):
        await DataGroupRepository.get_or_create(
            _DummyDB(),
            data_type="wsi",
            aggregation_level="file",
            task_type="classification",
        )

    assert create_called is False
