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
from functools import lru_cache
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Plan-2026-05-14 stage3 P1-4: registry-driven dataset list. The curated
# entries below stay as the historical baseline (CRC-MSI, TCGA-LUNG etc.
# are NOT in the registry today) and the registry contributes additional
# names so adding a dataset to ``pathology_datasets.json`` is enough —
# no second list to update.
_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent
    / "dataset" / "seed_data" / "pathology_datasets.json"
)

# Canonical pathology datasets we know about. Ordered by specificity so the
# regex can match 'TCGA-LUNG' before the more general 'TCGA' prefix.
_CURATED_KNOWN_DATASETS = [
    # SciDB gastric/chronic gastritis WSI cohort
    (
        "CG-MIL",
        re.compile(
            r"dataSetId=83ee1521074742cdaae997cf0b46a7b1|"
            r"\bCG[-_\s]?MIL\b|"
            r"Comprehensive\s+Assessment\s+of\s+Chronic\s+Gastritis\s+on\s+WSI\s+Data",
            re.IGNORECASE,
        ),
    ),
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

# Generic registry tags that should NOT seed a semantic rule — they are
# format/structure metadata, not discriminating domain phrases. Anything
# else (gleason, isup, metastasis, …) becomes a candidate target keyword.
_GENERIC_REGISTRY_TAGS = frozenset({
    "histology", "he", "wsi", "kaggle", "scidb", "tcga", "placeholder",
    "validation", "large", "gated", "binary", "tumor",
    "4-class", "9-class", "iciar2018",
    # Tags that are artifacts/markers, not domain phrases:
    "size_unknown", "task1", "task2", "task3", "task4",
})

# Token-to-regex aliases for organ names mentioned naturally in prompts.
_ORGAN_PHRASE_PATTERNS: dict[str, str] = {
    "colorectal": r"colorectal|colon|rectal|CRC",
    "prostate":   r"prostate|prostatic",
    "breast":     r"breast|mammary",
    "lung":       r"lung|pulmonary",
    "kidney":     r"kidney|renal",
    "stomach":    r"stomach|gastric",
    "gastric":    r"stomach|gastric",
    "lymph_node": r"lymph\s*node|sentinel",
    "uterus":     r"uterine|endometri\w*",
}


def _canonical_dataset_name(raw: str) -> str:
    """Pick the short canonical token from a registry display name.

    ``"PANDA — Prostate cANcer graDe Assessment"`` → ``"PANDA"``
    ``"PatchCamelyon (PCam)"`` → ``"PCam"``
    ``"TCGA-BRCA Diagnostic Slides"`` → ``"TCGA-BRCA"``
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "—" in raw:
        raw = raw.split("—", 1)[0].strip()
    m_paren = re.search(r"\(([^)]+)\)", raw)
    if m_paren:
        candidate = m_paren.group(1).strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9\-_]+", candidate):
            return candidate
    if " (" in raw:
        raw = raw.split(" (", 1)[0].strip()
    m_caps = re.match(r"[A-Z][A-Z0-9\-_]+", raw)
    if m_caps:
        return m_caps.group(0)
    return raw.split()[0]


def _build_dataset_regex(canonical: str) -> re.Pattern:
    """Build a tolerant regex for a registry-derived canonical name."""
    if not canonical:
        return re.compile(r"(?!x)x")  # never matches
    if "-" in canonical:
        spaced = canonical.replace("-", r"[-_\s]?")
        alts = [spaced]
        # Bare concatenation ("CRCMSI"): only emit when no ambiguity.
        no_sep = canonical.replace("-", "")
        if len(no_sep) >= 4 and no_sep.isupper():
            alts.append(re.escape(no_sep))
        return re.compile(rf"\b(?:{'|'.join(alts)})\b", re.IGNORECASE)
    return re.compile(rf"\b{re.escape(canonical)}\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def _registry_known_datasets() -> list[tuple[str, re.Pattern]]:
    """Derive ``(canonical_name, regex)`` entries from the dataset registry.

    Skips entries whose canonical name already appears in
    ``_CURATED_KNOWN_DATASETS`` so the curated entries' richer regexes
    (CG-MIL's dataSetId URL match, etc.) win.
    """
    if not _REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("objective_extractor: registry load failed: %s", e)
        return []
    curated_names = {name.lower() for name, _ in _CURATED_KNOWN_DATASETS}
    out: list[tuple[str, re.Pattern]] = []
    for entry in data if isinstance(data, list) else []:
        canonical = _canonical_dataset_name(entry.get("name", ""))
        if not canonical or canonical.lower() in curated_names:
            continue
        out.append((canonical, _build_dataset_regex(canonical)))
    return out


def _all_known_datasets() -> list[tuple[str, re.Pattern]]:
    """Return curated + registry-derived dataset patterns, curated first."""
    return list(_CURATED_KNOWN_DATASETS) + _registry_known_datasets()


# Plan-2026-05-14 stage3 P1-4 — back-compat alias. Existing call sites and
# tests reference ``_KNOWN_DATASETS`` directly; preserve the name as a
# *snapshot* of the merged list at import time. Tests that monkeypatch
# this still work for curated entries; registry entries reach the regex
# pass via ``_regex_dataset``'s explicit ``_all_known_datasets()`` call.
_KNOWN_DATASETS = _all_known_datasets()

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
_CURATED_SEMANTIC_RULES: list[tuple[str, list[re.Pattern]]] = [
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
    (
        "CG-MIL",
        [
            re.compile(r"\b(?:gastritis|gastric|stomach)\b", re.IGNORECASE),
            re.compile(
                r"\b(?:WSI|whole\s+slide|MIL|slide[-\s]?level)\b",
                re.IGNORECASE,
            ),
        ],
    ),
]


@lru_cache(maxsize=1)
def _registry_semantic_rules() -> list[tuple[str, list[re.Pattern]]]:
    """Build extra semantic rules from registry organ + non-generic tags.

    For each registry entry that names an organ AND has at least one
    domain-specific tag (i.e. NOT in ``_GENERIC_REGISTRY_TAGS``), emit a
    rule that requires the organ phrase AND the tag word to co-occur.
    Dataset whose canonical name already has a curated rule is skipped
    so we don't dilute the carefully-tuned CRC-MSI / CG-MIL patterns.
    """
    if not _REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    curated_names = {name.lower() for name, _ in _CURATED_SEMANTIC_RULES}
    out: list[tuple[str, list[re.Pattern]]] = []
    for entry in data if isinstance(data, list) else []:
        canonical = _canonical_dataset_name(entry.get("name", ""))
        if not canonical or canonical.lower() in curated_names:
            continue
        organs = [o.lower() for o in (entry.get("organs") or [])]
        tags = [t.lower() for t in (entry.get("tags") or [])]
        # Skip generic tags, tags shorter than 3 chars, and tags that
        # mirror the canonical name itself (those just reproduce the
        # literal-match regex with no added semantic value).
        canonical_low = canonical.lower()
        domain_tags = [
            t for t in tags
            if t not in _GENERIC_REGISTRY_TAGS
            and len(t) >= 3
            and t != canonical_low
        ]
        if not organs or not domain_tags:
            continue
        # Build organ alt-group from known phrase aliases; fall back to
        # the literal slug for unknown organs.
        organ_alts: list[str] = []
        for organ in organs:
            organ_alts.append(_ORGAN_PHRASE_PATTERNS.get(organ, re.escape(organ)))
        organ_re = re.compile(rf"\b(?:{'|'.join(organ_alts)})\b", re.IGNORECASE)
        # Domain tag → keyword alternation. Replace underscores with a
        # tolerant `[\s_-]?` so "chronic_gastritis" matches "chronic gastritis".
        tag_alts = [
            re.escape(t).replace(r"\_", r"[\s_-]?") for t in domain_tags
        ]
        tag_re = re.compile(rf"\b(?:{'|'.join(tag_alts)})\b", re.IGNORECASE)
        out.append((canonical, [organ_re, tag_re]))
    return out


def _all_semantic_rules() -> list[tuple[str, list[re.Pattern]]]:
    return list(_CURATED_SEMANTIC_RULES) + _registry_semantic_rules()


# Back-compat alias: snapshot for tests that import the name directly.
_SEMANTIC_DATASET_RULES = _all_semantic_rules()


def _semantic_dataset(question: str) -> str:
    for canonical, patterns in _all_semantic_rules():
        if all(p.search(question) for p in patterns):
            return canonical
    return ""

# Plan-2026-05-14 stage3 P1-7: shared task-keyword table used by BOTH
# ``_regex_task_type`` (here) and ``_heuristic_skill_candidate`` (in
# ``orchestrator/grounding.py``). Pre-fix the two scanners had different
# priority orders and slightly different keyword sets — a "survival +
# slide-level MIL" prompt resolved to ``mil_classification`` in one and
# ``survival`` in the other. Sharing this table forces both scanners to
# agree at the coarse level.
#
# Order = priority (first match wins). MIL > survival > segmentation >
# feature_extraction > patch mirrors the heuristic skill order — at the
# coarse level, MIL/patch both map to classification, so unifying
# priorities here just decides which *specific* skill wins for mixed
# prompts and keeps coarse_task_type consistent with the eventual
# selected_skill.
TASK_KEYWORD_RULES: list[tuple[str, str, tuple[re.Pattern, ...]]] = [
    # (skill_name, coarse_task_type, compiled patterns)
    (
        "mil_classification", "classification",
        (
            re.compile(r"(?<![a-z0-9])mil(?![a-z0-9])", re.IGNORECASE),
            re.compile(r"\bwsi\b", re.IGNORECASE),
            re.compile(r"\bslide[- ]level\b", re.IGNORECASE),
            re.compile(r"\bwhole\s+slide\b", re.IGNORECASE),
        ),
    ),
    (
        "survival_analysis", "survival",
        (
            re.compile(r"\bsurvival\b", re.IGNORECASE),
            re.compile(r"\bc[-_]?index\b", re.IGNORECASE),
            re.compile(r"\bconcordance\b", re.IGNORECASE),
            re.compile(r"\bos\b", re.IGNORECASE),
            re.compile(r"\brisk\s+strat", re.IGNORECASE),
        ),
    ),
    (
        "patch_segmentation", "segmentation",
        (
            re.compile(r"\bsegment\w*\b", re.IGNORECASE),
            re.compile(r"\bdice\b", re.IGNORECASE),
            re.compile(r"\biou\b", re.IGNORECASE),
            re.compile(r"\bmask\b", re.IGNORECASE),
            re.compile(r"\bpixel\b", re.IGNORECASE),
        ),
    ),
    (
        "feature_extraction", "feature_extraction",
        (
            re.compile(r"\bfeature\s*extract\w*\b", re.IGNORECASE),
            re.compile(r"\bextract\s+features\b", re.IGNORECASE),
            re.compile(r"\bfoundation\s+model\b", re.IGNORECASE),
            re.compile(r"\bextractor\b", re.IGNORECASE),
            re.compile(r"\bembed(?:ding)?\b", re.IGNORECASE),
            re.compile(r"\bencode\b", re.IGNORECASE),
        ),
    ),
    (
        "patch_classification", "classification",
        (
            re.compile(r"\bpatch(?:es)?\b", re.IGNORECASE),
            re.compile(r"\bpatch[- ]level\b", re.IGNORECASE),
            re.compile(r"\btile(?:s)?\b", re.IGNORECASE),
        ),
    ),
]

# Generic "classification" fallback patterns — too weak to pin a
# specific skill (patch vs mil), but enough to decide coarse_task_type
# when the specific rules above don't fire.
_GENERIC_CLASSIFICATION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bclassif\w*\b", re.IGNORECASE),
    re.compile(r"\bauc\b", re.IGNORECASE),
    re.compile(r"\bmsi\b", re.IGNORECASE),
    re.compile(r"\bmicrosatellite\b", re.IGNORECASE),
    re.compile(r"\bsubtype\b", re.IGNORECASE),
    re.compile(r"\bgrade\b", re.IGNORECASE),
    re.compile(r"\blinear\s+probe\b", re.IGNORECASE),
)


def _regex_dataset(question: str) -> str:
    known = _all_known_datasets()
    for canonical, rgx in known:
        if rgx.search(question):
            return canonical
    m = _PATH_DATASET_RE.search(question)
    if m:
        # Normalize the captured token against known list (case-insensitive).
        token = m.group(1)
        for canonical, rgx in known:
            if rgx.search(token):
                return canonical
        return token.upper() if not token.isupper() else token
    # Plan-2026-04-29 P1-5: semantic fallback — disease + prediction-target
    # phrasings (e.g. "MSI in colorectal cancer") map to the canonical
    # benchmark when no literal name appears.
    return _semantic_dataset(question)


def _regex_task_type(question: str, preferred_skill: str = "") -> str:
    """Plan-2026-05-14 stage3 P1-7: derives coarse task_type from the
    shared ``TASK_KEYWORD_RULES`` table (consumed by both this scanner
    and ``_heuristic_skill_candidate``). Short word-boundary patterns
    in the table prevent the old "pathology" → survival / "familial" →
    classification false positives without per-keyword special-casing.
    """
    text = (question or "") + " " + (preferred_skill or "")
    # Plan-2026-04-29 grounding-routing-repair Task 5: skill hint wins
    # over keyword guessing, but use exact registered-skill names to map.
    # An invalid preferred_skill containing "mil" no longer auto-classifies.
    skill = (preferred_skill or "").lower().strip()
    if skill in {"patch_classification", "mil_classification"}:
        return "classification"
    if skill == "patch_segmentation":
        return "segmentation"
    if skill == "survival_analysis":
        return "survival"
    if skill == "feature_extraction":
        return "feature_extraction"

    for _skill, coarse_task, patterns in TASK_KEYWORD_RULES:
        if any(p.search(text) for p in patterns):
            return coarse_task

    # Generic classification fallback — too weak to pin a specific
    # skill but enough to label the coarse task.
    if any(p.search(text) for p in _GENERIC_CLASSIFICATION_PATTERNS):
        return "classification"
    return ""


_LLM_PROMPT = """Extract the dataset name and task type from this research question.

Return ONLY a single JSON object with keys:
  "dataset":             canonical dataset name (e.g. "CRC-MSI", "Camelyon16", "TCGA-LUNG"),
                         or "" if no dataset is named or implied.
  "dataset_confidence":  one of "high" | "medium" | "low".
                         "high"   = explicit literal mention of the dataset.
                         "medium" = strong indirect signal (organ + target + modality).
                         "low"    = guess based on weak phrasing or domain norms.
  "task_type":           one of "classification" | "segmentation" | "survival" | "feature_extraction",
                         or "" if unclear.
  "task_type_confidence": one of "high" | "medium" | "low" (same scale).

Question: {question}
"""

# Allowed confidence vocabulary; mirrors `dataset/llm_task_profile.py` so
# callers can share `_conf_at_least` semantics later if they want.
_ALLOWED_CONFIDENCE = {"", "low", "medium", "high"}
_CONF_RANK = {"": 0, "low": 1, "medium": 2, "high": 3}


def _normalize_confidence(value) -> str:
    conf = str(value or "").strip().lower()
    return conf if conf in _ALLOWED_CONFIDENCE else ""


def _conf_at_least(confidence: str, minimum: str = "medium") -> bool:
    return _CONF_RANK.get(confidence, 0) >= _CONF_RANK.get(minimum, 0)


# Plan-2026-05-14 stage3 P2-7: process-local memoization of LLM-derived
# answers. The grounding pipeline can call ``extract_dataset_and_task``
# more than once per session (objective_extractor + task_profile inference
# + skill fallback each call it directly or indirectly). Caching by
# ``(question, preferred_skill)`` avoids paying for repeated LLM calls
# on the same prompt. Cap at 256 entries to bound memory; the cache is
# process-scoped, so it naturally resets on restart.
_LLM_EXTRACT_CACHE: dict[str, tuple[str, str]] = {}
_LLM_EXTRACT_CACHE_MAX = 256


def _llm_cache_get(question: str, preferred_skill: str) -> tuple[str, str] | None:
    return _LLM_EXTRACT_CACHE.get(f"{question}\x00{preferred_skill}")


def _llm_cache_put(question: str, preferred_skill: str, value: tuple[str, str]) -> None:
    if len(_LLM_EXTRACT_CACHE) >= _LLM_EXTRACT_CACHE_MAX:
        # FIFO eviction — drop the oldest entry. ``dict`` preserves
        # insertion order in Python 3.7+ so ``next(iter(...))`` is the
        # oldest.
        _LLM_EXTRACT_CACHE.pop(next(iter(_LLM_EXTRACT_CACHE)))
    _LLM_EXTRACT_CACHE[f"{question}\x00{preferred_skill}"] = value


def extract_dataset_and_task(
    question: str,
    *,
    llm_parser: Callable[[str], str] | None = None,
    preferred_skill: str = "",
) -> tuple[str, str]:
    """Return (dataset_hint, task_type) for this question.

    Regex first; fall through to LLM only when regex returns empty dataset.
    LLM dataset / task suggestions below "medium" confidence are discarded
    (low-confidence guesses become "") so they do not pin grounding to a
    hallucinated dataset.

    Plan-2026-05-14 stage3 P2-7: LLM results are memoized per
    ``(question, preferred_skill)`` so repeated calls in the same
    session don't re-fire the LLM.
    """
    dataset = _regex_dataset(question)
    task = _regex_task_type(question, preferred_skill=preferred_skill)
    if dataset and task:
        return dataset, task

    if llm_parser is not None:
        # Cache hit: skip the LLM call entirely.
        cached = _llm_cache_get(question, preferred_skill)
        if cached is not None:
            cached_dataset, cached_task = cached
            return dataset or cached_dataset, task or cached_task
        try:
            raw = llm_parser(_LLM_PROMPT.format(question=question)) or ""
            raw = raw.strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json.loads(raw)
            if isinstance(data, dict):
                dataset_llm = str(data.get("dataset", "") or "")
                dataset_conf = _normalize_confidence(data.get("dataset_confidence"))
                task_llm = str(data.get("task_type", "") or "")
                task_conf = _normalize_confidence(data.get("task_type_confidence"))

                # Gate: keep the LLM's suggestion only when the response
                # is explicitly confident OR when no confidence field was
                # emitted at all (legacy LLMs without the new schema).
                # The "missing confidence" case stays permissive to avoid
                # regressing real-world prompts that the old extractor
                # handled fine.
                if dataset_llm and not dataset:
                    if dataset_conf == "" or _conf_at_least(dataset_conf):
                        dataset = dataset_llm
                    else:
                        logger.debug(
                            "objective_extractor: discarded low-confidence "
                            "dataset=%r (conf=%s)", dataset_llm, dataset_conf,
                        )
                if task_llm and not task:
                    if task_conf == "" or _conf_at_least(task_conf):
                        task = task_llm
                    else:
                        logger.debug(
                            "objective_extractor: discarded low-confidence "
                            "task=%r (conf=%s)", task_llm, task_conf,
                        )
        except Exception as e:
            logger.debug("objective_extractor LLM fallback failed: %s", e)

        # Memoize LLM-derived final result so repeated calls in the same
        # session don't re-fire the LLM (P2-7).
        _llm_cache_put(question, preferred_skill, (dataset, task))

    return dataset, task
