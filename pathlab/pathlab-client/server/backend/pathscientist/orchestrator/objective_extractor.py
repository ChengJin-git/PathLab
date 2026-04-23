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

_TASK_KEYWORDS = {
    "classification": ("classif", "auc", "msi", "subtype", "grade", "patch",
                       "mil", "slide-level", "linear probe"),
    "segmentation":   ("segment", "dice", "iou", "mask", "pixel"),
    "survival":       ("survival", "c-index", "cindex", "concordance", "os",
                       "risk strat"),
    "feature_extraction": ("feature extract", "foundation model", "extractor",
                           "embed", "encode"),
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
    return ""


def _regex_task_type(question: str, preferred_skill: str = "") -> str:
    text = (question + " " + preferred_skill).lower()
    # Skill hint wins over keyword guessing (more reliable).
    skill = preferred_skill.lower()
    if "classification" in skill or "mil" in skill:
        return "classification"
    if "segment" in skill:
        return "segmentation"
    if "survival" in skill:
        return "survival"
    if "feature_extraction" in skill or "feature-extraction" in skill:
        return "feature_extraction"
    for task, kws in _TASK_KEYWORDS.items():
        if any(kw in text for kw in kws):
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
