"""Tests for DatasetRegistry JSON persistence + filtering."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset.registry import DatasetRegistry
from dataset.types import DatasetRecord, DownloadSpec


def _rec(dataset_id: str, task_types, organs, asset_types=None) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        name=dataset_id,
        provider="huggingface",
        access="public",
        task_types=list(task_types),
        asset_types=list(asset_types or ["patch_images"]),
        organs=list(organs),
        license="CC-BY-4.0",
        estimated_size_gb=1.0,
        tags=[],
        source_paper_ids=[],
        download=DownloadSpec(kind="hf_dataset", remote_id=dataset_id),
    )


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    return tmp_path / "registry.json"


@pytest.fixture
def populated_registry(registry_path: Path) -> DatasetRegistry:
    reg = DatasetRegistry(registry_path)
    reg.save([
        _rec("a", ["patch_classification"], ["colorectal"]),
        _rec("b", ["patch_classification"], ["breast"]),
        _rec("c", ["mil_classification"], ["breast"], asset_types=["wsi"]),
        _rec("d", ["segmentation"], ["lung"], asset_types=["wsi"]),
    ])
    return reg


def test_missing_file_yields_empty_list(registry_path: Path):
    reg = DatasetRegistry(registry_path)
    assert reg.load() == []
    assert reg.list_all() == []


def test_corrupted_json_yields_empty_list(registry_path: Path):
    registry_path.write_text("{{ not json")
    reg = DatasetRegistry(registry_path)
    assert reg.load() == []


def test_save_then_load_roundtrip(registry_path: Path):
    reg = DatasetRegistry(registry_path)
    records = [
        _rec("a", ["patch_classification"], ["colorectal"]),
        _rec("b", ["mil_classification"], ["breast"], asset_types=["wsi"]),
    ]
    reg.save(records)
    loaded = reg.load()
    assert loaded == records


def test_find_filter_by_task_type(populated_registry: DatasetRegistry):
    out = populated_registry.find(task_type="patch_classification")
    ids = sorted(r.dataset_id for r in out)
    assert ids == ["a", "b"]


def test_find_filter_by_organ(populated_registry: DatasetRegistry):
    out = populated_registry.find(organ="breast")
    ids = sorted(r.dataset_id for r in out)
    assert ids == ["b", "c"]


def test_find_filter_combined(populated_registry: DatasetRegistry):
    out = populated_registry.find(task_type="patch_classification", organ="breast")
    ids = sorted(r.dataset_id for r in out)
    assert ids == ["b"]


def test_find_filter_asset_type(populated_registry: DatasetRegistry):
    out = populated_registry.find(asset_type="wsi")
    ids = sorted(r.dataset_id for r in out)
    assert ids == ["c", "d"]


def test_find_case_insensitive(populated_registry: DatasetRegistry):
    out = populated_registry.find(task_type="PATCH_CLASSIFICATION", organ="Colorectal")
    ids = sorted(r.dataset_id for r in out)
    assert ids == ["a"]


def test_find_no_match_returns_empty(populated_registry: DatasetRegistry):
    assert populated_registry.find(task_type="nonexistent_task") == []
    assert populated_registry.find(organ="heart") == []


def test_find_no_filters_returns_all(populated_registry: DatasetRegistry):
    out = populated_registry.find()
    assert len(out) == 4


def test_seed_from_json_copies_records(tmp_path: Path):
    seed = tmp_path / "seed.json"
    rec = _rec("seeded", ["patch_classification"], ["colorectal"])
    seed.write_text(json.dumps([rec.to_dict()]))
    reg_path = tmp_path / "sub" / "registry.json"
    reg = DatasetRegistry(reg_path)
    count = reg.seed_from_json(seed)
    assert count == 1
    assert reg.load()[0].dataset_id == "seeded"


def test_seed_from_json_missing_file_returns_zero(tmp_path: Path):
    reg = DatasetRegistry(tmp_path / "registry.json")
    assert reg.seed_from_json(tmp_path / "does-not-exist.json") == 0


def test_real_seed_file_loads():
    seed_path = Path(__file__).resolve().parent.parent / "dataset" / "seed_data" / "pathology_datasets.json"
    assert seed_path.exists(), f"seed file missing: {seed_path}"
    raw = json.loads(seed_path.read_text())
    assert isinstance(raw, list)
    assert len(raw) >= 5
    # Each row must parse cleanly into a DatasetRecord.
    records = [DatasetRecord.from_dict(r) for r in raw]
    assert len(records) == len(raw)
    for r in records:
        assert r.dataset_id
        assert r.name
        assert r.provider
        assert r.access in {"public", "gated", "manual"}


def test_public_direct_http_seed_urls_are_file_like():
    """T0: every direct_http public seed entry must have file-like URLs.
    Landing-page URLs must be reclassified as manual access + manual kind."""
    seed_path = Path(__file__).resolve().parent.parent / "dataset" / "seed_data" / "pathology_datasets.json"
    rows = json.loads(seed_path.read_text())
    records = [DatasetRecord.from_dict(r) for r in rows]
    bad: list[tuple[str, str]] = []
    for r in records:
        if r.access == "public" and r.download.kind == "direct_http":
            for url in r.download.urls:
                stripped = url.lower().split("?", 1)[0]
                if not stripped.endswith((".zip", ".tar", ".tar.gz", ".tgz")):
                    bad.append((r.dataset_id, url))
    assert bad == [], f"Public direct_http seed records must have file-like URLs: {bad}"
