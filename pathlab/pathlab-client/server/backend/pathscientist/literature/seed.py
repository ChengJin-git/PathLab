"""Seed the literature store with curated pathology papers."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .store import LiteratureStore
from .types import PaperRecord

logger = logging.getLogger(__name__)

SEED_DATA_PATH = Path(__file__).parent / "seed_data" / "pathology_papers.json"


def seed_literature(store: LiteratureStore, seed_path: Path | None = None) -> int:
    """Load curated papers into the store. Returns count of papers added."""
    path = seed_path or SEED_DATA_PATH
    if not path.exists():
        logger.warning(f"Seed data not found: {path}")
        return 0

    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for entry in data:
        try:
            paper = PaperRecord.from_dict(entry)
            store.add(paper)
            count += 1
        except Exception as e:
            logger.warning(f"Failed to load paper {entry.get('paper_id', '?')}: {e}")

    logger.info(f"Seeded {count} papers from {path.name}")
    return count
