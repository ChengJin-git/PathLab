"""
FIXED — Training Utilities

Logging, checkpointing, and result saving for training sandbox.
This module runs inside the Docker sandbox and must NOT import any backend.* modules.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import torch


def setup_logging(log_file: str = "/results/training.log") -> logging.Logger:
    """Configure logging to both stdout and file."""
    logger = logging.getLogger("training")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # File handler
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def save_results(path: str, data: dict) -> None:
    """Write metrics dictionary to JSON file."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=_json_default)


def save_checkpoint(model: torch.nn.Module, path: str) -> None:
    """Save model state dict."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out)


def load_checkpoint(model: torch.nn.Module, path: str) -> torch.nn.Module:
    """Load model state dict."""
    state_dict = torch.load(path, map_location="cpu", weights_only=True)
    model.load_state_dict(state_dict)
    return model


def set_seed(seed: int = 42) -> None:
    """Set random seeds for reproducibility."""
    import random

    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def _json_default(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    import numpy as np

    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
