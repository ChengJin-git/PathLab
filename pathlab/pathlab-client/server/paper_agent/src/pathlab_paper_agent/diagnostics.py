"""Diagnostics and artifact-readiness checks for paper-generation runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import PaperAgentError
from .process_logging import PIPELINE_LOG_REL_PATH
from .schemas import (
    ArtifactReadinessIssue,
    PaperConfig,
    PaperManifest,
    PaperRunDiagnostics,
    PaperRunStage,
    StageDiagnostic,
)
from .storage import PaperRunPaths
from .stages.common import read_json


_BASE_REQUIRED: dict[PaperRunStage, tuple[str, ...]] = {
    PaperRunStage.collecting: (
        "inputs/source_tasks.json",
        "inputs/source_analyses.json",
    ),
    PaperRunStage.building_evidence: (
        "evidence/evidence_public.json",
        "evidence/evidence_lock.private.json",
        "tables/manifest.json",
    ),
    PaperRunStage.outlining: ("drafts/outline.json",),
    PaperRunStage.plotting: ("figures/manifest.json",),
    PaperRunStage.literature_review: (
        "citations/refs.bib",
        "citations/coverage_report.json",
    ),
    PaperRunStage.validating: ("validation/warnings.md",),
    PaperRunStage.refining: ("validation/refinement_log.json",),
}


def required_artifacts_for_stage(paths: PaperRunPaths, manifest: PaperManifest, stage: PaperRunStage) -> list[str]:
    required = list(_BASE_REQUIRED.get(stage, ()))
    if stage == PaperRunStage.section_writing:
        required.extend(_expected_section_paths(paths))
    elif stage == PaperRunStage.rendering:
        for template_id in _selected_template_ids(paths):
            required.extend(
                [
                    f"final/{template_id}/main.tex",
                    f"final/{template_id}/style.json",
                    f"final/{template_id}/main.compile_summary.txt",
                ]
            )
    elif stage == PaperRunStage.exporting:
        for template_id in _selected_template_ids(paths):
            required.append(f"exports/{template_id}_bundle.zip")
    return required


def artifact_readiness_issues(
    paths: PaperRunPaths,
    manifest: PaperManifest | None,
    *,
    stages: list[PaperRunStage] | None = None,
) -> list[ArtifactReadinessIssue]:
    issues: list[ArtifactReadinessIssue] = []
    if manifest is None:
        return [
            ArtifactReadinessIssue(
                code="missing_manifest",
                message="manifest.json is missing or unreadable.",
                severity="error",
                stage=None,
                path="manifest.json",
            )
        ]

    checked_stages = stages or _completed_or_current_stages(manifest)
    for stage in checked_stages:
        for rel_path in required_artifacts_for_stage(paths, manifest, stage):
            target = paths.root / rel_path
            if not target.is_file():
                issues.append(
                    ArtifactReadinessIssue(
                        code="missing_artifact",
                        message=f"Required artifact {rel_path} is missing after {stage.value}.",
                        severity="error",
                        stage=stage,
                        path=rel_path,
                    )
                )
                continue
            raw = manifest.artifact_index.get(rel_path)
            if raw is None:
                issues.append(
                    ArtifactReadinessIssue(
                        code="unregistered_artifact",
                        message=f"Artifact {rel_path} exists but is not registered in manifest.artifact_index.",
                        severity="warning",
                        stage=stage,
                        path=rel_path,
                    )
                )
            elif isinstance(raw, dict) and raw.get("stale") is True:
                issues.append(
                    ArtifactReadinessIssue(
                        code="stale_artifact",
                        message=f"Artifact {rel_path} is marked stale.",
                        severity="warning",
                        stage=stage,
                        path=rel_path,
                    )
                )

    issues.extend(_figure_manifest_issues(paths, manifest))
    return issues


def assert_stage_artifacts_ready(paths: PaperRunPaths, manifest: PaperManifest, stage: PaperRunStage) -> None:
    issues = [
        issue
        for issue in artifact_readiness_issues(paths, manifest, stages=[stage])
        if issue.severity == "error"
    ]
    if issues:
        raise PaperAgentError(
            "missing_artifact",
            "; ".join(issue.message for issue in issues[:5]),
            status_code=409,
            details={"stage": stage.value, "issues": [issue.model_dump(mode="json") for issue in issues]},
        )


def inspect_paper_run(paths: PaperRunPaths, manifest: PaperManifest | None = None) -> PaperRunDiagnostics:
    manifest = manifest or _load_manifest_or_none(paths)
    config = _load_config_or_none(paths)
    stage_diagnostics = _stage_diagnostics(manifest)
    issues = artifact_readiness_issues(paths, manifest)
    latest_error = _latest_error(manifest)
    return PaperRunDiagnostics(
        paper_id=paths.paper_id,
        status=manifest.status if manifest else None,
        current_stage=manifest.current_stage if manifest else None,
        title=config.title if config else None,
        selected_templates=config.selected_templates if config else [],
        source_task_ids=[item.task_id for item in config.source_tasks] if config else [],
        latest_error=latest_error,
        artifact_issues=issues,
        stage_diagnostics=stage_diagnostics,
        stage_log_count=len(manifest.stage_log) if manifest else 0,
        artifact_count=len(manifest.artifact_index) if manifest else 0,
        pipeline_log_path=PIPELINE_LOG_REL_PATH if (paths.root / PIPELINE_LOG_REL_PATH).is_file() else None,
        missing_artifact_count=sum(1 for issue in issues if issue.code == "missing_artifact"),
        stale_artifact_count=sum(1 for issue in issues if issue.code == "stale_artifact"),
    )


def _completed_or_current_stages(manifest: PaperManifest) -> list[PaperRunStage]:
    stages: list[PaperRunStage] = []
    for entry in manifest.stage_log:
        if str(entry.get("status")) not in {"completed", "failed"}:
            continue
        try:
            stage = PaperRunStage(str(entry.get("stage")))
        except ValueError:
            continue
        if stage not in stages:
            stages.append(stage)
    if manifest.current_stage not in stages:
        stages.append(manifest.current_stage)
    return stages


def _stage_diagnostics(manifest: PaperManifest | None) -> list[StageDiagnostic]:
    if manifest is None:
        return []
    latest: dict[str, dict[str, Any]] = {}
    for entry in manifest.stage_log:
        stage = str(entry.get("stage") or "")
        if stage:
            latest[stage] = entry
    diagnostics: list[StageDiagnostic] = []
    for stage, entry in sorted(latest.items()):
        diagnostics.append(
            StageDiagnostic(
                stage=stage,
                status=str(entry.get("status") or "unknown"),
                started_at=entry.get("started_at"),
                finished_at=entry.get("finished_at"),
                duration_ms=entry.get("duration_ms"),
                message=entry.get("message"),
                error_code=entry.get("error_code"),
                error_message=entry.get("error_message"),
            )
        )
    return diagnostics


def _latest_error(manifest: PaperManifest | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    for entry in reversed(manifest.stage_log):
        if entry.get("error_message") or str(entry.get("status")) == "failed":
            return {
                "stage": entry.get("stage"),
                "status": entry.get("status"),
                "code": entry.get("error_code") or "internal_error",
                "message": entry.get("error_message") or entry.get("message"),
                "ts": entry.get("ts"),
            }
    if manifest.error_message:
        return {"code": "internal_error", "message": manifest.error_message, "stage": manifest.current_stage.value}
    return None


def _figure_manifest_issues(paths: PaperRunPaths, manifest: PaperManifest) -> list[ArtifactReadinessIssue]:
    payload = _read_json_object(paths.figures_manifest)
    figures = payload.get("figures") if isinstance(payload.get("figures"), list) else []
    issues: list[ArtifactReadinessIssue] = []
    for item in figures:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        rel_path = item.get("path")
        figure_id = str(item.get("figure_id") or rel_path or "unknown")
        if status in {"failed", "missing"}:
            issues.append(
                ArtifactReadinessIssue(
                    code="figure_failed",
                    message=f"Figure {figure_id} is {status}.",
                    severity="error",
                    stage=PaperRunStage.plotting,
                    path=str(rel_path) if rel_path else None,
                )
            )
        if isinstance(rel_path, str) and rel_path and not (paths.root / rel_path).is_file():
            issues.append(
                ArtifactReadinessIssue(
                    code="missing_artifact",
                    message=f"Figure artifact {rel_path} is missing.",
                    severity="error",
                    stage=PaperRunStage.plotting,
                    path=rel_path,
                )
            )
    return issues


def _expected_section_paths(paths: PaperRunPaths) -> list[str]:
    if not paths.sections_dir.is_dir():
        return []
    return [path.relative_to(paths.root).as_posix() for path in sorted(paths.sections_dir.glob("*.tex")) if path.is_file()]


def _selected_template_ids(paths: PaperRunPaths) -> list[str]:
    config = _load_config_or_none(paths)
    if config is None:
        return []
    return [template.value for template in config.selected_templates]


def _load_config_or_none(paths: PaperRunPaths) -> PaperConfig | None:
    if not paths.config.exists():
        return None
    try:
        return PaperConfig.model_validate(read_json(paths.config))
    except Exception:
        return None


def _load_manifest_or_none(paths: PaperRunPaths) -> PaperManifest | None:
    if not paths.manifest.exists():
        return None
    try:
        return PaperManifest.model_validate(read_json(paths.manifest))
    except Exception:
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
