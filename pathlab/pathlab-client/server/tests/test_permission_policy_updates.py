import asyncio
import types

import pytest
from fastapi import HTTPException

from backend.auth.annotation_permissions import can_access_shared
from backend.auth.dependencies import check_dataset_gpu_permission
from backend.database.repositories.annotation import SegmentationAnnotationRepository
from backend.database.repositories.dataset_grant import DatasetGrantRepository
from gateway.routes.wsi_grants import _grant_or_renew_permission
from gateway.routes.wsi_grants import (
    batch_grant_dataset_grants,
    get_my_dataset_grants,
    grant_dataset_grant,
    update_dataset_visibility,
    BatchGrantDatasetGrantRequest,
)
from gateway.routes.annotation import save_annotation, extract_regions
from gateway.models import AnnotationSaveRequest, AnnotationExtractRequest


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value


class _DB:
    def __init__(self, value):
        self._value = value

    async def execute(self, _stmt):
        return _Result(self._value)

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_guest_cannot_gain_gpu_access_via_dataset_grant(monkeypatch):
    async def _has_valid_gpu(_db, _dataset_id, _user_id):
        return False

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
    guest_uuid = "11111111-1111-1111-1111-111111111111"

    class _GrantDB:
        async def execute(self, _stmt):
            return _Result(types.SimpleNamespace(id=guest_uuid, role="guest"))

        async def flush(self):
            return None

    monkeypatch.setattr(
        DatasetGrantRepository,
        "get_by_dataset_and_user",
        staticmethod(lambda *_args, **_kwargs: asyncio.sleep(0, result=None)),
    )

    with pytest.raises(
        HTTPException, match="Guest users cannot be granted GPU permission"
    ):
        await _grant_or_renew_permission(
            db=_GrantDB(),
            dataset_id="ds-1",
            user_id=guest_uuid,
            granted_by="22222222-2222-2222-2222-222222222222",
            can_use_gpu=True,
        )


@pytest.mark.asyncio
async def test_upsert_accepts_annotation_mode_alias_for_personal():
    class _InsertResult:
        def scalar_one(self):
            return 1

    class _SelectResult:
        def scalar_one(self):
            return types.SimpleNamespace(annotation_id="annot-alias")

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
        annotation_id="annot-alias",
        user_id="owner-1",
        annotations={},
        annotation_mode="personal",
    )

    assert result.annotation_id == "annot-alias"


@pytest.mark.asyncio
async def test_save_annotation_rejects_non_owner_non_admin_personal_draft(monkeypatch):
    async def _dataset_with_access(_dataset_id, _user, _db):
        return types.SimpleNamespace(dataset_id="ds-1", user_id="owner-1")

    monkeypatch.setattr(
        "gateway.routes.annotation._get_dataset_with_access",
        _dataset_with_access,
    )

    req = AnnotationSaveRequest(
        annotation_id="annot-owner-only",
        source_dataset_id="ds-1",
        annotations={},
    )
    user = types.SimpleNamespace(id="viewer-1", is_admin=lambda: False)

    with pytest.raises(
        HTTPException,
        match="Personal annotation is only available to the dataset owner or admin",
    ):
        await save_annotation(
            req, types.SimpleNamespace(add_task=lambda *a, **k: None), user, object()
        )


@pytest.mark.asyncio
async def test_extract_shared_dataset_scope_rejects_non_collaborator(monkeypatch):
    async def _resolve_effective(_dataset_id, _user, _db):
        return {
            "wsis": [types.SimpleNamespace(wsi_id="wsi-1")],
            "gt_annotations": {},
            "effective_annotations": {},
            "draft_annotation": None,
            "draft_annotations": {},
            "gt_record_count": 0,
            "shared_draft": types.SimpleNamespace(annotations={"wsi-1": []}),
        }

    async def _allow_wsi(_wsi_id, _user, _db, **_kwargs):
        return types.SimpleNamespace(wsi_id="wsi-1")

    async def _noop_request(*_args, **_kwargs):
        return None

    async def _noop_set_owner(*_args, **_kwargs):
        return None

    async def _deny_shared(_user, _dataset, _db):
        return False

    async def _dataset_with_access(_dataset_id, _user, _db):
        return types.SimpleNamespace(dataset_id="ds-1", user_id="owner-1")

    class _ExtractDB:
        async def execute(self, _stmt):
            return _Result(None)

        async def commit(self):
            return None

        async def rollback(self):
            return None

    monkeypatch.setattr(
        "gateway.routes.annotation._resolve_effective_dataset_annotations",
        _resolve_effective,
    )
    monkeypatch.setattr(
        "gateway.routes.annotation.get_wsi_with_access",
        _allow_wsi,
    )
    monkeypatch.setattr(
        "gateway.routes.annotation.request_preprocessing_service",
        _noop_request,
    )
    monkeypatch.setattr(
        "gateway.routes.annotation.set_task_owner",
        _noop_set_owner,
    )
    monkeypatch.setattr(
        "gateway.routes.annotation.can_access_shared",
        _deny_shared,
    )
    monkeypatch.setattr(
        "gateway.routes.annotation._get_dataset_with_access",
        _dataset_with_access,
    )

    req = AnnotationExtractRequest(
        dataset_name="derived",
        source_dataset_id="ds-1",
        dataset_scope=True,
        annotation_mode="shared",
    )
    user = types.SimpleNamespace(id="viewer-1", is_admin=lambda: False)

    with pytest.raises(HTTPException, match="Access denied"):
        await extract_regions(req, user, _ExtractDB())


def test_upload_request_defaults_to_private_visibility():
    from gateway.models import UploadByPathRequest

    request = UploadByPathRequest(
        wsi_path="/tmp/sample.svs",
        is_public=False,
    )

    assert request.is_public is False


@pytest.mark.asyncio
async def test_grant_dataset_grant_rejects_public_dataset(monkeypatch):
    async def _dataset_by_id(_db, _dataset_id):
        return types.SimpleNamespace(dataset_id="ds-public", is_public=True)

    monkeypatch.setattr(
        "gateway.routes.wsi_grants.DatasetRepository.get_by_id",
        _dataset_by_id,
    )

    admin_user = types.SimpleNamespace(id="admin-1")

    with pytest.raises(
        HTTPException,
        match="Temporary grants are only available for private datasets",
    ):
        await grant_dataset_grant(
            dataset_id="ds-public",
            user_id="user-1",
            user=admin_user,
            db=_DB(None),
        )


@pytest.mark.asyncio
async def test_batch_grant_dataset_grants_rejects_public_dataset(monkeypatch):
    async def _dataset_by_id(_db, _dataset_id):
        return types.SimpleNamespace(dataset_id="ds-public", is_public=True)

    monkeypatch.setattr(
        "gateway.routes.wsi_grants.DatasetRepository.get_by_id",
        _dataset_by_id,
    )

    admin_user = types.SimpleNamespace(id="admin-1")

    with pytest.raises(
        HTTPException,
        match="Temporary grants are only available for private datasets",
    ):
        await batch_grant_dataset_grants(
            dataset_id="ds-public",
            request=BatchGrantDatasetGrantRequest(user_ids=["user-1"]),
            user=admin_user,
            db=_DB(None),
        )


@pytest.mark.asyncio
async def test_update_visibility_public_revokes_temp_private_grants(monkeypatch):
    calls = {"delete_by_dataset": 0, "update": 0}

    datasets = [
        types.SimpleNamespace(dataset_id="ds-1", user_id="owner-1", is_public=False),
        types.SimpleNamespace(dataset_id="ds-1", user_id="owner-1", is_public=True),
    ]

    async def _dataset_by_id(_db, _dataset_id):
        return datasets.pop(0)

    async def _update(_db, _dataset_id, _updates):
        calls["update"] += 1
        return None

    async def _delete_by_dataset(_db, _dataset_id):
        calls["delete_by_dataset"] += 1
        return 2

    monkeypatch.setattr(
        "gateway.routes.wsi_grants.DatasetRepository.get_by_id",
        _dataset_by_id,
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_grants.DatasetRepository.update",
        _update,
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_grants.DatasetGrantRepository.delete_by_dataset",
        _delete_by_dataset,
    )

    db = _DB(None)
    user = types.SimpleNamespace(id="owner-1", is_admin=lambda: False)
    response = await update_dataset_visibility(
        dataset_id="ds-1",
        request=types.SimpleNamespace(is_public=True),
        user=user,
        db=db,
    )

    assert calls["update"] == 1
    assert calls["delete_by_dataset"] == 1
    assert response["is_public"] is True
    assert response["revoked_dataset_grants"] == 2


@pytest.mark.asyncio
async def test_get_my_dataset_grants_uses_valid_read_grants(monkeypatch):
    class _Grant:
        def __init__(self, dataset_id: str, can_read: bool, can_use_gpu: bool):
            self.dataset_id = dataset_id
            self.can_read = can_read
            self.can_use_gpu = can_use_gpu

        def is_valid(self):
            return True

        def to_dict(self):
            return {
                "dataset_id": self.dataset_id,
                "can_read": self.can_read,
                "can_use_gpu": self.can_use_gpu,
            }

    async def _valid_grants(_db, _user_id):
        return [
            _Grant("read-only", True, False),
            _Grant("gpu-only", False, True),
        ]

    monkeypatch.setattr(
        DatasetGrantRepository,
        "get_valid_by_user",
        staticmethod(_valid_grants),
    )

    response = await get_my_dataset_grants(
        user=types.SimpleNamespace(id="user-1"),
        db=_DB(None),
    )

    assert response["elevated_dataset_ids"] == ["read-only"]
    assert len(response["grants"]) == 1
