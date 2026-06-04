import types
from typing import cast

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User
from backend.database.repositories.wsi import (
    WSIRepository,
    _canonical_task_type_for_response,
)
from gateway.models import UploadByPathRequest
from gateway.routes import wsi as wsi_routes
from gateway.routes.wsi_upload import (
    _resolve_task_type_for_axes,
    get_csv_template,
    upload_wsi_by_path,
)
from backend.database.migrate_task_taxonomy import LEGACY_TO_CANONICAL
from helpers import _make_user


def _wsi_props(file_size: int = 123) -> dict[str, object]:
    return {
        "file_size": file_size,
        "mpp": None,
        "vendor": None,
        "objective_power": None,
        "magnification": None,
        "width": 100,
        "height": 200,
    }


@pytest.mark.asyncio
async def test_upload_by_path_maps_wsi_classification_to_canonical_task_type(
    monkeypatch,
):
    captured: dict[str, str] = {}

    async def _fake_get_or_create_data_group(db, **kwargs):
        captured.update(
            {
                "task_type": kwargs["task_type"],
                "data_type": kwargs["data_type"],
                "aggregation_level": kwargs["aggregation_level"],
            }
        )
        return types.SimpleNamespace(
            group_id="group-wsi",
            data_type=kwargs["data_type"],
            aggregation_level=kwargs["aggregation_level"],
            task_type=kwargs["task_type"],
        )

    async def _fake_get_or_create_dataset(db, dataset_name, **kwargs):
        return types.SimpleNamespace(dataset_id="ds-wsi", data_group=None)

    async def _fake_align_dataset_data_type_for_file(db, dataset, **kwargs):
        return dataset

    async def _fake_create_wsi(db, **kwargs):
        return types.SimpleNamespace(label=kwargs.get("label"))

    async def _fake_recompute_dataset_stats(db, dataset_id):
        return None

    async def _fake_get_by_filename_in_dataset(db, dataset_id, filename):
        return None

    async def _fake_get_by_id(db, wsi_id):
        return None

    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.exists", lambda path: True)
    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.getsize", lambda path: 123)
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.resolve_file_data_type_and_properties",
        lambda path: ("wsi", _wsi_props()),
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
        "gateway.routes.wsi_upload.WSIRepository.create",
        staticmethod(_fake_create_wsi),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.DatasetStatsRepository.recompute",
        staticmethod(_fake_recompute_dataset_stats),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_filename_in_dataset",
        staticmethod(_fake_get_by_filename_in_dataset),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_id",
        staticmethod(_fake_get_by_id),
    )

    req = UploadByPathRequest(
        wsi_path="/tmp/sample.svs",
        dataset_id=None,
        dataset_name="new-dataset",
        source_organ="lung",
        aggregation_level="case",
        task_type="wsi_classification",
        is_public=False,
        wsi_id="wsi-1",
        case_id="case-1",
        label="tumor",
        age=None,
        gender=None,
        event_time=None,
        event_status=None,
    )

    async def _noop():
        pass

    db_mock = types.SimpleNamespace(commit=_noop, rollback=_noop)
    await upload_wsi_by_path(
        req, cast(User, _make_user()), cast(AsyncSession, cast(object, db_mock))
    )

    assert captured == {
        "task_type": "wsi_classification",
        "data_type": "wsi",
        "aggregation_level": "case",
    }


@pytest.mark.asyncio
async def test_upload_by_path_maps_patch_classification_to_canonical_task_type(
    monkeypatch,
):
    captured: dict[str, str] = {}

    async def _fake_get_or_create_data_group(db, **kwargs):
        captured.update(
            {
                "task_type": kwargs["task_type"],
                "data_type": kwargs["data_type"],
                "aggregation_level": kwargs["aggregation_level"],
            }
        )
        return types.SimpleNamespace(
            group_id="group-patch",
            data_type=kwargs["data_type"],
            aggregation_level=kwargs["aggregation_level"],
            task_type=kwargs["task_type"],
        )

    async def _fake_get_or_create_dataset(db, dataset_name, **kwargs):
        return types.SimpleNamespace(dataset_id="ds-patch", data_group=None)

    async def _fake_align_dataset_data_type_for_file(db, dataset, **kwargs):
        return dataset

    async def _fake_create_wsi(db, **kwargs):
        return types.SimpleNamespace(label=kwargs.get("label"))

    async def _fake_recompute_dataset_stats(db, dataset_id):
        return None

    async def _fake_get_by_filename_in_dataset(db, dataset_id, filename):
        return None

    async def _fake_get_by_id(db, wsi_id):
        return None

    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.exists", lambda path: True)
    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.getsize", lambda path: 456)
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.resolve_file_data_type_and_properties",
        lambda path: ("patch", _wsi_props(file_size=456)),
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
        "gateway.routes.wsi_upload.WSIRepository.create",
        staticmethod(_fake_create_wsi),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.DatasetStatsRepository.recompute",
        staticmethod(_fake_recompute_dataset_stats),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_filename_in_dataset",
        staticmethod(_fake_get_by_filename_in_dataset),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_id",
        staticmethod(_fake_get_by_id),
    )

    req = UploadByPathRequest(
        wsi_path="/tmp/sample.png",
        dataset_id=None,
        dataset_name="new-patch-dataset",
        source_organ="lung",
        aggregation_level="file",
        task_type="patch_classification",
        is_public=False,
        wsi_id="patch-1",
        case_id="case-1",
        label="tumor",
        age=None,
        gender=None,
        event_time=None,
        event_status=None,
    )

    async def _noop():
        pass

    db_mock = types.SimpleNamespace(commit=_noop, rollback=_noop)
    await upload_wsi_by_path(
        req, cast(User, _make_user()), cast(AsyncSession, cast(object, db_mock))
    )

    assert captured == {
        "task_type": "patch_classification",
        "data_type": "patch",
        "aggregation_level": "file",
    }


@pytest.mark.asyncio
async def test_upload_by_path_rejects_patch_segmentation_case_aggregation(monkeypatch):
    async def _fake_get_by_id(db, wsi_id):
        return None

    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.exists", lambda path: True)
    monkeypatch.setattr("gateway.routes.wsi_upload.os.path.getsize", lambda path: 456)
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.resolve_file_data_type_and_properties",
        lambda path: ("patch", _wsi_props(file_size=456)),
    )
    monkeypatch.setattr(
        "gateway.routes.wsi_upload.WSIRepository.get_by_id",
        staticmethod(_fake_get_by_id),
    )

    with pytest.raises(ValidationError, match="unsupported aggregation_level"):
        UploadByPathRequest(
            wsi_path="/tmp/sample.png",
            dataset_id=None,
            dataset_name="seg-dataset",
            source_organ="lung",
            aggregation_level="case",
            task_type="patch_segmentation",
            is_public=False,
            wsi_id="seg-1",
            case_id="case-1",
            label=None,
            age=None,
            gender=None,
            event_time=None,
            event_status=None,
        )


def test_wsi_repository_filter_canonicalizes_segmentation_task_type():
    query = WSIRepository._build_dataset_summary_query(task_type="patch_segmentation")
    compiled = query.compile()
    params = compiled.params

    assert params.get("task_type_1") == "patch_segmentation"


def test_wsi_repository_filter_canonicalizes_classification_with_data_type():
    query = WSIRepository._build_dataset_summary_query(
        task_type="wsi_classification", data_type="wsi"
    )
    compiled = query.compile()
    params = compiled.params

    assert params.get("task_type_1") == "wsi_classification"


@pytest.mark.asyncio
async def test_csv_template_accepts_canonical_patch_segmentation_task_type():
    response = await get_csv_template(task_type="patch_segmentation", user=cast(User, _make_user()))

    content_disposition = response.headers["content-disposition"]
    assert "segmentation_metadata_template.csv" in content_disposition


@pytest.mark.asyncio
async def test_csv_template_accepts_canonical_patch_classification_task_type():
    response = await get_csv_template(task_type="patch_classification", user=cast(User, _make_user()))

    content_disposition = response.headers["content-disposition"]
    assert "patch_classification_metadata_template.csv" in content_disposition


@pytest.mark.asyncio
async def test_csv_template_default_uses_canonical_wsi_classification_task_type():
    response = await get_csv_template(user=cast(User, _make_user()))

    content_disposition = response.headers["content-disposition"]
    assert "wsi_classification_metadata_template.csv" in content_disposition


def test_wsi_repository_response_default_uses_patch_data_type_for_missing_task_type():
    assert _canonical_task_type_for_response(None, "patch") == "patch_classification"


def test_wsi_repository_response_uses_row_data_type():
    # When task_type is canonical but data_type doesn't match, it should return the canonical id as-is
    assert _canonical_task_type_for_response("wsi_classification", "patch") == "wsi_classification"


def test_upload_resolver_maps_default_classification_to_patch_classification():
    assert (
        _resolve_task_type_for_axes(
            "wsi_classification",
            data_type="patch",
            aggregation_level="file",
        )
        == "patch_classification"
    )


@pytest.mark.parametrize(
    ("task_type", "data_type", "aggregation_level"),
    [
        ("wsi_classification", "wsi", "case"),
        ("patch_classification", "patch", "file"),
        ("wsi_survival", "wsi", "case"),
        ("patch_segmentation", "patch", "file"),
    ],
)
def test_upload_resolver_accepts_all_canonical_task_terms(task_type, data_type, aggregation_level):
    assert (
        _resolve_task_type_for_axes(
            task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )
        == task_type
    )


def test_export_fieldnames_use_survival_columns_for_canonical_wsi_survival():
    fieldnames = wsi_routes._build_export_fieldnames("wsi_survival")

    assert "event_time" in fieldnames
    assert "event_status" in fieldnames
    assert "label" not in fieldnames


def test_export_row_uses_survival_metadata_for_canonical_wsi_survival():
    row = wsi_routes._build_export_row(
        types.SimpleNamespace(
            original_filename="slide.svs",
            case_id="case-1",
            age=61,
            gender="F",
            label="tumor",
            event_time=12.5,
            event_status=1,
        ),
        "wsi_survival",
        "train",
    )

    assert row["event_time"] == 12.5
    assert row["event_status"] == 1
    assert "label" not in row


def test_split_assignment_uses_event_status_labels_for_canonical_wsi_survival(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_generate_split_assignments(_wsis, **kwargs):
        captured.update(kwargs)
        return {"wsi-1": "train", "wsi-2": "val"}, False

    monkeypatch.setattr(wsi_routes, "generate_split_assignments", _fake_generate_split_assignments)

    assignments, fallback = wsi_routes._generate_split_assignments(
        [
            types.SimpleNamespace(wsi_id="wsi-1", event_status=1, label="A"),
            types.SimpleNamespace(wsi_id="wsi-2", event_status=0, label="B"),
        ],
        dataset_id="dataset-1",
        aggregation_level="file",
        task_type="wsi_survival",
        strategy="random",
        n_splits=5,
        seed=42,
        stratified=True,
        train_ratio=0.7,
        val_ratio=0.1,
        test_ratio=0.2,
        segmentation_multilabels={},
    )

    assert assignments == {"wsi-1": "train", "wsi-2": "val"}
    assert fallback is False
    assert captured["task_type"] == "survival"
    assert captured["split_config"]["stratified"] is True


def test_update_dataset_type_request_rejects_invalid_task_type():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        wsi_routes.DatasetUpdateTypeRequest(
            dataset_id="ds-1",
            task_type="invalid_task_type",
        )


def test_wsi_csv_template_accepts_wsi_survival():
    from gateway.routes.wsi_upload import get_csv_template
    import asyncio

    async def _run():
        response = await get_csv_template(
            task_type="wsi_survival", user=cast(User, _make_user())
        )
        return response

    response = asyncio.run(_run())
    assert "survival_metadata_template.csv" in response.headers["content-disposition"]


@pytest.mark.parametrize("legacy_task_type", ["classification", "survival", "segmentation"])
def test_wsi_csv_template_rejects_legacy_task_types(legacy_task_type):
    from gateway.routes.wsi_upload import get_csv_template
    import asyncio

    async def _run():
        with pytest.raises(ValueError, match=f"got: {legacy_task_type}"):
            await get_csv_template(
                task_type=legacy_task_type, user=cast(User, _make_user())
            )

    asyncio.run(_run())


def test_task_taxonomy_migration_maps_legacy_data_groups_to_canonical_ids():
    assert LEGACY_TO_CANONICAL[("classification", "wsi", "case")] == "wsi_classification"
    assert LEGACY_TO_CANONICAL[("classification", "wsi", "file")] == "wsi_classification"
    assert LEGACY_TO_CANONICAL[("classification", "patch", "file")] == "patch_classification"
    assert LEGACY_TO_CANONICAL[("survival", "wsi", "case")] == "wsi_survival"
    assert LEGACY_TO_CANONICAL[("survival", "wsi", "file")] == "wsi_survival"
    assert LEGACY_TO_CANONICAL[("segmentation", "patch", "file")] == "patch_segmentation"


def test_task_taxonomy_migration_marks_invalid_legacy_groups_for_cleanup():
    assert LEGACY_TO_CANONICAL[("classification", "patch", "case")] is None
    assert LEGACY_TO_CANONICAL[("survival", "patch", "file")] is None
