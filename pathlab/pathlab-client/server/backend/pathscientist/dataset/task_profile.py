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

from .organ_resolver import OrganResolver
from .types import TaskProfile

_MOLECULAR_MUTATION_GENES = ("egfr", "kras", "tp53", "braf", "idh1", "idh2")
_LUNG_MOLECULAR_MUTATION_GENES = {"egfr", "kras"}
_NSCLC_DATASET_KEYWORDS = [
    "TCGA-LUAD", "TCGA-LUSC", "TCGA-LUNG", "NSCLC", "LUAD", "LUSC", "lung",
]


def infer_task_profile(
    question: str,
    *,
    selected_skill: str = "",
    dataset_hint: str = "",
) -> TaskProfile:
    """Return a TaskProfile inferred from the question + skill + hint."""
    text = f"{question} {selected_skill} {dataset_hint}".lower()
    skill = (selected_skill or "").strip().lower()
    prediction_target, label_keywords = _infer_prediction_target(text)
    organ = _infer_organ(text, prediction_target=prediction_target)
    dataset_keywords = _infer_dataset_keywords(text, prediction_target)

    # Explicit skill selection wins over keyword matching. In a raw-WSI MIL
    # plan, "feature extraction" is the setup step, not the final task type.
    if skill == "patch_segmentation":
        return TaskProfile(
            task_type="segmentation",
            asset_level="region",
            input_modality="patch_images",
            label_granularity="pixel",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "patch_segmentation",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "survival_analysis":
        return TaskProfile(
            task_type="survival_analysis",
            asset_level="slide",
            input_modality="features",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "survival_analysis",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "mil_classification":
        return TaskProfile(
            task_type="mil_classification",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "mil_classification",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "feature_extraction":
        return TaskProfile(
            task_type="feature_extraction",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "feature_extraction",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if skill == "patch_classification":
        return TaskProfile(
            task_type="patch_classification",
            asset_level="patch",
            input_modality="patch_images",
            label_granularity="patch",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "patch_classification",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    # Missing/unknown selected_skill: infer task shape from text.
    if any(
        tok in text for tok in ("segment", "segmentation", "mask", " dice", " iou")
    ):
        return TaskProfile(
            task_type="segmentation",
            asset_level="region",
            input_modality="patch_images",
            label_granularity="pixel",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "patch_segmentation",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if any(
        tok in text for tok in ("survival", "c-index", "cindex", "concordance")
    ):
        return TaskProfile(
            task_type="survival_analysis",
            asset_level="slide",
            input_modality="features",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=True,
            preferred_skill=selected_skill or "survival_analysis",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    if any(
        tok in text for tok in ("feature extraction", "extract features", "foundation model")
    ):
        return TaskProfile(
            task_type="feature_extraction",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
            requires_feature_extraction=False,
            preferred_skill=selected_skill or "feature_extraction",
            prediction_target=prediction_target,
            required_label_keywords=label_keywords,
        )

    # MIL/WSI: word-boundary on "mil" so "similar"/"familial" don't trigger.
    if (
        (
            prediction_target == "gleason_grade"
            and skill not in {"patch_classification", "patch_segmentation"}
        )
        or (
            prediction_target == "nsclc_subtype"
            and skill not in {"patch_classification", "patch_segmentation"}
            and not _has_explicit_patch_intent(text)
        )
        or re.search(
            r"(?<![a-z0-9])mil(?![a-z0-9])|\bwsi\b|\bslide[- ]level\b|\bwhole slide\b",
            text,
        )
    ):
        return TaskProfile(
            task_type="mil_classification",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ=organ,
            dataset_keywords=dataset_keywords,
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
        dataset_keywords=dataset_keywords,
        requires_feature_extraction=False,
        preferred_skill=selected_skill or "patch_classification",
        prediction_target=prediction_target,
        required_label_keywords=label_keywords,
    )


def _infer_organ(text: str, *, prediction_target: str = "") -> str:
    """Return the canonical organ string when the text mentions it."""
    match = OrganResolver.load_default().resolve_text(
        f"{text} {prediction_target}",
        source="task_profile",
    )
    return match.canonical


def _infer_dataset_keywords(text: str, prediction_target: str) -> list[str]:
    """Map a prediction target to dataset name + organ keywords.

    The result is consumed by grounding's SOTA fallback (the first
    element becomes the dataset query when ``dataset_hint`` is empty),
    so a target with no entry here causes SOTA to report
    ``no_dataset_hint`` even when the user clearly named the prediction
    task.

    Plan-2026-05-14 stage3 P1-6: widened from 3 targets to 7. HER2 /
    EGFR / metastasis / subtype were returning [] and silently
    truncating the SOTA chain.
    """
    if prediction_target == "gleason_grade":
        return ["PANDA", "prostate", "gleason", "ISUP"]
    if prediction_target == "microsatellite_instability":
        return ["CRC-MSI", "MSI", "MSI-H", "MSS"]
    if prediction_target == "chronic_gastritis_grading":
        return [
            "CG-MIL",
            "SciDB",
            "chronic_gastritis",
            "gastritis",
            "stomach",
            "gastric",
            "Task1",
            "Task2",
            "Task3",
            "Task4",
        ]
    if prediction_target == "her2":
        return ["TCGA-BRCA", "BRCA-HER2", "HER2", "breast", "HER2-positive"]
    if prediction_target == "nsclc_subtype":
        return list(_NSCLC_DATASET_KEYWORDS)
    if prediction_target in _MOLECULAR_MUTATION_GENES:
        gene = prediction_target.upper()
        keywords = [gene, f"{gene}-mutation", "molecular", "mutation"]
        if prediction_target in _LUNG_MOLECULAR_MUTATION_GENES:
            return ["TCGA-LUNG", "TCGA-LUAD", *keywords, "lung"]
        return keywords
    if prediction_target == "metastasis":
        return [
            "Camelyon17", "Camelyon16",
            "metastasis", "lymph_node", "sentinel_lymph_node",
        ]
    if prediction_target == "subtype":
        # Generic — no canonical dataset, but seed with the target word
        # plus common subtype tasks so SotaLookup's fuzzy match has
        # something to work with. Better than no_dataset_hint.
        return ["subtype", "classification", "cancer subtype"]
    return []


# Plan-2026-04-29 P1-6: prediction-target inference. Returns
# (canonical_target, required_label_keywords) so the scout can refuse
# datasets that lack matching label semantics. Pre-fix, the MSI prompt
# matched NCT-CRC-HE-100K (a 9-class tissue dataset) because organ +
# task_type both lined up.
def _infer_prediction_target(text: str) -> tuple[str, list[str]]:
    # P0-B fix (session_858e8a2cdc49): the user's prompt referenced
    # ``CRC-MSI`` (a common dataset name). Pre-fix, this function only
    # caught standalone ``msi`` / ``msi-h`` / ``microsatellite``, so the
    # hyphenated form fell through and prediction_target stayed empty —
    # discovery then had no signal to reject NCT-CRC-HE-100K (a 9-class
    # tissue dataset) when ranking against the user's MSI binary task.
    # We add ``-msi`` / ``msi-`` patterns and check both as contiguous
    # tokens (so ``mismatch``, ``dismiss``, ``cosmis`` etc. don't fire).
    if (
        "microsatellite" in text
        or "msi-h" in text
        or "msi-l" in text
        or "-msi" in text          # crc-msi, panda-msi, tcga-msi, ...
        or "msi_" in text          # snake_case variants
        or "_msi" in text
        or " msi " in f" {text} "
        or text.endswith(" msi")
        or text.startswith("msi ")
    ):
        return (
            "microsatellite_instability",
            ["MSI", "MSI-H", "MSS", "microsatellite", "microsatellite_instability"],
        )
    if any(
        tok in text
        for tok in (
            "chronic gastritis",
            "gastritis",
            "gastric inflammation",
            "inflammation grading",
            "intestinal metaplasia",
        )
    ):
        return (
            "chronic_gastritis_grading",
            [
                "gastritis",
                "inflammation",
                "activity",
                "atrophy",
                "intestinal_metaplasia",
                "intestinal metaplasia",
                "Task1",
                "Task2",
                "Task3",
                "Task4",
            ],
        )
    if "her2" in text:
        return ("her2", ["HER2", "ERBB2"])
    molecular_gene = _infer_molecular_mutation_gene(text)
    if molecular_gene:
        return (molecular_gene, [molecular_gene.upper(), "mutation", "molecular"])
    if _is_nsclc_subtype_text(text):
        return ("nsclc_subtype", ["LUAD", "LUSC", "NSCLC"])
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


def _has_explicit_patch_intent(text: str) -> bool:
    """Return True only when the user explicitly asks for patch-level input.

    TCGA LUAD/LUSC subtype prompts are slide-level WSI/MIL by default; do not
    route them to patch classification unless the user says patch/tile.
    """
    return bool(re.search(r"\bpatch(?:es)?\b|\bpatch[- ]level\b|\btile(?:s)?\b", text))


def _is_nsclc_subtype_text(text: str) -> bool:
    tokens = set(re.split(r"[^a-z0-9]+", text.lower()))
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    has_luad_lusc = {"luad", "lusc"}.issubset(tokens) or (
        "tcgaluad" in compact and "tcgalusc" in compact
    )
    return "nsclc" in tokens or has_luad_lusc


def _infer_molecular_mutation_gene(text: str) -> str:
    has_molecular_context = any(
        tok in text
        for tok in (
            "mutation",
            "mutational",
            "mutant",
            "wildtype",
            "wild-type",
            "molecular",
            "variant",
            "alteration",
            "status",
        )
    )
    for gene in _MOLECULAR_MUTATION_GENES:
        if not re.search(rf"(?<![a-z0-9]){re.escape(gene)}(?![a-z0-9])", text):
            continue
        # Preserve the historical EGFR target inference while requiring
        # mutation/status context for broader gene symbols.
        if gene == "egfr" or has_molecular_context:
            return gene
    return ""
