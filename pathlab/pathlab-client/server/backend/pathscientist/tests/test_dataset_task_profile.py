"""Tests for dataset.task_profile.infer_task_profile + grounding's
emission of grounding["task_profile"]."""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

# Make the pathscientist package importable through the canonical sys.path
# trick used by the rest of the orchestrator tests, so we can also reach
# pathscientist.orchestrator.grounding here.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

# Bare-import path matches tests/test_dataset_types.py convention.
from dataset.task_profile import infer_task_profile

# pathscientist-prefix path matches tests/test_grounding_target_integration.py.
from pathscientist.orchestrator.grounding import ground_objective
from pathscientist.orchestrator.types import ResearchObjective


def test_infer_task_profile_patch_for_patch_question():
    p = infer_task_profile("train a patch-level MSI classifier on colorectal H&E patches",
                           selected_skill="patch_classification")
    assert p.task_type == "patch_classification"
    assert p.asset_level == "patch"
    assert p.input_modality == "patch_images"
    assert p.organ == "colorectal"
    assert p.requires_feature_extraction is False
    assert p.preferred_skill == "patch_classification"


def test_infer_task_profile_mil_for_wsi_question():
    p = infer_task_profile("run WSI-level MIL classification for breast cancer slides",
                           selected_skill="mil_classification")
    assert p.task_type == "mil_classification"
    assert p.asset_level == "slide"
    assert p.input_modality == "wsi"
    assert p.organ == "breast"
    assert p.requires_feature_extraction is True


def test_infer_task_profile_organ_fallback_empty():
    """No recognized organ in the text → organ defaults to empty string."""
    p = infer_task_profile("improve generic baseline metric")
    assert p.organ == ""


def test_infer_task_profile_uses_dataset_hint_for_organ():
    """Dataset hint (e.g. 'PANDA') flows into organ inference."""
    p = infer_task_profile("improve baseline", dataset_hint="PANDA")
    assert p.organ == "prostate"


def test_infer_task_profile_default_skill_when_unspecified():
    """When selected_skill is empty, preferred_skill defaults to a sensible task-shape default."""
    patch_p = infer_task_profile("train classifier on patches")
    assert patch_p.preferred_skill == "patch_classification"
    mil_p = infer_task_profile("WSI-level MIL training")
    assert mil_p.preferred_skill == "mil_classification"


# --- Integration: grounding emits task_profile ---


def test_grounding_emits_patch_classification_profile():
    objective = ResearchObjective(
        question="train a patch-level MSI classifier on colorectal H&E patches",
        success_metric="auc",
        preferred_skill="patch_classification",
    )
    grounding = ground_objective(objective, literature_store=None)
    profile = grounding["task_profile"]
    assert profile["task_type"] == "patch_classification"
    assert profile["asset_level"] == "patch"
    assert profile["input_modality"] == "patch_images"
    assert profile["organ"] == "colorectal"
    assert profile["requires_feature_extraction"] is False


def test_grounding_emits_mil_profile_for_wsi_prompt():
    objective = ResearchObjective(
        question="run WSI-level MIL classification for breast cancer slides",
        success_metric="auc",
        preferred_skill="mil_classification",
    )
    grounding = ground_objective(objective, literature_store=None)
    profile = grounding["task_profile"]
    assert profile["task_type"] == "mil_classification"
    assert profile["asset_level"] == "slide"
    assert profile["requires_feature_extraction"] is True


def test_grounding_task_profile_uses_objective_dataset_hint():
    """If objective.dataset_hint already set, that flows into organ inference."""
    objective = ResearchObjective(
        question="improve baseline",
        success_metric="auc",
        preferred_skill="mil_classification",
        dataset_hint="PANDA",
    )
    grounding = ground_objective(objective, literature_store=None)
    assert grounding["task_profile"]["organ"] == "prostate"


# --- Execution brief renders Task profile ---


def test_execution_brief_renders_task_profile_line():
    from pathscientist.orchestrator.prompts import build_execution_brief
    from pathscientist.orchestrator.types import ResearchSessionState

    state = ResearchSessionState.create(
        session_id="sid",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="train", success_metric="auc"),
    )
    state.grounding = {
        "task_profile": {
            "task_type": "patch_classification",
            "asset_level": "patch",
        }
    }
    brief = build_execution_brief(state)
    assert "Task profile:" in brief
    assert "patch_classification" in brief
    assert "patch" in brief


def test_execution_brief_omits_task_profile_when_absent():
    from pathscientist.orchestrator.prompts import build_execution_brief
    from pathscientist.orchestrator.types import ResearchSessionState

    state = ResearchSessionState.create(
        session_id="sid",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="train", success_metric="auc"),
    )
    state.grounding = {}
    brief = build_execution_brief(state)
    assert "Task profile:" not in brief
