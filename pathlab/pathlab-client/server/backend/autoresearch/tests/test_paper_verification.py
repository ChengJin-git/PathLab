"""Tests for paper draft verification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.synthesis.verification import verify_paper_draft
from autoresearch.synthesis.types import (
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
    # Use canonical run_id shape (run_[0-9a-f]{8}) to exercise the verifier's
    # regex. Legacy shapes like ``run_999`` are no longer regex-matched after
    # the legacy pattern was removed (prose-false-positive fix).
    draft = "## Results\n\nOur model run_99999999 achieved auc 0.8844."
    result = verify_paper_draft(report, draft)
    assert result.passed is False
    assert "run_99999999" in result.unsupported_run_ids


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
    # Canonical run_id shape — legacy ``run_999`` no longer matches the regex.
    draft = "## Results\n\nrun_99999999 achieved 0.9500. Also see [fake_2025]."
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


def _minimal_report_with_allowed_run_id(run_id: str) -> ResearchReport:
    """Build a minimal report whose only allowed run_id is ``run_id``.

    Used by tests that need the canonical-only run_id set to isolate what
    the verifier actually flags in prose.
    """
    return ResearchReport(
        session_id="sess1",
        conversation_id="conv1",
        objective="Improve AUC on BRACS",
        success_metric="auc",
        best_run_id=run_id,
        best_metric_value=0.8844,
        claims=[
            ClaimRecord(
                claim_id="claim_best",
                section="results",
                claim_type="result",
                statement=f"Best run {run_id} achieved AUC 0.8844.",
                evidence_run_ids=[run_id],
            ),
        ],
        sections=[
            ReportSection(name="results", title="Results", content="AUC 0.8844."),
        ],
        comparison_table=[
            {"run_id": run_id, "primary_metric_value": 0.8844, "committed": True},
        ],
        failure_table=[],
        references=[],
    )


def test_run_experiment_in_prose_is_not_false_flagged():
    """Tool names in Methods / Reproducibility prose must not be treated as run_ids."""
    report = _minimal_report_with_allowed_run_id("run_abc12345")
    draft = (
        "# Paper\n\n"
        "## Methods\n\n"
        "We used the run_experiment tool before ratchet_commit. "
        "The run_history was preserved across iterations.\n"
    )
    result = verify_paper_draft(report, draft)
    assert result.passed, (
        f"Prose tokens like 'run_experiment' / 'run_history' must not be flagged. "
        f"Got unsupported_run_ids={result.unsupported_run_ids}"
    )
    assert "run_experiment" not in result.unsupported_run_ids
    assert "run_history" not in result.unsupported_run_ids


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


def test_numeric_boilerplate_citation_not_flagged():
    """Regression for session_3f1795098784 / Finding 5 (2026-04-22).

    The paper draft contained LLM-boilerplate prose like
    ``... analyses [1].`` in a section whose references field was empty.
    The verifier's old regex matched any ``[N]`` and flagged ``1`` as an
    unsupported paper_id, which tripped the paper-verifier unnecessarily.
    Numeric citation markers are never canonical paper_ids in this project
    (canonical form is alphabetic, e.g. ``smith2023`` / DOI / OpenAlex id)
    so they must be silently ignored regardless of the references state.
    """
    report = _make_report()
    report.references = []  # no references at all, matching session_3f1795098784
    draft = (
        "## Integrity Issues\n\n"
        "Best practices in reproducible research emphasize the importance of "
        "maintaining complete documentation even for preliminary or "
        "exploratory analyses [1]. It should be noted that..."
    )
    result = verify_paper_draft(report, draft)

    # ``[1]`` is LLM boilerplate — must not flag.
    assert "1" not in result.unsupported_paper_ids, (
        f"Numeric boilerplate [1] flagged as unsupported paper_id: "
        f"{result.unsupported_paper_ids}"
    )
    # There are no other run_ids / metrics / papers in the draft, so the
    # verifier should pass overall.
    assert result.passed is True, (
        f"Draft with only numeric boilerplate should pass; got issues={result.issues}"
    )


def test_numeric_boilerplate_citation_with_populated_references_still_not_flagged():
    """Numeric markers are ignored even when references IS populated.

    The caller might have a rich references list but the LLM still emits
    stray ``[1]`` / ``[2]`` boilerplate in prose. Those numeric markers are
    never valid paper_ids in this project — they must not show up in
    ``unsupported_paper_ids`` even when ``allowed_paper_ids`` is non-empty.
    """
    report = _make_report()
    # references from _make_report already contains transmil_2021; add more
    # so allowed_paper_ids is clearly non-empty.
    report.references = [
        {"paper_id": "smith2023", "context": "Smith et al. 2023"},
        {"paper_id": "transmil_2021", "context": "TransMIL baseline"},
    ]
    draft = (
        "## Results\n\n"
        "Our method improved accuracy [1]. Prior work [2] had lower scores."
    )
    result = verify_paper_draft(report, draft)

    # Numeric tokens must not be flagged, even though references is populated.
    assert "1" not in result.unsupported_paper_ids
    assert "2" not in result.unsupported_paper_ids
    assert not any(
        issue.issue_type == "unsupported_paper_id" for issue in result.issues
    ), f"Numeric marker incorrectly flagged: {result.issues}"


def test_explicit_paper_id_citation_still_flagged_when_missing():
    """Non-numeric paper_ids that are NOT in references ARE still flagged.

    Tightening the regex for numeric boilerplate must not weaken detection
    of real paper_id hallucinations. If the LLM invents ``[smith2023]`` and
    the references list does not contain it, the verifier must still fail.
    """
    report = _make_report()
    report.references = []
    draft = "## Results\n\nOur approach outperformed prior work [smith2023]."
    result = verify_paper_draft(report, draft)

    assert result.passed is False
    assert "smith2023" in result.unsupported_paper_ids


def test_explicit_paper_id_citation_accepted_when_present():
    """Paper_ids that match an entry in references are NOT flagged."""
    report = _make_report()
    report.references = [
        {"paper_id": "smith2023", "context": "Smith et al. 2023 baseline"},
    ]
    # Clear prior claims so allowed_paper_ids draws purely from references.
    for claim in report.claims:
        claim.citation_paper_ids = []
    draft = "## Results\n\nOur approach builds on prior work [smith2023]."
    result = verify_paper_draft(report, draft)

    assert result.passed is True, (
        f"Draft citing a known paper_id should pass; got issues={result.issues}"
    )
    assert "smith2023" not in result.unsupported_paper_ids


def test_bracket_n_not_in_references_is_not_unsupported():
    """``[N]`` boilerplate with empty references must not flag.

    Regression for the exact session_3f1795098784 shape: the paper draft
    contains "... analyses [1]." prose, report.references is empty, so
    numeric brackets have nothing to point at. They must be silently
    ignored, and the paper must pass verification overall.
    """
    report = _make_report()
    report.references = []
    # Clear claims' citation_paper_ids too so allowed_paper_ids is empty.
    for claim in report.claims:
        claim.citation_paper_ids = []
    draft = (
        "## Integrity Issues\n\n"
        "Best practices in reproducible research emphasize the importance "
        "of maintaining complete documentation even for preliminary or "
        "exploratory analyses [1]. It should be noted that this warning..."
    )
    result = verify_paper_draft(report, draft)
    assert result.unsupported_paper_ids == [], (
        f"Numeric [1] boilerplate flagged when references is empty: "
        f"{result.unsupported_paper_ids}"
    )
    assert result.passed is True, (
        f"Draft should pass when only orphan [N] present; got {result.issues}"
    )


def test_bracket_n_in_allowed_ids_still_tracked():
    """If a report numbers its references (paper_id='1'), [1] IS valid.

    The positive-match path: when the allowed_paper_ids set literally
    contains the numeric id, the bracket reference is treated as legitimate
    and is NOT flagged unsupported. This is the rare case where a report
    genuinely uses numeric paper_ids.
    """
    report = _make_report()
    report.references = [
        {"paper_id": "1", "context": "Numbered reference 1"},
    ]
    for claim in report.claims:
        claim.citation_paper_ids = []
    draft = "## Results\n\nPrior work established the baseline [1]."
    result = verify_paper_draft(report, draft)

    assert "1" not in result.unsupported_paper_ids, (
        f"Numeric paper_id '1' in references should not be flagged: "
        f"{result.unsupported_paper_ids}"
    )
    # No other issues expected.
    assert not any(
        issue.issue_type == "unsupported_paper_id" for issue in result.issues
    ), f"Unexpected paper_id issues: {result.issues}"


def test_canonical_paper_id_still_works():
    """Canonical alphabetic paper_id detection is unchanged.

    A ``[smith2023]`` citation is still regex-matched, checked against
    allowed_paper_ids, and flagged unsupported if missing. Narrowing the
    numeric path must not weaken the canonical path.
    """
    report = _make_report()
    report.references = [
        {"paper_id": "smith2023", "context": "Smith et al. 2023"},
    ]
    for claim in report.claims:
        claim.citation_paper_ids = []

    # Allowed paper_id appears cleanly.
    draft_ok = "## Results\n\nPrior work [smith2023] informed our approach."
    result_ok = verify_paper_draft(report, draft_ok)
    assert result_ok.passed is True
    assert "smith2023" not in result_ok.unsupported_paper_ids

    # Hallucinated paper_id is still flagged.
    draft_bad = "## Results\n\nWe outperform [jones2024] baselines."
    result_bad = verify_paper_draft(report, draft_bad)
    assert result_bad.passed is False
    assert "jones2024" in result_bad.unsupported_paper_ids


# ---------------------------------------------------------------------------
# Option A (Finding 5, 2026-04-22): bare [N] only checked when the draft
# itself declares a ``## References`` / ``## Bibliography`` / ``## Citations``
# section. Without one, ``[N]`` is LLM prose decoration and is skipped.
# ---------------------------------------------------------------------------


def test_bare_bracket_citation_without_references_not_flagged():
    """``[1]`` in the draft with no ``## References`` heading is prose.

    Session_3f1795098784's paper_draft.md is the canonical case: the LLM
    wrote ``... analyses [1].`` in Integrity Issues but the draft has no
    References / Bibliography / Citations heading. Under Option A the
    verifier must not iterate numeric brackets at all and must return
    ``passed=True`` with empty ``unsupported_paper_ids``.
    """
    report = _make_report()
    report.references = []
    for claim in report.claims:
        claim.citation_paper_ids = []
    draft = (
        "## Methods\n\n"
        "We trained a patch classifier. Best practices in reproducible "
        "research emphasize complete documentation [1]."
    )
    result = verify_paper_draft(report, draft)

    assert result.passed is True, (
        f"Draft with no References section should pass; got issues={result.issues}"
    )
    assert result.unsupported_paper_ids == [], (
        f"Numeric [1] flagged despite no References section: "
        f"{result.unsupported_paper_ids}"
    )


def test_bare_bracket_citation_with_references_still_checked():
    """``[N]`` is checked when the draft has a ``## References`` section.

    Two companion assertions:
      1. ``[1]`` in Methods AND listed in ``## References`` → passes.
      2. ``[2]`` in Methods prose but only ``[1]`` in ``## References`` →
         ``[2]`` is flagged as unsupported.

    This preserves the invariant that once the paper actually declares a
    bibliography, every numeric marker must resolve into it (or into
    ``ResearchReport.references``). Option A only relaxes the check when
    there is no bibliography at all.
    """
    report = _make_report()
    report.references = []
    for claim in report.claims:
        claim.citation_paper_ids = []

    # (1) ``[1]`` is backed by the draft's own References section.
    draft_ok = (
        "## Methods\n\n"
        "We followed the approach of [1] for patch-level training.\n\n"
        "## References\n\n"
        "[1] Some et al 2024. Deep learning for histopathology."
    )
    result_ok = verify_paper_draft(report, draft_ok)
    assert result_ok.passed is True, (
        f"Draft with [1] backed by References should pass; got {result_ok.issues}"
    )
    assert "1" not in result_ok.unsupported_paper_ids

    # (2) ``[2]`` has no backing — flagged.
    draft_bad = (
        "## Methods\n\n"
        "We followed the approach of [1]. Prior work [2] reported higher AUC.\n\n"
        "## References\n\n"
        "[1] Some et al 2024. Deep learning for histopathology."
    )
    result_bad = verify_paper_draft(report, draft_bad)
    assert result_bad.passed is False, (
        "Draft with unbacked [2] and a References section should fail."
    )
    assert "2" in result_bad.unsupported_paper_ids
    # ``[1]`` is still fine even though [2] is bad.
    assert "1" not in result_bad.unsupported_paper_ids


def test_bare_bracket_backed_by_research_report_references_when_draft_has_heading():
    """With a ``## References`` heading, ``[N]`` is also backed by
    ``ResearchReport.references`` — not only the draft text.

    If the report carries ``paper_id='1'`` and the draft has a References
    heading but the heading's section text does not list ``[1]`` verbatim,
    the verifier should still accept it because the report-level allowed
    set backs it. This covers the case where the References section is a
    heading placeholder the report_builder populated indirectly.
    """
    report = _make_report()
    report.references = [
        {"paper_id": "1", "context": "Numbered reference 1"},
    ]
    for claim in report.claims:
        claim.citation_paper_ids = []

    draft = (
        "## Methods\n\n"
        "We cited prior work [1].\n\n"
        "## References\n\n"
        "See ResearchReport.references for the canonical listing."
    )
    result = verify_paper_draft(report, draft)

    assert result.passed is True, (
        f"[1] backed by ResearchReport.references with draft heading should pass; "
        f"got {result.issues}"
    )
    assert "1" not in result.unsupported_paper_ids


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
