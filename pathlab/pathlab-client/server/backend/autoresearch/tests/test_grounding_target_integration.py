from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from autoresearch.orchestrator.director import ResearchDirector
from autoresearch.orchestrator.grounding import ground_objective
from autoresearch.orchestrator.types import (
    ResearchObjective, ResearchSessionState, STAGE_GROUNDING,
)
from autoresearch.literature.types import SotaTarget


class _StubLookup:
    def __init__(self, target: SotaTarget | None = None):
        self._t = target
        self.calls: list[tuple[str, str, str]] = []
    def lookup(self, *, dataset, task_type, metric):
        self.calls.append((dataset, task_type, metric))
        return self._t


def _objective(question: str, dataset_hint: str = "") -> ResearchObjective:
    return ResearchObjective(
        question=question, success_metric="auc",
        dataset_hint=dataset_hint, preferred_skill="patch_classification",
    )


def _state(question: str, dataset_hint: str = "") -> ResearchSessionState:
    obj = _objective(question, dataset_hint=dataset_hint)
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
    obj = _objective("improve AUC on CRC-MSI")
    grounding = ground_objective(obj, literature_store=None, sota_lookup=lookup)
    sota = grounding.get("sota_target") or {}
    assert sota.get("metric_value") == 0.87
    assert sota.get("source") == "pwc"
    assert sota.get("paper_id") == "pwc:kather2019"
    assert sota.get("paper_title") == "Deep learning MSI"
    assert sota.get("confidence") == "high"


def test_grounding_leaves_target_empty_when_lookup_none():
    lookup = _StubLookup(target=None)
    obj = _objective("improve AUC on NOVEL-NEW-DATASET")
    grounding = ground_objective(obj, literature_store=None, sota_lookup=lookup)
    assert not grounding.get("sota_target")


def test_grounding_fills_dataset_hint_from_question():
    """If dataset_hint is empty, grounding must extract it from the question
    BEFORE calling the lookup — otherwise lookup is invoked with dataset=''
    and returns None unconditionally. Also emits dataset_hint_inferred in
    the returned dict so the director can copy it onto state.objective."""
    lookup = _StubLookup(target=None)
    obj = _objective("improve AUC on CRC-MSI", dataset_hint="")
    grounding = ground_objective(obj, literature_store=None, sota_lookup=lookup)
    # The recorded lookup call must have dataset="CRC-MSI", not "".
    assert lookup.calls[0][0] == "CRC-MSI"
    # Inferred hint surfaces in the returned dict.
    assert grounding.get("dataset_hint_inferred") == "CRC-MSI"
    # And the extracted dataset_hint is still written back to the passed
    # objective for the legacy single-caller case.
    assert obj.dataset_hint == "CRC-MSI"


def test_grounding_skips_lookup_when_none_passed():
    """Backward compat: ground_objective without sota_lookup must not
    error — some tests and backfill paths call it without the new arg."""
    obj = _objective("x")
    grounding = ground_objective(obj, literature_store=None, sota_lookup=None)
    assert not grounding.get("sota_target")


def test_director_copies_grounding_target_onto_state_objective():
    """The director, not grounding.py, is responsible for copying the
    sota_target payload off the grounding dict onto state.objective."""
    target = SotaTarget(
        dataset="CRC-MSI", task_type="classification", metric_name="auc",
        metric_value=0.87, paper_id="pwc:kather2019",
        paper_title="Deep learning MSI", paper_url="https://example.org/k",
        source="pwc", confidence="high",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    lookup = _StubLookup(target=target)
    state = _state("improve AUC on CRC-MSI", dataset_hint="")
    state.stage = STAGE_GROUNDING
    director = ResearchDirector(
        auto_approve=True, literature_store=None, sota_lookup=lookup,
    )
    director.advance(state)
    assert state.objective.target_metric_value == 0.87
    assert state.objective.target_confidence == "high"
    assert "kather2019" in state.objective.target_source
    assert state.objective.dataset_hint == "CRC-MSI"
