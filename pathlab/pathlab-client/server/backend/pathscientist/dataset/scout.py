"""Score and rank dataset candidates against a TaskProfile + policy.

Plan: docs/plans/2026-04-25-pathscientist-dataset-download-next-implementation-plan.md
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .policy import AcquisitionPolicy, PolicyDecision
from .registry import DatasetRegistry
from .types import DatasetRecord, TaskProfile


@dataclass
class DatasetCandidate:
    record: DatasetRecord
    score: float
    decision: PolicyDecision
    reasons: list[str] = field(default_factory=list)


class DatasetScout:
    """Rank registry records against a TaskProfile, gated by policy."""

    def __init__(self, registry: DatasetRegistry, policy: AcquisitionPolicy | None = None):
        self._registry = registry
        self._policy = policy or AcquisitionPolicy()

    def find_candidates(self, profile: TaskProfile, top_k: int = 5) -> list[DatasetCandidate]:
        records = self._registry.load()
        scored: list[DatasetCandidate] = []
        for r in records:
            score, reasons = self._score(r, profile)
            decision = self._policy.allow(
                access=r.access, estimated_size_gb=r.estimated_size_gb,
            )
            if not decision.allowed:
                score -= 100
                reasons.append(f"policy_reject:{decision.reason}")
            scored.append(DatasetCandidate(record=r, score=score, decision=decision, reasons=reasons))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]

    def _score(self, record: DatasetRecord, profile: TaskProfile) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        if profile.task_type and profile.task_type in record.task_types:
            score += 5.0
            reasons.append("task_type_match")
        if profile.organ and any(profile.organ.lower() == o.lower() for o in record.organs):
            score += 3.0
            reasons.append("organ_match")
        if profile.input_modality:
            asset_keys = {a.lower() for a in record.asset_types}
            if profile.input_modality.lower() in asset_keys:
                score += 2.0
                reasons.append("asset_match")
        # Keyword/tag/name fallback
        text = f"{record.name} {' '.join(record.tags)}".lower()
        for kw in profile.dataset_keywords or []:
            if kw and kw.lower() in text:
                score += 1.0
                reasons.append(f"keyword:{kw}")
        return score, reasons
