from huggingface_hub import hf_hub_download, snapshot_download
from pathlib import Path

__all__ = ["get_ckpt_path"]


def _get_ckpt_save_dir() -> Path:
    """Return the directory for extractor checkpoints.

    Uses Config.get_uploads_dir() / "extractor_checkpoints" so the files
    live outside the source tree and are never bundled by PyInstaller.
    """
    from backend.common.config import Config
    ckpt_dir = Config.get_uploads_dir() / "extractor_checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    return ckpt_dir


def conch(hf_token: str) -> str:
    """Download and return the local path to the CONCH model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "CONCH"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/CONCH",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def uni(hf_token: str) -> str:
    """Download and return the local path to the UNI model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "UNI"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/UNI",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def uni2(hf_token: str) -> str:
    """Download and return the local path to the UNI2 model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "UNI2"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/UNI2-h",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def virchow(hf_token: str) -> str:
    """Download and return the local path to the Virchow model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "Virchow"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="paige-ai/Virchow",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def virchow2(hf_token: str) -> str:
    """Download and return the local path to the Virchow2 model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "Virchow2"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="paige-ai/Virchow2",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def plip(hf_token: str) -> str:
    """Download and return the local path to the PLIP model checkpoint.

    Downloads all files from the PLIP repository including:
    - pytorch_model.bin (model weights)
    - config.json (model configuration)
    - preprocessor_config.json (image processor configuration)
    - All other necessary files for local loading
    """
    local_dir = _get_ckpt_save_dir() / "PLIP"
    local_dir.mkdir(parents=True, exist_ok=True)

    # Check if repo is already downloaded (look for key config files)
    config_path = local_dir / "config.json"
    model_path = local_dir / "pytorch_model.bin"

    if not config_path.exists() or not model_path.exists():
        # Download the entire PLIP repository from Hugging Face Hub
        # This ensures all necessary files (config, processor config, tokenizer, etc.) are available
        snapshot_download(
            repo_id="vinid/plip",
            local_dir=str(local_dir),
            token=hf_token,
        )

    return str(local_dir)


def phikon(hf_token: str) -> str:
    """Download and return the local path to the Phikon model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "Phikon"
    local_dir.mkdir(parents=True, exist_ok=True)
    if not (local_dir / "config.json").exists():
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="owkin/phikon",
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir)


def phikon2(hf_token: str) -> str:
    """Download and return the local path to the Phikon2 model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "Phikon2"
    local_dir.mkdir(parents=True, exist_ok=True)
    if not (local_dir / "config.json").exists():
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="owkin/phikon-v2",
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir)


def patho_clip(hf_token: str) -> str:
    """Download and return the local path to the PathoCLIP model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "PathoCLIP"
    local_dir.mkdir(parents=True, exist_ok=True)
    if not (local_dir / "Patho-CLIP-L.pt").exists():
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="WenchuanZhang/Patho-CLIP-L",
            local_dir=str(local_dir),
            token=hf_token,
        )

    ckpt_path = local_dir / "Patho-CLIP-L.pt"
    return str(ckpt_path)


def openmidnight(hf_token: str) -> str:
    """Download and return the local path to the OpenMidnight model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "OpenMidnight"
    file_name = "teacher_checkpoint_load.pt"
    local_dir.mkdir(parents=True, exist_ok=True)
    if not (local_dir / file_name).exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="SophontAI/OpenMidnight",
            filename=file_name,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir / file_name)


def conch15(hf_token: str) -> str:
    """Download and return the local path to the CONCH15 model checkpoint."""
    ckpt_filename = "pytorch_model_vision.bin"
    local_dir = _get_ckpt_save_dir() / "CONCH15"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="MahmoodLab/conchv1_5",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def h_optimus_1(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-1 model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "H-Optimus-1"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / "pytorch_model.bin"
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="bioptimus/H-optimus-1",
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir)


def h_optimus_0(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-0 model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "H-Optimus-0"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / "pytorch_model.bin"
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        snapshot_download(
            repo_id="bioptimus/H-optimus-0",
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir)


def mstar(hf_token: str) -> str:
    """Download and return the local path to the mSTAR model checkpoint."""
    ckpt_filename = "pytorch_model.bin"
    local_dir = _get_ckpt_save_dir() / "mSTAR"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="Wangyh/mSTAR",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def gpfm(hf_token: str) -> str:
    """Download and return the local path to the GPFM model checkpoint."""
    ckpt_filename = "GPFM.pth"
    local_dir = _get_ckpt_save_dir() / "GPFM"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        # Download the checkpoint from Hugging Face Hub
        hf_hub_download(
            repo_id="majiabo/GPFM",
            filename=ckpt_filename,
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_ckpt_path)


def smartccs(hf_token: str) -> str:
    """Return the local path to the SmartCCS model checkpoint."""
    ckpt_filename = "CCS_vitl_100M.pth"
    local_dir = _get_ckpt_save_dir() / "SmartCCS"
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        raise FileNotFoundError(
            f"SmartCCS checkpoint not found at {local_ckpt_path}. "
            f"Please place CCS_vitl_100M.pth in {local_dir}."
        )
    return str(local_ckpt_path)


def smartcyto(hf_token: str) -> str:
    """Return the local path to the SmartCyto model checkpoint."""
    ckpt_filename = "smartcyto_vl.pt"
    local_dir = _get_ckpt_save_dir() / "SmartCyto"
    local_ckpt_path = local_dir / ckpt_filename
    if not local_ckpt_path.exists():
        raise FileNotFoundError(
            f"SmartCyto checkpoint not found at {local_ckpt_path}. "
            f"Please place smartcyto_vl.pt in {local_dir}."
        )
    return str(local_ckpt_path)


def kronos(hf_token: str) -> str:
    """Download and return the local directory for the KRONOS model checkpoint."""
    local_dir = _get_ckpt_save_dir() / "KRONOS"
    local_dir.mkdir(parents=True, exist_ok=True)
    if not (local_dir / "kronos_vits16_model.pt").exists():
        snapshot_download(
            repo_id="MahmoodLab/KRONOS",
            local_dir=str(local_dir),
            token=hf_token,
        )
    return str(local_dir)


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
    "KRONOS": kronos,
}


def get_ckpt_path(extractor_name: str, hf_token: str) -> str:
    """Get the local path to the checkpoint for the specified extractor."""
    if extractor_name not in __supported_extractors:
        raise ValueError(f"Extractor '{extractor_name}' is not supported.")
    return __supported_extractors[extractor_name](hf_token)
