"""Validation stage: run deterministic M10a guards."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.validators import (
    GuardReport,
    run_citation_guard,
    run_identifier_guard,
    run_latex_guard,
    run_metric_guard,
)

from .common import register_artifact, write_json, write_text


def _warnings_markdown(reports: list[GuardReport]) -> str:
    lines = ["# Validation Warnings", ""]
    failed = [report for report in reports if report.status == "fail"]
    if not failed:
        lines.append("All deterministic M10a guards passed.")
        lines.append("")
    for report in reports:
        lines.append(f"## {report.guard}: {report.status}")
        if not report.issues:
            lines.append("- No issues.")
        for issue in report.issues:
            path = f" ({issue.path})" if issue.path else ""
            context = f" — `{issue.context}`" if issue.context else ""
            lines.append(f"- {issue.severity}: {issue.code}{path}: {issue.message}{context}")
        lines.append("")
    return "\n".join(lines)


def _register_report(manifest: PaperManifest, rel_path: str, label: str) -> None:
    register_artifact(
        manifest,
        rel_path,
        visibility="private_backend_only",
        downloadable=False,
        label=label,
        content_type="application/json",
    )


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    reports = [
        run_metric_guard(paths),
        run_identifier_guard(paths),
        run_latex_guard(paths),
        run_citation_guard(paths),
    ]

    report_paths = {
        "metric_guard": "validation/metric_guard.json",
        "identifier_guard": "validation/identifier_guard.json",
        "latex_guard": "validation/latex_guard.json",
        "citation_guard": "validation/citation_guard.json",
    }
    for report in reports:
        rel_path = report_paths[report.guard]
        write_json(paths.root / rel_path, report.to_dict())
        _register_report(manifest, rel_path, report.guard.replace("_", " ").title())

    write_text(paths.validation_dir / "warnings.md", _warnings_markdown(reports))
    register_artifact(
        manifest,
        "validation/warnings.md",
        label="Validation warnings",
        content_type="text/markdown",
    )

    failed = [report.guard for report in reports if report.status == "fail"]
    if failed:
        raise RuntimeError(f"validation guards failed: {', '.join(failed)}")
