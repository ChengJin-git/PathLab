from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState
from pathscientist.synthesis.context import build_synthesis_context


def test_synthesis_context_preserves_external_test_history():
    state = ResearchSessionState.create(
        session_id="sess_external",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="External validation", success_metric="auc"),
    )
    state.external_test_history = [
        {
            "run_id": "run_external",
            "metrics": {"auc": 0.76, "external_task_type": "mil_classification"},
            "dataset_name": "External cohort A",
            "status": "completed",
        }
    ]

    ctx = build_synthesis_context(state)

    assert ctx["external_test_history"] == state.external_test_history
