"""Tests for deterministic report builder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.synthesis.report_builder import build_report, render_report_markdown


def _make_context(**overrides):
    defaults = {
        "objective": "Improve AUC on BRACS",
        "success_metric": "auc",
        "best_run": {"run_id": "run_003", "primary_metric_value": 0.8844},
        "comparison_table": [
            {"run_id": "run_001", "primary_metric_value": 0.81, "committed": True, "error_type": ""},
            {"run_id": "run_002", "primary_metric_value": 0.77, "committed": False, "error_type": "CUDA_OOM"},
            {"run_id": "run_003", "primary_metric_value": 0.8844, "committed": True, "error_type": ""},
        ],
        "failures": [
            {"run_id": "run_002", "error_type": "CUDA_OOM", "error_hint": "Reduce batch size"}
        ],
        "references": [
            {"paper_id": "transmil_2021", "context": "TransMIL baseline 0.85 AUC"}
        ],
        "run_history": [],
        "reproducibility": {
            "session_id": "sess1",
            "conversation_id": "conv1",
            "total_iterations": 3,
            "committed_runs": 2,
            "reverted_runs": 1,
        },
    }
    defaults.update(overrides)
    return defaults


def test_build_report_creates_structured_report():
    ctx = _make_context()
    report = build_report(ctx)
    assert report.best_run_id == "run_003"
    assert report.best_metric_value == 0.8844
    assert len(report.claims) >= 3  # result + comparison + limitation + repro
    assert len(report.sections) >= 3  # results + limitations + reproducibility


def test_render_report_markdown_contains_all_sections():
    ctx = _make_context()
    report = build_report(ctx)
    md = render_report_markdown(report)

    assert "# Research Report" in md
    assert "## Results" in md
    assert "run_003" in md
    assert "0.8844" in md
    assert "## Failures And Limitations" in md
    assert "CUDA_OOM" in md
    assert "## Reproducibility" in md
    assert "## References" in md
    assert "transmil_2021" in md


def test_render_report_markdown_without_failures():
    ctx = _make_context(failures=[])
    report = build_report(ctx)
    md = render_report_markdown(report)

    assert "## Results" in md
    assert "Failures" not in md


# --- Integrity Issues section compactness (Finding 7, 2026-04-22 review) --


def _make_integrity_report(fatal: int, warning: int) -> dict:
    """Build a serialized integrity_report dict with ``fatal`` + ``warning`` issues."""
    issues = []
    for idx in range(fatal):
        issues.append({
            "code": f"fatal_code_{idx}",
            "severity": "fatal",
            "message": (
                f"Fatal issue {idx} first sentence goes here. "
                f"Subsequent sentences include long context paths like "
                f"/tmp/evidence/runs/run_{idx}/record.json and extra prose."
            ),
            "context": {"idx": idx},
        })
    for idx in range(warning):
        issues.append({
            "code": f"warn_code_{idx}",
            "severity": "warning",
            "message": (
                f"Warning issue {idx} first sentence goes here. "
                f"Deliberate out-of-band experiment — prefer running through "
                f"run_experiment when possible."
            ),
            "context": {"idx": idx},
        })
    return {
        "passed": fatal == 0,
        "fatal_count": fatal,
        "warning_count": warning,
        "issues": issues,
    }


def test_integrity_section_is_compact():
    """Regression for Finding 7: even with 3 fatal + 5 warning issues, the
    ## Integrity Issues section must stay around one preamble line + one
    bullet per issue (no multi-paragraph defensive prose, no markdown
    table). Cap at 15 lines so the section can never dominate Results.
    """
    ctx = _make_context()
    integrity_report = _make_integrity_report(fatal=3, warning=5)
    report = build_report(ctx, integrity_report=integrity_report)
    md = render_report_markdown(report)

    # Extract just the Integrity Issues section.
    header = "## Integrity Issues"
    assert header in md
    start = md.index(header)
    # Next section marker (## X) or EOF.
    rest = md[start + len(header):]
    next_section_offset = rest.find("\n## ")
    if next_section_offset == -1:
        section_body = rest
    else:
        section_body = rest[:next_section_offset]

    # Section title line + body ≤ 15 lines total (incl. blank lines).
    full_section = header + section_body
    total_lines = full_section.count("\n") + 1
    assert total_lines <= 15, (
        f"Integrity Issues section expanded to {total_lines} lines with 3 "
        f"fatal + 5 warning issues; expected ≤ 15.\n---\n{full_section}\n---"
    )

    # No defensive / apologetic prose fragments.
    for forbidden in (
        "This finding highlights",
        "It should be noted",
        "fundamental flaw",
        "constructive reminder",
        "opportunity to strengthen",
    ):
        assert forbidden not in full_section, (
            f"Defensive prose '{forbidden}' leaked back into integrity "
            f"section:\n{full_section}"
        )

    # No markdown table syntax (the old format rendered each issue as a
    # table row; the new format is a bulleted list).
    assert "| Severity |" not in full_section
    assert "|----------|" not in full_section

    # Each issue code still appears so the section retains diagnostic value.
    for idx in range(3):
        assert f"fatal_code_{idx}" in full_section
    for idx in range(5):
        assert f"warn_code_{idx}" in full_section


def test_integrity_section_omitted_when_clean():
    """A clean session must leave no integrity footprint in report.md.

    When no issues are reported, the rendered markdown should contain no
    ``## Integrity Issues`` header at all — a clean session shouldn't have
    to carry defensive plumbing through the report.
    """
    ctx = _make_context()
    # Pass an empty integrity_report explicitly.
    report = build_report(ctx, integrity_report={"passed": True, "fatal_count": 0, "warning_count": 0, "issues": []})
    md = render_report_markdown(report)
    assert "## Integrity Issues" not in md


def test_integrity_section_uses_bulleted_list_format():
    """The compact section must be a bulleted list of
    ``- [severity] code: first-line message`` rows, not a table."""
    ctx = _make_context()
    integrity_report = {
        "passed": False,
        "fatal_count": 0,
        "warning_count": 1,
        "issues": [
            {
                "code": "evidence_run_missing",
                "severity": "warning",
                "message": (
                    "Committed run 'run_xyz' was marked external (opt-in); no "
                    "evidence record at /some/path. Deliberate out-of-band "
                    "experiment — prefer running through run_experiment when "
                    "possible."
                ),
                "context": {},
            }
        ],
    }
    report = build_report(ctx, integrity_report=integrity_report)
    md = render_report_markdown(report)

    # Preamble shape: "Session-end integrity report: 0 fatal, 1 warning."
    assert "Session-end integrity report: 0 fatal, 1 warning." in md
    # Bullet row shape: "- [warning] evidence_run_missing: ..."
    assert "- [warning] evidence_run_missing:" in md
    # The trailing explanatory clause must be cut (first sentence only).
    assert "prefer running through run_experiment" not in md


def test_external_validation_renders_separate_section():
    ctx = _make_context(
        best_run={"run_id": "run_internal", "primary_metric_value": 0.81},
        comparison_table=[
            {"run_id": "run_internal", "primary_metric_value": 0.81, "committed": True, "error_type": ""},
        ],
        external_test_history=[
            {
                "run_id": "run_external",
                "metrics": {
                    "auc": 0.76,
                    "accuracy": 0.7,
                    "external_task_type": "mil_classification",
                },
                "dataset_name": "External cohort A",
                "committed": True,
            }
        ],
    )

    report = build_report(ctx)
    md = render_report_markdown(report)

    assert "## External Validation" in md
    assert "External cohort A" in md
    assert "run_external" in md
    assert "0.7600" in md
    assert "**Best Result:** 0.8100 (run_internal)" in md
    assert "| 0 | run_external |" not in md


def test_external_validation_resolves_prefixed_metric_and_escapes_table_cells():
    ctx = _make_context(
        external_test_history=[
            {
                "run_id": "run_external|pipe",
                "metrics": {
                    "external_auc": 0.765,
                    "external_task_type": "mil|classification",
                },
                "dataset_name": "External | Cohort",
                "status": "completed|ok",
            }
        ],
    )

    report = build_report(ctx)
    md = render_report_markdown(report)

    assert "0.7650" in md
    assert "External \\| Cohort" in md
    assert "run_external\\|pipe" in md
    assert "mil\\|classification" in md
    assert "completed\\|ok" in md


# --- Dataset section (T8a: surface acquisition in synthesis) -----------------


def _make_acquisition_context(status: str, **acq_overrides):
    """Helper: a minimal context with an ``acquisition`` block."""
    ctx = _make_context(failures=[])
    selected = {
        "dataset_id": "hf:demo/x",
        "name": "Demo",
        "provider": "huggingface",
        "access": "public",
        "license": "CC-BY-4.0",
    }
    acq = {
        "status": status,
        "manifest_path": "/workspace/.dataset/manifest.json",
        "selected_dataset": selected,
        "notes": "",
    }
    acq.update(acq_overrides)
    ctx["acquisition"] = acq
    return ctx


def test_report_includes_dataset_section_when_acquisition_prepared():
    """When acquisition.status == 'prepared', a ``dataset`` section is emitted
    with the dataset name, provider, license, and manifest path."""
    ctx = _make_acquisition_context("prepared")
    report = build_report(ctx)
    section_names = [s.name for s in report.sections]
    assert "dataset" in section_names
    dataset_section = next(s for s in report.sections if s.name == "dataset")
    assert "Demo" in dataset_section.content
    assert "huggingface" in dataset_section.content
    assert "/workspace/.dataset/manifest.json" in dataset_section.content
    # Rendered markdown should also contain the section.
    md = render_report_markdown(report)
    assert "## Dataset" in md
    assert "Demo" in md


def test_report_omits_dataset_section_when_acquisition_none():
    """Default ``acquisition.status == 'none'`` -> no dataset section."""
    ctx = _make_context(failures=[])
    # No "acquisition" key at all → the helper still must not emit a section.
    report = build_report(ctx)
    section_names = [s.name for s in report.sections]
    assert "dataset" not in section_names
    md = render_report_markdown(report)
    assert "## Dataset" not in md


def test_report_omits_dataset_section_when_acquisition_skipped_policy():
    """``skipped_policy`` -> no dataset section here (limitations path
    surfaces it elsewhere; the dataset section is for the *prepared* path)."""
    ctx = _make_acquisition_context(
        "skipped_policy",
        selected_dataset={},
        notes="access=gated",
    )
    report = build_report(ctx)
    section_names = [s.name for s in report.sections]
    assert "dataset" not in section_names
    md = render_report_markdown(report)
    assert "## Dataset" not in md


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
