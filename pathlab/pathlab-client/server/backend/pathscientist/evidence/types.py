"""Evidence data model — one record per finalized experiment iteration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArtifactRef:
    """Pointer to an artifact file."""
    name: str
    path: str           # relative to workspace
    size: int           # bytes
    hash: str           # MD5 for verification (optional for large files)
    storage_mode: str   # "manifest" | "symlink" | "copy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size": self.size,
            "hash": self.hash,
            "storage_mode": self.storage_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRef:
        return cls(**data)


@dataclass
class EvidenceRecord:
    """One experiment iteration's complete evidence."""
    # Identity
    run_id: str
    session_id: str
    iteration: int
    run_dir: str

    # Code state
    git_commit: str
    git_diff: str
    code_snapshot: str

    # Execution
    exit_code: int
    duration: float
    stdout: str
    stderr: str

    # Metrics
    metrics: dict
    primary_metric_name: str
    primary_metric_value: float

    # Outcome
    committed: bool
    error_type: str
    error_hint: str
    agent_notes: str

    # Artifacts
    artifacts: list[ArtifactRef] = field(default_factory=list)
    data_output_dir: str = ""  # stable user-visible output path (may differ from run_dir)
    untracked_files: dict[str, str] = field(default_factory=dict)  # filename→content for pre-revert untracked files

    # Timestamps
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "iteration": self.iteration,
            "run_dir": self.run_dir,
            "git_commit": self.git_commit,
            "git_diff": self.git_diff,
            "code_snapshot": self.code_snapshot,
            "exit_code": self.exit_code,
            "duration": self.duration,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "metrics": self.metrics,
            "primary_metric_name": self.primary_metric_name,
            "primary_metric_value": self.primary_metric_value,
            "committed": self.committed,
            "error_type": self.error_type,
            "error_hint": self.error_hint,
            "agent_notes": self.agent_notes,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "data_output_dir": self.data_output_dir,
            "untracked_files": self.untracked_files,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRecord:
        artifacts = [ArtifactRef.from_dict(a) for a in data.get("artifacts", [])]
        return cls(
            run_id=data["run_id"],
            session_id=data["session_id"],
            iteration=data["iteration"],
            run_dir=data["run_dir"],
            git_commit=data["git_commit"],
            git_diff=data.get("git_diff", ""),
            code_snapshot=data.get("code_snapshot", ""),
            exit_code=data["exit_code"],
            duration=data["duration"],
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            metrics=data.get("metrics", {}),
            primary_metric_name=data.get("primary_metric_name", ""),
            primary_metric_value=data.get("primary_metric_value", 0.0),
            committed=data["committed"],
            error_type=data.get("error_type", ""),
            error_hint=data.get("error_hint", ""),
            agent_notes=data.get("agent_notes", ""),
            artifacts=artifacts,
            data_output_dir=data.get("data_output_dir", ""),
            untracked_files=data.get("untracked_files", {}),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
        )
