"""Persist the dataset acquisition plan artifact.

Phase C T8 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

``DatasetAcquisitionService.acquire()`` writes
``<workspace>/.dataset/acquisition_plan.json`` *before* the download phase
so the agent (and any reviewer reading a stop-before-execution session) can
see *what* was considered, *why* it was selected/rejected, and what
``download_policy`` allowed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def acquisition_plan_path_for_workspace(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / ".dataset" / "acquisition_plan.json"


def save_acquisition_plan(path: Path | str, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_acquisition_plan(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("acquisition plan load failed at %s: %s", path, e)
        return {}


def candidate_to_plan_entry(candidate) -> dict[str, Any]:
    """Serialize a DatasetCandidate into the plan's ``considered`` list."""
    record = candidate.record
    decision = candidate.decision
    return {
        "dataset_id": record.dataset_id,
        "name": record.name,
        "provider": record.provider,
        "access": record.access,
        "score": float(candidate.score),
        "relevant": bool(candidate.relevant),
        "allowed": bool(getattr(decision, "allowed", False)),
        "policy_reason": getattr(decision, "reason", "") or "",
        "reasons": list(candidate.reasons or []),
        "tags": list(record.tags or []),
    }
