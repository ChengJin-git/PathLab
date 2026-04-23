from __future__ import annotations
import json, time, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from pathscientist.literature.sota_cache import SotaCache, Miss
from pathscientist.literature.types import SotaTarget


def _target(value: float = 0.87) -> SotaTarget:
    return SotaTarget(
        dataset="CRC-MSI", task_type="classification",
        metric_name="auc", metric_value=value,
        paper_id="p1", paper_title="t", paper_url="u",
        source="pwc", confidence="high",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def test_cache_miss_on_empty(tmp_path):
    c = SotaCache(tmp_path / "sota.json")
    assert c.get("CRC-MSI", "classification", "auc") is Miss


def test_cache_roundtrip(tmp_path):
    c = SotaCache(tmp_path / "sota.json")
    t = _target(0.9)
    c.put("CRC-MSI", "classification", "auc", t)
    got = c.get("CRC-MSI", "classification", "auc")
    assert got == t


def test_cache_negative_entry_returned_as_none(tmp_path):
    """put(..., None) = "we looked and found nothing"; distinct from Miss."""
    c = SotaCache(tmp_path / "sota.json")
    c.put("FAKE-DATASET", "classification", "auc", None)
    assert c.get("FAKE-DATASET", "classification", "auc") is None  # NOT Miss


def test_cache_key_case_insensitive(tmp_path):
    c = SotaCache(tmp_path / "sota.json")
    c.put("CRC-MSI", "classification", "auc", _target())
    assert c.get("crc-msi", "classification", "AUC") is not Miss


def test_cache_expired_entry_returns_miss(tmp_path):
    c = SotaCache(tmp_path / "sota.json", ttl_days=30)
    t = _target()
    c.put("CRC-MSI", "classification", "auc", t)
    # Manually rewrite retrieved_at to 40 days ago.
    raw = json.loads((tmp_path / "sota.json").read_text())
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    for row in raw.values():
        row["retrieved_at"] = stale
    (tmp_path / "sota.json").write_text(json.dumps(raw))
    c2 = SotaCache(tmp_path / "sota.json", ttl_days=30)
    assert c2.get("CRC-MSI", "classification", "auc") is Miss


def test_cache_corrupted_file_returns_miss(tmp_path):
    path = tmp_path / "sota.json"
    path.write_text("{this is not json")
    c = SotaCache(path)
    assert c.get("x", "y", "z") is Miss
    # Must be recoverable: subsequent put + get works.
    c.put("CRC-MSI", "classification", "auc", _target())
    assert c.get("CRC-MSI", "classification", "auc") is not Miss
