import os

from .checkpoint_resolver import (
    ModelDirSpec,
    ModelFileSpec,
    checkpoint_root,
    resolve_model_dir,
    resolve_model_file,
)

# Checkpoint directory: use env var if set, otherwise default to local 'checkpoints' subdir
FEATURE_EXTRACTOR_CKPT_SAVE_DIR = str(
    checkpoint_root()
) if os.environ.get("PATHLAB_CKPT_DIR") else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "checkpoints"
)
FEATURE_EXTRACTOR_CKPT_SAVE_DIR = os.environ.get(
    "PATHLAB_CKPT_DIR",
    FEATURE_EXTRACTOR_CKPT_SAVE_DIR,
)


__all__ = ["get_ckpt_path"]


def conch(hf_token: str) -> str:
    """Download and return the local path to the CONCH model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("CONCH", "CONCH", "MahmoodLab/CONCH", ("pytorch_model.bin",)), token=hf_token))


def uni(hf_token: str) -> str:
    """Download and return the local path to the UNI model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("UNI", "UNI", "MahmoodLab/UNI", ("pytorch_model.bin",)), token=hf_token))


def uni2(hf_token: str) -> str:
    """Download and return the local path to the UNI2 model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("UNI2", "UNI2", "MahmoodLab/UNI2-h", ("pytorch_model.bin",)), token=hf_token))


def virchow(hf_token: str) -> str:
    """Download and return the local path to the Virchow model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("Virchow", "Virchow", "paige-ai/Virchow", ("pytorch_model.bin",)), token=hf_token))


def virchow2(hf_token: str) -> str:
    """Download and return the local path to the Virchow2 model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("Virchow2", "Virchow2", "paige-ai/Virchow2", ("pytorch_model.bin", "model.safetensors")), token=hf_token))


def plip(hf_token: str) -> str:
    """Download and return the local path to the PLIP model checkpoint.

    Downloads all files from the PLIP repository including:
    - pytorch_model.bin (model weights)
    - config.json (model configuration)
    - preprocessor_config.json (image processor configuration)
    - All other necessary files for local loading
    """
    return str(resolve_model_dir(
        ModelDirSpec(
            display_name="PLIP",
            local_subdir="PLIP",
            repo_id="vinid/plip",
            required_files=("config.json", "preprocessor_config.json"),
            any_weight_files=("pytorch_model.bin", "model.safetensors"),
            optional_required_files=(
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
            ),
        ),
        token=hf_token,
    ))


def phikon(hf_token: str) -> str:
    """Download and return the local path to the Phikon model checkpoint."""
    return str(resolve_model_dir(
        ModelDirSpec(
            display_name="Phikon",
            local_subdir="Phikon",
            repo_id="owkin/phikon",
            required_files=("config.json", "preprocessor_config.json"),
            any_weight_files=("pytorch_model.bin", "model.safetensors"),
        ),
        token=hf_token,
    ))


def phikon2(hf_token: str) -> str:
    """Download and return the local path to the Phikon2 model checkpoint."""
    return str(resolve_model_dir(
        ModelDirSpec(
            display_name="Phikon2",
            local_subdir="Phikon2",
            repo_id="owkin/phikon-v2",
            required_files=("config.json", "preprocessor_config.json"),
            any_weight_files=("pytorch_model.bin", "model.safetensors"),
        ),
        token=hf_token,
    ))


def patho_clip(hf_token: str) -> str:
    """Download and return the local path to the PathoCLIP model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("PathoCLIP", "PathoCLIP", "WenchuanZhang/Patho-CLIP-L", ("Patho-CLIP-L.pt",)), token=hf_token))


def openmidnight(hf_token: str) -> str:
    """Download and return the local path to the OpenMidnight model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("OpenMidnight", "OpenMidnight", "SophontAI/OpenMidnight", ("teacher_checkpoint_load.pt",)), token=hf_token))


def conch15(hf_token: str) -> str:
    """Download and return the local path to the CONCH15 model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("CONCH15", "CONCH15", "MahmoodLab/conchv1_5", ("pytorch_model_vision.bin",)), token=hf_token))


def h_optimus_1(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-1 model checkpoint."""
    return str(resolve_model_dir(
        ModelDirSpec(
            display_name="H-Optimus-1",
            local_subdir="H-Optimus-1",
            repo_id="bioptimus/H-optimus-1",
            required_files=("config.json",),
            any_weight_files=("pytorch_model.bin", "model.safetensors"),
        ),
        token=hf_token,
    ))


def h_optimus_0(hf_token: str) -> str:
    """Download and return the local path to the H-Optimus-0 model checkpoint."""
    return str(resolve_model_dir(
        ModelDirSpec(
            display_name="H-Optimus-0",
            local_subdir="H-Optimus-0",
            repo_id="bioptimus/H-optimus-0",
            required_files=("config.json",),
            any_weight_files=("pytorch_model.bin", "model.safetensors"),
        ),
        token=hf_token,
    ))


def mstar(hf_token: str) -> str:
    """Download and return the local path to the mSTAR model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("mSTAR", "mSTAR", "Wangyh/mSTAR", ("pytorch_model.bin",)), token=hf_token))


def gpfm(hf_token: str) -> str:
    """Download and return the local path to the GPFM model checkpoint."""
    return str(resolve_model_file(ModelFileSpec("GPFM", "GPFM", "majiabo/GPFM", ("GPFM.pth",)), token=hf_token))


def smartccs(hf_token: str) -> str:
    """Return the local path to the SmartCCS model checkpoint."""
    ckpt_filename = "CCS_vitl_100M.pth"
    local_ckpt_path = checkpoint_root() / "SmartCCS" / ckpt_filename
    if not local_ckpt_path.exists():
        raise FileNotFoundError(
            f"SmartCCS checkpoint not found at {local_ckpt_path}. "
            "Please place CCS_vitl_100M.pth in the SmartCCS checkpoints directory."
        )
    return str(local_ckpt_path)


def smartcyto(hf_token: str) -> str:
    """Return the local path to the SmartCyto model checkpoint."""
    ckpt_filename = "smartcyto_vl.pt"
    local_ckpt_path = checkpoint_root() / "SmartCyto" / ckpt_filename
    if not local_ckpt_path.exists():
        raise FileNotFoundError(
            f"SmartCyto checkpoint not found at {local_ckpt_path}. "
            "Please place smartcyto_vl.pt in the SmartCyto checkpoints directory. "
            "This loader may also require a runtime timm version with DINOv3 support."
        )
    return str(local_ckpt_path)


def cytofm(hf_token: str) -> str:
    """Return the local path to the CytoFM model checkpoint."""
    ckpt_filename = "vitl-16-cytofm-v1.pth"
    local_ckpt_path = checkpoint_root() / "CytoFM" / ckpt_filename
    if not local_ckpt_path.exists():
        raise FileNotFoundError(
            f"CytoFM checkpoint not found at {local_ckpt_path}. "
            "Please place vitl-16-cytofm-v1.pth in the CytoFM checkpoints directory."
        )
    return str(local_ckpt_path)


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
