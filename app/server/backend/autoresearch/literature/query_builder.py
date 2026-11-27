"""Build search-engine friendly literature queries from user objectives.

The agent often receives prompts that mix natural language, local file paths,
and task requests. OpenAlex search works best with concise biomedical English
terms, not raw instructions such as ``/project/.../CRC-MSI``. This module keeps
the cleanup deterministic and offline.
"""
from __future__ import annotations

import re
from collections.abc import Iterable


_PATH_RE = re.compile(r"(?:~|/)[^\s]+")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+._-]*")
_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

_NOISE_TOKENS = {
    "project",
    "storage",
    "pathlab",
    "pathlab_data_collection",
    "data",
    "dataset",
    "training",
    "train",
    "ai",
    "model",
    "help",
    "classify",
    "classifiy",
    "finished",
    "finish",
    "once",
    "validate",
    "own",
    "with",
    "using",
    "the",
    "and",
    "for",
    "from",
    "this",
    "that",
    "into",
    "then",
    "after",
    "before",
    "your",
    "you",
    "my",
    "me",
    "it",
    "on",
    "to",
    "test",
    "tmp",
    "home",
    "patch-level",
}


def build_literature_search_query(
    query: str,
    *,
    dataset_hint: str = "",
    organ: str | None = None,
    task_type: str | None = None,
    prediction_target: str = "",
    required_label_keywords: Iterable[str] | None = None,
    dataset_keywords: Iterable[str] | None = None,
    alias_resolver=None,
) -> str:
    """Return a concise query suitable for OpenAlex / literature search.

    The builder preserves explicit biomedical tokens, strips filesystem paths,
    and expands common pathology dataset/target aliases. It intentionally avoids
    LLM calls so grounding remains deterministic and cheap.
    """
    raw = query or ""
    has_structured_context = bool(
        dataset_hint
        or organ
        or task_type
        or prediction_target
        or required_label_keywords
        or dataset_keywords
    )
    compact = _WS_RE.sub(" ", raw).strip()
    if (
        not has_structured_context
        and not _PATH_RE.search(raw)
        and not _CJK_RE.search(raw)
        and re.fullmatch(r"[A-Za-z0-9._-]{1,3}", compact)
    ):
        return compact

    # Grounding may pass an already-normalized query into retriever-level
    # cache handling. Keep that idempotent instead of expanding phrases twice.
    if (
        "histopathology" in raw.lower()
        and not _PATH_RE.search(raw)
        and not _CJK_RE.search(raw)
        and not dataset_hint
        and not prediction_target
        and not required_label_keywords
        and not dataset_keywords
    ):
        return compact

    path_tokens = _dataset_like_path_tokens(raw)
    text_without_paths = _PATH_RE.sub(" ", raw)
    text_tokens = _english_tokens(text_without_paths)

    parts: list[str] = []
    _add(parts, dataset_hint)
    for token in path_tokens:
        _add(parts, token)

    # Dataset aliases need to run before generic task terms so target words
    # such as MSI/Gleason become part of the search even when the prompt only
    # mentions a dataset name. When an ``alias_resolver`` is provided, its
    # expansions take precedence (so the LLM-cached entries override the
    # builtin if-elif fallback); when not, behavior is unchanged.
    structured_tokens = [str(x or "") for x in (dataset_keywords or [])]
    candidate_tokens = [dataset_hint, *path_tokens, *structured_tokens, *text_tokens]
    if alias_resolver is not None:
        seen_keys: set[str] = set()
        unique_tokens: list[str] = []
        for token in candidate_tokens:
            key = (token or "").strip().lower().replace("_", "-")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            unique_tokens.append(token)
        try:
            resolved = alias_resolver.bulk_expand(unique_tokens)
        except Exception:
            resolved = {}
        for token in candidate_tokens:
            aliases = resolved.get(token) if resolved else None
            if aliases:
                for expanded in aliases:
                    _add(parts, expanded)
            else:
                for expanded in _expand_dataset_alias(token):
                    _add(parts, expanded)
    else:
        for token in candidate_tokens:
            for expanded in _expand_dataset_alias(token):
                _add(parts, expanded)

    canonical_organ = (organ or "").strip().lower()
    for expanded in _expand_organ(canonical_organ):
        _add(parts, expanded)

    target = (prediction_target or "").strip().lower()
    if not target:
        target = _infer_target_from_terms(
            [dataset_hint, *path_tokens, *structured_tokens, *text_tokens]
        )
    for expanded in _expand_prediction_target(target):
        _add(parts, expanded)

    for kw in required_label_keywords or []:
        _add(parts, kw)

    # Preserve useful English words from the user prompt after removing paths.
    for token in text_tokens:
        if token.lower() not in _NOISE_TOKENS:
            _add(parts, token)

    for expanded in _expand_task_type(task_type or "", raw):
        _add(parts, expanded)

    if canonical_organ or parts:
        _add(parts, "histopathology")

    deduped = _dedupe(parts)
    if not deduped:
        return _WS_RE.sub(" ", raw).strip()
    return " ".join(deduped)


def _dataset_like_path_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _PATH_RE.finditer(text or ""):
        path = match.group(0).rstrip("/ ")
        for part in path.split("/"):
            if _looks_dataset_like(part):
                tokens.append(part)
    return tokens


def _looks_dataset_like(token: str) -> bool:
    token = token.strip()
    if not token:
        return False
    lowered = token.lower()
    if lowered in _NOISE_TOKENS:
        return False
    if lowered in {"crc-msi", "panda", "bracs", "camelyon16", "camelyon17"}:
        return True
    if lowered.startswith("tcga-"):
        return True
    # Keep short uppercase/hyphenated dataset-ish names, but avoid user names
    # and ordinary directory components.
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]+(?:[-_][A-Z0-9]+)+", token))


def _english_tokens(text: str) -> list[str]:
    out: list[str] = []
    for token in _TOKEN_RE.findall(text or ""):
        cleaned = token.strip("._-")
        if len(cleaned) < 2:
            continue
        out.append(cleaned)
    return out


def _expand_dataset_alias(token: str) -> list[str]:
    key = (token or "").strip().lower().replace("_", "-")
    if not key:
        return []
    if key in {"crc-msi", "crc msi"}:
        return [
            "CRC-MSI",
            "colorectal cancer",
            "microsatellite instability",
            "MSI",
            "MSS",
        ]
    if key == "panda":
        return ["PANDA", "prostate cancer", "Gleason grading", "ISUP grade"]
    if key == "bracs":
        return ["BRACS", "breast cancer", "breast histopathology"]
    if key.startswith("camelyon"):
        return ["Camelyon", "breast cancer metastasis", "lymph node"]
    if key.startswith("tcga-"):
        return [token.upper(), "TCGA", _tcga_organ_phrase(key)]
    return []


def builtin_dataset_alias_table() -> dict[str, list[str]]:
    """Snapshot of the deterministic alias table used as ``AliasResolver`` fallback.

    Only the closed-form entries are exposed — prefix-based ones (TCGA-*,
    Camelyon*) stay in ``_expand_dataset_alias`` because they need the
    token's literal form. ``AliasResolver.expand`` checks this dict first;
    the prefix logic still runs through ``_expand_dataset_alias`` in the
    query builder's fallback branch.
    """
    return {
        "crc-msi": [
            "CRC-MSI",
            "colorectal cancer",
            "microsatellite instability",
            "MSI",
            "MSS",
        ],
        "panda": ["PANDA", "prostate cancer", "Gleason grading", "ISUP grade"],
        "bracs": ["BRACS", "breast cancer", "breast histopathology"],
    }


def _tcga_organ_phrase(key: str) -> str:
    if "brca" in key:
        return "breast cancer"
    if "lung" in key or "luad" in key or "lusc" in key:
        return "lung cancer"
    if "coad" in key or "read" in key or "crc" in key:
        return "colorectal cancer"
    if "prad" in key:
        return "prostate cancer"
    return "cancer"


def _expand_organ(organ: str) -> list[str]:
    return {
        "colorectal": ["colorectal cancer"],
        "colon": ["colorectal cancer"],
        "rectal": ["colorectal cancer"],
        "prostate": ["prostate cancer"],
        "breast": ["breast cancer"],
        "lung": ["lung cancer"],
        "kidney": ["kidney cancer"],
        "uterus": ["uterine cancer"],
    }.get(organ, [])


def _infer_target_from_terms(terms: Iterable[str]) -> str:
    text = " ".join(str(t or "") for t in terms).lower().replace("_", "-")
    if "crc-msi" in text or "microsatellite" in text or re.search(r"\bmsi\b", text):
        return "microsatellite_instability"
    if "gleason" in text or "isup" in text or "panda" in text:
        return "gleason_grade"
    if "her2" in text:
        return "her2"
    if "egfr" in text:
        return "egfr"
    if "metastasis" in text or "metastatic" in text:
        return "metastasis"
    return ""


def _expand_prediction_target(target: str) -> list[str]:
    return {
        "microsatellite_instability": [
            "microsatellite instability",
            "MSI-H",
            "MSI",
            "MSS",
        ],
        "gleason_grade": ["Gleason grading", "Gleason score", "ISUP grade"],
        "her2": ["HER2 status"],
        "egfr": ["EGFR mutation"],
        "metastasis": ["metastasis detection"],
        "subtype": ["cancer subtype classification"],
        "nsclc_subtype": [
            "NSCLC subtype classification",
            "LUAD LUSC",
            "lung adenocarcinoma lung squamous cell carcinoma",
        ],
    }.get(target, [])


def _expand_task_type(task_type: str, raw_query: str) -> list[str]:
    text = f"{task_type or ''} {raw_query or ''}".lower().replace("_", "-")
    if "survival" in text:
        return ["survival prediction", "prognosis"]
    if "segmentation" in text or "segment" in text:
        return ["segmentation", "digital pathology"]
    if "feature-extraction" in text or "feature extraction" in text:
        return ["pathology foundation model", "feature extraction"]
    if "mil-classification" in text or re.search(r"(?<![a-z0-9])mil(?![a-z0-9])", text):
        return ["multiple instance learning", "whole slide image classification"]
    if "patch" in text:
        return ["patch-level classification", "deep learning"]
    if "classification" in text:
        return ["classification", "deep learning"]
    return []


def _add(parts: list[str], value: str | None) -> None:
    value = _WS_RE.sub(" ", str(value or "").strip())
    if value:
        parts.append(value)


def _dedupe(parts: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.strip().lower()
        if key and key not in seen:
            out.append(part.strip())
            seen.add(key)
    return out
