"""Tests for section-scoped grounding inputs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.synthesis.grounding import build_grounded_section_inputs
from autoresearch.synthesis.types import (
    ClaimRecord,
    GroundedSectionInput,
    ReportSection,
    ResearchReport,
)


def _make_report():
    return ResearchReport(
        session_id="sess1",
        conversation_id="conv1",
        objective="Improve AUC on BRACS",
        success_metric="auc",
        best_run_id="run_003",
        best_metric_value=0.8844,
        claims=[
            ClaimRecord(
                claim_id="claim_best_result",
                section="results",
                claim_type="result",
                statement="Best run achieved AUC 0.8844.",
                evidence_run_ids=["run_003"],
            ),
            ClaimRecord(
                claim_id="claim_ref_transmil_2021",
                section="results",
                claim_type="comparison",
                statement="Compared against TransMIL.",
                citation_paper_ids=["transmil_2021"],
                confidence="medium",
            ),
            ClaimRecord(
                claim_id="claim_failure_0",
                section="limitations",
                claim_type="limitation",
                statement="Run run_002 failed with CUDA_OOM.",
                evidence_run_ids=["run_002"],
            ),
            ClaimRecord(
                claim_id="claim_reproducibility",
                section="reproducibility",
                claim_type="reproducibility",
                statement="3 iterations, 2 committed.",
            ),
        ],
        sections=[
            ReportSection(name="results", title="Results", content="AUC table here.",
                          claim_ids=["claim_best_result", "claim_ref_transmil_2021"]),
            ReportSection(name="limitations", title="Failures And Limitations",
                          content="CUDA_OOM on run_002.",
                          claim_ids=["claim_failure_0"]),
            ReportSection(name="reproducibility", title="Reproducibility",
                          content="Session metadata.",
                          claim_ids=["claim_reproducibility"]),
            ReportSection(name="references", title="References",
                          content="- [transmil_2021]", claim_ids=[]),
        ],
        comparison_table=[
            {"run_id": "run_003", "primary_metric_value": 0.8844, "committed": True},
        ],
        failure_table=[{"run_id": "run_002", "error_type": "CUDA_OOM"}],
        references=[{"paper_id": "transmil_2021", "context": "TransMIL baseline 0.85 AUC"}],
        reproducibility={"total_iterations": 3, "committed_runs": 2, "reverted_runs": 1},
    )


def test_returns_one_input_per_section():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    assert len(inputs) == len(report.sections)


def test_claims_bound_to_correct_section():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    results_input = next(i for i in inputs if i.section_name == "results")
    assert len(results_input.claims) == 2
    assert results_input.allowed_claim_ids == ["claim_best_result", "claim_ref_transmil_2021"]


def test_allowed_run_ids_from_claims():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    results_input = next(i for i in inputs if i.section_name == "results")
    assert "run_003" in results_input.allowed_run_ids


def test_allowed_paper_ids_from_claims():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    results_input = next(i for i in inputs if i.section_name == "results")
    assert "transmil_2021" in results_input.allowed_paper_ids


def test_references_section_gets_all_paper_ids():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    refs_input = next(i for i in inputs if i.section_name == "references")
    assert "transmil_2021" in refs_input.allowed_paper_ids


def test_metric_facts_from_comparison_table():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    results_input = next(i for i in inputs if i.section_name == "results")
    metric_values = [f["metric_value"] for f in results_input.allowed_metric_facts]
    assert 0.8844 in metric_values


def test_limitations_gets_caution_flags():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    lim_input = next(i for i in inputs if i.section_name == "limitations")
    assert "acknowledge_failures" in lim_input.required_caution_flags


def test_grounded_section_input_round_trips():
    report = _make_report()
    inputs = build_grounded_section_inputs(report)
    for inp in inputs:
        restored = GroundedSectionInput.from_dict(inp.to_dict())
        assert restored.section_name == inp.section_name
        assert len(restored.claims) == len(inp.claims)


# --- Integrity grounded-section terseness (Finding 7, 2026-04-22 review) --


def _make_report_with_integrity(num_issues: int = 3):
    """Build a minimal report that includes an ``integrity_issues`` section.

    The grounding builder should condense the source text for this section
    regardless of how verbose the report's content is, so we synthesize a
    deliberately long section body AND populate
    ``report.integrity_issues`` with the structured data the condenser
    prefers.
    """
    issues = [
        {
            "code": f"issue_code_{idx}",
            "severity": "fatal" if idx == 0 else "warning",
            "message": (
                f"Short first sentence for issue {idx}. "
                f"Long trailing context that would bloat the paper prose: "
                f"/project/very/long/path/to/evidence/runs/run_{idx}/record.json "
                f"and additional commentary prefer running through "
                f"run_experiment when possible."
            ),
            "context": {},
        }
        for idx in range(num_issues)
    ]
    # A verbose source_report_section body to prove the condenser replaces
    # it rather than passing it through.
    verbose_body = " ".join(
        f"This is filler sentence {i}, intended to balloon the raw section "
        f"body so we can verify the grounding layer condenses it."
        for i in range(10)
    )
    return ResearchReport(
        session_id="sess1",
        conversation_id="conv1",
        objective="Test objective",
        success_metric="auc",
        best_run_id="run_ok",
        best_metric_value=0.9,
        claims=[],
        sections=[
            ReportSection(
                name="integrity_issues",
                title="Integrity Issues",
                content=verbose_body,
                claim_ids=[],
            ),
        ],
        integrity_issues=issues,
    )


def test_grounded_section_for_integrity_is_terse():
    """Finding 7 regression: the integrity grounded section's
    ``source_report_section`` must be short (< 500 chars) even when the
    raw report section body was verbose. This is what the paper_writer
    LLM prompt sees, so bounding it here is what prevents the LLM from
    producing multi-paragraph defensive prose on a single warning.
    """
    report = _make_report_with_integrity(num_issues=3)
    inputs = build_grounded_section_inputs(report)

    integrity_input = next(i for i in inputs if i.section_name == "integrity_issues")

    # Source text stays under the 500-char cap defined in grounding.py.
    assert len(integrity_input.source_report_section) < 500, (
        f"Integrity grounded source too long: "
        f"{len(integrity_input.source_report_section)} chars:\n"
        f"{integrity_input.source_report_section}"
    )

    # Filler from the raw section body must not survive — the condenser
    # replaces the body rather than appending to it.
    assert "filler sentence" not in integrity_input.source_report_section

    # The condenser must surface each code so the paper writer still knows
    # what to briefly acknowledge.
    for idx in range(3):
        assert f"issue_code_{idx}" in integrity_input.source_report_section

    # Must carry an explicit "do not expand" instruction so the LLM does
    # not pad the section.
    assert "do not expand" in integrity_input.source_report_section.lower()


def test_grounded_section_for_integrity_has_terse_section_goal():
    """The ``section_goal`` threaded into the paper_writer prompt must
    instruct the LLM to keep the integrity acknowledgement brief.
    Otherwise the default goal ('Write this section based on the report
    content.') gives the LLM no length guidance and it invents paragraphs.
    """
    report = _make_report_with_integrity(num_issues=1)
    inputs = build_grounded_section_inputs(report)

    integrity_input = next(i for i in inputs if i.section_name == "integrity_issues")
    goal = integrity_input.section_goal.lower()
    assert "briefly" in goal or "brief" in goal
    assert "do not expand" in goal or "not expand" in goal
    # Defensive-prose trigger phrases must be explicitly forbidden.
    assert "should be noted" in goal or "defensive" in goal


def test_grounded_section_for_integrity_has_keep_brief_caution():
    """The grounding layer must tag the integrity section with a
    keep-brief caution flag so downstream prompt builders can flag it."""
    report = _make_report_with_integrity(num_issues=2)
    inputs = build_grounded_section_inputs(report)

    integrity_input = next(i for i in inputs if i.section_name == "integrity_issues")
    assert "keep_brief_limitations_only" in integrity_input.required_caution_flags


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
