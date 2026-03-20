import types

import pytest

from gateway.routes.results import _has_external_validation_dataset_access
from gateway.routes.storage_tasks import _build_batch_import_task_params
from gateway.routes.training import _has_wsi_training_access


@pytest.mark.asyncio
async def test_training_wsi_access_uses_dataset_public_and_parent(monkeypatch):
    captured = {}

    async def _fake_check_wsi_access_permission(
        user,
        wsi_dataset_id,
        wsi_user_id,
        db,
        *,
        dataset_is_public=False,
        parent_dataset_id=None,
    ):
        captured["dataset_is_public"] = dataset_is_public
        captured["parent_dataset_id"] = parent_dataset_id
        captured["dataset_id"] = wsi_dataset_id
        captured["wsi_user_id"] = wsi_user_id
        return True

    monkeypatch.setattr(
        "gateway.routes.training.check_wsi_access_permission",
        _fake_check_wsi_access_permission,
    )

    user = types.SimpleNamespace(is_admin=lambda: False)
    wsi = types.SimpleNamespace(
        dataset_id="ds-1",
        user_id="owner-1",
        dataset=types.SimpleNamespace(is_public=True, parent_dataset_id="parent-1"),
    )

    allowed = await _has_wsi_training_access(user, wsi, object())

    assert allowed is True
    assert captured == {
        "dataset_is_public": True,
        "parent_dataset_id": "parent-1",
        "dataset_id": "ds-1",
        "wsi_user_id": "owner-1",
    }


@pytest.mark.asyncio
async def test_extval_access_uses_unified_dataset_access_check(monkeypatch):
    called = {}

    async def _fake_check_dataset_access_permission(
        user,
        dataset_id,
        dataset_user_id,
        db,
        *,
        is_public=False,
        parent_dataset_id=None,
    ):
        called["dataset_id"] = dataset_id
        called["dataset_user_id"] = dataset_user_id
        called["is_public"] = is_public
        called["parent_dataset_id"] = parent_dataset_id
        return True

    monkeypatch.setattr(
        "gateway.routes.results.check_dataset_access_permission",
        _fake_check_dataset_access_permission,
    )

    user = types.SimpleNamespace(is_admin=lambda: False)
    dataset = types.SimpleNamespace(
        dataset_id="ds-2",
        user_id="owner-2",
        is_public=True,
        parent_dataset_id="root-1",
    )

    allowed = await _has_external_validation_dataset_access(user, dataset, object())

    assert allowed is True
    assert called == {
        "dataset_id": "ds-2",
        "dataset_user_id": "owner-2",
        "is_public": True,
        "parent_dataset_id": "root-1",
    }


def test_build_batch_import_task_params_keeps_is_public_flag():
    request = types.SimpleNamespace(
        dataset_id="existing-ds",
        dataset_name=None,
        source_organ="lung",
        aggregation_level="file",
        task_type="classification",
        default_label="tumor",
        default_event_time=None,
        default_event_status=None,
        is_public=True,
    )

    params = _build_batch_import_task_params(
        request=request,
        resolved_files=[{"path": "/tmp/a.svs"}],
        resolved_scan_root="/tmp",
    )

    assert params["is_public"] is True
