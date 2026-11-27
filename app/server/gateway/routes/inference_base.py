"""Shared helpers for all inference_* route modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


def resolve_device(assigned_device: Optional[str] = None) -> str:
    import torch

    if assigned_device:
        return assigned_device
    return "cuda" if torch.cuda.is_available() else "cpu"


def resolve_checkpoint_paths(
    resources: dict[str, Any], uploads_dir: Path, checkpoint_name: str
) -> tuple[Path, Path]:
    model_path_value = resources.get("model_path")
    if model_path_value:
        model_path = Path(str(model_path_value)).expanduser()
        if model_path.exists() and model_path.name == checkpoint_name:
            config_path_value = resources.get("config_path")
            config_path = (
                Path(str(config_path_value)).expanduser()
                if config_path_value
                else model_path.parent / "config.json"
            )
            if not config_path.exists() and model_path.parent.name.startswith("fold_"):
                config_path = model_path.parent.parent / "config.json"
            return model_path, config_path

    model_dir = uploads_dir / "models" / str(resources["model_id"])
    root_checkpoint = model_dir / checkpoint_name
    if root_checkpoint.exists():
        return root_checkpoint, model_dir / "config.json"

    fold_checkpoints = sorted(model_dir.glob(f"fold_*/{checkpoint_name}"))
    if fold_checkpoints:
        checkpoint = fold_checkpoints[0]
        fold_config = checkpoint.parent / "config.json"
        return checkpoint, fold_config if fold_config.exists() else model_dir / "config.json"

    return root_checkpoint, model_dir / "config.json"


async def report_progress(
    progress_callback: Optional[Callable[[float], Awaitable[Any]]],
    idx: int,
    total: int,
    start: float = 0.1,
    end: float = 0.9,
) -> None:
    if progress_callback is not None and total > 0:
        value = start + (end - start) * (idx / total)
        await progress_callback(value)
