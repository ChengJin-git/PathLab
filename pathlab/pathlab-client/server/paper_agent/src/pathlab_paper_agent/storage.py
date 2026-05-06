"""
Paper-generation runtime filesystem layout.

A single source of truth for where every artifact in a paper run lives.
Other modules MUST go through `PaperRunPaths` to construct paths — never
manually concatenate strings.

Layout (matches §7 of the design doc)::

    uploads/paper_generation/{paper_id}/
        manifest.json
        config.json
        inputs/
        evidence/
        tables/
        locked_blocks/
        figures/
        citations/
        drafts/intro_rw_draft/
        drafts/sections/
        drafts/snapshots/
        validation/
        final/{template_name}/
        exports/
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .bootstrap import ensure_server_on_path

ensure_server_on_path()

from backend.common.config import Config  # noqa: E402

_PAPER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$")


def validate_paper_id(paper_id: str) -> str:
    """Reject anything that is not a tame identifier.

    Used both at API entry and inside path construction so a malformed id
    can never produce a path outside `uploads/paper_generation/`.
    """
    if not isinstance(paper_id, str) or not _PAPER_ID_PATTERN.fullmatch(paper_id):
        raise ValueError(f"Invalid paper_id: {paper_id!r}")
    return paper_id


def papers_root() -> Path:
    """Root directory for all paper runs."""
    return Config.get_uploads_dir() / "paper_generation"


@dataclass(frozen=True)
class PaperRunPaths:
    """Resolved paths for a single paper run."""

    paper_id: str
    root: Path

    @classmethod
    def for_paper(cls, paper_id: str) -> "PaperRunPaths":
        validate_paper_id(paper_id)
        return cls(paper_id=paper_id, root=papers_root() / paper_id)

    # --- top-level files ---
    @property
    def manifest(self) -> Path: return self.root / "manifest.json"

    @property
    def config(self) -> Path: return self.root / "config.json"

    # --- inputs ---
    @property
    def inputs_dir(self) -> Path: return self.root / "inputs"

    @property
    def idea(self) -> Path: return self.inputs_dir / "idea.md"

    @property
    def source_tasks(self) -> Path: return self.inputs_dir / "source_tasks.json"

    @property
    def source_analyses(self) -> Path: return self.inputs_dir / "source_analyses.json"

    # --- evidence ---
    @property
    def evidence_dir(self) -> Path: return self.root / "evidence"

    @property
    def evidence_lock_private(self) -> Path:
        return self.evidence_dir / "evidence_lock.private.json"

    @property
    def evidence_public(self) -> Path:
        return self.evidence_dir / "evidence_public.json"

    @property
    def experimental_log(self) -> Path:
        return self.evidence_dir / "experimental_log.md"

    # --- generated content ---
    @property
    def tables_dir(self) -> Path: return self.root / "tables"

    @property
    def locked_blocks_dir(self) -> Path: return self.root / "locked_blocks"

    @property
    def figures_dir(self) -> Path: return self.root / "figures"

    @property
    def figures_manifest(self) -> Path: return self.figures_dir / "manifest.json"

    @property
    def citations_dir(self) -> Path: return self.root / "citations"

    @property
    def refs_bib(self) -> Path: return self.citations_dir / "refs.bib"

    # --- drafts ---
    @property
    def drafts_dir(self) -> Path: return self.root / "drafts"

    @property
    def outline_json(self) -> Path: return self.drafts_dir / "outline.json"

    @property
    def intro_rw_draft_dir(self) -> Path: return self.drafts_dir / "intro_rw_draft"

    @property
    def sections_dir(self) -> Path: return self.drafts_dir / "sections"

    @property
    def snapshots_dir(self) -> Path: return self.drafts_dir / "snapshots"

    # --- validation / final / export ---
    @property
    def validation_dir(self) -> Path: return self.root / "validation"

    @property
    def final_dir(self) -> Path: return self.root / "final"

    def final_for_template(self, template_name: str) -> Path:
        # template_name is validated upstream against templates/registry.json
        return self.final_dir / template_name

    @property
    def exports_dir(self) -> Path: return self.root / "exports"

    # --- creation helpers ---
    def all_subdirs(self) -> Iterable[Path]:
        return [
            self.inputs_dir,
            self.evidence_dir,
            self.tables_dir,
            self.locked_blocks_dir,
            self.figures_dir,
            self.citations_dir,
            self.drafts_dir,
            self.intro_rw_draft_dir,
            self.sections_dir,
            self.snapshots_dir,
            self.validation_dir,
            self.final_dir,
            self.exports_dir,
        ]

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for d in self.all_subdirs():
            d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# File access allowlist (§3.7)
# ---------------------------------------------------------------------------

# Relative paths (or path prefixes ending with `/`) that GET /files/{path} may
# serve. Anything else returns 403. evidence_lock.private.json, raw analysis
# JSON, and intro_rw_draft are explicitly absent.

_ALLOWED_EXACT = {
    "manifest.json",
    "config.json",
    "evidence/experimental_log.md",
    "evidence/evidence_public.json",
    "evidence/dataset_summary.public.json",
    "evidence/model_summary.public.json",
    "evidence/analysis_summary.public.json",
    "drafts/outline.json",
    "citations/refs.bib",
    "citations/coverage_report.json",
    "validation/warnings.md",
}

_ALLOWED_PREFIXES = (
    "tables/",
    "figures/",
    "drafts/sections/",
    "final/",
    "exports/",
)


def is_path_allowed_for_download(rel_path: str) -> bool:
    """§3.7 allowlist check.

    Caller must already have run `safe_resolve` to verify the path is within
    the paper run root. This function only decides whether a (validated)
    relative path falls under public surfaces.
    """
    if rel_path in _ALLOWED_EXACT:
        return True
    return any(rel_path.startswith(p) for p in _ALLOWED_PREFIXES)


def safe_resolve(paths: PaperRunPaths, user_path: str) -> Path:
    """Resolve `user_path` against the paper run root, rejecting escapes.

    Rejects:
    - absolute paths
    - `..` segments
    - leading/trailing whitespace
    - hidden files (any segment starting with `.`)
    - symlinks (the resolved target must still be inside `paths.root`)
    """
    if not isinstance(user_path, str) or not user_path:
        raise ValueError("path must be a non-empty string")
    if user_path != user_path.strip():
        raise ValueError("path has leading/trailing whitespace")
    candidate = Path(user_path)
    if candidate.is_absolute():
        raise ValueError("absolute path not allowed")
    parts = candidate.parts
    if any(p in ("..", "") for p in parts):
        raise ValueError("path traversal not allowed")
    if any(p.startswith(".") for p in parts):
        raise ValueError("hidden files not allowed")

    target = (paths.root / candidate).resolve()
    root_resolved = paths.root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("path escapes paper run root") from exc
    return target
