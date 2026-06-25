"""Regression tests for the report builder / synthesis context preserving
every run_history entry even when upstream bugs cause duplicate run_ids.

Motivated by session_b14b074d2268 (2026-04-20): the sticky-run_id bug (Fix 1)
made all 17 iterations share run_id='2c696802'. ``build_synthesis_context``
folded those 17 rows into a ``{run_id: row}`` dict, collapsing the
comparison_table to a single row. The paper draft then falsely claimed
"only a single run was committed".

Fix 1 prevents duplicate run_ids going forward, but the synthesis layer
should be defense-in-depth — it must NOT silently erase history when
runtime corruption produces duplicates. The comparison table is a
presentation layer; it must faithfully reflect ``state.run_history``.
"""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.evidence.store import EvidenceStore
from autoresearch.evidence.types import EvidenceRecord
from autoresearch.orchestrator.types import (
    ResearchObjective,
    ResearchSessionState,
    RunRecord,
)
from autoresearch.synthesis.context import build_synthesis_context
from autoresearch.synthesis.report_builder import build_report


def _make_state_with_duplicate_run_ids() -> ResearchSessionState:
    """Build a session where all 3 iterations share run_id='run_abc' but differ
    in iteration index and metric value — mirroring the sticky-run_id bug.

    After Fix 5 the canonical run_id shape is ``run_<hex8>``; this fixture
    uses ``run_abc`` to stay under the prefix convention while still
    deliberately colliding across iterations.
    """
    state = ResearchSessionState.create(
        session_id="sess_dup",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="Improve AUC on BRACS"),
    )
    state.record_run(
        RunRecord(run_id="run_abc", iteration=0, metric_value=0.70, committed=True, notes="first")
    )
    state.record_run(
        RunRecord(run_id="run_abc", iteration=1, metric_value=0.80, committed=True, notes="second")
    )
    state.record_run(
        RunRecord(run_id="run_abc", iteration=2, metric_value=0.90, committed=False, notes="third")
    )
    return state


def test_comparison_table_preserves_duplicate_run_ids_without_store():
    """With no evidence_store, every run_history entry must appear as its
    own comparison_table row — ordered by iteration."""
    state = _make_state_with_duplicate_run_ids()

    ctx = build_synthesis_context(state)

    assert len(ctx["comparison_table"]) == 3, (
        f"Expected 3 rows for 3 run_history entries with duplicate run_id, "
        f"got {len(ctx['comparison_table'])}"
    )
    iterations = [row["iteration"] for row in ctx["comparison_table"]]
    assert iterations == [0, 1, 2], f"Iterations collapsed/reordered: {iterations}"
    metric_values = [row["primary_metric_value"] for row in ctx["comparison_table"]]
    assert metric_values == [0.70, 0.80, 0.90], (
        f"Metric values collapsed/overwritten: {metric_values}"
    )
    notes_values = [row["agent_notes"] for row in ctx["comparison_table"]]
    assert notes_values == ["first", "second", "third"], (
        f"Notes overwritten: {notes_values}"
    )


def test_comparison_table_preserves_duplicate_run_ids_with_store(tmp_path):
    """Even when an evidence_store is wired in, context must preserve every
    run_history row. Evidence enrichment may only augment existing rows,
    never silently fold them by run_id."""
    state = _make_state_with_duplicate_run_ids()

    # Evidence store keyed by run_id on disk — sticky run_id means only one
    # record survives there. That is outside this fix's scope; the invariant
    # under test is that the synthesis layer does not amplify the damage by
    # collapsing run_history too.
    store = EvidenceStore(tmp_path / ".evidence")
    store.save(EvidenceRecord(
        run_id="run_abc",
        session_id="sess_dup",
        iteration=2,
        run_dir="output/runs/run_abc",
        git_commit="deadbeef",
        git_diff="",
        code_snapshot="",
        exit_code=0,
        duration=3.0,
        stdout="",
        stderr="",
        metrics={"auc": 0.90},
        primary_metric_name="auc",
        primary_metric_value=0.90,
        committed=False,
        error_type="",
        error_hint="",
        agent_notes="third",
        artifacts=[],
        started_at="",
        finished_at="",
    ))

    ctx = build_synthesis_context(state, evidence_store=store)

    assert len(ctx["comparison_table"]) == 3, (
        f"Evidence enrichment collapsed run_history: "
        f"expected 3 rows, got {len(ctx['comparison_table'])}"
    )
    iterations = [row["iteration"] for row in ctx["comparison_table"]]
    assert iterations == [0, 1, 2], f"Iterations collapsed/reordered: {iterations}"

    # iteration=0 and iteration=1 should retain their original metrics from
    # run_history — they must NOT inherit iteration=2's evidence-store payload.
    metric_by_iter = {row["iteration"]: row["primary_metric_value"] for row in ctx["comparison_table"]}
    assert metric_by_iter[0] == 0.70, f"iter=0 metric overwritten: {metric_by_iter[0]}"
    assert metric_by_iter[1] == 0.80, f"iter=1 metric overwritten: {metric_by_iter[1]}"
    assert metric_by_iter[2] == 0.90, f"iter=2 metric lost: {metric_by_iter[2]}"


def test_build_report_preserves_duplicate_run_ids():
    """The structured ResearchReport must expose all 3 rows so downstream
    consumers (paper writer, markdown renderer, CLI) see the full lineage."""
    state = _make_state_with_duplicate_run_ids()
    ctx = build_synthesis_context(state)
    report = build_report(ctx)

    assert len(report.comparison_table) == 3, (
        f"ResearchReport collapsed run_history to {len(report.comparison_table)} rows"
    )
    iterations = [row["iteration"] for row in report.comparison_table]
    assert iterations == [0, 1, 2]


def test_real_world_ratio_17_to_17_not_17_to_1():
    """Synthetic reproducer of session_b14b074d2268: 17 run_history entries
    all sharing run_id='2c696802' across iterations 0..16 (11 committed).
    The synthesis context must emit 17 rows, not 1."""
    state = ResearchSessionState.create(
        session_id="sess_b14b074d2268",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="Improve AUC on dataset"),
    )
    committed_iters = {0, 1, 3, 8, 9, 10, 11, 12, 13, 14, 15}  # 11 committed
    metric_series = [
        0.7738, 0.8020, 0.7778, 0.8036, 0.7771, 0.7978, 0.7646,
        0.8021, 0.8123, 0.8163, 0.8217, 0.8265, 0.8336, 0.8426,
        0.8495, 0.8538, 0.8523,
    ]
    # Sticky run_id from the original session — canonicalized to the
    # post-Fix-5 ``run_<hex8>`` shape to reflect what future sessions
    # would emit. The test still exercises the 17→17 preservation
    # invariant under the duplicate-id condition.
    for i, m in enumerate(metric_series):
        state.record_run(RunRecord(
            run_id="run_2c696802",
            iteration=i,
            metric_value=m,
            committed=(i in committed_iters),
        ))

    ctx = build_synthesis_context(state)

    assert len(ctx["comparison_table"]) == 17, (
        f"17:1 collapse regression — comparison_table has "
        f"{len(ctx['comparison_table'])} row(s), expected 17"
    )
    committed_in_table = sum(1 for row in ctx["comparison_table"] if row["committed"])
    assert committed_in_table == 11, (
        f"Committed count collapsed: {committed_in_table}, expected 11"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
