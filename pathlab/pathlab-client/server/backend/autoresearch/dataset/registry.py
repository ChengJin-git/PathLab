"""JSON-backed registry of curated pathology datasets."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .types import DatasetRecord

logger = logging.getLogger(__name__)


class DatasetRegistry:
    """Persist/load dataset records at a JSON path.

    Fails open: a corrupted JSON file is treated as empty so acquisition
    never crashes on bad registry data.
    """

    def __init__(self, path: Path):
        self._path = Path(path)

    def load(self) -> list[DatasetRecord]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text())
        except Exception as e:
            logger.warning("DatasetRegistry load failed: %s", e)
            return []
        if not isinstance(raw, list):
            return []
        records: list[DatasetRecord] = []
        for row in raw:
            if isinstance(row, dict):
                try:
                    records.append(DatasetRecord.from_dict(row))
                except Exception as e:
                    logger.warning("Skipping malformed dataset row: %s", e)
        return records

    def save(self, records: Iterable[DatasetRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([r.to_dict() for r in records], indent=2)
        )

    def list_all(self) -> list[DatasetRecord]:
        return self.load()

    def find(
        self,
        task_type: str | None = None,
        organ: str | None = None,
        asset_type: str | None = None,
    ) -> list[DatasetRecord]:
        """Return records matching ALL non-None filters (case-insensitive)."""
        records = self.load()
        out: list[DatasetRecord] = []
        for r in records:
            if task_type and task_type.lower() not in (t.lower() for t in r.task_types):
                continue
            if organ and organ.lower() not in (o.lower() for o in r.organs):
                continue
            if asset_type and asset_type.lower() not in (a.lower() for a in r.asset_types):
                continue
            out.append(r)
        return out

    def seed_from_json(self, seed_path: Path) -> int:
        """One-shot: copy the curated seed file into `self._path`.

        Returns the count of records seeded. Overwrites existing contents.
        """
        seed_path = Path(seed_path)
        if not seed_path.exists():
            logger.warning("Seed file not found: %s", seed_path)
            return 0
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(seed_path.read_text())
        return len(self.load())
