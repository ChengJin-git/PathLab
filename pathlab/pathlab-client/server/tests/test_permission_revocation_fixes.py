import types

import pytest
import httpx

from backend.ai.permission_revocation import (
    PermissionRevokedException,
    clear_revocation,
    is_permission_revoked,
    revoke_task_permission,
)
from backend.auth.dependencies import check_dataset_gpu_permission
from backend.database.repositories.dataset_grant import DatasetGrantRepository


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value


class _DB:
    def __init__(self, value=None):
        self._value = value

    async def execute(self, _stmt):
        return _Result(self._value)

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeHttpClient:
    def __init__(self, *, raise_exc=None):
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def post(self, *_args, **_kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return types.SimpleNamespace(status_code=200)


@pytest.mark.asyncio
async def test_gpu_permission_reaches_has_valid_gpu_when_can_use_gpu_false(monkeypatch):
    called = {"count": 0}

    async def _has_valid_gpu(_db, _dataset_id, _user_id):
        called["count"] += 1
        return True

    monkeypatch.setattr(
        DatasetGrantRepository, "has_valid_gpu", staticmethod(_has_valid_gpu)
    )

    user = types.SimpleNamespace(id="user-no-gpu", can_use_gpu=lambda: False)

    assert await check_dataset_gpu_permission(user, "ds-1", _DB()) is True
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_gpu_permission_pathologist_never_hits_db(monkeypatch):
    async def _must_not_run(*_args, **_kwargs):
        raise AssertionError("has_valid_gpu must not be called for can_use_gpu() users")

    monkeypatch.setattr(
        DatasetGrantRepository, "has_valid_gpu", staticmethod(_must_not_run)
    )

    user = types.SimpleNamespace(id="pathologist-1", can_use_gpu=lambda: True)

    assert await check_dataset_gpu_permission(user, "ds-1", _DB()) is True


@pytest.mark.asyncio
async def test_gpu_permission_denied_when_no_grant_and_can_use_gpu_false(monkeypatch):
    async def _no_gpu(_db, _dataset_id, _user_id):
        return False

    monkeypatch.setattr(DatasetGrantRepository, "has_valid_gpu", staticmethod(_no_gpu))

    user = types.SimpleNamespace(id="user-denied", can_use_gpu=lambda: False)

    assert await check_dataset_gpu_permission(user, "ds-1", _DB()) is False


@pytest.mark.asyncio
async def test_notify_revocation_marks_task_revoked_in_process(monkeypatch):
    task_id = "task-local-revoke-1"

    monkeypatch.setattr(
        "gateway.routes.wsi_grants.httpx.AsyncClient",
        lambda **_kw: _FakeHttpClient(),
    )

    clear_revocation(task_id)
    assert not is_permission_revoked(task_id)

    from gateway.routes.wsi_grants import _notify_ai_service_permission_revocation

    await _notify_ai_service_permission_revocation([task_id])

    assert is_permission_revoked(task_id)

    clear_revocation(task_id)


@pytest.mark.asyncio
async def test_notify_revocation_marks_task_even_when_http_fails(monkeypatch):
    task_id = "task-http-fail-1"

    monkeypatch.setattr(
        "gateway.routes.wsi_grants.httpx.AsyncClient",
        lambda **_kw: _FakeHttpClient(
            raise_exc=httpx.ConnectError("connection refused")
        ),
    )

    clear_revocation(task_id)
    assert not is_permission_revoked(task_id)

    from gateway.routes.wsi_grants import _notify_ai_service_permission_revocation

    revoked = await _notify_ai_service_permission_revocation([task_id])

    assert is_permission_revoked(task_id)
    assert task_id not in revoked

    clear_revocation(task_id)


@pytest.mark.asyncio
async def test_run_task_analysis_raises_403_when_dataset_access_revoked(monkeypatch):
    from fastapi import HTTPException
    from gateway.routes.results import run_task_analysis

    task_id = "task-revoked-ds-1"
    dataset_id = "ds-revoked-1"

    async def _fake_get_task(_task_id, _user, _db, **_kw):
        return types.SimpleNamespace(task_id=_task_id, data_group=None), dataset_id

    monkeypatch.setattr("gateway.routes.results._get_task_with_access", _fake_get_task)

    async def _private_dataset(_db, _dataset_id):
        return types.SimpleNamespace(
            dataset_id=_dataset_id,
            user_id="other-owner",
            is_public=False,
            parent_dataset_id=None,
        )

    monkeypatch.setattr(
        "gateway.routes.results.DatasetRepository.get_by_id",
        staticmethod(_private_dataset),
    )

    async def _deny_access(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        "gateway.routes.results.check_dataset_access_permission", _deny_access
    )

    user = types.SimpleNamespace(
        id="pathologist-1", is_admin=lambda: False, can_use_gpu=lambda: True
    )

    with pytest.raises(HTTPException) as exc_info:
        await run_task_analysis(
            task_id=task_id,
            request=types.SimpleNamespace(metrics=[], charts=[]),
            user=user,
            db=_DB(),
        )

    assert exc_info.value.status_code == 403
    assert "revoked" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_run_task_analysis_admin_skips_dataset_access_check(monkeypatch):
    from gateway.routes.results import run_task_analysis

    class _Sentinel(Exception):
        pass

    task_id = "task-admin-bypass"
    dataset_id = "ds-admin-1"

    async def _fake_get_task(_task_id, _user, _db, **_kw):
        return (
            types.SimpleNamespace(
                task_id=_task_id,
                data_group=types.SimpleNamespace(task_type="wsi_classification"),
            ),
            dataset_id,
        )

    monkeypatch.setattr("gateway.routes.results._get_task_with_access", _fake_get_task)

    async def _must_not_run(*_args, **_kwargs):
        raise AssertionError("check_dataset_access_permission must not run for admin")

    monkeypatch.setattr(
        "gateway.routes.results.check_dataset_access_permission", _must_not_run
    )

    async def _sentinel_gpu(*_args, **_kw):
        raise _Sentinel("reached expected post-guard checkpoint")

    monkeypatch.setattr(
        "gateway.routes.results._require_task_gpu_permission", _sentinel_gpu
    )

    user = types.SimpleNamespace(id="admin-1", is_admin=lambda: True)

    with pytest.raises(_Sentinel):
        await run_task_analysis(
            task_id=task_id,
            request=types.SimpleNamespace(metrics=[], charts=[]),
            user=user,
            db=_DB(),
        )


def test_revoke_marks_task_and_clear_removes_it():
    task_id = "lifecycle-task-1"
    clear_revocation(task_id)
    assert not is_permission_revoked(task_id)
    revoke_task_permission(task_id)
    assert is_permission_revoked(task_id)
    clear_revocation(task_id)
    assert not is_permission_revoked(task_id)


def test_revoke_affects_only_named_task():
    t1, t2 = "multi-task-a", "multi-task-b"
    clear_revocation(t1)
    clear_revocation(t2)
    revoke_task_permission(t1)
    assert is_permission_revoked(t1)
    assert not is_permission_revoked(t2)
    clear_revocation(t1)


def test_clear_revocation_is_idempotent():
    task_id = "idempotent-task-1"
    clear_revocation(task_id)
    clear_revocation(task_id)
    revoke_task_permission(task_id)
    clear_revocation(task_id)
    clear_revocation(task_id)
    assert not is_permission_revoked(task_id)


def test_permission_revoked_exception_is_exception_subclass():
    exc = PermissionRevokedException("task revoked")
    assert isinstance(exc, Exception)
    assert "revoked" in str(exc)
