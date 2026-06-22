"""Tests for SOTA plan Task 10: mention literature target in paper Limitations.

The Limitations section of the synthesis report must mention where the
session's best result sits relative to the literature SOTA target when one
is set, using the SAME hard-vs-advisory semantics that the execution brief
uses (Correction #4, commit 5c446858):

- source in {"pwc", "local_store"}  -> quantitative "literature target"
  wording with confidence annotation.
- source "openalex+llm" (or anything else) -> advisory "reference value"
  wording that explicitly tells the reader this is directional context,
  not a canonical SOTA bound.

When the objective has no target (target_metric_value == 0.0), the
section keeps its previous behavior (failures-only; empty when no
failures).
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.types import (
    ResearchObjective,
    ResearchSessionState,
    RunRecord,
)
from pathscientist.synthesis.context import build_synthesis_context
from pathscientist.synthesis.report_builder import _build_limitations_content


def _state(
    target_value: float = 0.0,
    target_source: str = "",
    target_confidence: str = "",
    source: str = "pwc",
    best_metric_value: float = 0.0,
    best_run_id: str = "",
) -> ResearchSessionState:
    obj = ResearchObjective(
        question="Improve AUC on CRC-MSI",
        success_metric="auc",
        dataset_hint="CRC-MSI",
        target_metric_value=target_value,
        target_source=target_source,
        target_confidence=target_confidence,
    )
    state = ResearchSessionState.create(
        session_id="sid",
        conversation_id=uuid4(),
        objective=obj,
    )
    if target_value > 0.0:
        state.grounding["sota_target"] = {
            "source": source,
            "confidence": target_confidence or "medium",
        }
    if best_run_id:
        state.record_run(
            RunRecord(
                run_id=best_run_id,
                iteration=0,
                metric_value=best_metric_value,
                committed=True,
            )
        )
    return state


def test_limitations_includes_quantitative_gap_for_pwc_target():
    state = _state(
        target_value=0.87,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="high",
        source="pwc",
        best_metric_value=0.82,
        best_run_id="run_001",
    )
    ctx = build_synthesis_context(state)
    out = _build_limitations_content(ctx)
    assert "literature target" in out
    assert "0.8700" in out
    assert "0.8200" in out
    assert "pwc" in out


def test_limitations_uses_reference_wording_for_openalex_llm_target():
    state = _state(
        target_value=0.87,
        target_source="openalex:W1 — Title",
        target_confidence="medium",
        source="openalex+llm",
        best_metric_value=0.82,
        best_run_id="run_001",
    )
    ctx = build_synthesis_context(state)
    out = _build_limitations_content(ctx)
    assert "reference value" in out
    # Advisory wording must not borrow the hard-target phrasing.
    assert "literature target for this dataset" not in out
    assert "directional context" in out


def test_limitations_skips_target_line_when_no_target():
    state = _state(target_value=0.0)
    ctx = build_synthesis_context(state)
    out = _build_limitations_content(ctx)
    # No target, no failures -> empty string (current behavior preserved).
    assert out == ""
    assert "literature target" not in out
    assert "reference value" not in out


def test_limitations_preserves_failures_list():
    state = _state(
        target_value=0.87,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="high",
        source="pwc",
        best_metric_value=0.82,
        best_run_id="run_001",
    )
    ctx = build_synthesis_context(state)
    ctx["failures"] = [
        {
            "run_id": "run_002",
            "error_type": "CUDA_OOM",
            "error_hint": "Reduce batch size.",
        }
    ]
    out = _build_limitations_content(ctx)
    # Target line present.
    assert "literature target" in out
    assert "0.8700" in out
    # Failure bullet preserved.
    assert "run_002" in out
    assert "CUDA_OOM" in out


def test_limitations_uses_hard_wording_for_local_store_target():
    state = _state(
        target_value=0.82,
        target_source="local_store:curated — Some paper",
        target_confidence="high",
        source="local_store",
        best_metric_value=0.78,
        best_run_id="run_001",
    )
    ctx = build_synthesis_context(state)
    out = _build_limitations_content(ctx)
    assert "literature target" in out
    assert "0.8200" in out
    assert "0.7800" in out
    assert "local_store" in out
    # Must NOT use advisory wording.
    assert "reference value" not in out
    assert "directional context" not in out
