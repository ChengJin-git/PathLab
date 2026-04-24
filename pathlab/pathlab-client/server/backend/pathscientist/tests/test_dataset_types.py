"""Tests for dataset domain dataclasses."""
from __future__ import annotations

from dataset.types import (
    DatasetManifest,
    DatasetRecord,
    DownloadSpec,
    TaskProfile,
)


def test_task_profile_roundtrip():
    tp = TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="colorectal",
        dataset_keywords=["nct", "crc"],
        requires_feature_extraction=False,
        preferred_skill="patch_classifier",
    )
    d = tp.to_dict()
    tp2 = TaskProfile.from_dict(d)
    assert tp == tp2


def test_task_profile_from_dict_missing_optional_keys():
    tp = TaskProfile.from_dict({
        "task_type": "segmentation",
        "asset_level": "region",
        "input_modality": "wsi",
        "label_granularity": "pixel",
    })
    assert tp.task_type == "segmentation"
    assert tp.organ == ""
    assert tp.dataset_keywords == []
    assert tp.requires_feature_extraction is False
    assert tp.preferred_skill == ""


def test_download_spec_roundtrip():
    ds = DownloadSpec(
        kind="hf_dataset",
        remote_id="foo/bar",
        urls=["https://example.com/a.zip"],
        filename="a.zip",
        checksum_sha256="deadbeef",
    )
    d = ds.to_dict()
    ds2 = DownloadSpec.from_dict(d)
    assert ds == ds2


def test_download_spec_from_dict_empty():
    ds = DownloadSpec.from_dict({})
    assert ds.kind == ""
    assert ds.remote_id == ""
    assert ds.urls == []
    assert ds.filename == ""
    assert ds.checksum_sha256 == ""


def test_dataset_record_roundtrip():
    rec = DatasetRecord(
        dataset_id="hf:foo/bar",
        name="Foo Bar",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        license="CC-BY-4.0",
        estimated_size_gb=1.5,
        tags=["histology"],
        source_paper_ids=["openalex:W123"],
        download=DownloadSpec(kind="hf_dataset", remote_id="foo/bar"),
    )
    d = rec.to_dict()
    rec2 = DatasetRecord.from_dict(d)
    assert rec == rec2


def test_dataset_record_estimated_size_gb_from_string():
    rec = DatasetRecord.from_dict({
        "dataset_id": "x",
        "name": "X",
        "provider": "huggingface",
        "access": "public",
        "task_types": [],
        "asset_types": [],
        "estimated_size_gb": "3.5",
    })
    assert rec.estimated_size_gb == 3.5
    assert isinstance(rec.estimated_size_gb, float)


def test_dataset_record_missing_download_defaults_empty():
    rec = DatasetRecord.from_dict({
        "dataset_id": "x",
        "name": "X",
        "provider": "huggingface",
        "access": "public",
        "task_types": [],
        "asset_types": [],
    })
    assert isinstance(rec.download, DownloadSpec)
    assert rec.download.kind == ""
    assert rec.download.remote_id == ""
    assert rec.download.urls == []


def test_dataset_manifest_roundtrip_with_mounts_and_contract():
    m = DatasetManifest(
        dataset_id="hf:foo/bar",
        provider="huggingface",
        selected_for_task="patch_classification",
        raw_root="/data/raw/foo",
        prepared_root="/data/prepared/foo",
        data_mounts={"/host/data": "/data"},
        prepared_contract={
            "images_dir": "/data/images",
            "splits_file": "/data/splits.json",
        },
        checksum_sha256="abc123",
        access="public",
        status="prepared",
    )
    d = m.to_dict()
    m2 = DatasetManifest.from_dict(d)
    assert m == m2
    assert m2.data_mounts == {"/host/data": "/data"}
    assert m2.prepared_contract["splits_file"] == "/data/splits.json"
