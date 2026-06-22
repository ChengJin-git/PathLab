"""Path-restricted FileEditorTool — enforces write/view allowlists.

OpenHands SDK ships ``FileEditorExecutor`` with two restriction knobs:

- ``workspace_root``: only used by ``FileEditor.editor`` to suggest absolute
  paths when the agent gives a relative one. Does NOT reject writes
  outside the root (see ``editor.py`` ``__init__`` — workspace_path is
  stored as ``self.cwd`` and only consulted in path-suggestion text).
- ``allowed_edits_files``: an exact-file allowlist. Useful for "agent may
  only edit train.py" scenarios, too restrictive for PathScientist where
  the agent legitimately creates new files (model.py, helper.py, …).

This wrapper adds a directory-level allowlist + denylist with separate
``write_allow`` and ``view_allow`` sets — agent can browse a wider area
(e.g. ``dataset_cache_dir``) than it can modify, and a deny list takes
precedence to keep sensitive subpaths (``.git/``, source code, secrets)
off-limits even when they fall under an allowed root.

Data download paths (``dataset_cache_dir``, ``prepared_root``) are
populated by ``dataset/acquisition.py`` outside FileEditorTool, so this
wrapper does not affect data acquisition writes. New ``data_mounts``
from acquisition automatically appear in the next agent build's
``write_allow`` via ``config.data_mounts``.
"""
from __future__ import annotations

import logging
from pathlib import Path

from openhands.tools.file_editor import (
    FileEditorAction,
    FileEditorExecutor,
    FileEditorObservation,
)

logger = logging.getLogger(__name__)

# Commands that modify files (vs. ``view`` which only reads).
_DESTRUCTIVE_COMMANDS = frozenset({"create", "str_replace", "insert", "undo_edit"})


class RestrictedFileEditorExecutor(FileEditorExecutor):
    """``FileEditorExecutor`` subclass with directory-level path enforcement.

    Resolution order on each call:
      1. Resolve ``action.path`` to its real absolute form (follows
         symlinks and resolves ``..`` — defeats path-traversal tricks).
      2. If the resolved path is at or under any ``deny`` root → reject.
      3. Pick the allowlist by command:
            - destructive commands → ``write_allow``
            - ``view`` (read-only) → ``view_allow`` (defaults to write_allow)
      4. If the resolved path is at or under any allowed root → call
         the inherited executor.
      5. Otherwise reject with an explanation listing the allowed roots.

    Rejection returns a ``FileEditorObservation`` with ``is_error=True``
    so the agent sees a clear failure message and can adjust.
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        *,
        write_allow: list[str | Path],
        view_allow: list[str | Path] | None = None,
        deny: list[str | Path] | None = None,
    ):
        super().__init__(workspace_root=workspace_root)
        self._write_allow: list[Path] = self._normalize(write_allow)
        self._view_allow: list[Path] = (
            self._normalize(view_allow) if view_allow else list(self._write_allow)
        )
        self._deny: list[Path] = self._normalize(deny or [])

    @staticmethod
    def _normalize(paths: list[str | Path]) -> list[Path]:
        out: list[Path] = []
        for p in paths:
            if not p:
                continue
            try:
                resolved = Path(p).resolve(strict=False)
            except Exception:
                continue
            if resolved not in out:
                out.append(resolved)
        return out

    @staticmethod
    def _under(path: Path, roots: list[Path]) -> bool:
        for root in roots:
            try:
                if path == root or root in path.parents:
                    return True
            except Exception:
                continue
        return False

    def _check(self, action: FileEditorAction) -> FileEditorObservation | None:
        """Return an error observation if the action violates policy, else None."""
        raw = action.path or ""
        if not raw:
            return FileEditorObservation.from_text(
                text="DENIED: empty path",
                command=action.command,
                is_error=True,
            )
        try:
            resolved = Path(raw).resolve(strict=False)
        except Exception as e:
            return FileEditorObservation.from_text(
                text=f"DENIED: could not resolve path {raw!r}: {e}",
                command=action.command,
                is_error=True,
            )

        if self._under(resolved, self._deny):
            logger.warning(
                "file_editor DENIED (deny rule): command=%s path=%s",
                action.command, resolved,
            )
            return FileEditorObservation.from_text(
                text=(
                    f"DENIED: path '{resolved}' is in the protected denylist "
                    f"and cannot be {action.command!r}'d. Protected roots: "
                    f"{[str(p) for p in self._deny]}"
                ),
                command=action.command,
                is_error=True,
            )

        allowlist = (
            self._write_allow
            if action.command in _DESTRUCTIVE_COMMANDS
            else self._view_allow
        )
        if allowlist and not self._under(resolved, allowlist):
            kind = "write" if action.command in _DESTRUCTIVE_COMMANDS else "view"
            logger.warning(
                "file_editor DENIED (allowlist): command=%s path=%s "
                "(not under any %s-allowed root)",
                action.command, resolved, kind,
            )
            return FileEditorObservation.from_text(
                text=(
                    f"DENIED: '{action.command}' on '{resolved}' is outside "
                    f"the allowed {kind} roots. Allowed: "
                    f"{[str(p) for p in allowlist]}"
                ),
                command=action.command,
                is_error=True,
            )
        return None

    def __call__(
        self,
        action: FileEditorAction,
        conversation=None,  # noqa: ARG002 — kept for SDK signature parity
    ) -> FileEditorObservation:
        violation = self._check(action)
        if violation is not None:
            return violation
        return super().__call__(action, conversation)
