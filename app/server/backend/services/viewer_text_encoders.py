"""Text encoder plugins keyed by declared protocol, never by a model's name."""

from functools import lru_cache
from pathlib import Path
import numpy as np
from backend.ai.feature_contracts import TextEncoderContract, asset_digest

_providers = {}


def register_text_provider(name, loader):
    if name in _providers:
        raise ValueError("Duplicate text encoder provider")
    _providers[name] = loader


def available(contract):
    try:
        validate_assets(contract)
        return True
    except (ValueError, OSError):
        return False


def validate_assets(contract):
    if contract.provider not in _providers or not Path(contract.checkpoint).exists():
        raise ValueError("Text encoder provider or local checkpoint unavailable")
    if asset_digest(contract.checkpoint) != contract.revision:
        raise ValueError("Text encoder checkpoint changed")
    if (
        contract.tokenizer_revision
        and asset_digest(contract.tokenizer) != contract.tokenizer_revision
    ):
        raise ValueError("Text tokenizer changed")
    if contract.provider == "onnx_text" and not contract.tokenizer_revision:
        raise ValueError("ONNX tokenizer revision is required")


def _hf_clip(contract):
    from transformers import CLIPTextModelWithProjection, CLIPTokenizer

    model = CLIPTextModelWithProjection.from_pretrained(
        contract.checkpoint, local_files_only=True
    ).eval()
    tokenizer = CLIPTokenizer.from_pretrained(
        contract.tokenizer or contract.checkpoint, local_files_only=True
    )

    def encode(query, features):
        return model(
            **tokenizer([query], return_tensors="pt", truncation=True)
        ).text_embeds[0].numpy(), features

    return encode


def _open_clip(contract):
    import open_clip

    model, _, _ = open_clip.create_model_and_transforms(
        contract.architecture, pretrained=contract.checkpoint
    )
    model.eval()
    model.visual = None
    tokenizer = open_clip.get_tokenizer(contract.tokenizer or contract.architecture)
    return lambda query, features: (
        model.encode_text(tokenizer([query]))[0].numpy(),
        features,
    )


def _conch(contract):
    import torch
    from conch.open_clip_custom import (
        create_model_from_pretrained,
        get_tokenizer,
        tokenize,
    )

    model, _ = create_model_from_pretrained(contract.architecture, contract.checkpoint)
    model.eval()
    projection = (
        model.visual.proj_contrast.detach().clone()
        if contract.image_projection == "provider"
        else None
    )
    model.visual = None
    tokenizer = get_tokenizer()
    return lambda query, features: (
        model.encode_text(tokenize(texts=[query], tokenizer=tokenizer))[0].numpy(),
        (torch.from_numpy(features) @ projection).numpy()
        if projection is not None
        else features,
    )


def _onnx(contract):
    import onnxruntime as ort
    from tokenizers import Tokenizer

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(
        contract.checkpoint, sess_options=options, providers=["CPUExecutionProvider"]
    )
    tokenizer = Tokenizer.from_file(contract.tokenizer)

    def encode(query, features):
        encoded = tokenizer.encode(query)
        data = {
            "input_ids": np.array([encoded.ids], dtype=np.int64),
            "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
        }
        names = {item.name for item in session.get_inputs()}
        if not names <= data.keys():
            raise ValueError("Text encoder contract mismatch")
        output = session.run(None, {name: data[name] for name in names})[0]
        if output.ndim != 2 or output.shape[0] != 1:
            raise ValueError("Text encoder must return a pooled embedding")
        return output[0], features

    return encode


for name, loader in [
    ("hf_clip", _hf_clip),
    ("open_clip", _open_clip),
    ("conch", _conch),
    ("onnx_text", _onnx),
]:
    register_text_provider(name, loader)


@lru_cache(maxsize=1)
def _load(encoded_contract):
    contract = TextEncoderContract.model_validate_json(encoded_contract)
    return _providers[contract.provider](contract)


def encode(contract, query, features):
    import torch

    validate_assets(contract)
    with torch.inference_mode():
        vector, projected = _load(contract.model_dump_json())(query, features)
    vector = np.asarray(vector, dtype=np.float32)
    projected = np.asarray(projected, dtype=np.float32)
    if (
        vector.ndim != 1
        or projected.ndim != 2
        or len(projected) != len(features)
        or projected.shape[1] != len(vector)
        or not np.isfinite(vector).all()
        or not np.isfinite(projected).all()
        or np.linalg.norm(vector) < 1e-8
    ):
        raise ValueError("Text encoder returned an invalid embedding")
    return vector, projected
