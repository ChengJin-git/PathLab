from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from dataset.downloader import compute_sha256, extract_archive, safe_dataset_id


# ---- safe_dataset_id ----

def test_safe_dataset_id_replaces_path_chars():
    assert safe_dataset_id("hf:org/name") == "hf_org_name"


def test_safe_dataset_id_keeps_dot_dash_underscore():
    assert safe_dataset_id("a.b-c_d") == "a.b-c_d"


def test_safe_dataset_id_collapses_runs_of_unsafe_chars():
    assert safe_dataset_id("a//b: :c") == "a_b_c"


def test_safe_dataset_id_strips_leading_trailing_underscore():
    # "::abc::" -> "_abc_" -> strip -> "abc"
    assert safe_dataset_id("::abc::") == "abc"


def test_safe_dataset_id_handles_empty():
    assert safe_dataset_id("") == "_"


# ---- compute_sha256 ----

def test_compute_sha256_known_value(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello")
    assert compute_sha256(p) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_compute_sha256_streams_large_file(tmp_path):
    p = tmp_path / "big.bin"
    p.write_bytes(b"x" * (1 << 18))   # 256 KB > one default chunk
    digest = compute_sha256(p)
    # Just verify it's a hex digest of the right length, deterministic.
    assert len(digest) == 64
    assert int(digest, 16) >= 0


# ---- extract_archive ----

def test_extract_archive_zip(tmp_path):
    archive = tmp_path / "x.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("subdir/b.txt", "world")
    target = tmp_path / "out"
    files = extract_archive(archive, target)
    assert sorted(p.name for p in files) == ["a.txt", "b.txt"]
    assert (target / "a.txt").read_text() == "hello"
    assert (target / "subdir" / "b.txt").read_text() == "world"


def test_extract_archive_tar_gz(tmp_path):
    archive = tmp_path / "y.tar.gz"
    inner = tmp_path / "src"
    inner.mkdir()
    (inner / "a.txt").write_text("hi")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(inner / "a.txt", arcname="a.txt")
    target = tmp_path / "out"
    files = extract_archive(archive, target)
    assert len(files) == 1
    assert files[0].name == "a.txt"
    assert (target / "a.txt").read_text() == "hi"


def test_extract_archive_tgz_alias(tmp_path):
    archive = tmp_path / "z.tgz"
    inner = tmp_path / "src"
    inner.mkdir()
    (inner / "a.txt").write_text("ok")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(inner / "a.txt", arcname="a.txt")
    target = tmp_path / "out"
    files = extract_archive(archive, target)
    assert len(files) == 1


def test_extract_archive_rejects_path_traversal_zip(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "no")
        zf.writestr("safe.txt", "yes")
    target = tmp_path / "out"
    files = extract_archive(archive, target)
    # Only safe.txt should land; escape.txt must be skipped.
    assert [p.name for p in files] == ["safe.txt"]
    assert not (tmp_path / "escape.txt").exists()


def test_extract_archive_unsupported_ext_raises(tmp_path):
    weird = tmp_path / "x.7z"
    weird.write_bytes(b"x")
    with pytest.raises(ValueError):
        extract_archive(weird, tmp_path / "out")
