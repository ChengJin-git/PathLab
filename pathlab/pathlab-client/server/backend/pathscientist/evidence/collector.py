"""Evidence collector — gathers experiment output and persists on finalization."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import EvidenceStore
from .types import ArtifactRef, EvidenceRecord

logger = logging.getLogger(__name__)


@dataclass
class EvidenceFinalizeResult:
    """Outcome of a single ``EvidenceCollector.finalize()`` call.

    ``record_path`` is the absolute path to the persisted ``record.json`` on a
    successful finalize; empty when ``skipped=True``. ``skipped_reason`` is a
    stable short string (e.g. ``"no_last_experiment"``, ``"no_workspace"``,
    ``"exception:OSError:disk full"``) so downstream code and the
    IntegrityGuard can reason about *why* evidence was not written for a
    given run without parsing free-form logs.
    """

    record_path: str = ""
    skipped: bool = False
    skipped_reason: str = ""


class EvidenceCollector:
    """Accumulates experiment output during a run, persists on finalize."""

    def __init__(
        self,
        workspace_root: Path,
        store: EvidenceStore,
        session_id: str = "",
        primary_metric: str = "auc",
    ):
        self._workspace = Path(workspace_root)
        self._store = store
        self._session_id = session_id
        self._primary_metric = primary_metric
        self._experiment: dict[str, Any] = {}

    def record_experiment_output(
        self,
        run_id: str,
        run_dir: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        metrics: dict,
        duration: float,
        started_at: str = "",
        data_output_dir: str = "",
        data_output_artifacts: list[str] | None = None,
    ) -> None:
        """Buffer the latest experiment output for finalization."""
        self._experiment = {
            "run_id": run_id,
            "run_dir": run_dir,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "metrics": metrics,
            "duration": duration,
            "started_at": started_at or datetime.now(timezone.utc).isoformat(),
            "data_output_dir": data_output_dir,
            "data_output_artifacts": data_output_artifacts,
        }

    def finalize(self, committed: bool, iteration: int = 0) -> EvidenceFinalizeResult:
        """Create and persist an EvidenceRecord from buffered experiment output.

        Returns an :class:`EvidenceFinalizeResult` whose ``record_path`` points
        at the persisted ``record.json`` on success. The collector itself only
        raises ``RuntimeError`` when no experiment was recorded; any I/O
        exceptions from the underlying :class:`EvidenceStore.save` propagate
        to the caller (``tools.ratchet._finalize_iteration``) which converts
        them into a structured skip entry.
        """
        exp = self._experiment
        if not exp:
            raise RuntimeError("No experiment output recorded. Call record_experiment_output first.")

        # Git state
        git_commit = self._git_head()

        # For reverted runs, use pre-revert snapshots if available
        pre_revert_code = exp.pop("_pre_revert_code", None)
        pre_revert_diff = exp.pop("_pre_revert_diff", None)

        if pre_revert_code is not None:
            code_snapshot = pre_revert_code
            git_diff = pre_revert_diff or ""
        else:
            git_diff = self._git_diff()
            train_path = self._workspace / "train.py"
            code_snapshot = train_path.read_text(encoding="utf-8") if train_path.exists() else ""

        # Error classification
        error_type = ""
        error_hint = ""
        if exp["exit_code"] != 0:
            try:
                from ..error_classifier import classify_error, ERROR_FIX_HINTS
                et = classify_error(exp["stderr"])
                error_type = et.value
                error_hint = ERROR_FIX_HINTS.get(et, "")
            except Exception:
                error_type = "Unknown"

        # Resolve primary metric
        from ..orchestrator.metrics_utils import resolve_primary_metric
        primary_value = resolve_primary_metric(exp["metrics"], self._primary_metric)

        # Build artifact manifest from run_dir
        artifacts = self._scan_artifacts(exp["run_dir"])

        # Prefer explicit current-run outputs for shared DATA_OUTPUT_DIR values.
        data_output_dir = exp.get("data_output_dir", "")
        data_output_artifacts = exp.get("data_output_artifacts")
        if data_output_dir and not self._same_directory(data_output_dir, exp["run_dir"]):
            if data_output_artifacts is None:
                artifacts.extend(self._scan_external_artifacts(data_output_dir))
            else:
                artifacts.extend(self._scan_explicit_artifacts(data_output_artifacts))
        artifacts = self._dedupe_artifacts(artifacts)

        # Extract pre-revert untracked files if present
        untracked_files = exp.pop("_pre_revert_untracked", {}) or {}

        record = EvidenceRecord(
            run_id=exp["run_id"],
            session_id=self._session_id,
            iteration=iteration,
            run_dir=exp["run_dir"],
            git_commit=git_commit,
            git_diff=git_diff,
            code_snapshot=code_snapshot,
            exit_code=exp["exit_code"],
            duration=exp["duration"],
            stdout=exp["stdout"],
            stderr=exp["stderr"],
            metrics=exp["metrics"],
            primary_metric_name=self._primary_metric,
            primary_metric_value=primary_value,
            committed=committed,
            error_type=error_type,
            error_hint=error_hint,
            agent_notes="",
            artifacts=artifacts,
            data_output_dir=data_output_dir,
            untracked_files=untracked_files,
            started_at=exp["started_at"],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

        record_path = self._store.save(record)
        self._experiment = {}  # clear buffer
        return EvidenceFinalizeResult(record_path=str(record_path), skipped=False)

    def _git_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._workspace, capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _git_diff(self) -> str:
        """Get diff of all files between last two commits."""
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~1", "HEAD"],
                cwd=self._workspace, capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _scan_artifacts(self, run_dir: str) -> list[ArtifactRef]:
        """Scan run output directory for artifacts. Manifest only by default."""
        artifacts = []
        abs_dir = self._resolve_path(run_dir)
        if not abs_dir.is_dir():
            return artifacts

        for f in abs_dir.rglob("*"):
            if not f.is_file():
                continue
            artifact = self._build_artifact_ref(f, prefer_copy=True)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def _scan_external_artifacts(self, directory: str) -> list[ArtifactRef]:
        """Scan an external directory (e.g. DATA_OUTPUT_DIR) for artifacts."""
        artifacts = []
        abs_dir = self._resolve_path(directory)
        if not abs_dir.is_dir():
            return artifacts

        for f in abs_dir.rglob("*"):
            if not f.is_file():
                continue
            artifact = self._build_artifact_ref(f)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def _scan_explicit_artifacts(self, files: list[str]) -> list[ArtifactRef]:
        """Build manifest entries from a list of explicit artifact file paths."""
        artifacts = []
        for file_path in files:
            artifact = self._build_artifact_ref(self._resolve_path(file_path))
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def _build_artifact_ref(self, file_path: Path, prefer_copy: bool = False) -> ArtifactRef | None:
        """Create a manifest entry for an artifact file."""
        try:
            if not file_path.is_file():
                return None
            size = file_path.stat().st_size
        except OSError:
            return None

        try:
            rel = str(file_path.relative_to(self._workspace))
        except ValueError:
            rel = str(file_path)
        mode = "copy" if prefer_copy and file_path.name == "metrics.json" and size < 10_000 else "manifest"
        return ArtifactRef(
            name=file_path.name,
            path=rel,
            size=size,
            hash="",
            storage_mode=mode,
        )

    def _same_directory(self, left: str, right: str) -> bool:
        """Compare two directory paths after normalizing them to absolute paths."""
        return self._resolve_path(left) == self._resolve_path(right)

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a workspace-relative or absolute path without requiring it to exist."""
        path = Path(path_str)
        if not path.is_absolute():
            path = self._workspace / path
        return path.resolve(strict=False)

    def _artifact_key(self, artifact: ArtifactRef) -> str:
        """Build a stable dedupe key for an artifact entry."""
        return str(self._resolve_path(artifact.path))

    def _dedupe_artifacts(self, artifacts: list[ArtifactRef]) -> list[ArtifactRef]:
        """Drop duplicate artifacts while keeping the first occurrence."""
        deduped = []
        seen = set()
        for artifact in artifacts:
            key = self._artifact_key(artifact)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(artifact)
        return deduped
