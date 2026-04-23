from __future__ import annotations
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.types import (
    ResearchObjective, ResearchSessionState,
)
from pathscientist.orchestrator.state_bridge import (
    dump_research_session_state,
)


def test_objective_has_target_defaults():
    obj = ResearchObjective(question="x")
    assert obj.target_metric_value == 0.0
    assert obj.target_source == ""
    assert obj.target_confidence == ""


def test_session_state_dump_includes_target_fields():
    obj = ResearchObjective(
        question="improve AUC on CRC-MSI",
        target_metric_value=0.87,
        target_source="Kather et al. 2019",
        target_confidence="high",
    )
    state = ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(), objective=obj,
    )
    payload = dump_research_session_state(state)
    assert payload["objective"]["target_metric_value"] == 0.87
    assert payload["objective"]["target_source"] == "Kather et al. 2019"
    assert payload["objective"]["target_confidence"] == "high"
