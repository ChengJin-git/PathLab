"""Structured benchmark store for literature-derived metric rows."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from .types import BenchmarkRecord


_WS_RE = re.compile(r"\s+")
_VERIFIED_STATUSES = {"verified", "human_verified"}
_SOTA_CONFIDENCE = {"medium", "high"}


def _norm(value: str | None) -> str:
    return _WS_RE.sub(" ", (value or "").strip().lower())


def _matches_text(actual: str, expected: str | None, *, allow_multi_organ: bool = False) -> bool:
    if not expected:
        return True
    actual_n = _norm(actual)
    expected_n = _norm(expected)
    if not actual_n:
        return False
    if actual_n == expected_n:
        return True
    if allow_multi_organ and actual_n == "multi-organ":
        return True
    return expected_n in actual_n


def is_sota_eligible(record: BenchmarkRecord) -> bool:
    """True when a local benchmark can be promoted to a hard SOTA target."""
    return (
        _norm(record.verification_status) in _VERIFIED_STATUSES
        and _norm(record.confidence) in _SOTA_CONFIDENCE
    )


class BenchmarkStore:
    """JSON-backed benchmark records under ``literature/benchmarks/``.

    Explicit verified benchmark rows can be written here over time. Legacy
    paper-local baselines are supplied by ``LiteratureStore`` as extra records
    and remain low-confidence references unless separately verified.
    """

    def __init__(self, literature_dir: Path):
        self._dir = Path(literature_dir) / "benchmarks"
        self._path = self._dir / "index.json"
        self._dir.mkdir(parents=True, exist_ok=True)

    def add(self, record: BenchmarkRecord) -> None:
        rows = [r for r in self.list_benchmarks() if r.benchmark_id != record.benchmark_id]
        rows.append(record)
        self._write(rows)

    def list_benchmarks(self) -> list[BenchmarkRecord]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        rows: list[BenchmarkRecord] = []
        for item in data:
            try:
                rows.append(BenchmarkRecord.from_dict(item))
            except Exception:
                continue
        return rows

    def query(
        self,
        *,
        dataset: str | None = None,
        task_type: str | None = None,
        organ: str | None = None,
        prediction_target: str | None = None,
        metric_name: str | None = None,
        verified_only: bool = False,
        top_k: int | None = None,
        extra_records: Iterable[BenchmarkRecord] | None = None,
    ) -> list[BenchmarkRecord]:
        rows = self.list_benchmarks()
        if extra_records:
            explicit_ids = {r.benchmark_id for r in rows}
            rows.extend(r for r in extra_records if r.benchmark_id not in explicit_ids)

        filtered = [
            row for row in rows
            if self._matches(
                row,
                dataset=dataset,
                task_type=task_type,
                organ=organ,
                prediction_target=prediction_target,
                metric_name=metric_name,
                verified_only=verified_only,
            )
        ]
        filtered.sort(key=lambda r: r.metric_value, reverse=True)
        if top_k is not None:
            return filtered[:max(0, int(top_k))]
        return filtered

    def _matches(
        self,
        row: BenchmarkRecord,
        *,
        dataset: str | None,
        task_type: str | None,
        organ: str | None,
        prediction_target: str | None,
        metric_name: str | None,
        verified_only: bool,
    ) -> bool:
        if verified_only and not is_sota_eligible(row):
            return False
        if dataset and _norm(row.dataset) != _norm(dataset):
            return False
        if metric_name and _norm(row.metric_name) != _norm(metric_name):
            return False
        if not _matches_text(row.task_type, task_type):
            return False
        if not _matches_text(row.organ, organ, allow_multi_organ=bool(dataset)):
            return False
        if not _matches_text(row.prediction_target, prediction_target):
            return False
        return True

    def _write(self, rows: list[BenchmarkRecord]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([r.to_dict() for r in rows], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
