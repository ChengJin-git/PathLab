from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import MagicMock

import pytest

from pathscientist.dataset.providers.base import DownloadResult
from pathscientist.dataset.providers.direct_http import DirectHTTPProvider
from pathscientist.dataset.providers.huggingface import HuggingFaceProvider
from pathscientist.dataset.providers.zenodo import ZenodoProvider
from pathscientist.dataset.types import DatasetRecord, DownloadSpec


def _make_record(**overrides) -> DatasetRecord:
    base = dict(
        dataset_id="x",
        name="X",
        provider="direct_http",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        download=DownloadSpec(kind="direct_http", urls=["https://example.org/data.zip"]),
    )
    base.update(overrides)
    return DatasetRecord.from_dict({k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in base.items()})


# ---- DirectHTTPProvider ----

def test_direct_http_rejects_landing_page_url(tmp_path):
    record = _make_record(download=DownloadSpec(kind="direct_http", urls=["https://example.org/Dataset/"]))
    result = DirectHTTPProvider().download(record, tmp_path)
    assert result.status == "skipped_policy"
    assert "not_file_url" in result.reason


def test_direct_http_skips_when_no_urls(tmp_path):
    record = _make_record(download=DownloadSpec(kind="direct_http", urls=[]))
    result = DirectHTTPProvider().download(record, tmp_path)
    assert result.status == "skipped_policy"
    assert result.reason == "no_urls"


def test_direct_http_downloads_file_url_with_mocked_session(tmp_path):
    fake_response = MagicMock()
    fake_response.iter_content.return_value = [b"hello", b" ", b"world"]
    fake_response.raise_for_status = MagicMock()
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    record = _make_record(download=DownloadSpec(
        kind="direct_http",
        urls=["https://example.org/data.zip"],
        filename="data.zip",
    ))
    result = DirectHTTPProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "downloaded"
    assert len(result.files) == 1
    assert result.files[0].name == "data.zip"
    assert result.files[0].read_bytes() == b"hello world"


def test_direct_http_returns_failed_on_session_error(tmp_path):
    fake_session = MagicMock()
    fake_session.get.side_effect = RuntimeError("boom")
    record = _make_record(download=DownloadSpec(kind="direct_http", urls=["https://example.org/data.zip"]))
    result = DirectHTTPProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "failed"
    assert "http_error" in result.reason


def test_direct_http_accepts_targz(tmp_path):
    fake_response = MagicMock()
    fake_response.iter_content.return_value = [b"x"]
    fake_response.raise_for_status = MagicMock()
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    record = _make_record(download=DownloadSpec(kind="direct_http", urls=["https://example.org/data.tar.gz"]))
    result = DirectHTTPProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "downloaded"


# ---- ZenodoProvider ----

def test_zenodo_skips_with_no_urls(tmp_path):
    record = _make_record(download=DownloadSpec(kind="zenodo", urls=[]))
    result = ZenodoProvider().download(record, tmp_path)
    assert result.status == "skipped_policy"
    assert "doi" in result.reason.lower() or "no_urls" in result.reason.lower()


def test_zenodo_uses_direct_http_when_urls_provided(tmp_path):
    fake_response = MagicMock()
    fake_response.iter_content.return_value = [b"data"]
    fake_response.raise_for_status = MagicMock()
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    record = _make_record(download=DownloadSpec(
        kind="zenodo",
        urls=["https://zenodo.org/record/123/files/x.zip"],
        filename="x.zip",
    ))
    result = ZenodoProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "downloaded"
    assert result.files[0].name == "x.zip"


# ---- HuggingFaceProvider ----

def test_hf_provider_returns_failed_when_lib_missing(tmp_path):
    """Inject a snapshot_fn=None and patch the import to fail."""
    provider = HuggingFaceProvider(snapshot_fn=None)
    # Simulate huggingface_hub not installed by patching _resolve_snapshot.
    provider._resolve_snapshot = lambda: None
    record = _make_record(download=DownloadSpec(kind="hf_dataset", remote_id="org/x"))
    result = provider.download(record, tmp_path)
    assert result.status == "failed"
    assert result.reason == "missing_huggingface_hub"


def test_hf_provider_skips_when_no_remote_id(tmp_path):
    snapshot = MagicMock()
    provider = HuggingFaceProvider(snapshot_fn=snapshot)
    record = _make_record(download=DownloadSpec(kind="hf_dataset", remote_id=""))
    result = provider.download(record, tmp_path)
    assert result.status == "skipped_policy"
    assert result.reason == "no_remote_id"
    snapshot.assert_not_called()


def test_hf_provider_calls_snapshot_and_walks_files(tmp_path):
    target = tmp_path / "hf_target"

    def fake_snapshot(*, repo_id, repo_type, local_dir):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "a.parquet").write_bytes(b"x")
        (Path(local_dir) / "subdir").mkdir()
        (Path(local_dir) / "subdir" / "b.parquet").write_bytes(b"y")
        return local_dir

    provider = HuggingFaceProvider(snapshot_fn=fake_snapshot)
    record = _make_record(download=DownloadSpec(kind="hf_dataset", remote_id="org/x"))
    result = provider.download(record, target)
    assert result.status == "downloaded"
    assert len(result.files) == 2
    assert result.files[0].name in ("a.parquet", "b.parquet")


def test_hf_provider_returns_failed_on_snapshot_error(tmp_path):
    provider = HuggingFaceProvider(snapshot_fn=MagicMock(side_effect=RuntimeError("auth required")))
    record = _make_record(download=DownloadSpec(kind="hf_dataset", remote_id="org/x"))
    result = provider.download(record, tmp_path)
    assert result.status == "failed"
    assert "hf_error" in result.reason


# ---- Review fix R6 (P2): direct HTTP single-file SHA256 ----


def test_direct_http_computes_sha256_for_single_file(tmp_path):
    """R6: direct HTTP single-file download attaches sha256."""
    fake_response = MagicMock()
    fake_response.iter_content.return_value = [b"hello", b" ", b"world"]
    fake_response.raise_for_status = MagicMock()
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    record = _make_record(download=DownloadSpec(
        kind="direct_http",
        urls=["https://example.org/data.zip"],
        filename="data.zip",
    ))
    result = DirectHTTPProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "downloaded"
    # SHA256 of b"hello world"
    assert result.checksum_sha256 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_direct_http_no_checksum_on_multi_file(tmp_path):
    """Multi-file downloads leave checksum blank (manifest-of-hashes is later work)."""
    fake_response = MagicMock()
    fake_response.iter_content.return_value = [b"x"]
    fake_response.raise_for_status = MagicMock()
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    record = _make_record(download=DownloadSpec(
        kind="direct_http",
        urls=["https://example.org/a.zip", "https://example.org/b.zip"],
    ))
    result = DirectHTTPProvider(session=fake_session).download(record, tmp_path)
    assert result.status == "downloaded"
    assert result.checksum_sha256 == ""
