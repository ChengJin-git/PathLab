"""Deterministic claim extraction from synthesis context."""
from __future__ import annotations

from typing import Any

from .types import ClaimRecord


def build_claims(context: dict[str, Any]) -> list[ClaimRecord]:
    """Extract grounded claims from synthesis context using deterministic rules.

    Does NOT use LLM. Claims are derived from evidence and citations only.
    """
    claims: list[ClaimRecord] = []
    metric = context.get("success_metric", "auc")

    # Result claim for best run
    best = context.get("best_run", {})
    if best and best.get("run_id"):
        value = best.get("primary_metric_value", 0.0)
        claims.append(ClaimRecord(
            claim_id="claim_best_result",
            section="results",
            claim_type="result",
            statement=f"Best committed run achieved {metric} {value:.4f}.",
            evidence_run_ids=[best["run_id"]],
            citation_paper_ids=[],
            confidence="high",
        ))

    # Comparison claims from references
    for ref in context.get("references", []):
        paper_id = ref.get("paper_id", "")
        ref_context = ref.get("context", "")
        if paper_id and ref_context:
            claims.append(ClaimRecord(
                claim_id=f"claim_ref_{paper_id}",
                section="results",
                claim_type="comparison",
                statement=f"Compared against prior work: {ref_context}",
                evidence_run_ids=[best.get("run_id", "")] if best else [],
                citation_paper_ids=[paper_id],
                confidence="medium",
            ))

    # Plan-2026-04-28 P2 #7: split runtime failures from clean-exit
    # metric regressions. Pre-fix, every committed=False run was rendered
    # as `failed with <error_type>` even when the script ran cleanly and
    # the ratchet just reverted because the metric didn't beat the
    # tracker best.
    for i, failure in enumerate(context.get("failures", [])):
        run_id = failure.get("run_id", "")
        error_type = failure.get("error_type", "unknown")
        error_hint = failure.get("error_hint", "")
        claims.append(ClaimRecord(
            claim_id=f"claim_failure_{i}",
            section="limitations",
            claim_type="limitation",
            statement=f"Run {run_id} failed with {error_type}. {error_hint}".strip(),
            evidence_run_ids=[run_id] if run_id else [],
            citation_paper_ids=[],
            confidence="high",
        ))

    # Plan-2026-04-28 P2 #7: separate claim type for non-improving runs
    # (clean exit + reverted because metric regressed). These are part of
    # the experiment narrative, not failures.
    for i, regression in enumerate(context.get("non_improving_runs", [])):
        run_id = regression.get("run_id", "")
        metric_name = regression.get("primary_metric_name", "metric")
        metric_value = regression.get("primary_metric_value", 0.0)
        claims.append(ClaimRecord(
            claim_id=f"claim_non_improving_{i}",
            section="limitations",
            claim_type="non_improving",
            statement=(
                f"Run {run_id} completed but did not improve "
                f"{metric_name} ({metric_value:.4f}); ratchet reverted."
            ),
            evidence_run_ids=[run_id] if run_id else [],
            citation_paper_ids=[],
            confidence="high",
        ))

    # Reproducibility claim
    repro = context.get("reproducibility", {})
    if repro:
        total = repro.get("total_iterations", 0)
        committed = repro.get("committed_runs", 0)
        claims.append(ClaimRecord(
            claim_id="claim_reproducibility",
            section="reproducibility",
            claim_type="reproducibility",
            statement=f"Session completed {total} iterations ({committed} committed, {total - committed} reverted).",
            evidence_run_ids=[],
            citation_paper_ids=[],
            confidence="high",
            notes=f"session_id={repro.get('session_id', '')}, conversation_id={repro.get('conversation_id', '')}",
        ))

    return claims
