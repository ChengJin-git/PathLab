"""Runtime iteration policy — enforces validate → quick check → full run order.

Instead of relying on prompt suggestions, this module tracks file state
and blocks out-of-order tool calls at runtime.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


class PolicyViolation(Exception):
    """Raised when the agent violates the iteration policy."""
    pass


@dataclass
class IterationState:
    """Tracks experiment workflow state to enforce execution order.

    Rules enforced:
    - run_experiment(full) requires validate + quick_check for current file hash
    - run_experiment(quick_check) requires validate for current file hash
    - max iterations budget is enforced
    """

    max_iterations: int = 5
    iteration_index: int = 0
    remaining_budget: int = field(init=False)

    # File hash tracking
    current_file_hash: str = ""
    last_validated_hash: str = ""
    last_validated_path: str = ""  # workspace-relative path of the last validated file
    last_quick_check_hash: str = ""

    # Run tracking
    last_run_id: str = ""
    finalized_run_ids: list[str] = field(default_factory=list)  # append-only
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.remaining_budget = self.max_iterations

    def compute_file_hash(
        self,
        workspace_dir: Path,
        script_path: str = "train.py",
        script_inputs: list[str] | None = None,
    ) -> str:
        """Compute a stable hash for a script and optional dependency files."""
        paths = list(dict.fromkeys([script_path, *(script_inputs or [])]))
        digest = hashlib.md5()
        any_file = False
        for rel in sorted(paths):
            path = workspace_dir / rel
            if not path.exists() or not path.is_file():
                return ""
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
            any_file = True
        return digest.hexdigest()[:12] if any_file else ""

    def update_file_hash(
        self,
        workspace_dir: Path,
        script_path: str = "train.py",
        script_inputs: list[str] | None = None,
    ) -> str:
        """Update and return the current file hash."""
        self.current_file_hash = self.compute_file_hash(
            workspace_dir,
            script_path=script_path,
            script_inputs=script_inputs,
        )
        return self.current_file_hash

    def mark_validated(self, file_hash: str) -> None:
        """Record that this file hash passed validation."""
        self.last_validated_hash = file_hash
        logger.debug(f"[policy] Validated hash: {file_hash}")

    def mark_quick_check_passed(self, file_hash: str) -> None:
        """Record that this file hash passed quick check."""
        self.last_quick_check_hash = file_hash
        logger.debug(f"[policy] Quick check passed: {file_hash}")

    def _format_validation_mismatch(self, phase: str, file_hash: str, script_path: str) -> str:
        """Build an actionable refusal message for the validate→run handoff.

        Review Finding 1 (2026-04-22): the previous generic text
        ``"current script has not been validated"`` gave the agent no way to
        tell whether validate_script had never been called, or had been
        called on a different file content. That ambiguity was part of what
        drove commit_003's ``run_train.py`` wrapper workaround in
        session_3f1795098784.
        """
        # Case 1: validate_script never recorded a hash — straightforward.
        if not self.last_validated_hash:
            return (
                f"{phase} refused: no validation record on file. "
                "Call validate_script with the current "
                f"{script_path or 'script'} content first."
            )
        # Case 2: a hash is recorded but it doesn't match the current disk
        # file — the script changed (or was overwritten) after validation.
        validated_path = self.last_validated_path or script_path or "script"
        return (
            f"{phase} refused: script hash mismatch.\n"
            f"  last_validated_hash = {self.last_validated_hash} "
            f"(from validate_script on {validated_path})\n"
            f"  current_hash        = {file_hash or '<file missing>'} "
            f"({script_path or 'current script'} as it is now)\n"
            "The script changed after validation. "
            "Re-run validate_script first."
        )

    def check_can_quick_check(
        self,
        file_hash: str,
        script_path: str = "",
        *,
        ignore_budget: bool = False,
    ) -> None:
        """Raise PolicyViolation if quick check is not allowed.

        Requires: file has been validated.

        ``file_hash`` is the hash of the on-disk file that ``run_experiment``
        is about to execute. ``script_path`` is carried through into the
        refusal text so the agent sees exactly which file mismatched.
        """
        if self.remaining_budget <= 0 and not ignore_budget:
            raise PolicyViolation(
                f"Iteration budget exhausted ({self.max_iterations} iterations used). "
                "Call finish to complete the session."
            )
        if file_hash != self.last_validated_hash:
            raise PolicyViolation(
                self._format_validation_mismatch(
                    "Cannot run quick check", file_hash, script_path,
                )
            )

    def check_can_full_run(
        self,
        file_hash: str,
        script_path: str = "",
        *,
        ignore_budget: bool = False,
    ) -> None:
        """Raise PolicyViolation if full run is not allowed.

        Requires: file has been validated AND passed quick check.

        See ``check_can_quick_check`` for the ``file_hash`` / ``script_path``
        contract.
        """
        if self.remaining_budget <= 0 and not ignore_budget:
            raise PolicyViolation(
                f"Iteration budget exhausted ({self.max_iterations} iterations used). "
                "Call finish to complete the session."
            )
        if file_hash != self.last_validated_hash:
            raise PolicyViolation(
                self._format_validation_mismatch(
                    "Cannot run full experiment", file_hash, script_path,
                )
            )
        if file_hash != self.last_quick_check_hash:
            raise PolicyViolation(
                "Cannot run full experiment: current script has not passed quick check. "
                "Call run_experiment with quick_check=true first. "
                f"(validated hash {self.last_validated_hash} matches; "
                f"quick_check hash {self.last_quick_check_hash or '<none>'} does not)"
            )

    def ensure_run_id(self) -> str:
        """Return ``last_run_id``, generating a canonical ``run_<hex8>`` if blank.

        Provides a lineage guarantee for finalization paths that may have been
        reached without first calling ``RunExperimentTool`` (which normally
        populates ``last_run_id``). Callers that need a traceable run id
        should prefer this over reading ``last_run_id`` directly.

        The ``run_`` prefix is mandatory (Fix 5): the paper verifier's
        ``\\brun_[0-9a-f]{8}\\b`` regex only considers prefixed tokens as
        run_ids, so bare 8-hex shards from conversation UUIDs or commit
        hashes never collide with the run_id namespace.
        """
        if not self.last_run_id:
            self.last_run_id = f"run_{uuid4().hex[:8]}"
        return self.last_run_id

    def record_iteration(self, metrics: dict, committed: bool) -> None:
        """Record a completed iteration.

        Note: ``finalized_run_ids`` is populated by the caller
        (``tools.ratchet._finalize_iteration``) *before* invoking this method,
        so we do not append here — doing so would double-count the same run.
        """
        self.history.append({
            "iteration": self.iteration_index,
            "file_hash": self.current_file_hash,
            "metrics": metrics,
            "committed": committed,
            "run_id": self.last_run_id,
        })
        self.iteration_index += 1
        self.remaining_budget -= 1
        # Reset hashes — next iteration needs fresh validate + quick check
        self.last_validated_hash = ""
        self.last_validated_path = ""
        self.last_quick_check_hash = ""
        logger.info(
            f"[policy] Iteration {self.iteration_index - 1} done "
            f"(committed={committed}, remaining={self.remaining_budget})"
        )
