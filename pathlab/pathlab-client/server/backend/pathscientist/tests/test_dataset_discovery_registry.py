"""Tests for converting discovery records to acquisition DatasetRecords + merge.

Phase A T4 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

Review constraint #1: Discovery is NOT proof of downloadability. Discovered
records stay ``access="manual"`` unless curated metadata or live provider
verification proves otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_zenodo_hint_becomes_manual_record_pending_verification():
    """Review constraint #1: zenodo URL hint alone is NOT proof of public access."""
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    discovered = DatasetDiscoveryRecord(
        name="CRC-MSI",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        access="manual",
        confidence="medium",
        evidence=[DatasetDiscoveryEvidence(source="passage", quote="available on Zenodo")],
        provider_hints=[ProviderHint(provider="zenodo", remote_id="10.5281/zenodo.123")],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert record.dataset_id.startswith("discovered:")
    assert record.access == "manual"
    assert record.provider == "zenodo"
    assert record.download.kind == "zenodo"
    assert record.download.remote_id == "10.5281/zenodo.123"


def test_huggingface_hint_maps_to_hf_dataset_kind():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    discovered = DatasetDiscoveryRecord(
        name="X",
        confidence="medium",
        provider_hints=[ProviderHint(provider="huggingface", remote_id="org/x")],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert record.provider == "huggingface"
    assert record.download.kind == "hf_dataset"
    assert record.download.remote_id == "org/x"


def test_no_provider_hint_falls_back_to_manual():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    discovered = DatasetDiscoveryRecord(name="NoSource")
    record = discovery_record_to_dataset_record(discovered)
    assert record.provider == "manual"
    assert record.download.kind == "manual"
    assert record.access == "manual"


def test_dataset_id_is_safe_slug_of_name():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    discovered = DatasetDiscoveryRecord(name="CRC MSI / TCGA")
    record = discovery_record_to_dataset_record(discovered)
    # Spaces/slashes go to safe chars; lowercase.
    assert record.dataset_id == "discovered:crc-msi-tcga"


def test_record_carries_label_keywords_and_aliases_into_tags():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    discovered = DatasetDiscoveryRecord(
        name="CRC-MSI",
        aliases=["TCGA-CRC-MSI"],
        label_keywords=["MSI", "MSS"],
        prediction_target="microsatellite_instability",
        confidence="medium",
    )
    record = discovery_record_to_dataset_record(discovered)
    assert "MSI" in record.tags
    assert "MSS" in record.tags
    assert "microsatellite_instability" in record.tags
    assert "discovered" in record.tags
    assert "TCGA-CRC-MSI" in record.tags


def test_source_paper_ids_collected_from_evidence():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )

    discovered = DatasetDiscoveryRecord(
        name="X",
        evidence=[
            DatasetDiscoveryEvidence(source="baseline", paper_id="openalex:W1"),
            DatasetDiscoveryEvidence(source="passage", paper_id="openalex:W2"),
            DatasetDiscoveryEvidence(source="llm_hint", paper_id=""),
        ],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert "openalex:W1" in record.source_paper_ids
    assert "openalex:W2" in record.source_paper_ids
    assert "" not in record.source_paper_ids


# ---------------------------------------------------------------- merge


def test_merge_prefers_curated_record_over_discovered_alias():
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )
    from pathscientist.dataset.types import DatasetRecord, DownloadSpec

    curated = DatasetRecord(
        dataset_id="curated:crc-msi",
        name="CRC-MSI",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        download=DownloadSpec(kind="hf_dataset", remote_id="org/crc-msi"),
    )
    discovered = DatasetDiscoveryRecord(
        name="CRC-MSI",
        confidence="medium",
        evidence=[DatasetDiscoveryEvidence(source="baseline")],
    )
    merged = merge_curated_and_discovered([curated], [discovered])
    assert len(merged) == 1
    assert merged[0].dataset_id == "curated:crc-msi"


def test_merge_includes_distinct_discovered_record():
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )

    discovered = DatasetDiscoveryRecord(
        name="BRACS",
        confidence="medium",
        evidence=[DatasetDiscoveryEvidence(source="baseline")],
    )
    merged = merge_curated_and_discovered([], [discovered])
    assert [r.name for r in merged] == ["BRACS"]
    assert merged[0].dataset_id.startswith("discovered:")


def test_merge_drops_low_confidence_discovered():
    """Confidence gate: low → drop. Plan T4 step 3 spec."""
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )

    low = DatasetDiscoveryRecord(
        name="Mystery",
        confidence="low",
        evidence=[DatasetDiscoveryEvidence(source="paper")],
    )
    merged = merge_curated_and_discovered([], [low])
    assert merged == []


def test_merge_drops_evidence_less_discovered():
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    naked = DatasetDiscoveryRecord(name="Mystery", confidence="medium", evidence=[])
    merged = merge_curated_and_discovered([], [naked])
    assert merged == []


def test_merge_alias_match_against_curated_blocks_discovered():
    """A discovered record whose name matches a curated alias is dropped."""
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )
    from pathscientist.dataset.types import DatasetRecord, DownloadSpec

    curated = DatasetRecord(
        dataset_id="curated:crc-msi",
        name="CRC-MSI",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        tags=["TCGA-CRC-MSI"],
        download=DownloadSpec(kind="hf_dataset", remote_id="org/crc-msi"),
    )
    discovered = DatasetDiscoveryRecord(
        name="TCGA-CRC-MSI",  # only matches via curated.tags alias
        confidence="medium",
        evidence=[DatasetDiscoveryEvidence(source="baseline")],
    )
    merged = merge_curated_and_discovered([curated], [discovered])
    assert [r.dataset_id for r in merged] == ["curated:crc-msi"]


def test_discovered_direct_http_hint_becomes_direct_http_download_spec():
    """Task 2: a direct_http provider hint maps to ``download.kind="direct_http"`` + urls list."""
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    discovered = DatasetDiscoveryRecord(
        name="BRACS",
        confidence="medium",
        provider_hints=[
            ProviderHint(provider="direct_http", url="https://example.org/bracs.zip"),
        ],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert record.provider == "direct_http"
    assert record.download.kind == "direct_http"
    assert record.download.urls == ["https://example.org/bracs.zip"]


def test_discovered_kaggle_competition_hint_carries_kind_and_remote_id():
    """Task 2: Kaggle competition hint flows kind into DownloadSpec.kind."""
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    discovered = DatasetDiscoveryRecord(
        name="PANDA",
        confidence="medium",
        provider_hints=[
            ProviderHint(
                provider="kaggle",
                kind="kaggle_competition",
                remote_id="prostate-cancer-grade-assessment",
            ),
        ],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert record.provider == "kaggle"
    assert record.download.kind == "kaggle_competition"
    assert record.download.remote_id == "prostate-cancer-grade-assessment"


def test_discovered_kaggle_dataset_hint_carries_kind_and_remote_id():
    from pathscientist.dataset.discovery_registry import (
        discovery_record_to_dataset_record,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    discovered = DatasetDiscoveryRecord(
        name="PANDA-Corpus",
        confidence="medium",
        provider_hints=[
            ProviderHint(
                provider="kaggle",
                kind="kaggle_dataset",
                remote_id="owner/panda-corpus",
            ),
        ],
    )
    record = discovery_record_to_dataset_record(discovered)
    assert record.download.kind == "kaggle_dataset"
    assert record.download.remote_id == "owner/panda-corpus"


def test_merge_blocks_discovered_when_alias_matches_curated_name():
    """Task 2: a discovered record whose ``aliases`` collide with a curated
    record's name (or tag) is dropped, even when the discovered ``name`` differs."""
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )
    from pathscientist.dataset.types import DatasetRecord, DownloadSpec

    curated = DatasetRecord(
        dataset_id="curated:crc-msi",
        name="CRC-MSI",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        download=DownloadSpec(kind="hf_dataset", remote_id="org/crc-msi"),
    )
    # discovered.name DIFFERS from curated.name, but aliases collides.
    discovered = DatasetDiscoveryRecord(
        name="The CRC-MSI Corpus",
        aliases=["CRC-MSI"],
        confidence="medium",
        evidence=[DatasetDiscoveryEvidence(source="baseline")],
    )
    merged = merge_curated_and_discovered([curated], [discovered])
    assert len(merged) == 1
    assert merged[0].dataset_id == "curated:crc-msi"


def test_merge_high_confidence_discovered_passes_gate():
    from pathscientist.dataset.discovery_registry import merge_curated_and_discovered
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
    )

    discovered = DatasetDiscoveryRecord(
        name="PANDA",
        confidence="high",
        evidence=[DatasetDiscoveryEvidence(source="llm_hint")],
    )
    merged = merge_curated_and_discovered([], [discovered])
    assert [r.name for r in merged] == ["PANDA"]
