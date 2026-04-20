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
    last_quick_check_hash: str = ""

    # Run tracking
    last_run_id: str = ""
    finalized_run_ids: list[str] = field(default_factory=list)  # append-only
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.remaining_budget = self.max_iterations

    def compute_file_hash(self, workspace_dir: Path, script_path: str = "train.py") -> str:
        """Compute hash of the current script file."""
        path = workspace_dir / script_path
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def update_file_hash(self, workspace_dir: Path, script_path: str = "train.py") -> str:
        """Update and return the current file hash."""
        self.current_file_hash = self.compute_file_hash(workspace_dir, script_path)
        return self.current_file_hash

    def mark_validated(self, file_hash: str) -> None:
        """Record that this file hash passed validation."""
        self.last_validated_hash = file_hash
        logger.debug(f"[policy] Validated hash: {file_hash}")

    def mark_quick_check_passed(self, file_hash: str) -> None:
        """Record that this file hash passed quick check."""
        self.last_quick_check_hash = file_hash
        logger.debug(f"[policy] Quick check passed: {file_hash}")

    def check_can_quick_check(self, file_hash: str) -> None:
        """Raise PolicyViolation if quick check is not allowed.

        Requires: file has been validated.
        """
        if self.remaining_budget <= 0:
            raise PolicyViolation(
                f"Iteration budget exhausted ({self.max_iterations} iterations used). "
                "Call finish to complete the session."
            )
        if file_hash != self.last_validated_hash:
            raise PolicyViolation(
                "Cannot run quick check: current script has not been validated. "
                "Call validate_script first, then try again."
            )

    def check_can_full_run(self, file_hash: str) -> None:
        """Raise PolicyViolation if full run is not allowed.

        Requires: file has been validated AND passed quick check.
        """
        if self.remaining_budget <= 0:
            raise PolicyViolation(
                f"Iteration budget exhausted ({self.max_iterations} iterations used). "
                "Call finish to complete the session."
            )
        if file_hash != self.last_validated_hash:
            raise PolicyViolation(
                "Cannot run full experiment: current script has not been validated. "
                "Call validate_script first."
            )
        if file_hash != self.last_quick_check_hash:
            raise PolicyViolation(
                "Cannot run full experiment: current script has not passed quick check. "
                "Call run_experiment with quick_check=true first."
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
        self.last_quick_check_hash = ""
        logger.info(
            f"[policy] Iteration {self.iteration_index - 1} done "
            f"(committed={committed}, remaining={self.remaining_budget})"
        )
