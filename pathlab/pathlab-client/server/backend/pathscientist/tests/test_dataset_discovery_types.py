"""Tests for dataset discovery domain types.

Phase A T1 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_discovery_record_round_trips():
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    record = DatasetDiscoveryRecord(
        name="CRC-MSI",
        aliases=["TCGA CRC-MSI"],
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        label_keywords=["MSI", "MSI-H", "MSS"],
        prediction_target="microsatellite_instability",
        access="manual",
        confidence="medium",
        evidence=[
            DatasetDiscoveryEvidence(
                source="baseline",
                paper_id="openalex:W123",
                quote="CRC-MSI is used for MSI prediction.",
            )
        ],
        provider_hints=[
            ProviderHint(provider="zenodo", remote_id="10.5281/zenodo.123")
        ],
    )

    restored = DatasetDiscoveryRecord.from_dict(record.to_dict())
    assert restored.name == "CRC-MSI"
    assert restored.label_keywords == ["MSI", "MSI-H", "MSS"]
    assert restored.evidence[0].paper_id == "openalex:W123"
    assert restored.provider_hints[0].provider == "zenodo"


def test_evidence_defaults_empty():
    from pathscientist.dataset.discovery_types import DatasetDiscoveryEvidence

    e = DatasetDiscoveryEvidence(source="passage")
    assert e.paper_id == ""
    assert e.title == ""
    assert e.url == ""
    assert e.quote == ""
    assert e.section == ""


def test_provider_hint_defaults_empty():
    from pathscientist.dataset.discovery_types import ProviderHint

    h = ProviderHint(provider="huggingface")
    assert h.remote_id == ""
    assert h.url == ""
    assert h.kind == ""
    assert h.confidence == "low"


def test_record_from_dict_with_missing_optional_keys():
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    r = DatasetDiscoveryRecord.from_dict({"name": "BRACS"})
    assert r.name == "BRACS"
    assert r.aliases == []
    assert r.evidence == []
    assert r.provider_hints == []
    assert r.access == "manual"      # conservative default
    assert r.confidence == "low"


def test_record_drops_malformed_evidence_and_hints():
    """Bad rows are skipped, not raised."""
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    r = DatasetDiscoveryRecord.from_dict({
        "name": "X",
        "evidence": [
            {"source": "baseline", "paper_id": "p1"},
            "not a dict — should drop",
            {"source": "passage"},
        ],
        "provider_hints": [
            {"provider": "zenodo"},
            42,
        ],
    })
    assert len(r.evidence) == 2
    assert len(r.provider_hints) == 1


def test_record_estimated_size_string_coerces():
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    r = DatasetDiscoveryRecord.from_dict({"name": "X", "estimated_size_gb": "2.5"})
    assert r.estimated_size_gb == 2.5
    assert isinstance(r.estimated_size_gb, float)


def test_evidence_paper_id_canonical_shape_documented():
    """Caller should pass canonical-shape paper_id (e.g. 'openalex:W123', 'doi:10.1/x').

    The dataclass itself does not normalize — that's the extractor's job (Task 3).
    But the docstring must call out the expectation so future maintainers don't
    drop raw 'W123' strings here.
    """
    from pathscientist.dataset.discovery_types import DatasetDiscoveryEvidence

    doc = (DatasetDiscoveryEvidence.__doc__ or "").lower()
    assert "canonical" in doc, (
        "DatasetDiscoveryEvidence.__doc__ must mention canonical-id expectation"
    )
