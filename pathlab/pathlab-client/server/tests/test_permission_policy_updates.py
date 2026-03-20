import asyncio
import types

import pytest
from fastapi import HTTPException

from backend.auth.annotation_permissions import can_access_shared
from backend.auth.dependencies import check_dataset_gpu_permission
from backend.database.repositories.annotation import SegmentationAnnotationRepository
from backend.database.repositories.dataset_grant import DatasetGrantRepository
from gateway.routes.wsi_grants import _grant_or_renew_permission


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _DB:
    def __init__(self, value):
        self._value = value

    async def execute(self, _stmt):
        return _Result(self._value)


@pytest.mark.asyncio
async def test_guest_cannot_gain_gpu_access_via_dataset_grant(monkeypatch):
    async def _has_valid_gpu(_db, _dataset_id, _user_id):
        return True

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_gpu",
        staticmethod(_has_valid_gpu),
    )

    guest = types.SimpleNamespace(
        id="guest-1",
        can_use_gpu=lambda: False,
        is_guest=lambda: True,
    )

    allowed = await check_dataset_gpu_permission(guest, "ds-gpu", object())

    assert allowed is False


@pytest.mark.asyncio
async def test_shared_access_requires_explicit_collaborator_even_for_public_dataset(
    monkeypatch,
):
    async def _has_valid_collaborate(_db, _dataset_id, _user_id):
        return False

    monkeypatch.setattr(
        DatasetGrantRepository,
        "has_valid_collaborate",
        staticmethod(_has_valid_collaborate),
    )

    user = types.SimpleNamespace(id="user-1", is_admin=lambda: False)
    dataset = types.SimpleNamespace(
        dataset_id="ds-public",
        user_id="owner-1",
        is_public=True,
        is_open_collaboration=True,
    )

    allowed = await can_access_shared(user, dataset, object())

    assert allowed is False


@pytest.mark.asyncio
async def test_get_with_permission_blocks_non_owner_personal_annotation():
    annotation = types.SimpleNamespace(
        user_id="owner-1",
        status="draft",
        annotation_mode="personal",
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

    assert result is None




def test_upsert_rejects_legacy_inherit_mode():
    with pytest.raises(ValueError, match="legacy 'inherit' mode has been removed"):
        async def _run():
            await SegmentationAnnotationRepository.upsert(
                db=object(),
                annotation_id="annot-legacy",
                user_id="owner-1",
                annotations={},
                annotation_mode="inherit",
            )

        asyncio.run(_run())



@pytest.mark.asyncio
async def test_grant_or_renew_permission_rejects_guest_gpu_grant(monkeypatch):
    class _GrantDB:
        async def execute(self, _stmt):
            return _Result(types.SimpleNamespace(id='guest-1', role='guest'))

        async def flush(self):
            return None

    monkeypatch.setattr(
        DatasetGrantRepository,
        'get_by_dataset_and_user',
        staticmethod(lambda *_args, **_kwargs: asyncio.sleep(0, result=None)),
    )

    with pytest.raises(HTTPException, match='Guest users cannot be granted GPU permission'):
        await _grant_or_renew_permission(
            db=_GrantDB(),
            dataset_id='ds-1',
            user_id='guest-1',
            granted_by='admin-1',
            can_use_gpu=True,
        )


@pytest.mark.asyncio
async def test_upsert_accepts_annotation_mode_alias_for_personal():
    class _InsertResult:
        def scalar_one(self):
            return 1

    class _SelectResult:
        def scalar_one(self):
            return types.SimpleNamespace(annotation_id='annot-alias')

    class _AliasDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, _stmt):
            self.calls += 1
            if self.calls == 1:
                return _Result(None)
            if self.calls == 2:
                return _InsertResult()
            return _SelectResult()

    result = await SegmentationAnnotationRepository.upsert(
        db=_AliasDB(),
        annotation_id='annot-alias',
        user_id='owner-1',
        annotations={},
        annotation_mode='personal',
    )

    assert result.annotation_id == 'annot-alias'



def test_visibility_request_closes_open_collab_when_private():
    from gateway.models import DatasetUpdateVisibilityRequest

    request = DatasetUpdateVisibilityRequest(
        is_public=False,
        is_open_collaboration=True,
    )

    assert request.is_open_collaboration is False


def test_upload_request_closes_open_collab_when_private():
    from gateway.models import UploadByPathRequest

    request = UploadByPathRequest(
        wsi_path='/tmp/sample.svs',
        is_public=False,
        is_open_collaboration=True,
    )

    assert request.is_open_collaboration is False
