"""Heuristic task-profile inference from research question + skill hint.

Used by grounding to emit a structured TaskProfile that the dataset
acquisition layer (registry scout, normalizers) can match against.
Pure regex / keyword heuristics — no LLM call here. The plan's
``orchestrator/objective_extractor.py`` already does dataset-name
extraction; this module is the complementary task-shape inference.

Plan-2026-04-29 grounding-routing-repair Task 2: ``selected_skill``
wins over text-keyword inference. Pre-fix, only MIL vs patch was
distinguished — every survival/segmentation/feature_extraction prompt
collapsed to ``patch_classification`` because the keyword "patch"
appears in many phrasings. Now the body has skill-first branches so
the LLM-routed skill drives ``task_type`` consistency end-to-end.
"""
from __future__ import annotations

import re

from .types import TaskProfile


def infer_task_profile(
    question: str,
    *,
    selected_skill: str = "",
    dataset_hint: str = "",
) -> TaskProfile:
    """Return a TaskProfile inferred from the question + skill + hint."""
    text = f"{question} {selected_skill} {dataset_hint}".lower()
    skill = (selected_skill or "").strip().lower()
    organ = _infer_organ(text)
    prediction_target, label_keywords = _infer_prediction_target(text)

    # Skill-first branches. Order is specific-to-general so an explicit
    # ``selected_skill`` short-circuits keyword matching, but a missing
    # skill still gets a sensible default from the question text.
    if skill == "patch_segmentation" or any(
        tok in text for tok in ("segment", "segmentation", "mask", " dice", " iou")
    ):
        return TaskProfile(
            task_type="segmentation",
            asset_level="region",
            input_modality="patch_images",
            label_granularity="pixel",
            organ=organ,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "patch_segmentation",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "survival_analysis" or any(
        tok in text for tok in ("survival", "c-index", "cindex", "concordance")
    ):
        return TaskProfile(
            task_type="survival_analysis",
            asset_level="slide",
            input_modality="features",
            label_granularity="slide",
            organ=organ,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "survival_analysis",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "feature_extraction" or any(
        tok in text for tok in ("feature extraction", "extract features", "foundation model")
    ):
        return TaskProfile(
            task_type="feature_extraction",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "feature_extraction",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    # MIL/WSI: word-boundary on "mil" so "similar"/"familial" don't trigger.
    if skill == "mil_classification" or re.search(
        r"(?<![a-z0-9])mil(?![a-z0-9])|\bwsi\b|\bslide[- ]level\b|\bwhole slide\b",
        text,
    ):
        return TaskProfile(
            task_type="mil_classification",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "mil_classification",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    return TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ=organ,
        requires_feature_extraction=False,
        preferred_skill=selected_skill or "patch_classification",
        prediction_target=prediction_target,
        required_label_keywords=label_keywords,
    )


def _infer_organ(text: str) -> str:
    """Return the canonical organ string when the text mentions it."""
    if any(tok in text for tok in ("crc", "colorectal", "colon", "rectal", "msi")):
        return "colorectal"
    if any(tok in text for tok in ("breast", "brca", "camelyon", "bracs")):
        return "breast"
    if "prostate" in text or "panda" in text:
        return "prostate"
    if "lung" in text:
        return "lung"
    return ""


# Plan-2026-04-29 P1-6: prediction-target inference. Returns
# (canonical_target, required_label_keywords) so the scout can refuse
# datasets that lack matching label semantics. Pre-fix, the MSI prompt
# matched NCT-CRC-HE-100K (a 9-class tissue dataset) because organ +
# task_type both lined up.
def _infer_prediction_target(text: str) -> tuple[str, list[str]]:
    if (
        "microsatellite" in text
        or "msi-h" in text
        or " msi " in f" {text} "
        or text.endswith(" msi")
        or text.startswith("msi ")
    ):
        return (
            "microsatellite_instability",
            ["MSI", "MSI-H", "MSS", "microsatellite", "microsatellite_instability"],
        )
    if "her2" in text:
        return ("her2", ["HER2", "ERBB2"])
    if "egfr" in text:
        return ("egfr", ["EGFR"])
    if "metastasis" in text or "metastatic" in text:
        return (
            "metastasis",
            ["metastasis", "metastatic", "tumor", "lymph_node"],
        )
    if "gleason" in text or "isup" in text:
        return ("gleason_grade", ["gleason", "ISUP", "grade"])
    if "subtype" in text:
        return ("subtype", ["subtype"])
    return ("", [])
