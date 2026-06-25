from __future__ import annotations
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.orchestrator.prompts import build_execution_brief
from autoresearch.orchestrator.types import (
    ResearchObjective, ResearchSessionState,
)


def _state(target_value: float = 0.0, target_source: str = "",
           target_confidence: str = "",
           source: str = "pwc") -> ResearchSessionState:
    obj = ResearchObjective(
        question="Improve AUC on CRC-MSI",
        success_metric="auc", dataset_hint="CRC-MSI",
        target_metric_value=target_value, target_source=target_source,
        target_confidence=target_confidence,
    )
    state = ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(), objective=obj,
    )
    if target_value > 0.0:
        state.grounding["sota_target"] = {
            "source": source,
            "confidence": target_confidence or "medium",
        }
    return state


def test_brief_renders_explicit_target_when_set():
    state = _state(
        target_value=0.87,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="high",
        source="pwc",
    )
    brief = build_execution_brief(state)
    assert "0.87" in brief
    assert "kather2019" in brief.lower() or "deep learning msi" in brief.lower()
    assert "CRC-MSI" in brief
    assert "(high confidence)" in brief or "confidence: high" in brief
    assert "Your SOTA target" in brief


def test_brief_skips_target_line_when_zero_value():
    state = _state(target_value=0.0)
    brief = build_execution_brief(state)
    assert "Your target:" not in brief or "beat 0.00" not in brief
    assert "Your SOTA target" not in brief
    assert "Literature reference target" not in brief


def test_brief_low_confidence_caveat_for_hard_target():
    state = _state(
        target_value=0.80,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="low",
        source="pwc",
    )
    brief = build_execution_brief(state)
    assert "Your SOTA target" in brief
    assert "0.80" in brief
    assert "confidence is low" in brief.lower()
    # advisory-note should not appear for hard targets
    assert "abstract-level literature extraction" not in brief.lower()


def test_brief_low_confidence_caveat_for_advisory_target():
    state = _state(
        target_value=0.75,
        target_source="openalex:W1 — title",
        target_confidence="low",
        source="openalex+llm",
    )
    brief = build_execution_brief(state)
    assert "Literature reference target" in brief
    assert "Your SOTA target" not in brief
    assert "0.75" in brief
    # openalex+llm path uses its own advisory note, not the low-confidence caveat
    assert "abstract-level literature extraction" in brief.lower()


def test_brief_uses_advisory_wording_for_openalex_llm_target():
    state = _state(
        target_value=0.75,
        target_source="openalex:W1 — title",
        target_confidence="medium",
        source="openalex+llm",
    )
    brief = build_execution_brief(state)
    assert "Literature reference target" in brief
    assert "Your SOTA target" not in brief
    assert "roughly match" in brief
    assert "abstract-level literature extraction" in brief.lower()


def test_brief_uses_hard_wording_for_pwc_target():
    state = _state(
        target_value=0.87,
        target_source="pwc:kather2019 — Deep learning MSI",
        target_confidence="high",
        source="pwc",
    )
    brief = build_execution_brief(state)
    assert "Your SOTA target: beat" in brief
    assert "Literature reference target" not in brief
    assert "abstract-level literature extraction" not in brief.lower()


def test_brief_uses_hard_wording_for_local_store_target():
    state = _state(
        target_value=0.82,
        target_source="local_store:curated — Some paper",
        target_confidence="high",
        source="local_store",
    )
    brief = build_execution_brief(state)
    assert "Your SOTA target: beat" in brief
    assert "0.82" in brief
    assert "Literature reference target" not in brief
    assert "abstract-level literature extraction" not in brief.lower()
