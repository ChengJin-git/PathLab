"""Refinement-loop stage scaffold.

M11 will replace this with a critic-driven refinement loop that re-runs
section_writing and the M10 guards, snapshots accepted iterations under
``drafts/snapshots/iter_{N}/``, and physically reverts ``drafts/sections/``
when an iteration fails the monotonic-convergence acceptance check.

For now this is a contract-only no-op so the pipeline dispatch can advance
through ``PaperRunStage.refining`` without breaking other stages.
"""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    """No-op scaffold; M11 owns the real refinement loop."""
    del paths, manifest
