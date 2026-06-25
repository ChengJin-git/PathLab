# tests/test_sota_lookup.py
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from autoresearch.literature.sota_lookup import SotaLookup
from autoresearch.literature.sota_cache import SotaCache
from autoresearch.literature.types import (
    SotaTarget, ExtractedBenchmark, PaperRecord, BaselineEntry,
)


class _StubStore:
    def __init__(self, baselines: list[BaselineEntry] | None = None):
        self._b = baselines or []
    def get_baselines(self, dataset=None, task_type=None) -> list[BaselineEntry]:
        return list(self._b)


class _StubPwc:
    def __init__(self, slug: str | None, rows: list[ExtractedBenchmark] | None = None):
        self._slug = slug
        self._rows = rows or []
        self.slug_calls: list[str] = []
        self.board_calls: list[tuple[str, str]] = []
    def find_dataset(self, name): self.slug_calls.append(name); return self._slug
    def leaderboard(self, slug, metric):
        self.board_calls.append((slug, metric)); return self._rows


class _StubOnline:
    def __init__(self, papers: list[PaperRecord] | None = None):
        self._p = papers or []
    def search(self, query, top_k=5, organ="", task_type=""):
        return list(self._p)


class _StubExtractor:
    def __init__(self, rows: list[ExtractedBenchmark] | None = None):
        self._r = rows or []
    def extract(self, *, papers, dataset, task_type, metric):
        return list(self._r)


def test_cache_hit_returns_cached_target(tmp_path):
    cache = SotaCache(tmp_path / "c.json")
    t = SotaTarget(dataset="CRC-MSI", task_type="classification",
                   metric_name="auc", metric_value=0.9,
                   paper_id="p", paper_title="t", paper_url="u",
                   source="pwc", confidence="high",
                   retrieved_at=datetime.now(timezone.utc).isoformat())
    cache.put("CRC-MSI", "classification", "auc", t)
    lookup = SotaLookup(store=_StubStore(), cache=cache,
                        pwc_client=_StubPwc(slug="should-not-hit"))
    got = lookup.lookup(dataset="CRC-MSI", task_type="classification", metric="auc")
    assert got == t


def test_local_store_used_when_pwc_misses(tmp_path):
    """local_store is consulted only when PwC has no match."""
    pwc = _StubPwc(slug=None)  # PwC cannot resolve dataset
    lookup = SotaLookup(
        store=_StubStore(baselines=[BaselineEntry(
            method="ABMIL", metric_name="auc", metric_value=0.82,
            dataset="CRC-MSI", context="...",
            paper_id="local:p1", paper_title="abmil",
        )]),
        cache=SotaCache(tmp_path / "c.json"),
        pwc_client=pwc,
    )
    t = lookup.lookup(dataset="CRC-MSI", task_type="classification", metric="auc")
    assert t is not None
    assert t.metric_value == 0.82
    assert t.source == "local_store"
    # PwC must have been tried first.
    assert pwc.slug_calls == ["CRC-MSI"]


def test_pwc_used_before_local_store(tmp_path):
    """PwC is preferred over local_store even when both have a result."""
    pwc = _StubPwc(slug="crc-msi", rows=[
        ExtractedBenchmark(paper_id="pwc:k", method="KatherNet",
                           dataset="crc-msi", metric_name="auc",
                           metric_value=0.87, evidence="...",
                           confidence="high"),
    ])
    lookup = SotaLookup(
        store=_StubStore(baselines=[BaselineEntry(
            method="ABMIL", metric_name="auc", metric_value=0.82,
            dataset="CRC-MSI", context="...",
            paper_id="local:p1", paper_title="abmil",
        )]),
        cache=SotaCache(tmp_path / "c.json"),
        pwc_client=pwc,
    )
    t = lookup.lookup(dataset="CRC-MSI", task_type="classification", metric="auc")
    assert t is not None
    assert t.metric_value == 0.87
    assert t.source == "pwc"
    assert pwc.slug_calls == ["CRC-MSI"]
    assert pwc.board_calls == [("crc-msi", "auc")]


def test_openalex_plus_llm_used_when_pwc_empty(tmp_path):
    online = _StubOnline(papers=[
        PaperRecord(paper_id="openalex:W1", title="t", authors=["a"], year=2024,
                    abstract="0.91 AUC on CRC-MSI", venue="", source="openalex",
                    url="", methods=[], datasets=[], baselines=[],
                    organ="", task_type="", tags=[]),
    ])
    extractor = _StubExtractor(rows=[
        ExtractedBenchmark(paper_id="openalex:W1", method="NovelNet",
                           dataset="CRC-MSI", metric_name="auc",
                           metric_value=0.91, evidence="0.91 AUC on CRC-MSI",
                           confidence="medium"),
    ])
    lookup = SotaLookup(
        store=_StubStore(), cache=SotaCache(tmp_path / "c.json"),
        pwc_client=_StubPwc(slug=None),
        online_client=online, llm_extractor=extractor,
    )
    t = lookup.lookup(dataset="CRC-MSI", task_type="classification", metric="auc")
    assert t is not None
    assert t.metric_value == 0.91
    assert t.source == "openalex+llm"


def test_negative_result_cached_and_reused(tmp_path):
    cache = SotaCache(tmp_path / "c.json")
    pwc = _StubPwc(slug=None)
    online = _StubOnline(papers=[])
    lookup = SotaLookup(store=_StubStore(), cache=cache, pwc_client=pwc,
                        online_client=online,
                        llm_extractor=_StubExtractor(rows=[]))
    first = lookup.lookup(dataset="NADA", task_type="classification", metric="auc")
    assert first is None

    # Second call must not re-query PwC.
    pwc2 = _StubPwc(slug=None)
    lookup2 = SotaLookup(store=_StubStore(), cache=cache, pwc_client=pwc2,
                        online_client=online,
                        llm_extractor=_StubExtractor(rows=[]))
    second = lookup2.lookup(dataset="NADA", task_type="classification", metric="auc")
    assert second is None
    assert pwc2.slug_calls == []      # cache served the negative result


def test_offline_mode_skips_network_sources(tmp_path):
    pwc = _StubPwc(slug="x", rows=[ExtractedBenchmark(
        paper_id="p", method="m", dataset="x", metric_name="auc",
        metric_value=0.99, evidence="...", confidence="high")])
    lookup = SotaLookup(store=_StubStore(), cache=SotaCache(tmp_path / "c.json"),
                        pwc_client=pwc, offline=True)
    t = lookup.lookup(dataset="CRC-MSI", task_type="classification", metric="auc")
    assert t is None
    assert pwc.slug_calls == []


def test_highest_metric_wins_when_multiple_rows(tmp_path):
    pwc = _StubPwc(slug="s", rows=[
        ExtractedBenchmark(paper_id="p1", method="m1", dataset="s",
                           metric_name="auc", metric_value=0.80,
                           evidence="...", confidence="high"),
        ExtractedBenchmark(paper_id="p2", method="m2", dataset="s",
                           metric_name="auc", metric_value=0.89,
                           evidence="...", confidence="high"),
    ])
    lookup = SotaLookup(store=_StubStore(), cache=SotaCache(tmp_path / "c.json"),
                        pwc_client=pwc)
    t = lookup.lookup(dataset="S", task_type="classification", metric="auc")
    assert t.metric_value == 0.89
