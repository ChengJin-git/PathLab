"""M11 critic-driven content refinement loop."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.agents.content_refinement_agent import (
    RUBRIC_DIMENSIONS,
    ContentRefinementAgent,
    ContentRefinementAgentError,
    CriticReview,
    RefinementInputs,
)
from pathlab_paper_agent.validators import (
    GuardReport,
    run_citation_guard,
    run_identifier_guard,
    run_latex_guard,
    run_metric_guard,
)
from pathlab_paper_agent.validators.claim_guard import run as run_claim_guard
from pathlab_paper_agent.validators.consistency_guard import run as run_consistency_guard

from .common import register_artifact, write_json, write_text

_MAX_ITERATIONS = 3
_GUARD_REPORT_PATHS = {
    "metric_guard": "validation/metric_guard.json",
    "identifier_guard": "validation/identifier_guard.json",
    "latex_guard": "validation/latex_guard.json",
    "citation_guard": "validation/citation_guard.json",
    "claim_guard": "validation/claim_guard.json",
    "consistency_guard": "validation/consistency_guard.json",
}
GuardRunner = Callable[[PaperRunPaths], list[GuardReport]]


@dataclass(frozen=True)
class HybridScore:
    """M11 monotonic score: critic rubric plus deterministic guard state."""

    total: int
    rubric_total: int
    dimensions: dict[str, int]
    guard_status: str
    guard_failures: tuple[str, ...]
    guard_error_count: int

    @classmethod
    def from_review_and_reports(
        cls,
        review: CriticReview | None,
        reports: Sequence[GuardReport],
    ) -> "HybridScore":
        dimensions = {
            dimension: (review.scores.get(dimension, 0) if review is not None else 0)
            for dimension in RUBRIC_DIMENSIONS
        }
        rubric_total = sum(dimensions.values())
        failed = tuple(report.guard for report in reports if report.status == "fail")
        error_count = sum(1 for report in reports for issue in report.issues if issue.severity == "error")
        return cls(
            total=rubric_total - (5 * error_count),
            rubric_total=rubric_total,
            dimensions=dimensions,
            guard_status="fail" if failed else "pass",
            guard_failures=failed,
            guard_error_count=error_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "rubric_total": self.rubric_total,
            "dimensions": dict(self.dimensions),
            "guard_status": self.guard_status,
            "guard_failures": list(self.guard_failures),
            "guard_error_count": self.guard_error_count,
        }


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: ContentRefinementAgent | None = None,
    max_iterations: int = _MAX_ITERATIONS,
    guard_runner: GuardRunner | None = None,
) -> None:
    """Run at most three critic -> revise -> guards refinement iterations."""
    refinement_agent = agent or ContentRefinementAgent()
    iterations = max(0, min(max_iterations, _MAX_ITERATIONS))
    run_guards = guard_runner or _run_guard_reports

    initial_reports = run_guards(paths)
    _write_guard_reports(paths, manifest, initial_reports)
    initial_sections = _read_sections(paths)
    initial_inputs = RefinementInputs.from_paths(
        paths,
        sections=initial_sections,
        validation_reports=[report.to_dict() for report in initial_reports],
        iteration=0,
    )
    previous_review = refinement_agent.critique(initial_inputs)
    previous_score = HybridScore.from_review_and_reports(previous_review, initial_reports)
    log: dict[str, Any] = {
        "max_iterations": iterations,
        "initial_score": previous_score.to_dict(),
        "initial_critic": previous_review.to_dict(),
        "iterations": [],
        "accepted_iterations": [],
        "final_status": "not_started" if iterations == 0 else "unchanged",
    }

    for iteration in range(1, iterations + 1):
        current_sections = _read_sections(paths)
        inputs = RefinementInputs.from_paths(
            paths,
            sections=current_sections,
            validation_reports=[report.to_dict() for report in initial_reports],
            iteration=iteration,
        )
        snapshot_dir = _snapshot_sections(paths, iteration)
        iteration_log: dict[str, Any] = {
            "iteration": iteration,
            "snapshot": _rel_to_run(paths, snapshot_dir),
            "snapshot_files": _snapshot_files(paths, snapshot_dir),
            "accepted": False,
            "reason": "not_evaluated",
        }
        try:
            revision = refinement_agent.revise(inputs, previous_review)
            candidate_sections = dict(current_sections)
            candidate_sections.update(revision.sections)
            _write_sections(paths, candidate_sections)
            reports = run_guards(paths)
            if any(report.status == "fail" for report in reports):
                candidate_review = None
                score = HybridScore.from_review_and_reports(None, reports)
                accepted = False
                reason = "force_reject_guard_fail"
            else:
                candidate_inputs = RefinementInputs.from_paths(
                    paths,
                    sections=candidate_sections,
                    validation_reports=[report.to_dict() for report in reports],
                    iteration=iteration,
                )
                candidate_review = refinement_agent.critique(candidate_inputs)
                score = HybridScore.from_review_and_reports(candidate_review, reports)
                accepted, reason = _acceptance_decision(previous_score, score)
            iteration_log.update(
                {
                    "baseline_critic": previous_review.to_dict(),
                    "revision": revision.to_dict(),
                    "score": score.to_dict(),
                    "guard_reports": [report.to_dict() for report in reports],
                    "accepted": accepted,
                    "reason": reason,
                }
            )
            if candidate_review is not None:
                iteration_log["candidate_critic"] = candidate_review.to_dict()
            if accepted:
                previous_score = score
                previous_review = candidate_review or previous_review
                initial_reports = reports
                _write_guard_reports(paths, manifest, reports)
                log["accepted_iterations"].append(iteration)
                log["final_status"] = "accepted"
                log["iterations"].append(iteration_log)
                continue

            _restore_sections(snapshot_dir, paths.sections_dir)
            restored_reports = run_guards(paths)
            _write_guard_reports(paths, manifest, restored_reports)
            log["iterations"].append(iteration_log)
            log["final_status"] = "rejected"
            break
        except (ContentRefinementAgentError, RuntimeError, ValueError, KeyError) as exc:
            _restore_sections(snapshot_dir, paths.sections_dir)
            restored_reports = run_guards(paths)
            _write_guard_reports(paths, manifest, restored_reports)
            iteration_log.update(
                {
                    "accepted": False,
                    "reason": "force_reject_refinement_error",
                    "error": str(exc),
                    "score": previous_score.to_dict(),
                    "guard_reports": [report.to_dict() for report in restored_reports],
                }
            )
            log["iterations"].append(iteration_log)
            log["final_status"] = "rejected"
            break
    else:
        if log["accepted_iterations"]:
            log["final_status"] = "accepted"
        elif iterations > 0:
            log["final_status"] = "unchanged"

    write_json(paths.validation_dir / "refinement_log.json", log)
    register_artifact(
        manifest,
        "validation/refinement_log.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Refinement log",
        content_type="application/json",
    )


def _acceptance_decision(previous: HybridScore, current: HybridScore) -> tuple[bool, str]:
    if current.total > previous.total:
        return True, "score_increased"
    if current.total < previous.total:
        return False, "score_decreased"
    regressions = [
        dimension
        for dimension in RUBRIC_DIMENSIONS
        if current.dimensions.get(dimension, 0) < previous.dimensions.get(dimension, 0)
    ]
    if regressions:
        return False, "score_tied_with_subaxis_regression: " + ", ".join(regressions)
    return True, "score_tied_no_subaxis_regression"


def _run_guard_reports(paths: PaperRunPaths) -> list[GuardReport]:
    return [
        run_metric_guard(paths),
        run_identifier_guard(paths),
        run_latex_guard(paths),
        run_citation_guard(paths),
        run_claim_guard(paths),
        run_consistency_guard(paths),
    ]


def _write_guard_reports(paths: PaperRunPaths, manifest: PaperManifest, reports: Sequence[GuardReport]) -> None:
    for report in reports:
        rel_path = _GUARD_REPORT_PATHS[report.guard]
        write_json(paths.root / rel_path, report.to_dict())
        register_artifact(
            manifest,
            rel_path,
            visibility="private_backend_only",
            downloadable=False,
            label=report.guard.replace("_", " ").title(),
            content_type="application/json",
        )
    write_text(paths.validation_dir / "warnings.md", _warnings_markdown(reports))
    register_artifact(
        manifest,
        "validation/warnings.md",
        label="Validation warnings",
        content_type="text/markdown",
    )


def _warnings_markdown(reports: Sequence[GuardReport]) -> str:
    lines = ["# Validation Warnings", ""]
    if all(report.status == "pass" for report in reports):
        lines.extend(["All deterministic M10 guards passed.", ""])
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


def _snapshot_sections(paths: PaperRunPaths, iteration: int) -> Path:
    snapshot_dir = paths.snapshots_dir / f"iter_{iteration}" / "sections"
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if paths.sections_dir.exists():
        for path in sorted(paths.sections_dir.glob("*.tex")):
            if path.is_file():
                shutil.copy2(path, snapshot_dir / path.name)
    return snapshot_dir


def _restore_sections(snapshot_dir: Path, sections_dir: Path) -> None:
    if sections_dir.exists():
        shutil.rmtree(sections_dir)
    sections_dir.mkdir(parents=True, exist_ok=True)
    if not snapshot_dir.exists():
        return
    for path in sorted(snapshot_dir.glob("*.tex")):
        if path.is_file():
            shutil.copy2(path, sections_dir / path.name)


def _snapshot_files(paths: PaperRunPaths, snapshot_dir: Path) -> list[str]:
    return [_rel_to_run(paths, path) for path in sorted(snapshot_dir.glob("*.tex")) if path.is_file()]


def _read_sections(paths: PaperRunPaths) -> dict[str, str]:
    if not paths.sections_dir.exists():
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(paths.sections_dir.glob("*.tex"))
        if path.is_file()
    }


def _write_sections(paths: PaperRunPaths, sections: dict[str, str]) -> None:
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    for name, text in sections.items():
        write_text(paths.sections_dir / f"{name}.tex", text)


def _rel_to_run(paths: PaperRunPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)
