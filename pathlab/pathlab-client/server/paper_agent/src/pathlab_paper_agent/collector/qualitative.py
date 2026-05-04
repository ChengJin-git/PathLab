"""Qualitative artifact discovery without loading large arrays."""

from __future__ import annotations

import zipfile
from pathlib import Path

from .schemas import (
    AnalysisArtifact,
    AnalysisSummary,
    CollectorStatus,
    MissingEvidence,
    QualitativeSummary,
    SourceTaskDescriptor,
)

_ARTIFACT_GROUPS = ("attention", "attention_raw", "cam", "pred_mask")


def _inspect_zarr_zip(path: Path) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    result_keys: set[str] = set()
    groups: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                parts = Path(name).parts
                if len(parts) >= 3 and parts[0] == "results":
                    result_keys.add(parts[1])
                if parts and parts[0] in _ARTIFACT_GROUPS:
                    groups.add(parts[0])
    except zipfile.BadZipFile:
        return 0, []
    return len(result_keys), sorted(groups)


def build_qualitative_summary(
    uploads_dir: Path,
    descriptor: SourceTaskDescriptor,
    analysis: AnalysisSummary | None = None,
) -> QualitativeSummary:
    bundle_path = Path(uploads_dir) / "ai_results_bundles" / f"{descriptor.task_id}.zarr.zip"
    result_count, available = _inspect_zarr_zip(bundle_path)
    chart_artifacts: list[AnalysisArtifact] = []
    if analysis:
        for record in analysis.analyses[:1]:
            chart_artifacts.extend(
                artifact for artifact in record.artifacts if artifact.kind.startswith("chart:")
            )

    missing: list[MissingEvidence] = []
    if not bundle_path.exists() and not chart_artifacts:
        missing.append(
            MissingEvidence(
                item="qualitative_artifacts",
                task_id=descriptor.task_id,
                reason="No AI result bundle or analysis chart artifacts were found.",
                severity="warning",
            )
        )

    has_artifacts = bundle_path.exists() or bool(chart_artifacts)
    return QualitativeSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        status=CollectorStatus.ready if has_artifacts else CollectorStatus.missing,
        ai_result_bundle=str(bundle_path) if bundle_path.exists() else None,
        bundle_exists=bundle_path.exists(),
        result_count=result_count,
        available_artifacts=available,
        chart_artifacts=chart_artifacts,
        missing_evidence=missing,
    )
