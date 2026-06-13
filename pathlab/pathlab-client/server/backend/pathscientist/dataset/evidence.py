"""Acquisition evidence writer."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .downloader import safe_dataset_id


def write_acquisition_record(workspace_root: Path, payload: dict[str, Any]) -> Path:
    """Write an acquisition evidence record.

    The record lands at ``<workspace>/.evidence/datasets/<safe_id>.json``
    where ``safe_id`` is derived from ``payload["candidate"]["dataset_id"]``
    if present, else from a timestamp.
    """
    workspace_root = Path(workspace_root)
    target_dir = workspace_root / ".evidence" / "datasets"
    target_dir.mkdir(parents=True, exist_ok=True)

    cand = payload.get("candidate") or {}
    dataset_id = cand.get("dataset_id") or f"acquisition_{int(time.time() * 1000)}"
    fname = safe_dataset_id(dataset_id) + ".json"
    path = target_dir / fname

    enriched = dict(payload)
    enriched.setdefault("recorded_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path.write_text(json.dumps(enriched, indent=2))
    return path
