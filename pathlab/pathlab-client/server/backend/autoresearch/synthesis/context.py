"""Assemble synthesis context from session state, evidence, and citations."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..evidence.store import EvidenceStore
    from ..literature.citations import CitationTracker
    from ..orchestrator.types import ResearchSessionState


def build_synthesis_context(
    state: "ResearchSessionState",
    evidence_store: "EvidenceStore | None" = None,
    citation_tracker: "CitationTracker | None" = None,
) -> dict[str, Any]:
    """Build a normalized context dict for report generation.

    Merges orchestrator state, evidence records, and citations into one
    structured object that the report builder and paper writer consume.
    """
    context: dict[str, Any] = {
        "objective": state.objective.question,
        "success_metric": state.objective.success_metric,
        "best_run": {},
        "comparison_table": [],
        "failures": [],
        "references": [],
        "run_history": [],
        "external_test_history": list(
            getattr(state, "external_test_history", []) or []
        ),
        "grounding": dict(state.grounding) if state.grounding else {},
        "objective_target": {
            "metric_value": state.objective.target_metric_value,
            "source": state.objective.target_source,
            "confidence": state.objective.target_confidence,
            # Source-kind for hard-vs-advisory decisions. Mirrors the grounding
            # payload set by ResearchDirector.advance().
            "source_kind": ((state.grounding or {}).get("sota_target") or {}).get("source", ""),
        },
        "acquisition": {
            "status": getattr(state, "acquisition_status", "none"),
            "manifest_path": getattr(state, "dataset_manifest_path", ""),
            "selected_dataset": dict(getattr(state, "selected_dataset", {}) or {}),
            "notes": getattr(state, "acquisition_notes", ""),
        },
        "reproducibility": {
            "session_id": state.session_id,
            "conversation_id": str(state.conversation_id),
            "total_iterations": len(state.run_history),
            "committed_runs": sum(1 for r in state.run_history if r.committed),
            "reverted_runs": sum(1 for r in state.run_history if not r.committed),
            "max_iterations": state.max_iterations,
        },
    }

    # Build run history from orchestrator state
    for r in state.run_history:
        entry = {
            "run_id": r.run_id,
            "iteration": r.iteration,
            "metric_name": r.metric_name,
            "metric_value": r.metric_value,
            "committed": r.committed,
            "notes": r.notes,
            "metrics": dict(getattr(r, "metrics", {}) or {}),
            "run_dir": getattr(r, "run_dir", ""),
            "data_output_dir": getattr(r, "data_output_dir", ""),
            "data_output_artifacts": list(getattr(r, "data_output_artifacts", []) or []),
            "model_path": getattr(r, "model_path", ""),
            "pathlab": dict(getattr(r, "pathlab", {}) or {}),
            "quick_check": bool(getattr(r, "quick_check", False)),
            "run_kind": getattr(r, "run_kind", ""),
            "error_type": getattr(r, "error_type", ""),
        }
        context["run_history"].append(entry)

    # Treat orchestrator state as the canonical session summary, then enrich it
    # with evidence details when those records are available on disk.
    if state.best_run_id:
        context["best_run"] = {
            "run_id": state.best_run_id,
            "primary_metric_value": state.best_metric_value,
            "primary_metric_name": state.objective.success_metric,
        }

    context["comparison_table"] = [
        {
            "run_id": entry["run_id"],
            "iteration": entry["iteration"],
            "primary_metric_value": entry["metric_value"],
            "metric_name": entry["metric_name"],
            "metric_value": entry["metric_value"],
            "committed": entry["committed"],
            "metrics": entry["metrics"],
            "error_type": entry["error_type"],
            "duration": 0.0,
            "code_diff_summary": "",
            "agent_notes": entry["notes"],
            "run_dir": entry["run_dir"],
            "data_output_dir": entry["data_output_dir"],
            "data_output_artifacts": entry["data_output_artifacts"],
            "model_path": entry["model_path"],
            "pathlab": entry["pathlab"],
            "quick_check": entry["quick_check"],
            "run_kind": entry["run_kind"],
        }
        for entry in context["run_history"]
    ]

    # Enrich with evidence if available
    if evidence_store:
        from ..evidence.query import (
            query_best_run, query_comparison_table, query_failures,
            query_non_improving_runs,
        )

        sid = state.session_id
        # Plan T3: ResearchSessionState.best_run_id is canonical. When the
        # state has a best but its evidence is missing (this happens when a
        # later ratchet_revert wiped the untracked record — see Plan T2),
        # do NOT fall back to query_best_run() — that would silently
        # downgrade the report to whatever older run still has evidence on
        # disk (session_a70dd3a564c1 reported auc=0.81 when the actual best
        # was 0.8449). Instead, keep state's best and tag it with
        # evidence_status='missing' so IntegrityGuard's fatal
        # `evidence_run_missing` check stays correlated with the report.
        if state.best_run_id:
            try:
                best = evidence_store.load(state.best_run_id)
            except Exception:
                best = None
            if best:
                context["best_run"] = {
                    "run_id": best.run_id,
                    "primary_metric_value": best.primary_metric_value,
                    "primary_metric_name": best.primary_metric_name,
                    "git_commit": best.git_commit,
                    "duration": best.duration,
                    "code_diff_summary": best.git_diff[:200] if best.git_diff else "",
                    "run_dir": best.run_dir,
                    "data_output_dir": best.data_output_dir,
                    "model_path": best.model_path,
                    "pathlab": dict(best.pathlab or {}),
                    "evidence_status": "present",
                }
            else:
                # State best exists but evidence doesn't. Preserve state's
                # best_run_id + best_metric_value (already populated above
                # from state.run_history) and surface the integrity gap.
                context["best_run"]["evidence_status"] = "missing"
        else:
            # No state best at all → fall back to evidence-only lookup.
            best = query_best_run(evidence_store, session_id=sid)
            if best:
                context["best_run"] = {
                    "run_id": best.run_id,
                    "primary_metric_value": best.primary_metric_value,
                    "primary_metric_name": best.primary_metric_name,
                    "git_commit": best.git_commit,
                    "duration": best.duration,
                    "code_diff_summary": best.git_diff[:200] if best.git_diff else "",
                    "run_dir": best.run_dir,
                    "data_output_dir": best.data_output_dir,
                    "model_path": best.model_path,
                    "pathlab": dict(best.pathlab or {}),
                    "evidence_status": "present",
                }

        # Key rows by (iteration, run_id) rather than run_id alone. A sticky
        # run_id bug (e.g. session_b14b074d2268 / 2026-04-20) can leave
        # run_history with all entries sharing one run_id across distinct
        # iterations — keying solely by run_id would collapse 17 rows into
        # one, producing a report that falsely claims "only a single run was
        # committed". When there is exactly one state row for a run_id, merge
        # evidence into that row even if a non-metric setup step shifted the
        # evidence iteration number; otherwise reports duplicate the same
        # training run.
        comparison_rows: dict[tuple[int, str], dict] = {
            (row.get("iteration", 0), row.get("run_id", "")): row
            for row in context["comparison_table"]
        }
        for row in query_comparison_table(evidence_store, session_id=sid):
            run_id = row.get("run_id", "")
            if not run_id:
                continue
            matching_keys = [
                key for key in comparison_rows
                if key[1] == run_id
            ]
            key = (
                matching_keys[0]
                if len(matching_keys) == 1
                else (row.get("iteration", 0), run_id)
            )
            comparison_rows[key] = {
                **comparison_rows.get(key, {}),
                **row,
            }
        context["comparison_table"] = sorted(
            comparison_rows.values(),
            key=lambda row: (row.get("iteration", 0), row.get("run_id", "")),
        )
        context["failures"] = query_failures(evidence_store, session_id=sid)
        # Plan-2026-04-28 P2 #7: separate clean-exit metric regressions
        # so the report doesn't lump them under "failures".
        context["non_improving_runs"] = query_non_improving_runs(
            evidence_store, session_id=sid,
        )

    # Add citations
    if citation_tracker:
        conv_id = str(state.conversation_id)
        citations = citation_tracker.get_conversation_citations(conv_id)
        context["references"] = [
            {
                "paper_id": c.paper_id,
                "context": c.context,
                "cited_in": c.cited_in,
                "chunk_id": c.chunk_id,
                "page": c.page,
                "section": c.section,
                "quote_snippet": c.quote_snippet,
            }
            for c in citations
        ]

    return context
