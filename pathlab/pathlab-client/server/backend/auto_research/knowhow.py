"""
Pathology Know-How Library

Curated domain knowledge for experiment planning.
Phase 1: hardcoded best practices.
Phase 2: upgrade to RAG with vector retrieval from papers.
"""
from __future__ import annotations

import re
from typing import Optional


# Each entry: task pattern → recommended config + evidence
PATHOLOGY_KNOWHOW: list[dict] = [
    # ── Classification ────────────────────────────────────────────
    {
        "task_pattern": "MSI|microsatellite instability",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "ABMIL",
            "hyperparams": {"learning_rate": 0.0001, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "CONCH", "aggregator": "ABMIL"},
            {"extractor": "Virchow", "aggregator": "TransMIL"},
        ],
        "evidence": "UNI2 achieves AUC 0.93 on TCGA-CRC MSI prediction (2024 benchmark). "
                     "CONCH is a strong alternative with pathology-specific pretraining.",
        "data_type": "wsi",
    },
    {
        "task_pattern": "tumor classification|cancer classification|subtype|grading",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "ABMIL",
            "hyperparams": {"learning_rate": 0.0002, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "CONCH", "aggregator": "CLAM-SB"},
            {"extractor": "Virchow", "aggregator": "DSMIL"},
        ],
        "evidence": "UNI2 and CONCH are top performers across tumor classification benchmarks. "
                     "ABMIL provides good baseline; CLAM adds instance-level attention.",
        "data_type": "wsi",
    },
    {
        "task_pattern": "biomarker|molecular|mutation|expression|HER2|ER|PR|PD-L1|BRAF|KRAS",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "TransMIL",
            "hyperparams": {"learning_rate": 0.0001, "epochs": 80, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "CONCH", "aggregator": "ABMIL"},
        ],
        "evidence": "Biomarker prediction from H&E benefits from larger pretrained encoders. "
                     "TransMIL captures long-range dependencies useful for subtle morphological patterns.",
        "data_type": "wsi",
    },

    # ── Survival Analysis ─────────────────────────────────────────
    {
        "task_pattern": "survival|prognosis|outcome|OS|DFS|PFS|recurrence",
        "task_type": "survival",
        "recommended": {
            "extractor": "CONCH",
            "aggregator": "CLAM-SB",
            "hyperparams": {"learning_rate": 0.0002, "epochs": 30, "optimizer": "adam"},
        },
        "alternatives": [
            {"extractor": "UNI2", "aggregator": "ABMIL"},
            {"extractor": "CONCH", "aggregator": "TransMIL"},
        ],
        "evidence": "CONCH with pathology-specific pretraining is preferred for survival. "
                     "CLAM-SB with attention provides interpretable prognostic regions.",
        "data_type": "wsi",
    },

    # ── Segmentation ──────────────────────────────────────────────
    {
        "task_pattern": "segmentation|region|boundary|cell|nucleus|gland",
        "task_type": "segmentation",
        "recommended": {
            "extractor": "ResNet50",
            "aggregator": None,  # Segmentation uses architecture, not aggregator
            "architecture": "UNet++",
            "backbone": "resnet50",
            "hyperparams": {"learning_rate": 0.001, "epochs": 100, "optimizer": "adamw"},
        },
        "alternatives": [
            {"architecture": "DeepLabV3+", "backbone": "resnet101"},
            {"architecture": "FPN", "backbone": "efficientnet-b4"},
        ],
        "evidence": "UNet++ with ResNet50 backbone is a strong default for histopathology segmentation. "
                     "DeepLabV3+ excels at multi-scale tissue segmentation.",
        "data_type": "patch",
    },

    # ── Organ-Specific ────────────────────────────────────────────
    {
        "task_pattern": "lung|NSCLC|LUAD|LUSC",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "CLAM-MB",
            "hyperparams": {"learning_rate": 0.0001, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "CONCH", "aggregator": "ABMIL"},
        ],
        "evidence": "CLAM-MB (multi-branch) captures heterogeneous lung tumor subtypes effectively. "
                     "LUAD vs LUSC classification AUC > 0.95 with UNI2+CLAM-MB.",
        "data_type": "wsi",
    },
    {
        "task_pattern": "breast|BRCA|triple.negative|TNBC",
        "task_type": "classification",
        "recommended": {
            "extractor": "CONCH",
            "aggregator": "ABMIL",
            "hyperparams": {"learning_rate": 0.0002, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "UNI2", "aggregator": "TransMIL"},
        ],
        "evidence": "CONCH excels on breast cancer tasks due to pathology-specific features. "
                     "ABMIL is robust for binary/multi-class breast subtyping.",
        "data_type": "wsi",
    },
    {
        "task_pattern": "colorectal|colon|CRC|rectal",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "ABMIL",
            "hyperparams": {"learning_rate": 0.0001, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "CONCH", "aggregator": "DSMIL"},
        ],
        "evidence": "UNI2+ABMIL is the standard combination for CRC tasks. "
                     "DSMIL adds dual-stream attention useful for heterogeneous CRC tumors.",
        "data_type": "wsi",
    },
    {
        "task_pattern": "gastric|stomach|GC",
        "task_type": "classification",
        "recommended": {
            "extractor": "UNI2",
            "aggregator": "ABMIL",
            "hyperparams": {"learning_rate": 0.0001, "epochs": 50, "optimizer": "adamw"},
        },
        "alternatives": [
            {"extractor": "Virchow", "aggregator": "TransMIL"},
        ],
        "evidence": "Gastric cancer classification benefits from large pretrained encoders.",
        "data_type": "wsi",
    },

    # ── General Best Practices ────────────────────────────────────
    {
        "task_pattern": ".*",
        "task_type": "any",
        "recommended": None,
        "alternatives": None,
        "evidence": "General guidelines: "
                     "1) Start with UNI2+ABMIL as baseline for WSI classification. "
                     "2) Use CONCH for pathology-specific tasks. "
                     "3) Prefer AdamW optimizer with lr=0.0001-0.0002. "
                     "4) Use 5-fold cross-validation or 70/10/20 train/val/test split. "
                     "5) Report AUC, accuracy, and F1 for classification; C-index for survival.",
        "data_type": "any",
    },
]


def retrieve_knowhow(
    research_question: str,
    task_type: Optional[str] = None,
    max_results: int = 5,
) -> list[dict]:
    """
    Retrieve relevant know-how entries for a research question.

    Matches against task_pattern regex and optional task_type filter.
    Returns entries sorted by specificity (specific patterns first,
    catch-all '.*' last).

    Args:
        research_question: The user's research question
        task_type: Optional filter (classification, survival, segmentation)
        max_results: Maximum entries to return

    Returns:
        List of matching know-how entries
    """
    question_lower = research_question.lower()
    matches: list[tuple[int, dict]] = []

    for entry in PATHOLOGY_KNOWHOW:
        pattern = entry["task_pattern"]

        # Skip catch-all unless nothing else matches
        is_catchall = pattern == ".*"

        # Check task_type filter
        if task_type and entry["task_type"] not in (task_type, "any"):
            continue

        # Check pattern match
        try:
            if re.search(pattern, question_lower, re.IGNORECASE):
                # Score: specific patterns get higher priority than catch-all
                score = 0 if is_catchall else len(pattern)
                matches.append((score, entry))
        except re.error:
            continue

    # Sort by score descending (most specific first)
    matches.sort(key=lambda x: x[0], reverse=True)

    return [entry for _, entry in matches[:max_results]]
