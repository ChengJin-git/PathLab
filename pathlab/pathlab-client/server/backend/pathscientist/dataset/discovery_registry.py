"""Bridge discovery records into the acquisition DatasetRecord shape + merge.

Phase A T4 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

Two key behaviors from the review-update bullets:

- **Discovery is NOT proof of downloadability.** A discovered record stays
  ``access="manual"`` even when a provider URL is present. Only curated
  records or a successful provider probe (Task 5+6) can upgrade access.
- **Curated records always win on conflict.** Same name OR a curated tag
  matches the discovered name → curated wins, discovered is dropped.

Confidence gate: only ``confidence in {"medium", "high"}`` AND at least one
evidence entry survives the merge into the session-local registry.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from .discovery_types import DatasetDiscoveryRecord
from .types import DatasetRecord, DownloadSpec

logger = logging.getLogger(__name__)


_PROVIDER_TO_KIND: dict[str, str] = {
    "huggingface": "hf_dataset",
    "zenodo": "zenodo",
    "direct_http": "direct_http",
    # Plan-2026-04-30 dataset-provider-repair Task 2: when the hint carries
    # an explicit ``kind`` (e.g. ``kaggle_competition`` / ``kaggle_dataset``)
    # that wins. Falling back to ``"manual"`` means an unparsed kaggle URL
    # is downloadable only via the user's hand.
    "kaggle": "manual",
    "github": "manual",
    "figshare": "manual",
    "tcia": "manual",
}


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return s or "unknown"


def discovery_record_to_dataset_record(
    discovered: DatasetDiscoveryRecord,
) -> DatasetRecord:
    """Convert a discovery record into an acquisition-shape DatasetRecord.

    Always returns ``access="manual"`` — discovery alone cannot prove
    downloadability. The acquisition pipeline's policy / probe stages
    decide what gets upgraded.
    """
    primary_hint = discovered.provider_hints[0] if discovered.provider_hints else None
    if primary_hint is None:
        provider = "manual"
        kind = "manual"
        remote_id = ""
        urls: list[str] = []
    else:
        provider = primary_hint.provider or "manual"
        # Plan-2026-04-30 dataset-provider-repair Task 2: when the hint
        # carries an explicit ``kind`` (e.g. ``kaggle_competition``), it
        # wins over the provider→kind default. Otherwise fall back.
        kind = (primary_hint.kind or "").strip()
        if not kind:
            kind = _PROVIDER_TO_KIND.get(provider, "manual")
        remote_id = primary_hint.remote_id
        urls = [primary_hint.url] if primary_hint.url else []

    tags: list[str] = []
    seen_tags: set[str] = set()

    def _add_tag(t: str) -> None:
        t = (t or "").strip()
        if not t or t in seen_tags:
            return
        seen_tags.add(t)
        tags.append(t)

    for alias in discovered.aliases:
        _add_tag(alias)
    for kw in discovered.label_keywords:
        _add_tag(kw)
    if discovered.prediction_target:
        _add_tag(discovered.prediction_target)
    if discovered.confidence:
        _add_tag(f"confidence:{discovered.confidence}")
    _add_tag("discovered")

    source_paper_ids: list[str] = []
    seen_pids: set[str] = set()
    for ev in discovered.evidence:
        pid = (ev.paper_id or "").strip()
        if pid and pid not in seen_pids:
            seen_pids.add(pid)
            source_paper_ids.append(pid)

    return DatasetRecord(
        dataset_id=f"discovered:{_slugify(discovered.name)}",
        name=discovered.name,
        provider=provider,
        access="manual",
        task_types=list(discovered.task_types),
        asset_types=list(discovered.asset_types),
        organs=list(discovered.organs),
        license="",
        estimated_size_gb=discovered.estimated_size_gb,
        tags=tags,
        source_paper_ids=source_paper_ids,
        download=DownloadSpec(kind=kind, remote_id=remote_id, urls=urls),
    )


# ---------------------------------------------------------------- merge


def _curated_keys(rec: DatasetRecord) -> set[str]:
    """Lowercase set of name + tags so we can match aliases."""
    keys: set[str] = set()
    if rec.name:
        keys.add(rec.name.strip().lower())
    for tag in rec.tags or []:
        if tag:
            keys.add(tag.strip().lower())
    return keys


def merge_curated_and_discovered(
    curated: Iterable[DatasetRecord],
    discovered: Iterable[DatasetDiscoveryRecord],
) -> list[DatasetRecord]:
    """Merge curated records with discovered candidates.

    Rules (review constraint #1):
    - Curated records pass through unchanged.
    - A discovered record is dropped if any curated record's name or tag
      matches its name (case-insensitive).
    - Discovered records require ``confidence in {"medium", "high"}`` AND
      at least one evidence entry; otherwise dropped.
    """
    curated_list = list(curated)
    blocked: set[str] = set()
    for c in curated_list:
        blocked |= _curated_keys(c)

    out: list[DatasetRecord] = list(curated_list)
    seen_discovered: set[str] = set()
    for d in discovered:
        if d.confidence not in {"medium", "high"}:
            continue
        if not d.evidence:
            continue
        key = d.name.strip().lower()
        if not key or key in seen_discovered:
            continue
        # Plan-2026-04-30 dataset-provider-repair Task 2: also block
        # discovered records whose *aliases* collide with curated names/tags.
        # Without this, "TCGA CRC-MSI" with aliases=["CRC-MSI"] would slip
        # past a curated "CRC-MSI" record.
        alias_keys = {a.strip().lower() for a in (d.aliases or []) if a}
        if key in blocked or (alias_keys & blocked):
            continue
        seen_discovered.add(key)
        out.append(discovery_record_to_dataset_record(d))
    return out
