"""Tests for paper draft verification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.synthesis.verification import verify_paper_draft
from pathscientist.synthesis.types import (
    ClaimRecord,
    PaperDraftVerificationResult,
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
                claim_id="claim_best",
                section="results",
                claim_type="result",
                statement="Best run achieved AUC 0.8844.",
                evidence_run_ids=["run_003"],
            ),
        ],
        sections=[
            ReportSection(name="results", title="Results", content="AUC 0.8844."),
        ],
        comparison_table=[
            {"run_id": "run_003", "primary_metric_value": 0.8844, "committed": True},
        ],
        failure_table=[{"run_id": "run_002", "error_type": "CUDA_OOM", "primary_metric_value": 0.75}],
        references=[{"paper_id": "transmil_2021", "context": "TransMIL baseline"}],
    )


def test_clean_draft_passes_verification():
    report = _make_report()
    draft = "## Results\n\nBest run run_003 achieved auc 0.8844. See [transmil_2021]."
    result = verify_paper_draft(report, draft)
    assert result.passed is True
    assert result.issue_count == 0


def test_unsupported_run_id_flagged():
    report = _make_report()
    draft = "## Results\n\nOur model run_999 achieved auc 0.8844."
    result = verify_paper_draft(report, draft)
    assert result.passed is False
    assert "run_999" in result.unsupported_run_ids


def test_unsupported_paper_id_flagged():
    report = _make_report()
    draft = "## Results\n\nWe outperformed [made_up_2025]."
    result = verify_paper_draft(report, draft)
    assert result.passed is False
    assert "made_up_2025" in result.unsupported_paper_ids


def test_unsupported_metric_flagged():
    report = _make_report()
    draft = "## Results\n\nWe achieved 0.9500 AUC."
    result = verify_paper_draft(report, draft)
    assert any(i.issue_type == "unsupported_metric" for i in result.issues)
    assert "0.9500" in result.unsupported_metric_mentions


def test_multiple_issues_all_reported():
    report = _make_report()
    draft = "## Results\n\nrun_999 achieved 0.9500. Also see [fake_2025]."
    result = verify_paper_draft(report, draft)
    assert result.issue_count >= 3
    assert len(result.unsupported_run_ids) >= 1
    assert len(result.unsupported_paper_ids) >= 1
    assert len(result.unsupported_metric_mentions) >= 1


def test_empty_draft_passes():
    report = _make_report()
    result = verify_paper_draft(report, "")
    assert result.passed is True


def test_verification_result_round_trips():
    report = _make_report()
    draft = "## Results\n\nrun_999 invented."
    result = verify_paper_draft(report, draft)
    restored = PaperDraftVerificationResult.from_dict(result.to_dict())
    assert restored.passed == result.passed
    assert restored.issue_count == result.issue_count
    assert len(restored.issues) == len(result.issues)


def test_real_hex_run_id_format_is_verified():
    """Canonical ``run_[0-9a-f]{8}`` run_ids are extracted and checked.

    After Fix 5, run_ids minted by ``ensure_run_id`` / ``RunExperimentTool``
    / ``_finalize_iteration`` all have shape ``run_<hex8>``. Bare-hex
    ids from pre-Fix-5 state are ignored by the regex; only the prefixed
    form is treated as a run_id token.
    """
    report = _make_report()
    report.best_run_id = "run_a1b2c3d4"
    report.claims[0].evidence_run_ids = ["run_a1b2c3d4"]
    report.comparison_table = [
        {"run_id": "run_a1b2c3d4", "primary_metric_value": 0.8844, "committed": True},
    ]

    draft = "## Results\n\nBest run run_deadbeef achieved auc 0.8844."
    result = verify_paper_draft(report, draft)

    assert result.passed is False
    assert "run_deadbeef" in result.unsupported_run_ids


def test_doi_like_paper_id_is_verified():
    report = _make_report()
    report.references = [{"paper_id": "10.1038/s41591-024-12345", "context": "DOI baseline"}]

    draft = "## Results\n\nWe outperformed [10.1038/s41591-024-99999]."
    result = verify_paper_draft(report, draft)

    assert result.passed is False
    assert "10.1038/s41591-024-99999" in result.unsupported_paper_ids


def test_openalex_paper_id_is_verified():
    report = _make_report()
    report.references = [{"paper_id": "openalex:W1234567890", "context": "OpenAlex baseline"}]

    draft = "## Results\n\nWe outperformed [openalex:W9999999999]."
    result = verify_paper_draft(report, draft)

    assert result.passed is False
    assert "openalex:W9999999999" in result.unsupported_paper_ids


def test_conversation_uuid_shard_is_not_flagged_as_run_id():
    """Regression for session_b14b074d2268 (2026-04-20).

    The paper's Reproducibility section quoted the full conversation UUID
    ``d0df5148-5a12-4cda-9cc8-a899ff810a17``. The verifier's old regex
    matched any bare 8-char hex token, so ``d0df5148`` (the first shard of
    the UUID) was flagged as an unsupported run_id. After canonicalizing
    run_ids to ``run_[0-9a-f]{8}``, UUID shards can no longer collide
    with the regex because the regex now requires the ``run_`` prefix.

    The allowed run_id in the report is itself in canonical form
    (``run_2c696802``), mirroring how _finalize_iteration / ensure_run_id
    now mint ids after Fix 5.
    """
    report = _make_report()
    report.best_run_id = "run_2c696802"
    report.claims[0].evidence_run_ids = ["run_2c696802"]
    report.comparison_table = [
        {"run_id": "run_2c696802", "primary_metric_value": 0.8844, "committed": True},
    ]

    # Mirror the exact sentence shape from session_b14b074d2268's
    # paper_verification.json issue:
    #   "tifier b14b074d2268 within conversation d0df5148-5a12-4cda-9cc8-a899ff810a17."
    draft = (
        "## Reproducibility\n\n"
        "Identifier b14b074d2268 within conversation "
        "d0df5148-5a12-4cda-9cc8-a899ff810a17. The best run was "
        "run_2c696802 with AUC 0.8844."
    )
    result = verify_paper_draft(report, draft)

    # The UUID shard d0df5148 must NOT be flagged as an unsupported run_id.
    assert "d0df5148" not in result.unsupported_run_ids, (
        f"Conversation UUID shard incorrectly flagged as run_id: "
        f"{result.unsupported_run_ids}"
    )
    # The canonical run_2c696802 is supported, so no run_id should be flagged.
    assert not result.unsupported_run_ids, (
        f"Unexpected unsupported run_ids: {result.unsupported_run_ids}"
    )


def test_canonical_run_id_prefix_is_required_for_flagging():
    """Only run_-prefixed tokens can be flagged as run_ids.

    A bare 8-hex token (commit shard, UUID shard, dataset hash, etc.) must
    never trip ``unsupported_run_id``; the verifier only checks tokens that
    match ``\\brun_[0-9a-f]{8}\\b``. This prevents the bug where verifier
    scans flagged tokens that happen to look like hex because an allowed
    run_id was also bare hex.
    """
    report = _make_report()
    report.best_run_id = "run_abcdef01"
    report.claims[0].evidence_run_ids = ["run_abcdef01"]
    report.comparison_table = [
        {"run_id": "run_abcdef01", "primary_metric_value": 0.8844, "committed": True},
    ]

    # An actually-bogus run_id in run_-prefixed form IS flagged.
    draft_with_bogus = "## Results\n\nThe unsupported run_99999999 came out of nowhere."
    result = verify_paper_draft(report, draft_with_bogus)
    assert "run_99999999" in result.unsupported_run_ids

    # A bare 8-hex token that matches nothing in allowed_run_ids is NOT flagged.
    draft_with_bare_hex = (
        "## Reproducibility\n\nCommit deadbeef of conversation "
        "11223344-5566-7788-9900-aabbccddeeff was recorded."
    )
    result = verify_paper_draft(report, draft_with_bare_hex)
    assert "deadbeef" not in result.unsupported_run_ids, (
        f"Bare 8-hex token flagged: {result.unsupported_run_ids}"
    )
    assert "11223344" not in result.unsupported_run_ids


def test_hex_run_id_pattern_disabled_when_bare_allowed_ids_present():
    """Even if an allowed_run_id is bare hex (legacy state), UUID shards
    must not be flagged.

    A session's stored report could still have a bare-hex best_run_id from
    before Fix 5 landed (persistent state migrating forward). The verifier
    must stay safe in that case too: the regex now unconditionally requires
    ``run_`` prefix, so legacy bare-hex allowed_run_ids never re-enable the
    loose ``\\b[a-f0-9]{8}\\b`` pattern.
    """
    report = _make_report()
    # Simulate legacy on-disk state: bare-hex ids on every surface.
    report.best_run_id = "2c696802"
    report.claims[0].evidence_run_ids = ["2c696802"]
    report.comparison_table = [
        {"run_id": "2c696802", "primary_metric_value": 0.8844, "committed": True},
    ]

    draft = (
        "## Reproducibility\n\n"
        "Conversation d0df5148-5a12-4cda-9cc8-a899ff810a17 ran on commit "
        "b14b074d. The best run id was 2c696802."
    )
    result = verify_paper_draft(report, draft)

    # Under the new regex, none of the 8-hex tokens are checked at all, so
    # d0df5148 / b14b074d never show up as issues.
    assert "d0df5148" not in result.unsupported_run_ids
    assert "b14b074d" not in result.unsupported_run_ids


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
