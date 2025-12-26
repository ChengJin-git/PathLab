from typing import Dict, List
import os
from huggingface_hub import snapshot_download

# Store checkpoints under the segmentors package so they are reused across runs
SEGMENTOR_CKPT_SAVE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "checkpoints"
)
os.makedirs(SEGMENTOR_CKPT_SAVE_DIR, exist_ok=True)


# Mapping from backbone alias to Hugging Face repo id used by timm
_SUPPORTED_BACKBONES: Dict[str, str] = {
    "vit_large_patch16_dinov3": "timm/vit_large_patch16_dinov3.lvd1689m",
    "vit_huge_plus_patch16_dinov3": "timm/vit_huge_plus_patch16_dinov3.lvd1689m",
}


def _ensure_local_repo(backbone: str, repo_id: str, hf_token: str) -> str:
    """Download the backbone weights repo locally if missing and return the path."""
    local_dir = os.path.join(SEGMENTOR_CKPT_SAVE_DIR, backbone)
    os.makedirs(local_dir, exist_ok=True)

    has_weights = any(
        os.path.isfile(os.path.join(local_dir, fname))
        for fname in ("model.safetensors", "pytorch_model.bin")
    )
    if not has_weights:
        snapshot_download(repo_id=repo_id, local_dir=local_dir, token=hf_token or None)

    return local_dir


def get_backbone_source(backbone: str, hf_token: str = "") -> str:
    """Return a timm-compatible local-dir source for the requested backbone."""
    key = backbone.strip().lower()
    if key not in _SUPPORTED_BACKBONES:
        raise ValueError(
            f"Backbone '{backbone}' is not supported. Supported backbones: {list_supported_backbones()}"
        )

    local_dir = _ensure_local_repo(key, _SUPPORTED_BACKBONES[key], hf_token)
    return f"local-dir:{local_dir}"


def list_supported_backbones() -> List[str]:
    return sorted(_SUPPORTED_BACKBONES.keys())
