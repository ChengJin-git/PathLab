"""Filesystem analysis discovery for PathLab analysis outputs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import (
    AnalysisArtifact,
    AnalysisRecord,
    AnalysisSummary,
    CollectorStatus,
    MissingEvidence,
    SourceTaskDescriptor,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def _parse_analysis_time(name: str) -> datetime | None:
    raw = name.removesuffix("_auto")
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d-%H%M%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _result_count(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("results", "items", "predictions", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return len(payload) if payload else 0
    return None


def _chart_paths(summary: dict[str, Any]) -> dict[str, str]:
    chart_paths = summary.get("chart_paths")
    if isinstance(chart_paths, dict):
        return {str(k): str(v) for k, v in chart_paths.items()}
    charts = summary.get("charts")
    if isinstance(charts, dict):
        return {str(k): str(v) for k, v in charts.items()}
    return {}


def _record_from_dir(path: Path) -> AnalysisRecord | None:
    summary_path = path / "summary.json"
    results_path = path / "results.json"
    if not summary_path.exists() and not results_path.exists():
        return None

    summary = _read_json(summary_path) if summary_path.exists() else {}
    results = _read_json(results_path) if results_path.exists() else {}
    charts = _chart_paths(summary)
    artifacts = [
        AnalysisArtifact(kind="summary", path=str(summary_path), exists=summary_path.exists()),
        AnalysisArtifact(kind="results", path=str(results_path), exists=results_path.exists()),
    ]
    for name, chart_path in charts.items():
        artifacts.append(
            AnalysisArtifact(kind=f"chart:{name}", path=chart_path, exists=Path(chart_path).exists())
        )

    return AnalysisRecord(
        analysis_id=path.name,
        analysis_dir=str(path),
        created_at=_parse_analysis_time(path.name),
        summary_path=str(summary_path) if summary_path.exists() else None,
        results_path=str(results_path) if results_path.exists() else None,
        summary=summary,
        results_count=_result_count(results),
        chart_paths=charts,
        artifacts=artifacts,
    )


def discover_analysis_runs(
    uploads_dir: Path,
    descriptor: SourceTaskDescriptor,
    *,
    selection: str = "latest",
    db_analysis_runs: list[dict[str, Any]] | None = None,
) -> AnalysisSummary:
    base = Path(uploads_dir) / "logs" / "analysis" / descriptor.task_id
    records: list[AnalysisRecord] = []
    if base.exists() and base.is_dir():
        for child in sorted(base.iterdir(), reverse=True):
            if child.is_dir() and (record := _record_from_dir(child)) is not None:
                records.append(record)

    records.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
    selected = records[0] if records else None
    missing: list[MissingEvidence] = []
    if selected is None:
        missing.append(
            MissingEvidence(
                item="analysis_summary",
                task_id=descriptor.task_id,
                reason="No complete analysis run with summary.json/results.json was found.",
            )
        )

    return AnalysisSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        status=CollectorStatus.ready if selected else CollectorStatus.missing,
        selection=selection,
        selected_analysis_id=selected.analysis_id if selected else None,
        analyses=records,
        db_analysis_runs=db_analysis_runs or [],
        missing_evidence=missing,
    )
