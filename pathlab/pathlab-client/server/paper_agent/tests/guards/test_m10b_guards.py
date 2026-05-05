from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.schemas import PaperManifest
from pathlab_paper_agent.stages.validating import run as run_validating
from pathlab_paper_agent.validators.claim_guard import derive_evidence_flags, run as run_claim_guard
from pathlab_paper_agent.validators.consistency_guard import run as run_consistency_guard


@pytest.mark.asyncio
async def test_claim_guard_flags_unsupported_external_baseline_and_stats_claims(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_claim_fail", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "source_tasks": [{"task_id": "main_task", "role": "main"}],
                "external_validation": [],
                "metrics": {"main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123}},
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "discussion.tex").write_text(
        "External validation on an independent cohort supports generalization to deployment.\n\n"
        "The method outperforms state-of-the-art alternatives and is statistically significant.\n",
        encoding="utf-8",
    )

    report = run_claim_guard(paths)

    assert report.status == "fail"
    assert report.metadata["has_external_validation"] is False
    assert report.metadata["has_baseline"] is False
    assert report.metadata["has_statistical_test"] is False
    codes = {issue.code for issue in report.issues}
    assert "unsupported_external_validation_claim" in codes
    assert "unsupported_baseline_comparison_claim" in codes
    assert "unsupported_statistical_significance_claim" in codes
    assert all("missing=" in str(issue.context) for issue in report.issues)


@pytest.mark.asyncio
async def test_claim_guard_derives_support_flags_from_existing_evidence_lock(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_claim_pass", uploads_dir=tmp_path)
    paths.ensure_dirs()
    evidence_lock = {
        "source_tasks": [
            {"task_id": "main_task", "role": "main"},
            {"task_id": "baseline_task", "role": "baseline"},
        ],
        "external_validation": [{"task_id": "ext_task", "status": "ready"}],
        "metrics": {
            "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123},
            "main.metrics.p_value": {"formatted": "p < 0.05", "value": 0.01},
        },
    }
    paths.evidence_lock_private.write_text(json.dumps(evidence_lock), encoding="utf-8")
    (paths.sections_dir / "results.tex").write_text(
        "External validation on an independent cohort is reported. "
        "The method outperforms the baseline and is statistically significant.\n",
        encoding="utf-8",
    )

    flags = derive_evidence_flags(evidence_lock)
    report = run_claim_guard(paths)

    assert flags == {
        "has_external_validation": True,
        "has_baseline": True,
        "has_statistical_test": True,
    }
    assert report.status == "pass"


@pytest.mark.asyncio
async def test_claim_guard_does_not_flag_negated_external_evidence_statement(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_claim_negated", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps({"source_tasks": [{"role": "main"}], "external_validation": [], "metrics": {}}),
        encoding="utf-8",
    )
    (paths.sections_dir / "limitations.tex").write_text(
        "No external validation evidence was available for this run.\n",
        encoding="utf-8",
    )

    report = run_claim_guard(paths)

    assert report.status == "pass"


@pytest.mark.asyncio
async def test_claim_guard_does_not_flag_negated_baseline_or_statistical_statements(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_claim_negated_other", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps({"source_tasks": [{"role": "main"}], "external_validation": [], "metrics": {}}),
        encoding="utf-8",
    )
    (paths.sections_dir / "limitations.tex").write_text(
        "The model did not outperform the prior baseline.\n\n"
        "Differences across folds were not statistically significant.\n",
        encoding="utf-8",
    )

    report = run_claim_guard(paths)

    assert report.status == "pass"


@pytest.mark.asyncio
async def test_consistency_guard_flags_val_metric_in_test_paragraph(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_val_in_test", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                    "main.metrics.val_accuracy": {"formatted": "0.8012", "value": 0.8012, "role": "main"},
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "On the test set, \\metricMainMetricsValAccuracy is reported as the headline result.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "fail"
    assert any(issue.code == "metric_context_crosstalk" for issue in report.issues)
    assert any("main.metrics.val_accuracy" in str(issue.context) for issue in report.issues)


@pytest.mark.asyncio
async def test_consistency_guard_flags_internal_number_in_external_paragraph(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_internal_external", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                    "external_validation.metrics.test_accuracy": {
                        "formatted": "0.7333",
                        "value": 0.7333,
                        "role": "external_validation",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "In external validation, the reported accuracy was 0.9123.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "fail"
    assert any("external paragraph references internal metric" in issue.message for issue in report.issues)


@pytest.mark.asyncio
async def test_consistency_guard_allows_matching_test_and_external_metrics(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_pass", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                    "external_validation.metrics.test_accuracy": {
                        "formatted": "0.7333",
                        "value": 0.7333,
                        "role": "external_validation",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "On the test set, \\metricMainMetricsTestAccuracy is reported.\n\n"
        "In external validation, \\metricExternalValidationMetricsTestAccuracy is reported.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "pass"


@pytest.mark.asyncio
async def test_consistency_guard_allows_test_and_external_metrics_in_same_paragraph(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_same_paragraph", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                    "external_validation.metrics.test_accuracy": {
                        "formatted": "0.7333",
                        "value": 0.7333,
                        "role": "external_validation",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "On the test set, 0.9123 was observed. In external validation, 0.7333 was observed.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "pass"


@pytest.mark.asyncio
async def test_consistency_guard_ignores_ambiguous_duplicate_raw_values(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_duplicate_values", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                    "main.metrics.val_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"},
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "On the test set, 0.9123 was observed.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "pass"


@pytest.mark.asyncio
async def test_consistency_guard_uses_zero_decimal_percent_variants(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_consistency_percent_rounding", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "metrics": {
                    "main.metrics.test_accuracy": {"value": 0.8012, "role": "main"},
                    "main.metrics.val_accuracy": {"value": 0.9123, "role": "main"},
                }
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "On the test set, the reported accuracy was 91\\%.\n",
        encoding="utf-8",
    )

    report = run_consistency_guard(paths)

    assert report.status == "fail"
    assert any("main.metrics.val_accuracy" in str(issue.context) for issue in report.issues)


@pytest.mark.asyncio
async def test_validating_stage_writes_m10b_reports(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_m10b_validating_stage", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "source_tasks": [{"task_id": "main_task", "role": "main"}],
                "external_validation": [],
                "metrics": {"main.metrics.test_accuracy": {"formatted": "0.9123", "value": 0.9123, "role": "main"}},
            }
        ),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text(
        "\\section{Results}\nOn the test set, the locked accuracy was 0.9123.\n",
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_validating(paths, manifest)

    for name in [
        "metric_guard",
        "identifier_guard",
        "latex_guard",
        "citation_guard",
        "claim_guard",
        "consistency_guard",
    ]:
        report_path = paths.validation_dir / f"{name}.json"
        assert report_path.is_file()
        assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "pass"
        assert f"validation/{name}.json" in manifest.artifact_index
    warnings = (paths.validation_dir / "warnings.md").read_text(encoding="utf-8")
    assert "All deterministic M10 guards passed." in warnings
