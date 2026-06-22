from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json

import pytest

from pathscientist.dataset.normalizers.base import NormalizerError
from pathscientist.dataset.normalizers.mil_classification import MILClassificationNormalizer
from pathscientist.dataset.normalizers.patch_classification import PatchClassificationNormalizer


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
    (raw / "normal").mkdir()
    (raw / "normal" / "b.png").write_bytes(b"b")
    (raw / "normal" / "NOTES.md").write_text("ignore me")
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["n_train"] + contract["n_val"] == 2


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


def test_mil_normalizer_uses_task4_for_intestinal_metaplasia_profile(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    (raw / "slides" / "s1.svs").write_bytes(b"fake")
    (raw / "slides" / "s2.svs").write_bytes(b"fake")
    (raw / "labels.csv").write_text(
        "slide_id,Task1,Task4\n"
        "s1,0,Intestinal metaplasia\n"
        "s2,1,Not Intestinal metaplasia\n"
    )
    prepared = tmp_path / "prepared"

    contract = MILClassificationNormalizer().prepare(
        raw,
        prepared,
        task_profile={"prediction_target": "intestinal_metaplasia"},
    )

    assert contract["label_column"] == "Task4"
    assert Path(contract["labels_file"]).read_text() == (
        "slide_id,label\ns1,Intestinal metaplasia\ns2,Not Intestinal metaplasia\n"
    )


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


# ---- Empty / unsupported layout validation (Review fix R3 / P1 #4) ----


def test_patch_normalizer_raises_on_empty_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    prepared = tmp_path / "prepared"
    with pytest.raises(NormalizerError, match="unsupported_layout|no_images"):
        PatchClassificationNormalizer().prepare(raw, prepared)


def test_patch_normalizer_raises_when_only_non_image_files(tmp_path):
    raw = tmp_path / "raw"
    (raw / "tumor").mkdir(parents=True)
    (raw / "tumor" / "README.txt").write_text("ignore")
    (raw / "normal").mkdir()
    (raw / "normal" / "notes.md").write_text("ignore")
    prepared = tmp_path / "prepared"
    with pytest.raises(NormalizerError, match="unsupported_layout|no_images"):
        PatchClassificationNormalizer().prepare(raw, prepared)


def test_patch_normalizer_raises_on_single_class(tmp_path):
    raw = tmp_path / "raw"
    (raw / "tumor").mkdir(parents=True)
    (raw / "tumor" / "a.png").write_bytes(b"a")
    (raw / "tumor" / "b.png").write_bytes(b"b")
    prepared = tmp_path / "prepared"
    with pytest.raises(NormalizerError, match="insufficient_classes"):
        PatchClassificationNormalizer().prepare(raw, prepared)


def test_patch_normalizer_handles_single_top_level_dir(tmp_path):
    """Common .zip extraction pattern: archive contains one top-level dir
    that holds the actual class subdirs."""
    raw = tmp_path / "raw"
    inner = raw / "MyDataset"
    (inner / "tumor").mkdir(parents=True)
    (inner / "normal").mkdir()
    (inner / "tumor" / "a.png").write_bytes(b"a")
    (inner / "normal" / "b.png").write_bytes(b"b")
    (inner / "tumor" / "c.png").write_bytes(b"c")
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["n_train"] + contract["n_val"] == 3


def test_patch_normalizer_clamps_split_for_tiny_dataset(tmp_path):
    """A 2-image dataset must produce 1 train + 1 val (not 1+1 with empty side)."""
    raw = tmp_path / "raw"
    (raw / "a").mkdir(parents=True)
    (raw / "b").mkdir()
    (raw / "a" / "x.png").write_bytes(b"x")
    (raw / "b" / "y.png").write_bytes(b"y")
    prepared = tmp_path / "prepared"
    contract = PatchClassificationNormalizer().prepare(raw, prepared)
    assert contract["n_train"] >= 1
    assert contract["n_val"] >= 1


def test_mil_normalizer_raises_on_no_slides(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "README.txt").write_text("no slides here")
    prepared = tmp_path / "prepared"
    with pytest.raises(NormalizerError, match="no_slides"):
        MILClassificationNormalizer().prepare(raw, prepared)


def test_mil_normalizer_raises_when_slides_dir_present_but_empty(tmp_path):
    raw = tmp_path / "raw"
    (raw / "slides").mkdir(parents=True)
    prepared = tmp_path / "prepared"
    with pytest.raises(NormalizerError, match="no_slides"):
        MILClassificationNormalizer().prepare(raw, prepared)
