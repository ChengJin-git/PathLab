from __future__ import annotations
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.prompts import build_execution_brief
from pathscientist.orchestrator.types import (
    ResearchObjective, ResearchSessionState,
)


def _state(target_value: float = 0.0, target_source: str = "",
           target_confidence: str = "") -> ResearchSessionState:
    obj = ResearchObjective(
        question="Improve AUC on CRC-MSI",
        success_metric="auc", dataset_hint="CRC-MSI",
        target_metric_value=target_value, target_source=target_source,
        target_confidence=target_confidence,
    )
    return ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(), objective=obj,
    )


def test_brief_renders_explicit_target_when_set():
    state = _state(
        target_value=0.87,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="high",
    )
    brief = build_execution_brief(state)
    assert "0.87" in brief
    assert "kather2019" in brief.lower() or "deep learning msi" in brief.lower()
    assert "CRC-MSI" in brief
    assert "(high confidence)" in brief or "confidence: high" in brief


def test_brief_skips_target_line_when_zero_value():
    state = _state(target_value=0.0)
    brief = build_execution_brief(state)
    assert "Your target:" not in brief or "beat 0.00" not in brief


def test_brief_includes_low_confidence_caveat():
    state = _state(
        target_value=0.75, target_source="openalex:W1 — title",
        target_confidence="low",
    )
    brief = build_execution_brief(state)
    # Must flag low confidence so the agent doesn't overfit to a noisy number.
    assert "low" in brief.lower()
    assert "0.75" in brief
