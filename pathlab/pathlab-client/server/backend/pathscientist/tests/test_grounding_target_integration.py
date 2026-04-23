from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from pathscientist.orchestrator.grounding import ground_objective
from pathscientist.orchestrator.types import (
    ResearchObjective, ResearchSessionState,
)
from pathscientist.literature.types import SotaTarget


class _StubLookup:
    def __init__(self, target: SotaTarget | None = None):
        self._t = target
        self.calls: list[tuple[str, str, str]] = []
    def lookup(self, *, dataset, task_type, metric):
        self.calls.append((dataset, task_type, metric))
        return self._t


def _state(question: str, dataset_hint: str = "") -> ResearchSessionState:
    obj = ResearchObjective(
        question=question, success_metric="auc",
        dataset_hint=dataset_hint, preferred_skill="patch_classification",
    )
    return ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(), objective=obj,
    )


def test_grounding_sets_target_from_lookup():
    target = SotaTarget(
        dataset="CRC-MSI", task_type="classification", metric_name="auc",
        metric_value=0.87, paper_id="pwc:kather2019",
        paper_title="Deep learning MSI", paper_url="https://example.org/k",
        source="pwc", confidence="high",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    lookup = _StubLookup(target=target)
    state = _state("improve AUC on CRC-MSI")
    ground_objective(state, literature_store=None, sota_lookup=lookup)
    assert state.objective.target_metric_value == 0.87
    assert "kather2019" in state.objective.target_source.lower() or \
           "deep learning msi" in state.objective.target_source.lower()
    assert state.objective.target_confidence == "high"


def test_grounding_leaves_target_empty_when_lookup_none():
    lookup = _StubLookup(target=None)
    state = _state("improve AUC on NOVEL-NEW-DATASET")
    ground_objective(state, literature_store=None, sota_lookup=lookup)
    assert state.objective.target_metric_value == 0.0
    assert state.objective.target_source == ""


def test_grounding_fills_dataset_hint_from_question():
    """If dataset_hint is empty, grounding must extract it from the question
    BEFORE calling the lookup — otherwise lookup is invoked with dataset=''
    and returns None unconditionally."""
    lookup = _StubLookup(target=None)
    state = _state("improve AUC on CRC-MSI", dataset_hint="")
    ground_objective(state, literature_store=None, sota_lookup=lookup)
    # The recorded lookup call must have dataset="CRC-MSI", not "".
    assert lookup.calls[0][0] == "CRC-MSI"
    # And the extracted dataset_hint must be persisted on the objective.
    assert state.objective.dataset_hint == "CRC-MSI"


def test_grounding_skips_lookup_when_none_passed():
    """Backward compat: ground_objective without sota_lookup must not
    error — some tests and backfill paths call it without the new arg."""
    state = _state("x")
    ground_objective(state, literature_store=None, sota_lookup=None)
    assert state.objective.target_metric_value == 0.0
