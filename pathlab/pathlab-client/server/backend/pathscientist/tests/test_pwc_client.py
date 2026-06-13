from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from pathscientist.literature.pwc_client import PapersWithCodeClient


class _FakeResponse:
    def __init__(self, status: int, body: dict | list):
        self.status_code = status
        self._body = body
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_find_dataset_returns_slug(monkeypatch):
    calls: list[str] = []
    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return _FakeResponse(200, {"results": [{"id": "crc-msi", "name": "CRC-MSI"}]})
    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    c = PapersWithCodeClient()
    assert c.find_dataset("CRC-MSI") == "crc-msi"
    assert any("datasets" in u for u in calls)


def test_find_dataset_returns_none_on_empty(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(200, {"results": []}))
    c = PapersWithCodeClient()
    assert c.find_dataset("UNKNOWN-DATASET") is None


def test_leaderboard_returns_extracted_benchmarks(monkeypatch):
    sample = {"results": [
        {"methodology": "KatherNet",
         "paper": {"id": "kather2019", "title": "Deep learning MSI",
                   "url_pdf": "https://example.org/k.pdf"},
         "metrics": [{"name": "AUC", "value": 0.87}]},
        {"methodology": "ResNet50",
         "paper": {"id": "p2", "title": "baseline", "url_pdf": ""},
         "metrics": [{"name": "AUC", "value": 0.80}]},
    ]}
    import requests
    monkeypatch.setattr(requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(200, sample))
    c = PapersWithCodeClient()
    rows = c.leaderboard("crc-msi", "auc")
    assert len(rows) == 2
    assert rows[0].method == "KatherNet"
    assert rows[0].metric_value == 0.87
    assert rows[0].paper_id == "pwc:kather2019"
    assert rows[1].metric_value == 0.80


def test_leaderboard_filters_by_metric_name(monkeypatch):
    sample = {"results": [
        {"methodology": "X", "paper": {"id": "p1", "title": "t", "url_pdf": ""},
         "metrics": [{"name": "Accuracy", "value": 0.9}]},
        {"methodology": "Y", "paper": {"id": "p2", "title": "t", "url_pdf": ""},
         "metrics": [{"name": "AUC", "value": 0.8}]},
    ]}
    import requests
    monkeypatch.setattr(requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(200, sample))
    c = PapersWithCodeClient()
    rows = c.leaderboard("crc-msi", "auc")
    assert len(rows) == 1
    assert rows[0].method == "Y"


def test_leaderboard_http_error_returns_empty(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get",
        lambda url, params=None, timeout=None: _FakeResponse(503, {}))
    c = PapersWithCodeClient()
    assert c.leaderboard("x", "auc") == []
