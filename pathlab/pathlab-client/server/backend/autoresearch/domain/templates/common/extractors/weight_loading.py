from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Mapping

import torch


def load_state_dict_file(path: str | Path):
    """Load PyTorch or safetensors weights from a trusted local path."""
    path = Path(path)
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        return load_file(str(path))
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(path, map_location="cpu")


def unwrap_state_dict(obj):
    if isinstance(obj, Mapping):
        for key in ("state_dict", "model", "module"):
            value = obj.get(key)
            if isinstance(value, Mapping):
                return value
    return obj


def extract_teacher_backbone_state(obj):
    if "teacher" not in obj:
        return unwrap_state_dict(obj)
    result = OrderedDict()
    for key, value in obj["teacher"].items():
        if key.startswith("backbone."):
            result[key[len("backbone.") :]] = value
    return result


def first_existing_weight_file(model_dir: str | Path) -> Path:
    model_dir = Path(model_dir)
    for name in ("model.safetensors", "pytorch_model.bin"):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No supported weight file found in {model_dir}; expected model.safetensors or pytorch_model.bin"
    )
