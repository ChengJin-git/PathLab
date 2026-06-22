"""Tests for dataset discovery JSON persistence.

Phase A T2 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_discovery_path_for_workspace(tmp_path):
    from pathscientist.dataset.discovery_store import discovery_path_for_workspace

    assert discovery_path_for_workspace(tmp_path) == tmp_path / ".dataset" / "discovery.json"


def test_save_and_load_round_trip(tmp_path):
    from pathscientist.dataset.discovery_store import (
        discovery_path_for_workspace,
        load_discovery_records,
        save_discovery_records,
    )
    from pathscientist.dataset.discovery_types import (
        DatasetDiscoveryEvidence,
        DatasetDiscoveryRecord,
        ProviderHint,
    )

    path = discovery_path_for_workspace(tmp_path)
    save_discovery_records(path, [
        DatasetDiscoveryRecord(
            name="BRACS",
            confidence="medium",
            evidence=[DatasetDiscoveryEvidence(source="paper", paper_id="openalex:W1")],
            provider_hints=[ProviderHint(provider="zenodo", remote_id="10.5281/zenodo.99")],
        ),
    ])
    loaded = load_discovery_records(path)
    assert [r.name for r in loaded] == ["BRACS"]
    assert loaded[0].evidence[0].paper_id == "openalex:W1"
    assert loaded[0].provider_hints[0].provider == "zenodo"


def test_load_missing_returns_empty(tmp_path):
    from pathscientist.dataset.discovery_store import load_discovery_records

    assert load_discovery_records(tmp_path / "missing.json") == []


def test_save_creates_parent_directory(tmp_path):
    from pathscientist.dataset.discovery_store import save_discovery_records
    from pathscientist.dataset.discovery_types import DatasetDiscoveryRecord

    path = tmp_path / "nested" / "deep" / "discovery.json"
    save_discovery_records(path, [DatasetDiscoveryRecord(name="X")])
    assert path.exists()


def test_load_corrupt_json_returns_empty(tmp_path):
    """Corrupt artifacts must not crash the runner; just log + skip."""
    from pathscientist.dataset.discovery_store import load_discovery_records

    path = tmp_path / "discovery.json"
    path.write_text("{not json")
    assert load_discovery_records(path) == []


def test_load_non_list_payload_returns_empty(tmp_path):
    """Anything that isn't a JSON list is treated as no records."""
    from pathscientist.dataset.discovery_store import load_discovery_records

    path = tmp_path / "discovery.json"
    path.write_text(json.dumps({"records": []}))
    assert load_discovery_records(path) == []
