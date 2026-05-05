"""Stage implementations for the standalone paper-agent pipeline."""

from __future__ import annotations

from .collecting import run as run_collecting
from .evidence import run as run_building_evidence
from .exporting import run as run_exporting
from .literature import run as run_literature_review
from .outlining import run as run_outlining
from .plotting import run as run_plotting
from .refining import run as run_refining
from .rendering import run as run_rendering
from .sections import run as run_section_writing
from .validating import run as run_validating

__all__ = [
    "run_collecting",
    "run_building_evidence",
    "run_exporting",
    "run_literature_review",
    "run_outlining",
    "run_plotting",
    "run_refining",
    "run_rendering",
    "run_section_writing",
    "run_validating",
]
