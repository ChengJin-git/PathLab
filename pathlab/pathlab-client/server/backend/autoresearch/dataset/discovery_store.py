"""Dataset discovery JSON persistence.

Phase A T2 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

Writes and reads ``.dataset/discovery.json`` under the workspace. The runner
calls ``save_discovery_records`` after running ``extract_dataset_candidates``
and before merging with the curated registry; downstream consumers (execution
brief, paper writer) read via ``load_discovery_records`` from the persisted
``state.grounding["dataset_discovery_path"]`` pointer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .discovery_types import DatasetDiscoveryRecord

logger = logging.getLogger(__name__)


def discovery_path_for_workspace(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / ".dataset" / "discovery.json"


def save_discovery_records(
    path: Path | str,
    records: Iterable[DatasetDiscoveryRecord],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.to_dict() for r in records]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_discovery_records(path: Path | str) -> list[DatasetDiscoveryRecord]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Dataset discovery load failed at %s: %s", path, e)
        return []
    if not isinstance(raw, list):
        return []
    return [
        DatasetDiscoveryRecord.from_dict(row)
        for row in raw
        if isinstance(row, dict)
    ]
