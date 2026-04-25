from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset.normalizers.mil_classification import MILClassificationNormalizer
from dataset.normalizers.patch_classification import PatchClassificationNormalizer


# ---- Patch ----

def _build_class_subdir_layout(root: Path) -> None:
    (root / "tumor").mkdir(parents=True)
    (root / "normal").mkdir()
    (root / "tumor" / "a.png").write_bytes(b"a")
    (root / "tumor" / "b.png").write_bytes(b"b")
    (root / "normal" / "c.png").write_bytes(b"c")
    (root / "normal" / "d.png").write_bytes(b"d")
    (root / "normal" / "e.png").write_bytes(b"e")


def test_patch_normalizer_emits_images_and_splits(tmp_path):
    raw = tmp_path / "raw"
    _build_class_subdir_layout(raw)
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["task_type"] == "patch_classification"
    assert Path(contract["images_dir"]).exists()
    assert Path(contract["splits_file"]).exists()
    splits = json.loads(Path(contract["splits_file"]).read_text())
    assert "train" in splits and "val" in splits
    assert contract["n_train"] + contract["n_val"] == 5


def test_patch_normalizer_data_mounts_present(tmp_path):
    raw = tmp_path / "raw"
    _build_class_subdir_layout(raw)
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["data_mounts"] == {str(prepared): "/data"}


def test_patch_normalizer_skips_non_image_files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "tumor").mkdir()
    (raw / "tumor" / "a.png").write_bytes(b"a")
    (raw / "tumor" / "README.txt").write_text("ignore me")
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["n_train"] + contract["n_val"] == 1


def test_patch_normalizer_supports_check():
    n = PatchClassificationNormalizer()
    assert n.supports("patch_classification") is True
    assert n.supports("mil_classification") is False


def test_patch_normalizer_deterministic_splits(tmp_path):
    """Running twice on identical input produces identical splits.json."""
    raw = tmp_path / "raw"
    _build_class_subdir_layout(raw)
    prepared1 = tmp_path / "prepared1"
    prepared2 = tmp_path / "prepared2"
    c1 = PatchClassificationNormalizer().prepare(raw, prepared1)
    c2 = PatchClassificationNormalizer().prepare(raw, prepared2)
    s1 = json.loads(Path(c1["splits_file"]).read_text())
    s2 = json.loads(Path(c2["splits_file"]).read_text())
    # Strip the prepared_root prefix to compare class membership.
    def strip(splits):
        return [(d["label"], Path(d["path"]).name) for d in splits["train"] + splits["val"]]
    assert strip(s1) == strip(s2)


# ---- MIL ----

def test_mil_normalizer_emits_wsi_contract(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    (raw / "slides" / "s1.svs").write_bytes(b"fake")
    (raw / "slides" / "s2.tiff").write_bytes(b"fake")
    prepared = tmp_path / "prepared"
    contract = MILClassificationNormalizer().prepare(raw, prepared)
    assert contract["task_type"] == "mil_classification"
    assert "wsi_dir" in contract
    assert contract["requires_feature_extraction"] is True
    assert contract["n_slides"] == 2
    assert Path(contract["wsi_dir"]).exists()
    assert (Path(contract["wsi_dir"]) / "s1.svs").exists()


def test_mil_normalizer_falls_back_to_root_when_no_slides_dir(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "slide_a.svs").write_bytes(b"fake")
    (raw / "slide_b.ndpi").write_bytes(b"fake")
    (raw / "notes.txt").write_text("ignore")
    prepared = tmp_path / "prepared"
    contract = MILClassificationNormalizer().prepare(raw, prepared)
    assert contract["n_slides"] == 2


def test_mil_normalizer_carries_labels_when_present(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    (raw / "slides" / "s1.svs").write_bytes(b"fake")
    (raw / "labels.csv").write_text("slide_id,label\ns1,tumor\n")
    prepared = tmp_path / "prepared"
    contract = MILClassificationNormalizer().prepare(raw, prepared)
    assert Path(contract["labels_file"]).read_text() == "slide_id,label\ns1,tumor\n"


def test_mil_normalizer_emits_empty_labels_when_missing(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    (raw / "slides" / "s1.svs").write_bytes(b"fake")
    prepared = tmp_path / "prepared"
    contract = MILClassificationNormalizer().prepare(raw, prepared)
    assert Path(contract["labels_file"]).read_text() == "slide_id,label\n"


def test_mil_normalizer_supports_check():
    n = MILClassificationNormalizer()
    assert n.supports("mil_classification") is True
    assert n.supports("patch_classification") is False


def test_mil_normalizer_data_mounts_present(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    (raw / "slides" / "s1.svs").write_bytes(b"fake")
    prepared = tmp_path / "prepared"
    contract = MILClassificationNormalizer().prepare(raw, prepared)
    assert contract["data_mounts"] == {str(prepared): "/data"}
