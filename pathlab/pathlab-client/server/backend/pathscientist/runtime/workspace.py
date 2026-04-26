"""Git-backed workspace with ratchet semantics, built on OpenHands SDK LocalWorkspace.

The SDK LocalWorkspace provides: execute_command(), file ops, git_changes/diff.
This module adds: ratchet (commit/revert), baseline management, diff parsing,
and optional Apptainer sandbox execution.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from openhands.sdk.workspace.local import LocalWorkspace
from openhands.sdk.workspace.models import CommandResult

if TYPE_CHECKING:
    from .sandbox import ApptainerSandbox

logger = logging.getLogger(__name__)

# Regex for SEARCH/REPLACE diff blocks
_DIFF_PATTERN = re.compile(
    r"<<<SEARCH\n(.*?)\n===\n(.*?)\n>>>REPLACE",
    re.DOTALL,
)


@dataclass
class CommitInfo:
    hash: str
    message: str
    timestamp: str


class CommitFailed(RuntimeError):
    """Raised when a git subprocess invoked by the workspace exits non-zero.

    ``commit()``, ``revert()`` and ``set_baseline()`` previously returned
    silently even when ``git add``/``git commit``/``git rev-parse`` failed,
    which produced tracker entries claiming successful commits on a workspace
    that had none (see ``session_142a4acaed08`` — "6 committed" with zero
    actual commits). This exception makes any such failure loud so tool
    executors can finalize the iteration as ``committed=False`` and surface
    the stderr to the agent.
    """

    def __init__(self, stage: str, exit_code: int, stderr: str):
        trimmed = (stderr or "").strip()[:200]
        super().__init__(f"git {stage} failed (exit={exit_code}): {trimmed}")
        self.stage = stage
        self.exit_code = exit_code
        self.stderr = stderr


class Workspace:
    """Git-backed workspace with Karpathy-style ratchet.

    Delegates command execution and file ops to SDK LocalWorkspace.
    Adds ratchet semantics: improvements committed, failures reverted.
    """

    def __init__(self, root: Path, sandbox: ApptainerSandbox | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ws = LocalWorkspace(working_dir=self.root)
        self._sandbox = sandbox

        if not (self.root / ".git").exists():
            self._git("init")
            self._git("config user.email pathscientist@pathlab.local")
            self._git("config user.name 'PathScientist Code Agent'")

    @property
    def sdk_workspace(self) -> LocalWorkspace:
        """Expose the underlying SDK workspace for tools that need it."""
        return self._ws

    # --- Command execution (delegated to SDK) ---

    def execute_command(self, command: str, timeout: float = 60.0) -> CommandResult:
        """Run a shell command in the workspace via SDK LocalWorkspace."""
        return self._ws.execute_command(command, timeout=timeout)

    def run_script(
        self,
        script_path: str = "train.py",
        env_vars: dict[str, str] | None = None,
        timeout: float = 600.0,
        data_mounts: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run a Python script in the workspace.

        Uses the sandbox passed at construction if present, otherwise runs
        via direct subprocess through the SDK workspace.

        When a sandbox is configured, additional ``data_mounts`` (host_path
        -> container_path) get bound into the container so prepared-dataset
        paths from acquisition land at their declared container locations.
        The non-sandbox branch ignores ``data_mounts`` since host paths are
        directly accessible without any bind translation.
        """
        if self._sandbox is not None:
            result = self._sandbox.run_script(
                script_path=script_path,
                workspace_dir=self.root,
                output_dir=self.root / "output",
                env_vars=env_vars,
                timeout=timeout,
                data_mounts=data_mounts,
            )
            return CommandResult(
                command=f"[apptainer] python {script_path}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout_occurred=result.timed_out,
            )

        env_prefix = ""
        if env_vars:
            env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items()) + " "
        cmd = f"{env_prefix}python {script_path}"
        return self._ws.execute_command(cmd, timeout=timeout)

    # --- File operations ---

    def write_file(self, rel_path: str, content: str) -> Path:
        """Write a file to the workspace."""
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_file(self, rel_path: str) -> str | None:
        """Read a file from the workspace. Returns None if not found."""
        path = self.root / rel_path
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_files(self) -> list[str]:
        """List all tracked + untracked files in workspace."""
        result = self._git("ls-files --cached --others --exclude-standard")
        if result.exit_code != 0:
            return []
        return [f for f in result.stdout.strip().split("\n") if f]

    # --- Ratchet operations ---

    def set_baseline(self, files: dict[str, str]) -> None:
        """Commit initial files as baseline. Raises CommitFailed on git error."""
        for rel_path, content in files.items():
            self.write_file(rel_path, content)

        add = self._git("add -A")
        if add.exit_code != 0:
            raise CommitFailed("add", add.exit_code, add.stderr)

        commit = self._commit_with_message_file(
            "baseline: initial template",
            extra_flags="--allow-empty",
        )
        if commit.exit_code != 0:
            raise CommitFailed("commit", commit.exit_code, commit.stderr)

    def commit(self, message: str, metrics: dict | None = None) -> str:
        """Commit all changes. Returns commit hash. Raises CommitFailed on any git error.

        The commit message is passed via ``-F <tmpfile>`` rather than ``-m
        '<msg>'`` so arbitrary characters (apostrophes, newlines, JSON braces)
        in the message cannot break shell quoting — see ``session_142a4acaed08``
        where a Chinese objective + metrics JSON silently failed ``git commit``
        under the old single-quoted form.
        """
        add = self._git("add -A")
        if add.exit_code != 0:
            raise CommitFailed("add", add.exit_code, add.stderr)

        commit_msg = message
        if metrics:
            commit_msg += f" | metrics={json.dumps(metrics, default=str)}"

        commit = self._commit_with_message_file(commit_msg, extra_flags="--allow-empty")
        if commit.exit_code != 0:
            raise CommitFailed("commit", commit.exit_code, commit.stderr)

        rev = self._git("rev-parse HEAD")
        if rev.exit_code != 0:
            raise CommitFailed("rev-parse", rev.exit_code, rev.stderr)

        commit_hash = rev.stdout.strip()
        logger.info(f"[workspace] Committed: {commit_hash[:8]} \u2014 {message}")
        return commit_hash

    def revert(self) -> None:
        """Discard all uncommitted changes. Raises CommitFailed on any git error."""
        checkout = self._git("checkout -- .")
        if checkout.exit_code != 0:
            raise CommitFailed(
                "revert_checkout", checkout.exit_code, checkout.stderr,
            )

        clean = self._git("clean -fd")
        if clean.exit_code != 0:
            raise CommitFailed("revert_clean", clean.exit_code, clean.stderr)

        logger.info("[workspace] Reverted to last commit")

    # --- Internal: commit helper ------------------------------------------

    _COMMIT_MSG_FILENAME = "COMMIT_EDITMSG_PATHSCIENTIST"

    def _commit_with_message_file(
        self,
        message: str,
        extra_flags: str = "",
    ) -> CommandResult:
        """Run ``git commit -F <tmpfile>`` with the given message.

        Using ``-F`` avoids shell quoting entirely: LocalWorkspace executes the
        command through a shell, so embedded apostrophes or newlines in
        ``message`` would otherwise break ``commit -m '...'``. The tmpfile
        lives under ``.git/`` so it doesn't pollute tracked/untracked state.
        """
        git_dir = self.root / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        msg_file = git_dir / self._COMMIT_MSG_FILENAME
        msg_file.write_text(message, encoding="utf-8")
        flags = f" {extra_flags}" if extra_flags else ""
        return self._git(f"commit{flags} -F {msg_file}")

    # --- History ---

    def get_history(self) -> list[CommitInfo]:
        """Return commit history."""
        result = self._git("log --oneline --format='%H|%s|%ai'")
        entries = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip("'")
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append(CommitInfo(
                    hash=parts[0],
                    message=parts[1],
                    timestamp=parts[2],
                ))
        return entries

    def get_current_commit(self) -> str:
        """Return current HEAD commit hash."""
        result = self._git("rev-parse HEAD")
        return result.stdout.strip() if result.exit_code == 0 else ""

    # --- Checkpoints (named git tags) ---

    _CHECKPOINT_PREFIX = "checkpoint/"

    def create_checkpoint(self, name: str) -> str:
        """Create a named checkpoint at current HEAD.

        Commits any uncommitted changes first, then tags.
        Returns the commit hash.
        """
        # Auto-commit if there are uncommitted changes
        status = self._git("status --porcelain")
        if status.stdout.strip():
            self.commit(f"checkpoint: {name}")

        tag = f"{self._CHECKPOINT_PREFIX}{name}"
        # Delete existing tag with same name if exists
        self._git(f"tag -d {tag}")
        self._git(f"tag {tag}")
        commit_hash = self.get_current_commit()
        logger.info(f"[workspace] Checkpoint '{name}' at {commit_hash[:8]}")
        return commit_hash

    def restore_checkpoint(self, name: str) -> str:
        """Restore workspace to a named checkpoint.

        Discards all uncommitted changes and resets to the checkpoint.
        Returns the commit hash restored to.
        """
        tag = f"{self._CHECKPOINT_PREFIX}{name}"
        # Check tag exists
        result = self._git(f"rev-parse {tag}")
        if result.exit_code != 0:
            raise ValueError(f"Checkpoint '{name}' not found")

        commit_hash = result.stdout.strip()
        self._git(f"checkout {tag} -- .")
        self._git("clean -fd")
        logger.info(f"[workspace] Restored checkpoint '{name}' ({commit_hash[:8]})")
        return commit_hash

    def list_checkpoints(self) -> list[dict]:
        """List all named checkpoints.

        Returns list of {"name": str, "hash": str}.
        """
        result = self._git("tag -l 'checkpoint/*'")
        if result.exit_code != 0 or not result.stdout.strip():
            return []

        checkpoints = []
        for tag in result.stdout.strip().split("\n"):
            tag = tag.strip()
            if not tag:
                continue
            name = tag.removeprefix(self._CHECKPOINT_PREFIX)
            hash_result = self._git(f"rev-parse {tag}")
            commit_hash = hash_result.stdout.strip() if hash_result.exit_code == 0 else ""
            checkpoints.append({"name": name, "hash": commit_hash[:8]})
        return checkpoints

    def delete_checkpoint(self, name: str) -> bool:
        """Delete a named checkpoint. Returns True if deleted."""
        tag = f"{self._CHECKPOINT_PREFIX}{name}"
        result = self._git(f"tag -d {tag}")
        return result.exit_code == 0

    # --- Diff parsing and application (static methods) ---

    @staticmethod
    def extract_search_replace(response: str) -> list[tuple[str, str]] | None:
        """Extract <<<SEARCH ... === ... >>>REPLACE blocks from LLM response."""
        matches = _DIFF_PATTERN.findall(response)
        if not matches:
            return None
        return [(s.strip("\r"), r.strip("\r")) for s, r in matches]

    @staticmethod
    def apply_search_replace(
        original: str,
        diffs: list[tuple[str, str]],
    ) -> tuple[str, str]:
        """Apply search/replace diffs to original.

        Returns (modified_script, "") on success,
        or ("", error_message) on failure.
        """
        result = original
        for idx, (search, replace) in enumerate(diffs, 1):
            if search in result:
                result = result.replace(search, replace, 1)
                continue
            search_stripped = "\n".join(line.rstrip() for line in search.split("\n"))
            result_stripped = "\n".join(line.rstrip() for line in result.split("\n"))
            if search_stripped in result_stripped:
                result = result_stripped.replace(search_stripped, replace, 1)
                continue
            return "", f"SEARCH block #{idx} not found (first 60 chars: {search[:60]!r})"
        return result, ""

    # --- Internal: git via SDK execute_command ---

    def _git(self, args: str) -> CommandResult:
        """Run a git command via SDK LocalWorkspace.execute_command."""
        return self._ws.execute_command(f"git {args}", timeout=30.0)
