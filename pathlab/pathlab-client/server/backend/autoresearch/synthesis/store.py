"""Report store — file-based persistence for synthesis outputs."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .types import ResearchReport

logger = logging.getLogger(__name__)


class ReportStore:
    """File-based report storage under .reports/<session_id>/."""

    def __init__(self, reports_dir: Path):
        self._dir = Path(reports_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        d = self._dir / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, report: ResearchReport) -> Path:
        """Save structured report JSON."""
        d = self.session_dir(report.session_id)
        path = d / "report.json"
        path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Report saved: {path}")
        return path

    def load(self, session_id: str) -> ResearchReport:
        """Load a report by session_id."""
        path = self.session_dir(session_id) / "report.json"
        if not path.exists():
            raise FileNotFoundError(f"No report for session {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return ResearchReport.from_dict(data)

    def save_markdown(self, session_id: str, markdown: str, filename: str = "report.md") -> Path:
        """Save markdown report."""
        d = self.session_dir(session_id)
        path = d / filename
        path.write_text(markdown, encoding="utf-8")
        return path

    def save_grounded_sections(self, session_id: str, sections: list) -> Path:
        """Save grounded section inputs as JSON."""
        d = self.session_dir(session_id)
        path = d / "grounded_sections.json"
        path.write_text(
            json.dumps([s.to_dict() for s in sections], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def save_verification(self, session_id: str, result) -> Path:
        """Save paper verification result."""
        d = self.session_dir(session_id)
        path = d / "paper_verification.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def save_critique(self, session_id: str, result) -> Path:
        """Save paper critique result."""
        d = self.session_dir(session_id)
        path = d / "paper_critique.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def save_manifest(self, session_id: str, manifest: dict) -> Path:
        """Save synthesis artifact manifest."""
        d = self.session_dir(session_id)
        path = d / "manifest.json"
        path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
