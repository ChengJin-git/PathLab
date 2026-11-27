"""Explicit feature-space contracts shared by extraction and retrieval.

A provider declares its capabilities; neither directory names nor dimensionality
identify a model. External producers can write the same versioned manifest.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class TextEncoderContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=100)
    checkpoint: str
    revision: str = Field(min_length=1, max_length=100)
    architecture: str = ""
    tokenizer: str = ""
    tokenizer_revision: str = ""
    aligned_space: str = Field(min_length=1, max_length=255)
    image_projection: Literal["identity", "provider"] = "identity"


class FeatureContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, max_length=100)
    model_revision: str = Field(min_length=1, max_length=100)
    embedding_space: str = Field(min_length=1, max_length=255)
    dimensions: int = Field(ge=1, le=65536)
    preprocessing: str = Field(min_length=1, max_length=2000)
    text_encoder: TextEncoderContract | None = None


@lru_cache(maxsize=64)
def _file_digest(path, size, mtime):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def asset_digest(path):
    path = Path(path)
    paths = (
        sorted(
            p
            for p in path.rglob("*")
            if p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(path).parts)
        )
        if path.is_dir()
        else [path]
    )
    digest = hashlib.sha256()
    for item in paths:
        stat = item.stat()
        digest.update(
            (str(item.relative_to(path)) if path.is_dir() else item.name).encode()
        )
        digest.update(_file_digest(str(item), stat.st_size, stat.st_mtime_ns).encode())
    if not paths:
        raise ValueError("Feature model assets are missing")
    return digest.hexdigest()


def text_feature_contract(
    model_id,
    checkpoint,
    dimensions,
    preprocessing,
    *,
    provider,
    architecture="",
    projection="identity",
    tokenizer="",
):
    revision = asset_digest(checkpoint)
    space = f"{model_id}:{revision}:contrastive"
    return FeatureContract(
        model_id=model_id,
        model_revision=revision,
        embedding_space=space,
        dimensions=dimensions,
        preprocessing=preprocessing,
        text_encoder=TextEncoderContract(
            provider=provider,
            checkpoint=str(checkpoint),
            revision=revision,
            architecture=architecture,
            tokenizer=str(tokenizer),
            tokenizer_revision=asset_digest(tokenizer)
            if tokenizer and Path(tokenizer).exists()
            else "",
            aligned_space=space,
            image_projection=projection,
        ),
    ).model_dump()


def model_state_digest(model):
    """Identify actual extractor weights once at construction, without naming heuristics."""
    import torch

    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(f"{name}:{value.dtype}:{tuple(value.shape)}".encode())
        raw = value.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy()
        digest.update(memoryview(raw))
    return digest.hexdigest()
