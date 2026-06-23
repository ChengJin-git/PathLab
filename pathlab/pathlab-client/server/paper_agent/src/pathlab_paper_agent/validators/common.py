"""Common types and file helpers for deterministic validation guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pathlab_paper_agent.storage import PaperRunPaths


@dataclass
class GuardIssue:
    """One hard-gate issue emitted by a validation guard."""

    code: str
    message: str
    severity: str = "error"
    path: str | None = None
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.context is not None:
            payload["context"] = self.context
        return payload


@dataclass
class GuardReport:
    """Stable JSON report shape for M10a guards."""

    guard: str
    issues: list[GuardIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "fail" if any(issue.severity == "error" for issue in self.issues) else "pass"

    def error(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        context: str | None = None,
    ) -> None:
        self.issues.append(
            GuardIssue(code=code, message=message, path=path, context=context)
        )

    def warn(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        context: str | None = None,
    ) -> None:
        self.issues.append(
            GuardIssue(
                code=code,
                message=message,
                severity="warning",
                path=path,
                context=context,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "guard": self.guard,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata,
        }


def rel_to_run(paths: PaperRunPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)


def existing_files(candidates: Iterable[Path]) -> list[Path]:
    return [path for path in candidates if path.exists() and path.is_file()]


def tex_files_under(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.rglob("*.tex") if path.is_file())


def paper_text_files(paths: PaperRunPaths) -> list[Path]:
    """Files that may become LLM-facing or paper-facing text."""
    candidates: list[Path] = []
    candidates.extend(tex_files_under(paths.sections_dir))
    candidates.extend(tex_files_under(paths.tables_dir))
    candidates.extend(tex_files_under(paths.locked_blocks_dir))
    candidates.extend(existing_files([paths.experimental_log]))
    return candidates
