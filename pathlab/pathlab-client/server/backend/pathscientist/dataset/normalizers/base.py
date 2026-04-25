"""Normalizer interface for converting raw downloaded datasets into a
skill-compatible prepared layout.

Each normalizer returns a "prepared contract" dict that the orchestrator
acquisition stage can persist into the manifest and surface to the
execution agent's prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DatasetNormalizer(Protocol):
    name: str
    supported_task_types: set[str]

    def supports(self, task_type: str) -> bool:
        ...

    def prepare(self, raw_root: Path, prepared_root: Path) -> dict[str, Any]:
        """Convert raw_root into prepared_root; return prepared contract."""
        ...
