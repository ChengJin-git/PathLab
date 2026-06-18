"""Git-backed workspace with ratchet semantics, built on OpenHands SDK LocalWorkspace.

The SDK LocalWorkspace provides: execute_command(), file ops, git_changes/diff.
This module adds: ratchet (commit/revert), baseline management, diff parsing,
and optional Apptainer sandbox execution.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from openhands.sdk.workspace.local import LocalWorkspace
    from openhands.sdk.workspace.models import CommandResult
except ModuleNotFoundError:
    LocalWorkspace = None

if TYPE_CHECKING:
    from .sandbox import ApptainerSandbox

logger = logging.getLogger(__name__)

# Runtime artifacts are captured by output/evidence plumbing, not by broad
# git ratchet commits. Keep this list conservative and only for generated
# files that can be huge or volatile.
_GENERATED_ARTIFACT_PATHS = (
    "output",
    "output/**",
    ".evidence",
    ".evidence/**",
    # Plan-2026-04-29 P1 #4: synthesis writes report manifests / paper
    # drafts under ``.reports/<session_id>/`` — these belong with
    # evidence, not with code commits. Pre-fix, ratchet swept them up
    # via ``git add -A``.
    ".reports",
    ".reports/**",
    "logs/completions",
    "logs/completions/**",
    "cache",
    "cache/**",
    ".cache",
    ".cache/**",
    "__pycache__",
    "**/__pycache__/**",
    "*.pt",
    "**/*.pt",
    "*.pth",
    "**/*.pth",
    "*.ckpt",
    "**/*.ckpt",
    "*.safetensors",
    "**/*.safetensors",
    "*.h5",
    "**/*.h5",
    "*.hdf5",
    "**/*.hdf5",
)


def _artifact_exclusion_pathspecs() -> str:
    """Return shell-quoted git pathspec excludes for generated artifacts."""
    specs = ["."]
    specs.extend(f":(exclude){pattern}" for pattern in _GENERATED_ARTIFACT_PATHS)
    return " ".join(shlex.quote(spec) for spec in specs)


# Regex for SEARCH/REPLACE diff blocks
_DIFF_PATTERN = re.compile(
    r"<<<SEARCH\n(.*?)\n===\n(.*?)\n>>>REPLACE",
    re.DOTALL,
)
_CHECKPOINT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SHELL_CONTROL_CHARS_RE = re.compile(r"[;&|`$<>]")


def _validate_checkpoint_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not _CHECKPOINT_NAME_RE.fullmatch(normalized):
        raise ValueError(
            "Invalid checkpoint name. Use 1-64 characters: letters, numbers, '.', '_' or '-'."
        )
    return normalized


@dataclass
class CommitInfo:
    hash: str
    message: str
    timestamp: str


@dataclass
class _FallbackCommandResult:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timeout_occurred: bool = False


if "CommandResult" not in globals():
    CommandResult = _FallbackCommandResult


def _allow_subprocess_workspace_fallback() -> bool:
    return os.getenv("PATHSCIENTIST_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK", "").lower() in {
        "1",
        "true",
        "yes",
    }


class _SubprocessWorkspace:
    """Small local executor used when OpenHands SDK is unavailable."""

    def __init__(self, working_dir: Path):
        self.working_dir = Path(working_dir)

    def execute_command(self, command: str, timeout: float = 60.0) -> CommandResult:
        if _SHELL_CONTROL_CHARS_RE.search(str(command or "")):
            return CommandResult(
                command=command,
                exit_code=2,
                stdout="",
                stderr="Shell metacharacters are not supported by the subprocess workspace fallback",
                timeout_occurred=False,
            )
        try:
            argv = shlex.split(str(command or ""))
        except ValueError as exc:
            return CommandResult(
                command=command,
                exit_code=2,
                stdout="",
                stderr=str(exc),
                timeout_occurred=False,
            )
        if not argv:
            return CommandResult(
                command=command,
                exit_code=0,
                stdout="",
                stderr="",
                timeout_occurred=False,
            )
        try:
            completed = subprocess.run(
                argv,
                cwd=self.working_dir,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timeout_occurred=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timeout_occurred=True,
            )


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
        if LocalWorkspace is None and not _allow_subprocess_workspace_fallback():
            raise RuntimeError(
                "OpenHands SDK LocalWorkspace is required. Set "
                "PATHSCIENTIST_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK=1 only for "
                "lightweight tests that deliberately run without the SDK."
            )
        workspace_cls = LocalWorkspace or _SubprocessWorkspace
        self._ws = workspace_cls(working_dir=self.root)
        self._sandbox = sandbox

        if not (self.root / ".git").exists():
            self._git("init")
            self._git("config user.email pathscientist@pathlab.local")
            self._git("config user.name 'PathScientist Code Agent'")

    @property
    def sdk_workspace(self) -> Any:
        """Expose the underlying SDK workspace for tools that need it."""
        if LocalWorkspace is None or not isinstance(self._ws, LocalWorkspace):
            raise RuntimeError("OpenHands SDK LocalWorkspace is not available")
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
        script_type: str = "python",
        session_id: str = "",
        run_id: str = "",
        tool_name: str = "run_experiment",
    ) -> CommandResult:
        """Run a Python or bash script in the workspace.

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
                script_type=script_type,
                session_id=session_id,
                run_id=run_id,
                tool_name=tool_name,
            )
            return CommandResult(
                command=f"[apptainer] {script_type} {script_path}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout_occurred=result.timed_out,
            )

        runner = "bash" if script_type == "bash" else sys.executable
        cmd = [runner, str(script_path)]
        env = os.environ.copy()
        if env_vars:
            env.update({str(k): str(v) for k, v in env_vars.items()})
        command_text = " ".join(shlex.quote(part) for part in cmd)
        try:
            completed = subprocess.run(
                cmd,
                cwd=self.root,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            return CommandResult(
                command=command_text,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timeout_occurred=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command_text,
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timeout_occurred=True,
            )

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
        result = self._git(
            "ls-files --cached --others --exclude-standard -- "
            f"{_artifact_exclusion_pathspecs()}"
        )
        if result.exit_code != 0:
            return []
        return [f for f in result.stdout.strip().split("\n") if f]

    # --- Ratchet operations ---

    def set_baseline(self, files: dict[str, str]) -> None:
        """Commit initial files as baseline. Raises CommitFailed on git error."""
        for rel_path, content in files.items():
            self.write_file(rel_path, content)

        add = self._git(f"add -A -- {_artifact_exclusion_pathspecs()}")
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
        add = self._git(f"add -A -- {_artifact_exclusion_pathspecs()}")
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

    def commit_paths(self, paths: list[str], message: str) -> str:
        """Commit ONLY the supplied workspace-relative paths.

        Used for metadata commits (e.g. .evidence) after a scientific run
        has already been finalized. Unlike ``commit()`` this must NOT use
        ``git add -A`` because we don't want unrelated dirty train.py
        changes from a follow-up iteration sweeping into the metadata
        commit.

        Returns the new HEAD's commit hash. If nothing in ``paths`` was
        actually staged (no diff), returns the existing HEAD without
        creating an empty commit. Raises ``CommitFailed`` on any git
        error.

        Plan T2 (docs/plans/2026-04-28-pathscientist-latest-session-review-fixes-plan.md):
        evidence files were previously left untracked after ratchet_commit,
        and a later iteration's ``git clean -fd`` (in revert()) would wipe
        them, leading to ``evidence_run_missing`` and a downgraded report.
        """
        safe_paths = [p for p in paths if p]
        if not safe_paths:
            return self.get_current_commit()

        quoted = " ".join(shlex.quote(p) for p in safe_paths)
        add = self._git(f"add -- {quoted}")
        if add.exit_code != 0:
            raise CommitFailed("commit_paths_add", add.exit_code, add.stderr)

        # exit code 0 = no staged changes, 1 = staged changes present.
        diff = self._git(f"diff --cached --quiet -- {quoted}")
        if diff.exit_code == 0:
            return self.get_current_commit()
        if diff.exit_code != 1:
            raise CommitFailed("commit_paths_diff", diff.exit_code, diff.stderr)

        commit = self._commit_with_message_file(message)
        if commit.exit_code != 0:
            raise CommitFailed("commit_paths_commit", commit.exit_code, commit.stderr)

        rev = self._git("rev-parse HEAD")
        if rev.exit_code != 0:
            raise CommitFailed("commit_paths_rev", rev.exit_code, rev.stderr)
        commit_hash = rev.stdout.strip()
        logger.info(f"[workspace] Metadata-committed paths {safe_paths}: {commit_hash[:8]} — {message}")
        return commit_hash

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

    def _checkpoint_tag(self, name: str) -> str:
        return f"{self._CHECKPOINT_PREFIX}{_validate_checkpoint_name(name)}"

    def create_checkpoint(self, name: str) -> str:
        """Create a named checkpoint at current HEAD.

        Commits any uncommitted changes first, then tags.
        Returns the commit hash.
        """
        # Auto-commit if there are uncommitted changes
        tag = self._checkpoint_tag(name)
        status = self._git("status --porcelain")
        if status.stdout.strip():
            self.commit(f"checkpoint: {name}")

        quoted_tag = shlex.quote(tag)
        # Delete existing tag with same name if exists
        self._git(f"tag -d {quoted_tag}")
        self._git(f"tag {quoted_tag}")
        commit_hash = self.get_current_commit()
        logger.info(f"[workspace] Checkpoint '{name}' at {commit_hash[:8]}")
        return commit_hash

    def restore_checkpoint(self, name: str) -> str:
        """Restore workspace to a named checkpoint.

        Discards all uncommitted changes and resets to the checkpoint.
        Returns the commit hash restored to.
        """
        tag = self._checkpoint_tag(name)
        quoted_tag = shlex.quote(tag)
        # Check tag exists
        result = self._git(f"rev-parse {quoted_tag}")
        if result.exit_code != 0:
            raise ValueError(f"Checkpoint '{name}' not found")

        commit_hash = result.stdout.strip()
        self._git(f"checkout {quoted_tag} -- .")
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
            hash_result = self._git(f"rev-parse {shlex.quote(tag)}")
            commit_hash = hash_result.stdout.strip() if hash_result.exit_code == 0 else ""
            checkpoints.append({"name": name, "hash": commit_hash[:8]})
        return checkpoints

    def delete_checkpoint(self, name: str) -> bool:
        """Delete a named checkpoint. Returns True if deleted."""
        tag = self._checkpoint_tag(name)
        result = self._git(f"tag -d {shlex.quote(tag)}")
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
