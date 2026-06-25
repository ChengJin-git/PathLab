"""Dataset discovery domain types.

Phase A T1 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

These dataclasses are written by ``discovery_extractor.extract_dataset_candidates``
from persisted grounding outputs and persisted to ``.dataset/discovery.json``.

Identifiers
-----------
``DatasetDiscoveryEvidence.paper_id`` is expected to be a *canonical* paper
identifier such as ``"doi:10.1038/foo"``, ``"openalex:W123"``,
``"arxiv:2401.12345"``, ``"pmid:12345"``, ``"s2:abc"``, or ``"curated:slug"``.
Normalize whatever shape the source carries via
``autoresearch.literature.id_resolver.to_canonical_id`` before constructing
the evidence — the dataclasses themselves stay dumb on purpose so they can be
imported without pulling literature/* into dataset/.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DatasetDiscoveryEvidence:
    """A single evidence pointer for a discovered dataset candidate.

    ``paper_id`` MUST be a *canonical* identifier — the extractor that
    builds these instances normalizes via ``id_resolver.to_canonical_id``.
    Storing raw provider-specific keys here breaks cross-session linking
    through ``PaperRegistry``.

    ``source`` is one of ``"baseline" | "sota_target" | "paper" |
    "passage" | "llm_hint" | "dataset_hint"`` — the upstream signal
    that surfaced this dataset.
    """

    source: str
    paper_id: str = ""
    title: str = ""
    url: str = ""
    quote: str = ""
    section: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetDiscoveryEvidence":
        return cls(
            source=data.get("source", ""),
            paper_id=data.get("paper_id", ""),
            title=data.get("title", ""),
            url=data.get("url", ""),
            quote=data.get("quote", ""),
            section=data.get("section", ""),
        )


@dataclass
class ProviderHint:
    """A provider-specific download pointer for a discovered candidate.

    ``provider`` aligns with ``DatasetRecord.provider`` — ``"huggingface"``,
    ``"zenodo"``, ``"direct_http"``, ``"kaggle"``, etc. Hints surfaced by
    discovery are *unverified* — even when ``provider`` and ``remote_id``
    are populated, the conservative default in
    ``discovery_record_to_dataset_record`` keeps ``access="manual"`` until
    a probe / curated record raises confidence.
    """

    provider: str
    remote_id: str = ""
    url: str = ""
    kind: str = ""
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderHint":
        return cls(
            provider=data.get("provider", ""),
            remote_id=data.get("remote_id", ""),
            url=data.get("url", ""),
            kind=data.get("kind", ""),
            confidence=data.get("confidence", "low"),
        )


@dataclass
class DatasetDiscoveryRecord:
    """A dataset candidate surfaced from literature grounding.

    Discovery records are persisted under
    ``<workspace>/.dataset/discovery.json`` and bridged into a
    session-local ``DatasetRegistry`` via ``discovery_record_to_dataset_record``
    (Task 4). They never overwrite curated registry records.

    ``confidence`` is one of ``"low" | "medium" | "high"`` and gates whether
    the merge step in Task 4 keeps the record. The default is ``"low"``
    (skip-by-default unless evidence confirms it).
    """

    name: str
    aliases: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    asset_types: list[str] = field(default_factory=list)
    organs: list[str] = field(default_factory=list)
    label_keywords: list[str] = field(default_factory=list)
    prediction_target: str = ""
    access: str = "manual"
    estimated_size_gb: float = 0.0
    confidence: str = "low"
    evidence: list[DatasetDiscoveryEvidence] = field(default_factory=list)
    provider_hints: list[ProviderHint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [e.to_dict() for e in self.evidence]
        data["provider_hints"] = [h.to_dict() for h in self.provider_hints]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetDiscoveryRecord":
        return cls(
            name=data.get("name", ""),
            aliases=list(data.get("aliases", []) or []),
            task_types=list(data.get("task_types", []) or []),
            asset_types=list(data.get("asset_types", []) or []),
            organs=list(data.get("organs", []) or []),
            label_keywords=list(data.get("label_keywords", []) or []),
            prediction_target=data.get("prediction_target", ""),
            access=data.get("access", "manual"),
            estimated_size_gb=float(data.get("estimated_size_gb", 0.0) or 0.0),
            confidence=data.get("confidence", "low"),
            evidence=[
                DatasetDiscoveryEvidence.from_dict(e)
                for e in data.get("evidence", []) or []
                if isinstance(e, dict)
            ],
            provider_hints=[
                ProviderHint.from_dict(h)
                for h in data.get("provider_hints", []) or []
                if isinstance(h, dict)
            ],
        )
