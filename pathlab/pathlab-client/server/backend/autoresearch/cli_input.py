"""CLI input helpers — line editing, history, @file expansion, and !shell commands."""
from __future__ import annotations

import atexit
import importlib
import os
import re
from pathlib import Path

from .runtime.session import DEFAULT_BASE_DIR


FILE_REF_RE = re.compile(r"@([A-Za-z0-9_./-]+)")
ANSI_ESCAPE_RE = re.compile(r"(\x1b\[[0-9;]*m)")

_READLINE_STATE: dict[str, object | None] = {"module": None, "history_path": None}


def wrap_prompt_for_readline(prompt: str) -> str:
    """Wrap ANSI escape codes so readline ignores them in cursor math."""
    return ANSI_ESCAPE_RE.sub(lambda match: f"\001{match.group(1)}\002", prompt)


def build_cli_history_path(base_dir: str | Path | None = None) -> Path:
    """Return the persistent history file path for the interactive CLI."""
    root = Path(
        base_dir or os.environ.get(
            "AUTORESEARCH_BASE_DIR",
            DEFAULT_BASE_DIR,
        )
    ).expanduser().resolve()
    history_dir = root / "cli"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / "history"


def _write_history_file(path: str) -> None:
    """Persist readline history at process exit."""
    readline_mod = _READLINE_STATE.get("module")
    if readline_mod is None:
        return
    try:
        readline_mod.write_history_file(path)
    except Exception:
        pass


def configure_line_editing(base_dir: str | Path | None = None):
    """Enable readline-backed line editing and persistent history when available."""
    readline_mod = _READLINE_STATE.get("module")
    if readline_mod is not None:
        return readline_mod

    try:
        readline_mod = importlib.import_module("readline")
    except ImportError:
        return None

    history_path = build_cli_history_path(base_dir)

    readline_mod.parse_and_bind("tab: complete")
    readline_mod.parse_and_bind("set editing-mode emacs")
    readline_mod.parse_and_bind(r'"\e[1~": beginning-of-line')
    readline_mod.parse_and_bind(r'"\e[4~": end-of-line')
    readline_mod.parse_and_bind(r'"\e[7~": beginning-of-line')
    readline_mod.parse_and_bind(r'"\e[8~": end-of-line')
    readline_mod.set_history_length(1000)

    if history_path.exists():
        try:
            readline_mod.read_history_file(str(history_path))
        except Exception:
            pass

    atexit.register(_write_history_file, str(history_path))
    _READLINE_STATE["module"] = readline_mod
    _READLINE_STATE["history_path"] = history_path
    return readline_mod


def read_user_input(prompt: str, base_dir: str | Path | None = None) -> str:
    """Read one line from stdin using readline when available."""
    readline_mod = configure_line_editing(base_dir)
    effective_prompt = wrap_prompt_for_readline(prompt) if readline_mod is not None else prompt
    return input(effective_prompt)


def parse_bang_command(text: str) -> str | None:
    """Detect !shell commands. Returns the shell command or None."""
    if text.startswith("!"):
        cmd = text[1:].strip()
        return cmd or None
    return None


def expand_file_mentions(text: str, workspace_root: Path) -> str:
    """Replace @filename references with the file content from workspace."""
    def _replace(match: re.Match[str]) -> str:
        rel = match.group(1)
        path = workspace_root / rel
        if not path.exists() or not path.is_file():
            return match.group(0)  # keep as-is if not found
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return match.group(0)
        # Guess language from extension
        ext = path.suffix.lstrip(".")
        lang = {"py": "python", "yaml": "yaml", "yml": "yaml", "json": "json", "sh": "bash"}.get(ext, "")
        return f"`{rel}`:\n```{lang}\n{content}\n```"

    return FILE_REF_RE.sub(_replace, text)
