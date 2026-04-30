"""Extract (dataset_hint, task_type) from a free-form research question.

Two-stage: regex pass against known pathology dataset names + common task
keywords, then (optional) LLM disambiguation when regex returns empty.
Keeps LLM use strictly additive — the regex path handles the common case
without any network/LLM cost.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

# Canonical pathology datasets we know about. Ordered by specificity so the
# regex can match 'TCGA-LUNG' before the more general 'TCGA' prefix.
_KNOWN_DATASETS = [
    # CRC-MSI and variants
    ("CRC-MSI", re.compile(r"\bCRC[-_\s]?MSI\b", re.IGNORECASE)),
    ("CRC-DX",  re.compile(r"\bCRC[-_\s]?DX\b", re.IGNORECASE)),
    # Camelyon family
    ("Camelyon17", re.compile(r"\bCamelyon[-_\s]?17\b", re.IGNORECASE)),
    ("Camelyon16", re.compile(r"\bCamelyon[-_\s]?16\b", re.IGNORECASE)),
    # TCGA cohorts — specific first
    ("TCGA-LUNG", re.compile(r"\bTCGA[-_\s]?LUNG\b", re.IGNORECASE)),
    ("TCGA-BRCA", re.compile(r"\bTCGA[-_\s]?BRCA\b", re.IGNORECASE)),
    ("TCGA-RCC",  re.compile(r"\bTCGA[-_\s]?RCC\b", re.IGNORECASE)),
    ("TCGA-UCEC", re.compile(r"\bTCGA[-_\s]?UCEC\b", re.IGNORECASE)),
    # General pathology benchmarks
    ("BRACS", re.compile(r"\bBRACS\b", re.IGNORECASE)),
    ("PANDA", re.compile(r"\bPANDA\b", re.IGNORECASE)),
    ("BACH",  re.compile(r"\bBACH\b", re.IGNORECASE)),
    ("NCT-CRC-HE-100K", re.compile(r"\bNCT[-_]?CRC[-_]?HE[-_]?100K\b", re.IGNORECASE)),
    ("PatchCamelyon", re.compile(r"\bPatch[-_\s]?Camelyon\b", re.IGNORECASE)),
]

# Accept dataset names that appear inside filesystem paths ("/Data/CRC-MSI").
_PATH_DATASET_RE = re.compile(r"/(?:data|Data|DATA|Dataset|datasets?)/([A-Z0-9][A-Z0-9\-_]{2,})", re.IGNORECASE)


# Plan-2026-04-29 P1-5: natural-language semantic mappings. Pre-fix, the
# prompt "predicting microsatellite instability from colorectal cancer
# H&E pathology images" produced ``dataset_hint=""`` because the regex
# only matched the literal "CRC-MSI" string. Now we map common
# disease+target phrasings to canonical dataset names so SOTA lookup,
# RAG, and acquisition can all use the same hint without the user
# having to spell "CRC-MSI".
#
# Each rule requires ALL of its ``all_of`` patterns to match before
# emitting the canonical dataset — keeps "MSI" alone (e.g. in a
# protein-binding paper) from accidentally pinning to CRC-MSI.
_SEMANTIC_DATASET_RULES: list[tuple[str, list[re.Pattern]]] = [
    (
        "CRC-MSI",
        [
            re.compile(
                r"microsatellite\s+instability|\bMSI[-_]?H\b|"
                r"(?<![A-Za-z])MSI(?![A-Za-z])",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:colorectal|colon|rectal|CRC)\b",
                re.IGNORECASE,
            ),
        ],
    ),
]


def _semantic_dataset(question: str) -> str:
    for canonical, patterns in _SEMANTIC_DATASET_RULES:
        if all(p.search(question) for p in patterns):
            return canonical
    return ""

# Plan-2026-04-29 grounding-routing-repair Task 5: order matters now —
# dict iteration order is insertion order in Python 3.7+, and the
# matching loop in ``_regex_task_type`` short-circuits on the first hit.
# Specific-task keywords (segmentation/survival/feature_extraction)
# must be checked BEFORE classification, because mixed prompts like
# "segment masks and report AUC/Dice" should classify as segmentation
# even though they mention AUC.
_TASK_KEYWORDS = {
    "segmentation": ("segment", "dice", "iou", "mask", "pixel"),
    "survival":     ("survival", "c-index", "cindex", "concordance", "os",
                     "risk strat"),
    "feature_extraction": (
        "feature extract", "feature extraction",
        "extract features", "foundation model", "extractor",
        "embed", "encode",
    ),
    "classification": (
        "classif", "auc", "msi", "microsatellite",
        "subtype", "grade", "patch", "mil",
        "slide-level", "linear probe",
    ),
}


def _regex_dataset(question: str) -> str:
    for canonical, rgx in _KNOWN_DATASETS:
        if rgx.search(question):
            return canonical
    m = _PATH_DATASET_RE.search(question)
    if m:
        # Normalize the captured token against known list (case-insensitive).
        token = m.group(1)
        for canonical, rgx in _KNOWN_DATASETS:
            if rgx.search(token):
                return canonical
        return token.upper() if not token.isupper() else token
    # Plan-2026-04-29 P1-5: semantic fallback — disease + prediction-target
    # phrasings (e.g. "MSI in colorectal cancer") map to the canonical
    # benchmark when no literal name appears.
    return _semantic_dataset(question)


def _regex_task_type(question: str, preferred_skill: str = "") -> str:
    text = (question + " " + preferred_skill).lower()
    # Plan-2026-04-29 grounding-routing-repair Task 5: skill hint wins
    # over keyword guessing, but use exact registered-skill names to map.
    # An invalid preferred_skill containing "mil" no longer auto-classifies.
    skill = preferred_skill.lower().strip()
    if skill in {"patch_classification", "mil_classification"}:
        return "classification"
    if skill == "patch_segmentation":
        return "segmentation"
    if skill == "survival_analysis":
        return "survival"
    if skill == "feature_extraction":
        return "feature_extraction"
    # Plan-2026-04-29 P1-5 + Task 5: short keywords ("os" / "mil")
    # require word boundaries — otherwise "pathology" matches survival
    # and "familial" matches classification.
    short_keywords = {"os", "mil"}
    for task, kws in _TASK_KEYWORDS.items():
        for kw in kws:
            if kw in short_keywords:
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    return task
            elif kw in text:
                return task
    return ""


_LLM_PROMPT = """Extract the dataset name and task type from this research question.

Return ONLY a single JSON object with keys:
  "dataset":   canonical dataset name (e.g. "CRC-MSI", "Camelyon16", "TCGA-LUNG"),
               or "" if no dataset is named or implied.
  "task_type": one of "classification" | "segmentation" | "survival" | "feature_extraction",
               or "" if unclear.

Question: {question}
"""


def extract_dataset_and_task(
    question: str,
    *,
    llm_parser: Callable[[str], str] | None = None,
    preferred_skill: str = "",
) -> tuple[str, str]:
    """Return (dataset_hint, task_type) for this question.

    Regex first; fall through to LLM only when regex returns empty dataset.
    """
    dataset = _regex_dataset(question)
    task = _regex_task_type(question, preferred_skill=preferred_skill)
    if dataset and task:
        return dataset, task

    if llm_parser is not None:
        try:
            raw = llm_parser(_LLM_PROMPT.format(question=question)) or ""
            raw = raw.strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json.loads(raw)
            if isinstance(data, dict):
                dataset = dataset or str(data.get("dataset", "") or "")
                task = task or str(data.get("task_type", "") or "")
        except Exception as e:
            logger.debug("objective_extractor LLM fallback failed: %s", e)

    return dataset, task
