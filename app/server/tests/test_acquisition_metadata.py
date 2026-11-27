"""Verify the new-download -> prepared manifest -> Data Repo metadata contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import validate

from backend.autoresearch.dataset import pathlab_registration as registration
from backend.autoresearch.dataset.types import DatasetManifest, DatasetRecord
from backend.autoresearch.engine.acquisition_contract import AcquisitionRecord
from backend.autoresearch.engine.tools import TOOLS


@pytest.fixture
def registry(monkeypatch):
    datasets, slides = {}, {}

    async def group(db, **kwargs):
        return SimpleNamespace(group_id="g", **kwargs)

    async def get_dataset(db, name, user_id=None):
        return datasets.get((user_id, name))

    async def create_dataset(db, **kwargs):
        kwargs['tasks'] = [SimpleNamespace(task_type=task) for task in kwargs['task_types']]
        row = SimpleNamespace(dataset_id="dataset", **kwargs)
        datasets[(kwargs["user_id"], kwargs["name"])] = row
        return row

    async def source_dataset(db, *, user_id, provider, source_id):
        return next(
            (
                row
                for row in datasets.values()
                if row.user_id == user_id
                and (getattr(row, "acquisition_metadata", None) or {}).get("provider")
                == provider
                and row.acquisition_metadata.get("dataset_id") == source_id
            ),
            None,
        )

    async def create_slide(db, **kwargs):
        row = SimpleNamespace(**kwargs)
        slides[kwargs["wsi_id"]] = row
        return row

    monkeypatch.setattr(registration.DataGroupRepository, "get_or_create", group)
    monkeypatch.setattr(registration.DatasetRepository, "get_by_name", get_dataset)
    monkeypatch.setattr(
        registration.DatasetRepository, "get_by_acquisition", source_dataset
    )
    monkeypatch.setattr(registration.DatasetRepository, "get_or_create", create_dataset)
    monkeypatch.setattr(
        registration.WSIRepository,
        "get_by_id",
        AsyncMock(side_effect=lambda db, key: slides.get(key)),
    )
    monkeypatch.setattr(registration.WSIRepository, "create", create_slide)
    monkeypatch.setattr(registration.DatasetStatsRepository, "recompute", AsyncMock())
    return datasets, slides


@pytest.mark.parametrize(
    "provider,access,visibility,expected",
    [
        ("direct_http", "public", None, True),
        ("dataverse", "public", None, True),
        ("huggingface", "gated", None, False),
        ("zenodo", "public", "private", False),
    ],
)
async def test_registration_retains_metadata_for_all_providers(
    registry, tmp_path, provider, access, visibility, expected
):
    (tmp_path / "slide.svs").write_bytes(b"test")
    labels = tmp_path / "labels.csv"
    labels.write_text("slide_id,label,case_id\nslide,A,patient-1\n")
    manifest = DatasetManifest(
        dataset_id="doi:source",
        provider=provider,
        selected_for_task="wsi_classification",
        raw_root=str(tmp_path),
        prepared_root="",
        data_mounts={},
        prepared_contract={"labels_file": str(labels)},
        access=access,
        status="prepared",
        metadata={
            "name": "A new cohort",
            "organs": ["Lung", "Liver"],
            "license": "CC-BY-4.0",
            "source_url": "https://data.example/dataset",
            "description": "Author supplied description",
            "visibility": visibility,
            "aggregation_level": "case",
        },
    )
    result = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    dataset = next(iter(registry[0].values()))
    slide = next(iter(registry[1].values()))
    assert dataset.source_organ == "Lung; Liver" and dataset.is_public is expected
    assert dataset.acquisition_metadata["dataset_id"] == "doi:source"
    assert dataset.acquisition_metadata["license"] == "CC-BY-4.0"
    assert slide.case_id == "patient-1" and slide.source == "Lung; Liver"
    assert result["metadata_complete"] and result["label_count"] == 1
    assert not result["training_ready"]  # One-class data is not classification-ready.
    again = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    assert again["created_wsi_count"] == 0 and len(registry[1]) == 1


async def test_unknown_metadata_and_missing_labels_are_explicit(registry, tmp_path):
    (tmp_path / "slide.svs").write_bytes(b"test")
    manifest = DatasetManifest(
        "source",
        "direct_http",
        "wsi_classification",
        str(tmp_path),
        "",
        {},
        {},
        status="prepared",
        metadata={
            "organs": ["Unknown"],
            "license": "Unknown",
            "source_url": "https://data.example/source",
            "aggregation_level": "case",
        },
    )
    result = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    assert not result["metadata_complete"] and set(result["missing_metadata"]) == {
        "organs",
        "license",
    }
    assert (
        not result["training_ready"] and result["missing_annotations"]["case_ids"] == 1
    )
    assert next(iter(registry[1].values())).case_id is None


async def test_survival_columns_preserve_censoring_zero(registry, tmp_path):
    (tmp_path / "slide.svs").write_bytes(b"test")
    table = tmp_path / "clinical.csv"
    table.write_text("image,patient,days,event\nslide.svs,patient-2,45.5,0\n")
    manifest = DatasetManifest(
        "source",
        "direct_http",
        "wsi_survival",
        str(tmp_path),
        "",
        {},
        {"labels_file": str(table)},
        status="prepared",
        metadata={
            "organs": ["Breast"],
            "license": "CC0",
            "source_url": "https://data.example",
            "aggregation_level": "case",
            "annotation_columns": {
                "slide_id": "image",
                "case_id": "patient",
                "event_time": "days",
                "event_status": "event",
            },
        },
    )
    result = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    slide = next(iter(registry[1].values()))
    assert (
        slide.event_time == 45.5
        and slide.event_status == 0
        and result["task_type"] == "wsi_survival"
    )
    assert result["training_ready"]
    # A corrected censoring/time remains authoritative when a source is re-imported.
    slide.event_time = 0.0
    table.write_text("image,patient,days,event\nslide.svs,patient-2,,\n")
    again = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    assert again["training_ready"] and slide.event_time == 0 and slide.event_status == 0


async def test_reimport_preserves_manual_metadata_and_source_identity(
    registry, tmp_path
):
    (tmp_path / "slide.svs").write_bytes(b"fixture")
    manifest = DatasetManifest(
        "source",
        "direct_http",
        "wsi_classification",
        str(tmp_path),
        "",
        {},
        {},
        status="prepared",
        access="public",
        metadata={
            "name": "Original",
            "organs": ["Lung"],
            "license": "CC0",
            "source_url": "https://example.org",
        },
    )
    await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    row = next(iter(registry[0].values()))
    row.source_organ, row.is_public, row.description = (
        "Kidney",
        False,
        "Manually verified description",
    )
    manifest.metadata.update(
        name="Source renamed", organs=["Unknown"], license="Unknown"
    )
    receipt = await registration.register_manifest_with_pathlab(
        db=None, manifest=manifest, session_id="s", user_id="owner"
    )
    assert len(registry[0]) == 1 and receipt["created_wsi_count"] == 0
    assert (
        row.source_organ == "Kidney"
        and not row.is_public
        and row.description == "Manually verified description"
    )
    assert row.acquisition_metadata["license"] == "CC0"


async def test_registration_rejects_patient_split_leakage(registry, tmp_path):
    import json

    for name in ["a", "b"]:
        (tmp_path / f"{name}.svs").write_bytes(b"fixture")
    table = tmp_path / "labels.csv"
    table.write_text("slide_id,label,case_id\na,A,p1\nb,A,p1\n")
    splits = tmp_path / "splits.json"
    splits.write_text(json.dumps({"train": ["a"], "test": ["b"]}))
    manifest = DatasetManifest(
        "source",
        "direct_http",
        "wsi_classification",
        str(tmp_path),
        "",
        {},
        {"labels_file": str(table), "splits_file": str(splits)},
        status="prepared",
        metadata={"aggregation_level": "case"},
    )
    with pytest.raises(ValueError, match="Inconsistent split"):
        await registration.register_manifest_with_pathlab(
            db=None, manifest=manifest, session_id="s", user_id="owner"
        )


def test_acquire_tool_schema_requires_full_record_and_nested_refs_resolve():
    tool = next(t for t in TOOLS if t["name"] == "acquire_dataset")
    record = {
        "dataset_id": "doi:test",
        "name": "test",
        "provider": "dataverse",
        "access": "public",
        "task_types": ["wsi_classification"],
        "asset_types": ["wsi"],
        "organs": ["Lung"],
        "license": "CC0",
        "source_url": "https://data.example/source",
        "download": {"kind": "dataverse", "remote_id": "doi:test"},
    }
    validate({"record": record}, tool["inputSchema"])
    parsed = DatasetRecord.from_dict(
        AcquisitionRecord.model_validate(record).model_dump()
    )
    assert parsed.organs == ["Lung"] and parsed.source_url == record["source_url"]
    del record["organs"]
    with pytest.raises(ValueError):
        AcquisitionRecord.model_validate(record)


async def test_acquire_downloads_prepares_registers_and_attaches_metadata(
    tmp_path, monkeypatch, registry
):
    from contextlib import asynccontextmanager

    from backend.autoresearch.dataset.providers.base import DownloadResult
    from backend.autoresearch.engine import datasets

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "downloads").mkdir()
    session = SimpleNamespace(
        user_id="owner",
        workspace_path=str(workspace),
        recovery_metadata={"allow_downloads": True},
    )
    monkeypatch.setattr(
        datasets.Config, "get_autoresearch_dir", lambda: tmp_path / "research"
    )
    monkeypatch.setattr(datasets.store, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(datasets.store, "update", AsyncMock())
    prepare = AsyncMock()
    monkeypatch.setattr(datasets, "prepare_dataset", prepare)

    @asynccontextmanager
    async def database():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(datasets, "safe_session", database)

    class Provider:
        def download(self, record, root, progress):
            (root / "a.svs").write_bytes(b"fixture")
            (root / "b.svs").write_bytes(b"fixture")
            (root / "clinical.csv").write_text(
                "slide_id,label,case_id\na,A,patient-a\nb,B,patient-b\n"
            )
            return DownloadResult(
                "downloaded",
                root,
                files=[root / "a.svs", root / "b.svs", root / "clinical.csv"],
            )

    monkeypatch.setattr(
        datasets, "build_default_providers", lambda: {"direct_http": Provider()}
    )
    record = {
        "dataset_id": "official:cohort-v2",
        "name": "New cohort",
        "provider": "direct_http",
        "access": "public",
        "task_types": ["wsi_classification"],
        "asset_types": ["wsi"],
        "organs": ["Kidney"],
        "license": "CC-BY-4.0",
        "source_url": "https://example.org/study",
        "aggregation_level": "case",
        "annotations_file": "clinical.csv",
        "download": {"kind": "direct_http", "urls": ["https://example.org/study.zip"]},
    }
    first = await datasets.acquire("session", record, "download-1")
    second = await datasets.acquire("session", record, "download-2")
    assert (
        first["registration"]["is_public"]
        and first["registration"]["source_organ"] == "Kidney"
    )
    assert (
        first["registration"]["training_ready"]
        and not first["registration"]["split_ready"]
    )
    assert second["cache_hit"] and second["registration"]["created_wsi_count"] == 0
    assert len(registry[1]) == 2 and prepare.await_count == 2
    stored = next(iter(registry[0].values()))
    assert stored.acquisition_metadata["source_url"] == record["source_url"]


def test_dataverse_download_uses_source_metadata_and_checksums(tmp_path, monkeypatch):
    import hashlib

    from backend.autoresearch.dataset.providers import dataverse
    from backend.autoresearch.dataset.types import DownloadSpec

    body = b"fixture image bytes"
    payload = {
        "data": {
            "latestVersion": {
                "license": {"name": "CC0"},
                "metadataBlocks": {
                    "citation": {
                        "fields": [
                            {"typeName": "title", "value": "Official title"},
                            {
                                "typeName": "dsDescription",
                                "value": [
                                    {
                                        "dsDescriptionValue": {
                                            "value": "Source description"
                                        }
                                    }
                                ],
                            },
                        ]
                    }
                },
                "files": [
                    {
                        "dataFile": {
                            "id": 42,
                            "filename": "slide.svs",
                            "filesize": len(body),
                            "checksum": {
                                "type": "SHA-256",
                                "value": hashlib.sha256(body).hexdigest(),
                            },
                        }
                    }
                ],
            }
        }
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def json(self):
            return payload

        def iter_content(self, size):
            yield body

    calls = []

    def fetch(session, url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(dataverse, "guarded_requests_get", fetch)
    record = DatasetRecord(
        "doi:test",
        "draft",
        "dataverse",
        "public",
        ["wsi_classification"],
        ["wsi"],
        organs=["Lung"],
        license="Unknown",
        source_url="https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:test",
        download=DownloadSpec(kind="dataverse", remote_id="doi:test"),
    )
    result = dataverse.DataverseProvider().download(record, tmp_path)
    assert (
        result.status == "downloaded" and (tmp_path / "slide.svs").read_bytes() == body
    )
    assert (
        record.name == "Official title"
        and record.license == "CC0"
        and record.organs == ["Lung"]
    )
    assert calls[-1] == "https://dataverse.harvard.edu/api/access/datafile/42"
