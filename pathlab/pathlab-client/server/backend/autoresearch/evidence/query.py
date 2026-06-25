"""Evidence query helpers for Phase 4 paper/report generation."""
from __future__ import annotations

from .store import EvidenceStore
from .types import EvidenceRecord


def _is_non_metric_setup_record(record: EvidenceRecord) -> bool:
    from ..orchestrator.metrics_utils import is_non_metric_setup_run

    return is_non_metric_setup_run(
        record.metrics,
        record.primary_metric_name or "auc",
        exit_code=record.exit_code,
        error_type=record.error_type,
    )


def query_best_run(store: EvidenceStore, session_id: str = "") -> EvidenceRecord | None:
    """Get the best committed run by primary metric, optionally filtered by session."""
    committed = store.list_runs(committed=True)
    if session_id:
        committed = [r for r in committed if r.get("session_id") == session_id]
    filtered = []
    for row in committed:
        try:
            value = float(row.get("primary_metric_value", 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0.0:
            filtered.append(row)
    committed = filtered
    if not committed:
        return None
    best = max(committed, key=lambda r: r.get("primary_metric_value", 0.0))
    return store.load(best["run_id"])


def query_comparison_table(store: EvidenceStore, session_id: str = "") -> list[dict]:
    """Build a comparison table of all runs for a Results section."""
    runs = store.list_runs()
    if session_id:
        runs = [r for r in runs if r.get("session_id") == session_id]
    table = []
    for run_summary in runs:
        try:
            record = store.load(run_summary["run_id"])
            if _is_non_metric_setup_record(record):
                continue
            table.append({
                "run_id": record.run_id,
                "iteration": record.iteration,
                "primary_metric_value": record.primary_metric_value,
                "primary_metric_name": record.primary_metric_name,
                "metrics": dict(record.metrics or {}),
                "committed": record.committed,
                "error_type": record.error_type,
                "duration": record.duration,
                "code_diff_summary": record.git_diff[:200] if record.git_diff else "",
                "agent_notes": record.agent_notes,
                "run_dir": record.run_dir,
                "data_output_dir": record.data_output_dir,
                "model_path": record.model_path,
                "pathlab": dict(record.pathlab or {}),
            })
        except Exception:
            continue
    return table


def query_failures(store: EvidenceStore, session_id: str = "") -> list[dict]:
    """Get only RUNTIME failures for a Limitations section.

    Plan-2026-04-28 P2 #7: previously this returned every committed=False
    run, which conflated metric regressions (script ran cleanly, model
    regressed, ratchet reverted) with actual runtime failures
    (CUDA_OOM, ModuleNotFoundError, etc.). The report then wrote
    "failed with " for the regressions, misrepresenting clean reverts
    as crashes.

    A runtime failure is now defined as: ``error_type`` set OR
    ``exit_code != 0``. Use ``query_non_improving_runs`` for the
    metric-regression-but-clean-exit set.
    """
    runs = store.list_runs(committed=False)
    if session_id:
        runs = [r for r in runs if r.get("session_id") == session_id]
    failures = []
    for run_summary in runs:
        try:
            record = store.load(run_summary["run_id"])
        except Exception:
            continue
        # A run is a true runtime failure when the script raised or
        # exit_code != 0. Reverted-due-to-regression runs (clean exit,
        # metric below tracker best) go to query_non_improving_runs.
        is_runtime_failure = bool(record.error_type) or record.exit_code != 0
        if not is_runtime_failure:
            continue
        failures.append({
            "run_id": record.run_id,
            "iteration": record.iteration,
            "error_type": record.error_type,
            "error_hint": record.error_hint,
            "primary_metric_value": record.primary_metric_value,
            "stderr_preview": record.stderr[:500] if record.stderr else "",
        })
    return failures


def query_non_improving_runs(store: EvidenceStore, session_id: str = "") -> list[dict]:
    """Plan-2026-04-28 P2 #7: reverted-but-clean-exit runs.

    A non-improving run is committed=False AND error_type=='' AND
    exit_code==0 — i.e. the script ran to completion, produced metrics,
    but the metric was below the tracker best so ratchet_revert was
    called. These should NOT be presented as failures in the report.
    """
    runs = store.list_runs(committed=False)
    if session_id:
        runs = [r for r in runs if r.get("session_id") == session_id]
    out: list[dict] = []
    for run_summary in runs:
        try:
            record = store.load(run_summary["run_id"])
        except Exception:
            continue
        if record.error_type or record.exit_code != 0:
            # That's a runtime failure, handled by query_failures.
            continue
        out.append({
            "run_id": record.run_id,
            "iteration": record.iteration,
            "primary_metric_value": record.primary_metric_value,
            "primary_metric_name": record.primary_metric_name,
            "agent_notes": record.agent_notes,
            "duration": record.duration,
        })
    return out


def query_evidence_for_claim(store: EvidenceStore, claim: str, session_id: str = "") -> list[EvidenceRecord]:
    """Find evidence records relevant to a claim (keyword search).

    Searches across: agent_notes, metrics, git_diff, error_type, error_hint,
    artifact names, and stdout/stderr previews.
    """
    claim_lower = claim.lower()
    results = []
    for run_summary in store.list_runs():
        if session_id and run_summary.get("session_id") != session_id:
            continue
        try:
            record = store.load(run_summary["run_id"])
            artifact_names = " ".join(a.name for a in record.artifacts)
            searchable = " ".join([
                record.agent_notes,
                f"{record.primary_metric_name}={record.primary_metric_value}",
                record.git_diff[:2000] if record.git_diff else "",
                record.error_type,
                record.error_hint,
                artifact_names,
                record.stdout[:500] if record.stdout else "",
                record.stderr[:500] if record.stderr else "",
            ])
            if claim_lower in searchable.lower():
                results.append(record)
        except Exception:
            continue
    return results
