"""Tests for GDCProvider (also serves the ``tcia`` provider name).

Plan-2026-04-30 dataset-provider-repair Task 5: TCGA / GDC datasets need
a manifest-only safety boundary. Portal/project URLs return
``skipped_policy/gdc_manifest_required`` rather than ``no_provider:tcia``;
explicit ``api.gdc.cancer.gov/data/<uuid>`` URLs stream individual files.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _record(kind="gdc_data_urls", urls=None, remote_id="", provider="gdc"):
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    return DatasetRecord(
        dataset_id="tcga:BRCA",
        name="TCGA-BRCA Diagnostic Slides",
        provider=provider,
        access="gated",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["breast"],
        tags=["TCGA", "WSI"],
        download=DownloadSpec(kind=kind, remote_id=remote_id, urls=list(urls or [])),
    )


# ---------------------------------------------------------------- probe


def test_gdc_probe_tags_data_urls_present():
    from autoresearch.dataset.providers.gdc import GDCProvider

    out = GDCProvider().probe(
        _record(urls=["https://api.gdc.cancer.gov/data/uuid1"]),
    )
    assert out.access == "gated"
    assert "probe:gdc_data_urls_present" in out.tags


def test_gdc_probe_tags_manifest_required_on_portal_url():
    from autoresearch.dataset.providers.gdc import GDCProvider

    out = GDCProvider().probe(
        _record(urls=["https://portal.gdc.cancer.gov/projects/TCGA-BRCA"]),
    )
    assert out.access == "gated"   # NEVER upgraded
    assert "probe:gdc_manifest_required" in out.tags


def test_gdc_probe_tags_manifest_required_when_no_urls():
    from autoresearch.dataset.providers.gdc import GDCProvider

    out = GDCProvider().probe(_record(urls=[]))
    assert "probe:gdc_manifest_required" in out.tags


# ---------------------------------------------------------------- download


def test_gdc_download_requires_manifest_when_only_portal_url(tmp_path):
    from autoresearch.dataset.providers.gdc import GDCProvider

    result = GDCProvider().download(
        _record(
            kind="manual",
            urls=["https://portal.gdc.cancer.gov/projects/TCGA-BRCA"],
        ),
        tmp_path,
    )
    assert result.status == "skipped_policy"
    assert result.reason == "gdc_manifest_required"


def test_gdc_downloads_explicit_data_urls(tmp_path):
    from unittest.mock import MagicMock
    from autoresearch.dataset.providers.gdc import GDCProvider

    class _Resp:
        headers = {"content-disposition": "attachment; filename=file1.svs"}
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): return iter([b"svs"])
        def __enter__(self): return self
        def __exit__(self, *args): return None

    session = MagicMock()
    session.get.return_value = _Resp()
    record = _record(
        kind="gdc_data_urls",
        urls=["https://api.gdc.cancer.gov/data/uuid1"],
    )
    result = GDCProvider(session=session).download(record, tmp_path)
    assert result.status == "downloaded"
    assert result.files[0].name == "file1.svs"


def test_gdc_falls_back_to_uuid_filename_when_no_content_disposition(tmp_path):
    from unittest.mock import MagicMock
    from autoresearch.dataset.providers.gdc import GDCProvider

    class _Resp:
        headers = {}
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): return iter([b"x"])
        def __enter__(self): return self
        def __exit__(self, *args): return None

    session = MagicMock()
    session.get.return_value = _Resp()
    result = GDCProvider(session=session).download(
        _record(kind="gdc_data_urls", urls=["https://api.gdc.cancer.gov/data/abcd-uuid"]),
        tmp_path,
    )
    assert result.status == "downloaded"
    # UUID basename used as filename.
    assert "abcd-uuid" in result.files[0].name


def test_gdc_failed_request_returns_structured_failure(tmp_path):
    from unittest.mock import MagicMock
    from autoresearch.dataset.providers.gdc import GDCProvider

    session = MagicMock()
    session.get.side_effect = RuntimeError("network down")
    result = GDCProvider(session=session).download(
        _record(kind="gdc_data_urls", urls=["https://api.gdc.cancer.gov/data/uuid"]),
        tmp_path,
    )
    assert result.status == "failed"
    assert "gdc" in result.reason.lower() or "network" in result.reason.lower()


def test_gdc_download_rejects_redirect_to_internal_url(tmp_path):
    from unittest.mock import MagicMock
    from autoresearch.dataset.providers.gdc import GDCProvider

    class _RedirectResp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        def raise_for_status(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None

    session = MagicMock()
    session.get.return_value = _RedirectResp()
    result = GDCProvider(session=session).download(
        _record(kind="gdc_data_urls", urls=["https://api.gdc.cancer.gov/data/uuid"]),
        tmp_path,
    )
    assert result.status == "failed"
    assert session.get.call_count == 1


def test_gdc_no_urls_returns_skipped_policy(tmp_path):
    from autoresearch.dataset.providers.gdc import GDCProvider

    result = GDCProvider().download(_record(kind="gdc_data_urls", urls=[]), tmp_path)
    assert result.status == "skipped_policy"
    assert "gdc_manifest_required" in result.reason


# ---------------------------------------------------------------- factory wiring


def test_factory_registers_gdc_and_tcia_to_same_instance():
    """``"tcia"`` is just an alias — same provider class. (Plan calls it
    out so ``provider:tcia`` records don't fall back to ``no_provider``.)"""
    from autoresearch.dataset.providers.factory import build_default_providers

    providers = build_default_providers()
    assert "gdc" in providers
    assert "tcia" in providers
    # Same instance OR same class — either is acceptable.
    assert (
        providers["gdc"] is providers["tcia"]
        or type(providers["gdc"]) is type(providers["tcia"])
    )
