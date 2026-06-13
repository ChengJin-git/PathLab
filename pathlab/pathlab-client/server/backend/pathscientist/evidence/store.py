"""Evidence store — file-based persistence for EvidenceRecords."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .types import EvidenceRecord

logger = logging.getLogger(__name__)


class EvidenceStore:
    """File-based evidence storage under .evidence/runs/<run_id>/."""

    def __init__(self, evidence_dir: Path):
        self._dir = Path(evidence_dir)
        self._runs_dir = self._dir / "runs"
        self._index_path = self._dir / "evidence.json"
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: EvidenceRecord) -> Path:
        """Persist an EvidenceRecord to disk. Returns path to record.json."""
        run_dir = self._runs_dir / record.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write record.json with truncated stdout/stderr preview
        # Full logs go in sidecar files (stdout.txt, stderr.txt)
        MAX_LOG_PREVIEW = 2000
        record_data = record.to_dict()
        if len(record_data.get("stdout", "")) > MAX_LOG_PREVIEW:
            record_data["stdout"] = record_data["stdout"][:MAX_LOG_PREVIEW] + "\n...[truncated, see stdout.txt]..."
        if len(record_data.get("stderr", "")) > MAX_LOG_PREVIEW:
            record_data["stderr"] = record_data["stderr"][:MAX_LOG_PREVIEW] + "\n...[truncated, see stderr.txt]..."

        record_path = run_dir / "record.json"
        record_path.write_text(
            json.dumps(record_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Write code snapshot
        if record.code_snapshot:
            (run_dir / "code_snapshot.py").write_text(record.code_snapshot, encoding="utf-8")

        # Write full stdout/stderr (untruncated)
        if record.stdout:
            (run_dir / "stdout.txt").write_text(record.stdout, encoding="utf-8")
        if record.stderr:
            (run_dir / "stderr.txt").write_text(record.stderr, encoding="utf-8")

        # Write untracked files (pre-revert snapshots of files that were never committed)
        if record.untracked_files:
            untracked_dir = run_dir / "untracked"
            untracked_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in record.untracked_files.items():
                safe_name = self._safe_untracked_path(filename)
                if safe_name is None:
                    continue
                try:
                    target = untracked_dir / safe_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                except Exception:
                    pass

        # Copy/symlink artifacts based on storage_mode
        artifacts_dir = run_dir / "artifacts"
        for artifact in record.artifacts:
            if artifact.storage_mode == "copy":
                src = self._dir.parent / artifact.path  # workspace-relative
                if src.exists() and src.is_file():
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    try:
                        shutil.copy2(str(src), str(artifacts_dir / artifact.name))
                    except Exception:
                        pass
            elif artifact.storage_mode == "symlink":
                src = self._dir.parent / artifact.path
                if src.exists():
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    target = artifacts_dir / artifact.name
                    if not target.exists():
                        try:
                            target.symlink_to(src.resolve())
                        except Exception:
                            pass

        # Update index
        self._update_index(record)

        logger.info(f"Evidence saved: {record.run_id} (committed={record.committed})")
        return record_path

    def load(self, run_id: str) -> EvidenceRecord:
        """Load an EvidenceRecord by run_id, rehydrating full logs from sidecar files."""
        run_dir = self._runs_dir / run_id
        record_path = run_dir / "record.json"
        if not record_path.exists():
            raise FileNotFoundError(f"No evidence record for run_id={run_id}")
        data = json.loads(record_path.read_text(encoding="utf-8"))

        # Rehydrate full logs from sidecar files (record.json may have truncated previews)
        stdout_path = run_dir / "stdout.txt"
        if stdout_path.exists():
            data["stdout"] = stdout_path.read_text(encoding="utf-8")
        stderr_path = run_dir / "stderr.txt"
        if stderr_path.exists():
            data["stderr"] = stderr_path.read_text(encoding="utf-8")

        # Rehydrate untracked files from sidecar directory
        untracked_dir = run_dir / "untracked"
        if untracked_dir.is_dir():
            untracked = {}
            for f in untracked_dir.rglob("*"):
                if f.is_file():
                    try:
                        rel_path = f.relative_to(untracked_dir).as_posix()
                        untracked[rel_path] = f.read_text(encoding="utf-8")
                    except Exception:
                        pass
            if untracked:
                data["untracked_files"] = untracked

        return EvidenceRecord.from_dict(data)

    def _safe_untracked_path(self, filename: str) -> Path | None:
        """Normalize an untracked file key into a safe relative path."""
        candidate = Path(filename)
        parts = [part for part in candidate.parts if part not in ("", ".", "..", "/")]
        if not parts:
            return None
        return Path(*parts)

    def list_runs(self, committed: bool | None = None) -> list[dict[str, Any]]:
        """List all evidence runs. Optionally filter by committed status.

        Returns list of summary dicts (not full records).
        """
        index = self._read_or_rebuild_index()
        if committed is not None:
            index = [r for r in index if r.get("committed") == committed]
        return index

    def get_best_run(self) -> EvidenceRecord | None:
        """Get the best committed run by primary metric value."""
        committed = self.list_runs(committed=True)
        if not committed:
            return None
        best = max(committed, key=lambda r: r.get("primary_metric_value", 0.0))
        return self.load(best["run_id"])

    def _update_index(self, record: EvidenceRecord) -> None:
        """Append a summary entry to evidence.json."""
        index = self._read_index()
        # Remove old entry with same run_id if exists
        index = [r for r in index if r.get("run_id") != record.run_id]
        index.append({
            "run_id": record.run_id,
            "session_id": record.session_id,
            "iteration": record.iteration,
            "primary_metric_name": record.primary_metric_name,
            "primary_metric_value": record.primary_metric_value,
            "committed": record.committed,
            "error_type": record.error_type,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        })
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_index(self) -> list[dict[str, Any]]:
        """Read evidence.json if it exists."""
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        return []

    def _read_or_rebuild_index(self) -> list[dict[str, Any]]:
        """Read index or rebuild from runs/ directories."""
        index = self._read_index()
        if index:
            return index

        # Rebuild from disk
        if not self._runs_dir.exists():
            return []

        index = []
        for run_dir in sorted(self._runs_dir.iterdir()):
            record_path = run_dir / "record.json"
            if not record_path.exists():
                continue
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
                index.append({
                    "run_id": data["run_id"],
                    "session_id": data.get("session_id", ""),
                    "iteration": data.get("iteration", 0),
                    "primary_metric_name": data.get("primary_metric_name", ""),
                    "primary_metric_value": data.get("primary_metric_value", 0.0),
                    "committed": data.get("committed", False),
                    "error_type": data.get("error_type", ""),
                    "started_at": data.get("started_at", ""),
                    "finished_at": data.get("finished_at", ""),
                })
            except Exception:
                continue

        # Persist rebuilt index
        if index:
            self._index_path.write_text(
                json.dumps(index, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return index
