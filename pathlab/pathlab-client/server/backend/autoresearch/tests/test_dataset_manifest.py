from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json

from autoresearch.dataset.manifests import load_manifest, manifest_path_for_workspace, save_manifest
from autoresearch.dataset.types import DatasetManifest


def test_manifest_path_for_workspace(tmp_path):
    assert manifest_path_for_workspace(tmp_path) == tmp_path / ".dataset" / "manifest.json"


def test_save_and_load_manifest_round_trip(tmp_path):
    manifest = DatasetManifest(
        dataset_id="hf:demo/x",
        provider="huggingface",
        selected_for_task="patch_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(tmp_path / "prepared"),
        data_mounts={str(tmp_path): "/data"},
        prepared_contract={"images_dir": "/data/images", "splits_file": "/data/splits.json"},
        checksum_sha256="abc123",
        status="prepared",
    )
    path = tmp_path / "manifest.json"
    save_manifest(path, manifest)
    restored = load_manifest(path)
    assert restored.dataset_id == "hf:demo/x"
    assert restored.prepared_contract["images_dir"] == "/data/images"
    assert restored.status == "prepared"


def test_save_manifest_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "manifest.json"
    manifest = DatasetManifest(
        dataset_id="x", provider="huggingface",
        selected_for_task="patch_classification",
        raw_root="/r", prepared_root="/p",
        data_mounts={}, prepared_contract={},
    )
    save_manifest(target, manifest)
    assert target.exists()


def test_load_manifest_returns_failed_manifest_on_corrupt_json(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{this is not json")
    restored = load_manifest(p)
    assert restored.status == "failed"


def test_load_manifest_raises_on_missing_file(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "absent.json")


def test_save_manifest_writes_pretty_json(tmp_path):
    """Manifests should be human-readable for debugging."""
    manifest = DatasetManifest(
        dataset_id="x", provider="huggingface",
        selected_for_task="patch_classification",
        raw_root="/r", prepared_root="/p",
        data_mounts={}, prepared_contract={},
    )
    path = tmp_path / "m.json"
    save_manifest(path, manifest)
    text = path.read_text()
    assert "\n" in text   # pretty-printed has newlines
    parsed = json.loads(text)
    assert parsed["dataset_id"] == "x"
