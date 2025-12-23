
from huggingface_hub import hf_hub_download
import os

# set the dir where this file is located, and create a subdir 'checkpoints' to save the downloaded checkpoints
FEATURE_EXTRACTOR_CKPT_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoints")
os.makedirs(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, exist_ok=True)


__all__ = ["get_ckpt_path"]


def conch(hf_token: str) -> str:
    """Download and return the local path to the CONCH model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "CONCH")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/CONCH",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def uni(hf_token: str) -> str:
    """Download and return the local path to the UNI model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "UNI")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/UNI",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


__supported_extractors = {
    "CONCH": conch,
    "UNI": uni,
}


def get_ckpt_path(extractor_name: str, hf_token: str) -> str:
    """Get the local path to the checkpoint for the specified extractor."""
    if extractor_name not in __supported_extractors:
        raise ValueError(f"Extractor '{extractor_name}' is not supported.")
    return __supported_extractors[extractor_name](hf_token)
    