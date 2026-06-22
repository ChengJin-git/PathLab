"""Conversation persistence directory layout.

Each conversation is stored under ``persistence_root/<conversation_id_hex>/``
by the OpenHands SDK (``BaseConversation.get_persistence_dir``).
"""
from __future__ import annotations

from pathlib import Path


def get_persistence_root(base_dir: str | Path) -> Path:
    """Return the root directory for all conversation persistence.

    The SDK will create per-conversation subdirectories automatically.
    """
    root = Path(base_dir).expanduser().resolve() / "conversations"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create PathScientist conversation persistence directory at {root}: {exc}. "
            "Set PATHSCIENTIST_BASE_DIR=/tmp/autoresearch or "
            "PATHSCIENTIST_PERSISTENCE_DIR to a writable location."
        ) from exc
    return root
