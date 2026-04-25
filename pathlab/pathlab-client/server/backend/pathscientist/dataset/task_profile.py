"""Heuristic task-profile inference from research question + skill hint.

Used by grounding to emit a structured TaskProfile that the dataset
acquisition layer (registry scout, normalizers) can match against.
Pure regex / keyword heuristics — no LLM call here. The plan's
``orchestrator/objective_extractor.py`` already does dataset-name
extraction; this module is the complementary task-shape inference.
"""
from __future__ import annotations

from .types import TaskProfile


def infer_task_profile(
    question: str,
    *,
    selected_skill: str = "",
    dataset_hint: str = "",
) -> TaskProfile:
    """Return a TaskProfile inferred from the question + skill + hint."""
    text = f"{question} {selected_skill} {dataset_hint}".lower()
    organ = _infer_organ(text)
    if "mil" in text or "wsi" in text or "slide-level" in text or "whole slide" in text:
        return TaskProfile(
            task_type="mil_classification",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "mil_classification",
        )
    return TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ=organ,
        requires_feature_extraction=False,
        preferred_skill=selected_skill or "patch_classification",
    )


def _infer_organ(text: str) -> str:
    """Return the canonical organ string when the text mentions it."""
    if any(tok in text for tok in ("crc", "colorectal", "colon", "rectal", "msi")):
        return "colorectal"
    if any(tok in text for tok in ("breast", "brca", "camelyon")):
        return "breast"
    if "prostate" in text or "panda" in text:
        return "prostate"
    if "lung" in text:
        return "lung"
    return ""
