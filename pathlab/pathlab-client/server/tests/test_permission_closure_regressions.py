import types

import pytest

from gateway.routes.results import _has_external_validation_dataset_access
from gateway.routes.storage_tasks import _build_batch_import_task_params
from gateway.routes.training import _has_wsi_training_access
from gateway.routes.wsi_upload import upload_wsi_by_path


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


def test_build_batch_import_task_params_keeps_visibility_flags():
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
        is_open_collaboration=True,
    )

    params = _build_batch_import_task_params(
        request=request,
        resolved_files=[{"path": "/tmp/a.svs"}],
        resolved_scan_root="/tmp",
    )

    assert params["is_public"] is True
    assert params["is_open_collaboration"] is True


@pytest.mark.asyncio
async def test_upload_by_path_uses_request_visibility_flags_for_new_dataset(monkeypatch):
    captured = {}

    async def _fake_get_by_id(db, dataset_id):
        return None

    async def _fake_get_or_create_data_group(db, **kwargs):
        return types.SimpleNamespace(
            group_id="group-1",
            data_type=kwargs.get("data_type", "wsi"),
            aggregation_level=kwargs.get("aggregation_level", "file"),
            task_type=kwargs.get("task_type", "classification"),
        )

    async def _fake_get_or_create_dataset(db, dataset_name, **kwargs):
        captured["dataset_name"] = dataset_name
        captured["source_organ"] = kwargs.get("source_organ")
        captured["is_public"] = kwargs.get("is_public")
        captured["is_open_collaboration"] = kwargs.get("is_open_collaboration")
        return types.SimpleNamespace(dataset_id="ds-new", data_group=None)

    async def _fake_align_dataset_data_type_for_file(db, dataset, **kwargs):
        return dataset

    async def _fake_create_wsi(db, wsi_data):
        return types.SimpleNamespace(label=wsi_data.get("label"))

    async def _fake_recompute_dataset_stats(db, dataset_id):
        return None

    monkeypatch.setattr(
        "gateway.routes.wsi_upload.os.path.exists",
        lambda path: True,
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.os.path.getsize",
        lambda path: 123,
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.Path",
        lambda path: types.SimpleNamespace(name="sample.svs", suffix=".svs"),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_id",
        staticmethod(_fake_get_by_id),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.DataGroupRepository.get_or_create",
        staticmethod(_fake_get_or_create_data_group),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.DatasetRepository.get_or_create",
        staticmethod(_fake_get_or_create_dataset),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.align_dataset_data_type_for_file",
        _fake_align_dataset_data_type_for_file,
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.resolve_file_data_type_and_properties",
        lambda path: (
            "wsi",
            {
                "file_size": 123,
                "mpp": None,
                "vendor": None,
                "objective_power": None,
                "magnification": None,
                "width": 100,
                "height": 200,
            },
        ),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.ensure_segmentation_contract",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.DatasetStatsRepository.recompute",
        staticmethod(_fake_recompute_dataset_stats),
    )

        "gateway.routes.wsi_upload.WSIRepository.create",
        staticmethod(_fake_create_wsi),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.uuid.uuid4",
        lambda: "generated-uuid",
    )

    req = types.SimpleNamespace(
        wsi_path="/tmp/sample.svs",
        dataset_id=None,
        dataset_name="new-dataset",
        source_organ="lung",
        aggregation_level="file",
        task_type="classification",
        is_public=True,
        is_open_collaboration=True,
        wsi_id="wsi-1",
        case_id="case-1",
        label="tumor",
        age=None,
        gender=None,
        event_time=None,
        event_status=None,
    )
    user = types.SimpleNamespace(id="user-1")

    response = await upload_wsi_by_path(req, user, object())

    assert response["wsi_id"] == "wsi-1"
    assert captured == {
        "dataset_name": "new-dataset",
        "source_organ": "lung",
        "is_public": True,
        "is_open_collaboration": True,
    }

