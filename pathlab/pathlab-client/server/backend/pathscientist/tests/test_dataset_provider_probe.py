"""Tests for dataset provider probe() contracts.

Phase B T5 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

Review constraint #3: no-network probes are PROVISIONAL. They may tag the
record (e.g. ``probe:file_url_unverified``) but MUST NOT upgrade ``access``
to ``"public"``. Acquisition policy + live verification are the only paths
to ``"public"``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _record(provider="direct_http", urls=None, remote_id="", access="manual", tags=None):
    from pathscientist.dataset.types import DatasetRecord, DownloadSpec
    return DatasetRecord(
        dataset_id="x",
        name="X",
        provider=provider,
        access=access,
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        tags=list(tags or []),
        download=DownloadSpec(kind=provider, urls=list(urls or []), remote_id=remote_id),
    )


# ---------------------------------------------------------------- DirectHTTP


def test_direct_http_probe_no_urls_tags_and_keeps_manual():
    from pathscientist.dataset.providers.direct_http import DirectHTTPProvider

    out = DirectHTTPProvider().probe(_record(urls=[]))
    assert out.access == "manual"
    assert "probe:no_urls" in out.tags


def test_direct_http_probe_landing_page_tags_and_keeps_manual():
    from pathscientist.dataset.providers.direct_http import DirectHTTPProvider

    out = DirectHTTPProvider().probe(_record(urls=["https://example.org/Data/"]))
    assert out.access == "manual"
    assert "probe:not_file_url" in out.tags


def test_direct_http_probe_file_like_url_tags_provisional_and_does_not_upgrade_access():
    """Review constraint #3: file-like URL alone is NOT proof of public access."""
    from pathscientist.dataset.providers.direct_http import DirectHTTPProvider

    out = DirectHTTPProvider().probe(
        _record(urls=["https://example.org/data.zip"], access="manual")
    )
    assert out.access == "manual", "probe MUST NOT upgrade manual → public"
    assert "probe:file_url_unverified" in out.tags


def test_direct_http_probe_preserves_existing_curated_access():
    """A curated record that already has access=public stays public — probe never demotes."""
    from pathscientist.dataset.providers.direct_http import DirectHTTPProvider

    out = DirectHTTPProvider().probe(
        _record(urls=["https://example.org/data.zip"], access="public")
    )
    assert out.access == "public"


# ---------------------------------------------------------------- Zenodo


def test_zenodo_probe_doi_only_tags_and_keeps_manual():
    from pathscientist.dataset.providers.zenodo import ZenodoProvider

    out = ZenodoProvider().probe(
        _record(provider="zenodo", remote_id="10.5281/zenodo.123", urls=[])
    )
    assert out.access == "manual"
    assert "probe:zenodo_resolution_pending" in out.tags


def test_zenodo_probe_with_file_urls_delegates_to_direct_http_tag():
    from pathscientist.dataset.providers.zenodo import ZenodoProvider

    out = ZenodoProvider().probe(
        _record(provider="zenodo", urls=["https://zenodo.org/records/1/files/x.zip"])
    )
    assert out.access == "manual"
    assert "probe:file_url_unverified" in out.tags


# ---------------------------------------------------------------- HuggingFace


def test_huggingface_probe_no_remote_id_tags_and_keeps_manual():
    from pathscientist.dataset.providers.huggingface import HuggingFaceProvider

    out = HuggingFaceProvider().probe(
        _record(provider="huggingface", remote_id="")
    )
    assert out.access == "manual"
    assert "probe:no_remote_id" in out.tags


def test_huggingface_probe_with_remote_id_tags_provisional_does_not_upgrade():
    """remote_id present is provisional; access stays manual."""
    from pathscientist.dataset.providers.huggingface import HuggingFaceProvider

    out = HuggingFaceProvider().probe(
        _record(provider="huggingface", remote_id="org/x", access="manual")
    )
    assert out.access == "manual"
    assert "probe:hf_remote_unverified" in out.tags


def test_huggingface_probe_with_gated_tag_adds_gated_marker():
    from pathscientist.dataset.providers.huggingface import HuggingFaceProvider

    out = HuggingFaceProvider().probe(
        _record(
            provider="huggingface",
            remote_id="org/x",
            access="manual",
            tags=["gated"],
        )
    )
    assert out.access == "manual"
    assert "probe:hf_gated" in out.tags


def test_huggingface_probe_preserves_curated_public_access():
    from pathscientist.dataset.providers.huggingface import HuggingFaceProvider

    out = HuggingFaceProvider().probe(
        _record(provider="huggingface", remote_id="org/x", access="public")
    )
    assert out.access == "public"


# ---------------------------------------------------------------- idempotency


def test_acquisition_uses_probe_return_value(tmp_path):
    """Task 0 blocker #4: when ``probe()`` returns a NEW record (rather than
    mutating in-place), acquisition must use that returned object so the new
    tags propagate into the plan/considered list."""
    import json
    from copy import deepcopy
    from pathscientist.dataset.acquisition import DatasetAcquisitionService
    from pathscientist.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from pathscientist.dataset.policy import AcquisitionPolicy
    from pathscientist.dataset.providers.base import DownloadResult
    from pathscientist.dataset.registry import DatasetRegistry
    from pathscientist.dataset.types import (
        DatasetRecord, DownloadSpec, TaskProfile,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        DatasetRecord(
            dataset_id="d1", name="CRC-MSI", provider="huggingface",
            access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], tags=["MSI"],
            download=DownloadSpec(kind="hf_dataset", remote_id="org/x"),
        )
    ])

    class CopyingProvider:
        provider_name = "huggingface"
        def probe(self, record):
            # Return a NEW object — do not mutate caller's instance.
            new = deepcopy(record)
            new.tags = list(new.tags) + ["probe:copying_marker"]
            return new
        def download(self, record, target_dir):
            from pathlib import Path as _P
            return DownloadResult(status="failed", raw_root=_P(target_dir), reason="stub")

    service = DatasetAcquisitionService(
        registry=registry, providers={"huggingface": CopyingProvider()},
        normalizers=[], cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        required_label_keywords=["MSI"],
    )
    service.acquire(profile, workspace_root=workspace)

    payload = json.loads(acquisition_plan_path_for_workspace(workspace).read_text())
    sample = payload["considered"][0]
    assert "probe:copying_marker" in sample.get("tags", []), (
        "probe()'s return value must propagate into plan considered tags"
    )


def test_probe_is_idempotent_does_not_duplicate_tag():
    """Probing twice should not create duplicate ``probe:*`` tags."""
    from pathscientist.dataset.providers.direct_http import DirectHTTPProvider

    rec = _record(urls=["https://example.org/data.zip"], access="manual")
    p = DirectHTTPProvider()
    out1 = p.probe(rec)
    out2 = p.probe(out1)
    assert out2.tags.count("probe:file_url_unverified") == 1
