"""Extract dataset candidates from already-persisted grounding outputs.

Phase A T3 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

Two design rules from the review-update bullets — DO NOT "improve" them away:

1. **Read the persisted ``grounding`` dict, NOT live ``LiteratureService.find_papers()``.**
   Grounding has already paid the network cost. Re-calling the service here would
   re-spend the OpenAlex budget AND violate the "acquisition stage runs offline-by-
   default after grounding" invariant. The function takes ``grounding: dict[str, Any]``
   as input and never imports ``LiteratureService``.

2. **Canonicalize ``paper_id`` on the way in.** Whatever shape
   ``grounding["papers"][i]["paper_id"]`` etc. carries (raw ``"W123"``, scheme-
   prefixed ``"openalex:W123"``, DOI, ...), pass it through
   ``literature.id_resolver.to_canonical_id`` before stamping into
   ``DatasetDiscoveryEvidence.paper_id`` so cross-session linking through
   ``PaperRegistry`` works.

Source priority (review-update bullets 4 + 5):
  1. ``baselines`` (structured)            — confidence: medium
  2. ``sota_target`` (structured)           — confidence: medium
  3. ``papers[].datasets`` (structured)     — confidence: low
  4. ``dataset_hint_candidates`` (LLM)      — confidence: from LLM (low/medium/high)
  5. ``passages`` (regex, denylisted)       — confidence: medium when URL found, else low

Same dataset name showing up across multiple sources merges into one record
with combined evidence (case-insensitive dedup).
"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import Any

from .discovery_types import (
    DatasetDiscoveryEvidence,
    DatasetDiscoveryRecord,
    ProviderHint,
)

logger = logging.getLogger(__name__)


# Plan-2026-04-30 dataset-provider-repair Task 2: provider patterns now
# parse structured remote_ids / kinds out of the URL so the bridge into
# DownloadSpec doesn't need to re-parse them.
_KAGGLE_COMPETITION_RE = re.compile(
    r"https?://(?:www\.)?kaggle\.com/competitions/([^/?\s]+)(?:/[^?\s]*)?",
    re.IGNORECASE,
)
_KAGGLE_DATASET_RE = re.compile(
    r"https?://(?:www\.)?kaggle\.com/datasets/([^/?\s]+)/([^/?\s]+)(?:/[^?\s]*)?",
    re.IGNORECASE,
)
_HF_DATASET_RE = re.compile(
    r"https?://(?:www\.)?huggingface\.co/datasets/([^/?\s]+)/([^/?\s]+)(?:/[^?\s]*)?",
    re.IGNORECASE,
)
_ZENODO_RECORD_RE = re.compile(
    r"https?://(?:www\.)?zenodo\.org/records?/(\d+)(?:/[^?\s]*)?",
    re.IGNORECASE,
)
_SCIDB_DETAIL_RE = re.compile(
    r"https?://(?:www\.|china\.)?scidb\.cn/(?:en/)?detail\?[^\s#]*dataSetId=([A-Za-z0-9]+)[^\s]*",
    re.IGNORECASE,
)
_SCIDB_DOWNLOAD_RE = re.compile(
    r"https?://(?:www\.|china\.)?scidb\.cn/download\?[^\s#]*fileId=([A-Za-z0-9]+)[^\s]*",
    re.IGNORECASE,
)
# Generic fallback per-provider host (for cases that don't match the
# structured patterns above).
_PROVIDER_HOST_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("zenodo", re.compile(r"https?://(?:www\.)?zenodo\.org/\S+", re.IGNORECASE)),
    ("huggingface", re.compile(r"https?://(?:www\.)?huggingface\.co/\S+", re.IGNORECASE)),
    ("kaggle", re.compile(r"https?://(?:www\.)?kaggle\.com/\S+", re.IGNORECASE)),
    ("github", re.compile(r"https?://(?:www\.)?github\.com/\S+", re.IGNORECASE)),
    ("figshare", re.compile(r"https?://(?:www\.)?figshare\.com/\S+", re.IGNORECASE)),
    ("tcia", re.compile(r"https?://(?:www\.)?cancerimagingarchive\.net/\S+", re.IGNORECASE)),
]

# Catch-all URL regex (used to strip URLs out of passage text before name regex).
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# File-extension allowlist for the direct_http catch-all. Anything else
# is treated as a landing page and NOT promoted into a hint.
_FILE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".7z", ".h5", ".hdf5", ".csv", ".tsv", ".json")

# Acronym/dataset-like name pattern: starts with uppercase letter, may contain
# hyphens / digits / following capitalized fragments. Min 2 chars.
# Used ONLY when the passage already contains a provider URL — passages
# without a provider URL are not regex-mined (review constraint #5).
_DATASET_TOKEN_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]+(?:[- ][A-Z0-9][A-Za-z0-9]*){0,4})\b"
)

# Generic phrases that look acronym-shaped but are NOT dataset names.
# Lowercase strings; comparison is case-insensitive.
_DENYLIST = {
    "data",
    "data availability",
    "data availability section",
    "data availability statement",
    "supplementary",
    "supplementary materials",
    "supplementary material",
    "supplementary information",
    "abstract",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "acknowledgments",
    "references",
    "table",
    "figure",
    "section",
    "appendix",
    "image",
    "images",
    "datasets",
    "dataset",
    "training",
    "training set",
    "test set",
    "validation set",
    "available at",
    "available on",
    "available from",
    "available",
    "online",
    "github",
    "huggingface",
    "hugging face",
    "zenodo",
    "kaggle",
    "tcga",  # too generic by itself; specific TCGA-* names allowed below
    "gdc",
    "tcia",
    "cptac",
    "h&e",
    "auc",
    "loss",
    "the",
    "we",
    "these",
    "this",
    "that",
    "such",
    "all",
    "which",
    "with",
    "the data",
    "this data",
    "such data",
    "all data",
}

_SCIDB_GASTRITIS_DATASET_ID = "83ee1521074742cdaae997cf0b46a7b1"
_SCIDB_GASTRITIS_URL = (
    "https://www.scidb.cn/detail?"
    f"dataSetId={_SCIDB_GASTRITIS_DATASET_ID}"
)
_KNOWN_HINT_ALIASES: dict[str, dict[str, Any]] = {
    "cg-mil": {
        "name": "CG-MIL",
        "aliases": [
            "Comprehensive Assessment of Chronic Gastritis on WSI Data",
            "SciDB chronic gastritis WSI",
            f"scidb:{_SCIDB_GASTRITIS_DATASET_ID}",
            _SCIDB_GASTRITIS_DATASET_ID,
        ],
        "provider_hint": ProviderHint(
            provider="scidb",
            remote_id=_SCIDB_GASTRITIS_DATASET_ID,
            url=_SCIDB_GASTRITIS_URL,
            kind="scidb_dataset",
            confidence="high",
        ),
        "confidence": "high",
    },
    "comprehensive assessment of chronic gastritis on wsi data": {
        "name": "CG-MIL",
        "aliases": [
            "Comprehensive Assessment of Chronic Gastritis on WSI Data",
            "SciDB chronic gastritis WSI",
            f"scidb:{_SCIDB_GASTRITIS_DATASET_ID}",
            _SCIDB_GASTRITIS_DATASET_ID,
        ],
        "provider_hint": ProviderHint(
            provider="scidb",
            remote_id=_SCIDB_GASTRITIS_DATASET_ID,
            url=_SCIDB_GASTRITIS_URL,
            kind="scidb_dataset",
            confidence="high",
        ),
        "confidence": "high",
    },
    f"scidb:{_SCIDB_GASTRITIS_DATASET_ID}": {
        "name": "CG-MIL",
        "aliases": [
            "Comprehensive Assessment of Chronic Gastritis on WSI Data",
            "SciDB chronic gastritis WSI",
            f"scidb:{_SCIDB_GASTRITIS_DATASET_ID}",
            _SCIDB_GASTRITIS_DATASET_ID,
        ],
        "provider_hint": ProviderHint(
            provider="scidb",
            remote_id=_SCIDB_GASTRITIS_DATASET_ID,
            url=_SCIDB_GASTRITIS_URL,
            kind="scidb_dataset",
            confidence="high",
        ),
        "confidence": "high",
    },
    _SCIDB_GASTRITIS_DATASET_ID: {
        "name": "CG-MIL",
        "aliases": [
            "Comprehensive Assessment of Chronic Gastritis on WSI Data",
            "SciDB chronic gastritis WSI",
            f"scidb:{_SCIDB_GASTRITIS_DATASET_ID}",
            _SCIDB_GASTRITIS_DATASET_ID,
        ],
        "provider_hint": ProviderHint(
            provider="scidb",
            remote_id=_SCIDB_GASTRITIS_DATASET_ID,
            url=_SCIDB_GASTRITIS_URL,
            kind="scidb_dataset",
            confidence="high",
        ),
        "confidence": "high",
    },
}


def _canonical(any_id: str) -> str:
    """Normalize a paper id to canonical form. Empty in → empty out."""
    if not any_id:
        return ""
    try:
        from ..literature.id_resolver import to_canonical_id
    except Exception:
        return any_id
    try:
        return to_canonical_id(any_id) or any_id
    except Exception:
        return any_id


def _profile_fields(profile) -> dict[str, Any]:
    """Extract task semantics from TaskProfile (or None)."""
    if profile is None:
        return {
            "task_types": [],
            "asset_types": [],
            "organs": [],
            "label_keywords": [],
            "prediction_target": "",
        }
    asset_types: list[str] = []
    if getattr(profile, "input_modality", ""):
        asset_types.append(profile.input_modality)
    organs: list[str] = []
    if getattr(profile, "organ", ""):
        organs.append(profile.organ)
    return {
        "task_types": [profile.task_type] if getattr(profile, "task_type", "") else [],
        "asset_types": asset_types,
        "organs": organs,
        "label_keywords": list(getattr(profile, "required_label_keywords", []) or []),
        "prediction_target": getattr(profile, "prediction_target", "") or "",
    }


def _is_file_like_url(url: str) -> bool:
    from urllib.parse import urlparse

    path = (urlparse(url).path or "").lower().split("?", 1)[0]
    return any(path.endswith(ext) for ext in _FILE_EXTS)


def _provider_hints_from_text(text: str) -> list[ProviderHint]:
    """Scan text for provider URLs and emit structured ``ProviderHint``s.

    Plan-2026-04-30 dataset-provider-repair Task 2:
    - Kaggle competitions / datasets get ``kind`` populated so the bridge
      to ``DownloadSpec.kind`` doesn't need to re-parse the URL.
    - HF / Zenodo URLs surface their canonical ``remote_id`` (``org/repo``
      / numeric record id).
    - Anything else that ends in a known file extension becomes a generic
      ``direct_http`` hint, so a paper that hosts data on its own site
      still reaches the DirectHTTP downloader.
    """
    hints: list[ProviderHint] = []
    consumed_urls: set[str] = set()

    def _add(hint: ProviderHint) -> None:
        key = (hint.provider, hint.url, hint.remote_id)
        if any(
            (h.provider, h.url, h.remote_id) == key for h in hints
        ):
            return
        hints.append(hint)
        if hint.url:
            consumed_urls.add(hint.url)

    # 1. Kaggle competition (most specific).
    for m in _KAGGLE_COMPETITION_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        slug = m.group(1)
        _add(ProviderHint(
            provider="kaggle",
            url=url,
            remote_id=slug,
            kind="kaggle_competition",
            confidence="low",
        ))

    # 2. Kaggle dataset.
    for m in _KAGGLE_DATASET_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        owner, slug = m.group(1), m.group(2)
        _add(ProviderHint(
            provider="kaggle",
            url=url,
            remote_id=f"{owner}/{slug}",
            kind="kaggle_dataset",
            confidence="low",
        ))

    # 3. HuggingFace dataset.
    for m in _HF_DATASET_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        org, repo = m.group(1), m.group(2)
        _add(ProviderHint(
            provider="huggingface",
            url=url,
            remote_id=f"{org}/{repo}",
            confidence="low",
        ))

    # 4. Zenodo record (with optional /files/* tail).
    for m in _ZENODO_RECORD_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        record_id = m.group(1)
        _add(ProviderHint(
            provider="zenodo",
            url=url,
            remote_id=record_id,
            confidence="low",
        ))

    # 5. SciDB detail page / file endpoint.
    for m in _SCIDB_DETAIL_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        dataset_id = m.group(1)
        _add(ProviderHint(
            provider="scidb",
            url=url,
            remote_id=dataset_id,
            kind="scidb_dataset",
            confidence="low",
        ))
    for m in _SCIDB_DOWNLOAD_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        file_id = m.group(1)
        _add(ProviderHint(
            provider="scidb",
            url=url,
            remote_id=file_id,
            kind="scidb_file",
            confidence="low",
        ))

    # 6. Other host-level providers (github / figshare / tcia / unstructured zenodo / hf).
    for provider, pattern in _PROVIDER_HOST_PATTERNS:
        for m in pattern.finditer(text):
            url = m.group(0).rstrip(".,);")
            if url in consumed_urls:
                continue
            _add(ProviderHint(provider=provider, url=url, confidence="low"))

    # 7. Catch-all: any *file-like* URL not yet consumed becomes direct_http.
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        if url in consumed_urls:
            continue
        if not _is_file_like_url(url):
            continue
        _add(ProviderHint(provider="direct_http", url=url, confidence="low"))

    return hints


def _looks_like_dataset_name(name: str) -> bool:
    """Reject generic phrases per review constraint #5."""
    n = name.strip().lower()
    if not n or len(n) < 2:
        return False
    if n in _DENYLIST:
        return False
    # Single-token lowercase noise — disallow.
    if " " in n and all(p in _DENYLIST for p in n.split()):
        return False
    return True


def _trim_leading_denylisted_words(token: str) -> str:
    """Strip leading common-word prefixes the regex greedily ate.

    The token regex is generous to accommodate names like ``TCGA-CRC-MSI``
    or ``Hugging Face Hub``, but it also captures things like
    ``"The BRACS"`` or ``"This PANDA"``. Drop the leading word(s) when
    they're in the denylist so the remaining capitalized acronym surfaces
    as the dataset name.
    """
    parts = token.split()
    while parts and parts[0].lower() in _DENYLIST:
        parts = parts[1:]
    return " ".join(parts).strip()


def _extract_passage_dataset_names(text: str) -> list[str]:
    """Extract dataset-name tokens from passage text — only when context warrants.

    Scans for tokens like ``CRC-MSI``, ``TCGA-CRC``, ``BRACS`` near words like
    ``dataset``. Filters through ``_DENYLIST``.
    """
    # Strip URLs first so they don't pollute the name regex.
    cleaned = _URL_RE.sub(" ", text)
    candidates: list[str] = []
    for m in _DATASET_TOKEN_RE.finditer(cleaned):
        token = m.group(1).strip()
        token = _trim_leading_denylisted_words(token)
        if not token:
            continue
        if _looks_like_dataset_name(token):
            candidates.append(token)
    return candidates


# ----------------------------------------------------------------- main


def _get_or_create(
    by_key: OrderedDict[str, DatasetDiscoveryRecord],
    name: str,
    profile_fields: dict[str, Any],
) -> DatasetDiscoveryRecord:
    key = name.strip().lower()
    if key in by_key:
        return by_key[key]
    rec = DatasetDiscoveryRecord(
        name=name.strip(),
        task_types=list(profile_fields["task_types"]),
        asset_types=list(profile_fields["asset_types"]),
        organs=list(profile_fields["organs"]),
        label_keywords=list(profile_fields["label_keywords"]),
        prediction_target=profile_fields["prediction_target"],
        access="manual",
        confidence="low",
    )
    by_key[key] = rec
    return rec


def _known_hint_config(name: str) -> dict[str, Any] | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    return _KNOWN_HINT_ALIASES.get(key)


def _add_known_dataset_hint_record(
    by_key: OrderedDict[str, DatasetDiscoveryRecord],
    *,
    hint_name: str,
    profile_fields: dict[str, Any],
    source: str,
) -> None:
    config = _known_hint_config(hint_name)
    if not config:
        return
    name = str(config["name"])
    rec = _get_or_create(by_key, name, profile_fields)
    for alias in config.get("aliases", []) or []:
        alias = str(alias or "").strip()
        if alias and alias not in rec.aliases:
            rec.aliases.append(alias)
    hint = config.get("provider_hint")
    if isinstance(hint, ProviderHint):
        exists = any(
            h.provider == hint.provider
            and h.remote_id == hint.remote_id
            and h.url == hint.url
            for h in rec.provider_hints
        )
        if not exists:
            rec.provider_hints.append(hint)
    rec.evidence.append(DatasetDiscoveryEvidence(
        source="dataset_hint",
        quote=f"{source}:{hint_name}",
    ))
    _bump_confidence(rec, str(config.get("confidence") or "medium"))


def _candidate_profile_fields(
    profile_fields: dict[str, Any],
    name: str,
    *evidence_texts: str,
) -> dict[str, Any]:
    """Copy label semantics only when the candidate text supports them.

    Baselines in grounding can be broad reference results rather than
    same-dataset evidence. A Gleason prompt must not turn unrelated baselines
    like TCGA-LUNG into fake Gleason datasets by blindly inheriting
    ``required_label_keywords`` from the current task profile.
    """
    label_keywords = list(profile_fields.get("label_keywords") or [])
    if not label_keywords:
        return profile_fields

    text = " ".join([name, *[t or "" for t in evidence_texts]]).lower()
    if any(kw and kw.lower() in text for kw in label_keywords):
        return profile_fields

    out = dict(profile_fields)
    out["organs"] = []
    out["label_keywords"] = []
    out["prediction_target"] = ""
    return out


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _bump_confidence(rec: DatasetDiscoveryRecord, candidate: str) -> None:
    """Raise rec.confidence if candidate is higher."""
    if _CONFIDENCE_ORDER.get(candidate, 0) > _CONFIDENCE_ORDER.get(rec.confidence, 0):
        rec.confidence = candidate


def extract_dataset_candidates(
    grounding: dict[str, Any],
    profile,
    *,
    llm_extractor=None,
) -> list[DatasetDiscoveryRecord]:
    """Extract candidate datasets from persisted grounding outputs.

    ``llm_extractor`` (optional, T10): when provided and produces records,
    they're merged on top of the heuristic extraction. Heuristic records
    win on name conflict unless the LLM record has higher confidence AND
    at least one provider hint.
    """
    if not isinstance(grounding, dict):
        return []
    pf = _profile_fields(profile)
    by_key: OrderedDict[str, DatasetDiscoveryRecord] = OrderedDict()

    # 0. Strong dataset hints already extracted during grounding. This is a
    # safety net for explicit provider URLs/names in the user prompt when
    # literature search returns no papers/passages. Known hints carry provider
    # metadata so they can still enter acquisition even if the cache registry
    # is stale.
    inferred_hint = (grounding.get("dataset_hint_inferred") or "").strip()
    if inferred_hint:
        _add_known_dataset_hint_record(
            by_key,
            hint_name=inferred_hint,
            profile_fields=pf,
            source="dataset_hint_inferred",
        )
    explicit_hint = (grounding.get("dataset_hint") or "").strip()
    if explicit_hint:
        _add_known_dataset_hint_record(
            by_key,
            hint_name=explicit_hint,
            profile_fields=pf,
            source="dataset_hint",
        )

    # 1. Baselines (structured) — medium confidence.
    for b in grounding.get("baselines", []) or []:
        if not isinstance(b, dict):
            continue
        name = (b.get("dataset") or "").strip()
        if not name:
            continue
        rec = _get_or_create(
            by_key,
            name,
            _candidate_profile_fields(
                pf,
                name,
                b.get("paper_title", "") or "",
                b.get("context", "") or "",
            ),
        )
        rec.evidence.append(DatasetDiscoveryEvidence(
            source="baseline",
            paper_id=_canonical(b.get("paper_id", "")),
            title=b.get("paper_title", "") or "",
            quote=b.get("context", "") or "",
        ))
        _bump_confidence(rec, "medium")

    # 2. SOTA target (structured) — medium confidence.
    sota = grounding.get("sota_target")
    if isinstance(sota, dict):
        name = (sota.get("dataset") or "").strip()
        if name:
            rec = _get_or_create(
                by_key,
                name,
                _candidate_profile_fields(
                    pf,
                    name,
                    sota.get("paper_title", "") or "",
                    sota.get("raw_evidence", "") or "",
                ),
            )
            rec.evidence.append(DatasetDiscoveryEvidence(
                source="sota_target",
                paper_id=_canonical(sota.get("paper_id", "")),
                title=sota.get("paper_title", "") or "",
                url=sota.get("paper_url", "") or "",
                quote=sota.get("raw_evidence", "") or "",
            ))
            _bump_confidence(rec, "medium")

    # 3. papers[].datasets (structured, when present) — low confidence.
    for p in grounding.get("papers", []) or []:
        if not isinstance(p, dict):
            continue
        datasets = p.get("datasets") or []
        if not isinstance(datasets, list):
            continue
        paper_id = _canonical(p.get("paper_id", ""))
        title = p.get("title", "") or ""
        url = p.get("url", "") or ""
        for ds in datasets:
            if not isinstance(ds, str):
                continue
            name = ds.strip()
            if not name:
                continue
            rec = _get_or_create(
                by_key,
                name,
                _candidate_profile_fields(pf, name, title),
            )
            rec.evidence.append(DatasetDiscoveryEvidence(
                source="paper",
                paper_id=paper_id,
                title=title,
                url=url,
            ))
            # Low confidence — paper.datasets is more aspirational than baseline.
            # Don't bump from medium to low; only set if still default low.

    # 4. dataset_hint_candidates (LLM) — confidence from LLM directly.
    for hint in grounding.get("dataset_hint_candidates", []) or []:
        if not isinstance(hint, dict):
            continue
        name = (hint.get("name") or "").strip()
        if not name:
            continue
        rec = _get_or_create(
            by_key,
            name,
            _candidate_profile_fields(pf, name, hint.get("reason", "") or ""),
        )
        rec.evidence.append(DatasetDiscoveryEvidence(
            source="llm_hint",
            quote=hint.get("reason", "") or "",
        ))
        llm_conf = (hint.get("confidence") or "low").lower()
        if llm_conf not in _CONFIDENCE_ORDER:
            llm_conf = "low"
        _bump_confidence(rec, llm_conf)

    # 5. Passages (regex, last-resort with denylist + provider-URL gating).
    for passage in grounding.get("passages", []) or []:
        if not isinstance(passage, dict):
            continue
        text = (passage.get("text") or "")
        if not text.strip():
            continue
        url_hints = _provider_hints_from_text(text)
        # Only mine names from passages that already mention a provider URL —
        # this is the "regex is last resort" gate from review-update #5.
        if not url_hints:
            continue
        names = _extract_passage_dataset_names(text)
        if not names:
            continue
        paper_id = _canonical(passage.get("paper_id", ""))
        section = passage.get("section", "") or ""
        # Take just the first plausible dataset name per passage to avoid
        # flooding with adjacent acronyms; the explicit "<name> dataset"
        # phrase is normally first.
        seen_in_passage: set[str] = set()
        for name in names:
            key = name.strip().lower()
            if key in seen_in_passage:
                continue
            seen_in_passage.add(key)
            rec = _get_or_create(
                by_key,
                name,
                _candidate_profile_fields(pf, name, text),
            )
            rec.evidence.append(DatasetDiscoveryEvidence(
                source="passage",
                paper_id=paper_id,
                quote=text[:300],
                section=section,
            ))
            for hint in url_hints:
                # Dedup hints on (provider, url).
                exists = any(
                    h.provider == hint.provider and h.url == hint.url
                    for h in rec.provider_hints
                )
                if not exists:
                    rec.provider_hints.append(hint)
            _bump_confidence(rec, "medium")
            break  # one name per passage; the rest are usually noise.

    # 6. Optional LLM extractor — merge on top of heuristic extraction.
    if llm_extractor is not None:
        try:
            llm_texts = _collect_llm_input_texts(grounding)
            llm_records = llm_extractor.extract(texts=llm_texts, profile=profile)
        except Exception as e:
            logger.warning("LLM dataset extractor failed: %s", e)
            llm_records = []
        for llm_rec in llm_records:
            key = llm_rec.name.strip().lower()
            if not key:
                continue
            existing = by_key.get(key)
            if existing is None:
                # Merge profile semantics into the LLM record for tag carryover.
                if not existing:
                    by_key[key] = llm_rec
                continue
            # Conflict: heuristic wins unless LLM is higher confidence AND has hints.
            llm_better = (
                _CONFIDENCE_ORDER.get(llm_rec.confidence, 0)
                > _CONFIDENCE_ORDER.get(existing.confidence, 0)
                and bool(llm_rec.provider_hints)
            )
            # Always merge evidence + hints; only confidence/access elevate when llm_better.
            for ev in llm_rec.evidence:
                existing.evidence.append(ev)
            for hint in llm_rec.provider_hints:
                exists = any(
                    h.provider == hint.provider and h.url == hint.url
                    for h in existing.provider_hints
                )
                if not exists:
                    existing.provider_hints.append(hint)
            if llm_better:
                _bump_confidence(existing, llm_rec.confidence)

    return list(by_key.values())


_LLM_TEXT_BUDGET_PER_PASSAGE = 600


def _collect_llm_input_texts(grounding: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull text snippets from grounding for the LLM extractor.

    Prefer passages (richest, already chunked); fall back to baseline
    contexts when no passages are present.
    """
    texts: list[dict[str, Any]] = []
    for p in grounding.get("passages", []) or []:
        if not isinstance(p, dict):
            continue
        text = (p.get("text") or "").strip()
        if not text:
            continue
        texts.append({
            "paper_id": p.get("paper_id", ""),
            "text": text[:_LLM_TEXT_BUDGET_PER_PASSAGE],
        })
    if not texts:
        for b in grounding.get("baselines", []) or []:
            if not isinstance(b, dict):
                continue
            ctx = (b.get("context") or "").strip()
            if not ctx:
                continue
            texts.append({
                "paper_id": b.get("paper_id", ""),
                "text": ctx[:_LLM_TEXT_BUDGET_PER_PASSAGE],
            })
    return texts
