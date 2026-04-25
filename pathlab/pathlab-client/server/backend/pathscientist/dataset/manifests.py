"""Persist DatasetManifest records to <workspace>/.dataset/manifest.json."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .types import DatasetManifest

logger = logging.getLogger(__name__)


def manifest_path_for_workspace(workspace_root: Path) -> Path:
    """Canonical workspace-relative manifest location."""
    return Path(workspace_root) / ".dataset" / "manifest.json"


def save_manifest(path: Path, manifest: DatasetManifest) -> None:
    """Write manifest to path; create parents if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2))


def load_manifest(path: Path) -> DatasetManifest:
    """Load manifest from path. Raises FileNotFoundError if absent;
    returns a `status="failed"` manifest with reason if the JSON is corrupted."""
    path = Path(path)
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except Exception as e:
        logger.warning("Manifest parse failed at %s: %s", path, e)
        return DatasetManifest(
            dataset_id="", provider="", selected_for_task="",
            raw_root="", prepared_root="",
            data_mounts={}, prepared_contract={},
            status="failed",
        )
    return DatasetManifest.from_dict(data)
