from huggingface_hub import hf_hub_download, snapshot_download
import os

# set the dir where this file is located, and create a subdir 'checkpoints' to save the downloaded checkpoints
FEATURE_EXTRACTOR_CKPT_SAVE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "checkpoints"
)
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


def uni2(hf_token: str) -> str:
    """Download and return the local path to the UNI2 model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "UNI2")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/UNI2-h",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def virchow(hf_token: str) -> str:
    """Download and return the local path to the Virchow model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "Virchow")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="paige-ai/Virchow",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def virchow2(hf_token: str) -> str:
    """Download and return the local path to the Virchow2 model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "Virchow2")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="paige-ai/Virchow2",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def plip(hf_token: str) -> str:
    """Download and return the local path to the PLIP model checkpoint.

    Downloads all files from the PLIP repository including:
    - pytorch_model.bin (model weights)
    - config.json (model configuration)
    - preprocessor_config.json (image processor configuration)
    - All other necessary files for local loading
    """
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "PLIP")
    os.makedirs(local_dir, exist_ok=True)

    # Check if repo is already downloaded (look for key config files)
    config_path = os.path.join(local_dir, "config.json")
    model_path = os.path.join(local_dir, "pytorch_model.bin")

    if not os.path.exists(config_path) or not os.path.exists(model_path):
        # Download the entire PLIP repository from Hugging Face Hub
        # This ensures all necessary files (config, processor config, tokenizer, etc.) are available
        snapshot_download(
            repo_id="vinid/plip",
            local_dir=local_dir,
            token=hf_token,
        )

    return local_dir


def phikon(hf_token: str) -> str:
    """Download and return the local path to the Phikon model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "Phikon")
    os.makedirs(local_dir, exist_ok=True)
    if not os.path.exists(os.path.join(local_dir, "config.json")):
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="owkin/phikon",
            local_dir=local_dir,
            token=hf_token,
        )
    return local_dir


def phikon2(hf_token: str) -> str:
    """Download and return the local path to the Phikon2 model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "Phikon2")
    os.makedirs(local_dir, exist_ok=True)
    if not os.path.exists(os.path.join(local_dir, "config.json")):
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="owkin/phikon-v2",
            local_dir=local_dir,
            token=hf_token,
        )
    return local_dir


def patho_clip(hf_token: str) -> str:
    """Download and return the local path to the PathoCLIP model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "PathoCLIP")
    os.makedirs(local_dir, exist_ok=True)
    if not os.path.exists(os.path.join(local_dir, "Patho-CLIP-L.pt")):
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="WenchuanZhang/Patho-CLIP-L",
            local_dir=local_dir,
            token=hf_token,
        )

    ckpt_path = os.path.join(local_dir, "Patho-CLIP-L.pt")
    return ckpt_path


def openmidnight(hf_token: str) -> str:
    """Download and return the local path to the OpenMidnight model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "OpenMidnight")
    file_name = "teacher_checkpoint_load.pt"
    os.makedirs(local_dir, exist_ok=True)
    if not os.path.exists(os.path.join(local_dir, file_name)):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="SophontAI/OpenMidnight",
            filename=file_name,
            local_dir=local_dir,
            token=hf_token,
        )
    return os.path.join(local_dir, file_name)


def conch15(hf_token: str) -> str:
    """Download and return the local path to the CONCH15 model checkpoint."""
    ckpt_filename = "pytorch_model_vision.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "CONCH15")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/conchv1_5",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def h_optimus_1(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-1 model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "H-Optimus-1")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, "pytorch_model.bin")
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="bioptimus/H-optimus-1",
            local_dir=local_dir,
            token=hf_token,
        )
    return local_dir


def h_optimus_0(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-0 model checkpoint."""
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "H-Optimus-0")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, "pytorch_model.bin")
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="bioptimus/H-optimus-0",
            local_dir=local_dir,
            token=hf_token,
        )
    return local_dir


def mstar(hf_token: str) -> str:
    """Download and return the local path to the mSTAR model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "mSTAR")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="Wangyh/mSTAR",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def gpfm(hf_token: str) -> str:
    """Download and return the local path to the GPFM model checkpoint."""
    ckpt_filename = "GPFM.pth"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "GPFM")
    os.makedirs(local_dir, exist_ok=True)
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="majiabo/GPFM",
            filename=ckpt_filename,
            local_dir=local_dir,
            token=hf_token,
        )
    return local_ckpt_path


def smartccs(hf_token: str) -> str:
    """Return the local path to the SmartCCS model checkpoint."""
    ckpt_filename = "CCS_vitl_100M.pth"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "SmartCCS")
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        raise FileNotFoundError(
            f"SmartCCS checkpoint not found at {local_ckpt_path}. "
            "Please place CCS_vitl_100M.pth in the SmartCCS checkpoints directory."
        )
    return local_ckpt_path


def smartcyto(hf_token: str) -> str:
    """Return the local path to the SmartCyto model checkpoint."""
    ckpt_filename = "smartcyto_vl.pt"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "SmartCyto")
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        raise FileNotFoundError(
            f"SmartCyto checkpoint not found at {local_ckpt_path}. "
            "Please place smartcyto_vl.pt in the SmartCyto checkpoints directory."
        )
    return local_ckpt_path


def cytofm(hf_token: str) -> str:
    """Return the local path to the CytoFM model checkpoint."""
    ckpt_filename = "vitl-16-cytofm-v1.pth"
    local_dir = os.path.join(FEATURE_EXTRACTOR_CKPT_SAVE_DIR, "CytoFM")
    local_ckpt_path = os.path.join(local_dir, ckpt_filename)
    if not os.path.exists(local_ckpt_path):
        raise FileNotFoundError(
            f"CytoFM checkpoint not found at {local_ckpt_path}. "
            "Please place vitl-16-cytofm-v1.pth in the CytoFM checkpoints directory."
        )
    return local_ckpt_path


__supported_extractors = {
    "CONCH": conch,
    "UNI": uni,
    "UNI2": uni2,
    "Virchow": virchow,
    "Virchow2": virchow2,
    "PLIP": plip,
    "Phikon": phikon,
    "Phikon2": phikon2,
    "PathoCLIP": patho_clip,
    "OpenMidnight": openmidnight,
    "CONCH15": conch15,
    "H-Optimus-1": h_optimus_1,
    "H-Optimus-0": h_optimus_0,
    "mSTAR": mstar,
    "GPFM": gpfm,
    "SmartCCS": smartccs,
    "SmartCyto": smartcyto,
    "CytoFM": cytofm,
}


def get_ckpt_path(extractor_name: str, hf_token: str) -> str:
    """Get the local path to the checkpoint for the specified extractor."""
    if extractor_name not in __supported_extractors:
        raise ValueError(f"Extractor '{extractor_name}' is not supported.")
    return __supported_extractors[extractor_name](hf_token)
