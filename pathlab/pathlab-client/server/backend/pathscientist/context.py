"""Runtime environment context provider.

Detects GPU, installed packages, data paths, and formats as context
for injection into agent system prompt via SDK AgentContext.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_gpu() -> str:
    """Detect available GPUs via nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            gpus = []
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpus.append(f"GPU {parts[0]}: {parts[1]} ({parts[2]} MB)")
            visible = os.environ.get("CUDA_VISIBLE_DEVICES", "all")
            return (
                f"Available GPUs ({len(gpus)}):\n"
                + "\n".join(f"  {g}" for g in gpus)
                + f"\nCUDA_VISIBLE_DEVICES: {visible}"
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check torch as fallback
    try:
        import torch
        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            gpus = [f"GPU {i}: {torch.cuda.get_device_name(i)}" for i in range(count)]
            return f"Available GPUs ({count}):\n" + "\n".join(f"  {g}" for g in gpus)
        else:
            return "No GPU available (CPU only)"
    except ImportError:
        return "GPU status: unknown (no nvidia-smi, no torch)"


def detect_packages() -> str:
    """List key ML/science packages installed."""
    key_packages = [
        "torch", "torchvision", "numpy", "scipy", "scikit-learn", "sklearn",
        "pandas", "matplotlib", "seaborn", "pillow", "opencv-python",
        "timm", "transformers", "einops", "h5py",
    ]
    installed = []
    try:
        result = subprocess.run(
            ["pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            pkg_lines = result.stdout.strip().split("\n")[2:]  # skip header
            pkg_map = {}
            for line in pkg_lines:
                parts = line.split()
                if len(parts) >= 2:
                    pkg_map[parts[0].lower()] = parts[1]

            for pkg in key_packages:
                version = pkg_map.get(pkg.lower())
                if version:
                    installed.append(f"  {pkg}=={version}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if installed:
        return "Key installed packages:\n" + "\n".join(installed)
    return "Package detection unavailable"


def detect_data_paths(data_mounts: dict[str, str] | None = None) -> str:
    """Describe available data paths."""
    if not data_mounts:
        return "No data mounts configured"

    lines = ["Data mounts:"]
    for host_path, container_path in data_mounts.items():
        exists = Path(host_path).exists()
        if Path(host_path).is_dir():
            try:
                count = len(list(Path(host_path).iterdir()))
                lines.append(f"  {container_path} → {host_path} ({count} items)")
            except PermissionError:
                lines.append(f"  {container_path} → {host_path} (permission denied)")
        elif Path(host_path).is_file():
            size = Path(host_path).stat().st_size
            lines.append(f"  {container_path} → {host_path} ({size} bytes)")
        else:
            lines.append(f"  {container_path} → {host_path} (NOT FOUND)")
    return "\n".join(lines)


def detect_hf_model_cache() -> str:
    """List pathology-relevant models already present in HF_HOME cache.

    Surfaces the fact that UNI / CONCH / Virchow / etc. are pre-downloaded
    and can be loaded offline — without this, the agent reads the
    'no network access' rule and concludes pathology FMs are unusable,
    falling back to ImageNet baselines.
    """
    home = os.path.expanduser("~")
    hf_home = os.environ.get("HF_HOME", f"{home}/.cache/huggingface")
    hub_dir = Path(hf_home) / "hub"

    if not hub_dir.is_dir():
        return (
            f"HuggingFace cache: {hub_dir} (not present)\n"
            "  No pre-cached models detected. Loading UNI/CONCH/Virchow "
            "from the internet would require network access and will "
            "likely fail in the sandbox."
        )

    # Curated list of pathology FM repo prefixes we know about, in
    # preference order (from the patch_classification / feature_extraction
    # skill YAMLs). Anything not in this list is noise we don't need to
    # surface (e.g. random text LLMs in the same cache).
    pathology_repo_markers = [
        ("MahmoodLab/UNI2-h", "UNI2"),
        ("MahmoodLab/uni", "UNI"),
        ("MahmoodLab/conch", "CONCH"),
        ("paige-ai/Virchow2", "Virchow2"),
        ("paige-ai/Virchow", "Virchow"),
        ("bioptimus/H-optimus-1", "H-Optimus-1"),
        ("bioptimus/H-optimus-0", "H-Optimus-0"),
        ("owkin/phikon-v2", "Phikon2"),
        ("owkin/phikon", "Phikon"),
        ("histai/hibou-L", "Hibou-L"),
    ]

    cached: list[str] = []
    try:
        dir_names = {d.name for d in hub_dir.iterdir() if d.is_dir()}
    except PermissionError:
        dir_names = set()

    for repo, nick in pathology_repo_markers:
        marker = "models--" + repo.replace("/", "--")
        if any(d.lower() == marker.lower() for d in dir_names):
            cached.append(f"  - {nick} ({repo})")

    if not cached:
        return (
            f"HuggingFace cache: {hub_dir}\n"
            "  No pathology foundation models detected in the local cache.\n"
            "  The sandbox blocks network; avoid extractors that would "
            "need a fresh download. ImageNet backbones bundled with timm "
            "(resnet50, vit_large_patch16_224, etc.) stay usable."
        )

    return (
        f"Pre-cached HuggingFace models (loadable OFFLINE, no network needed):\n"
        + "\n".join(cached)
        + f"\n  Cache location: {hub_dir} (HF_HOME={hf_home})\n"
        "  Load via common/extractors/registry.get_extractor(name), timm.create_model(..., pretrained=True), "
        "or transformers.AutoModel.from_pretrained(...). The cache is bind-mounted into "
        "the sandbox; these loads work without network access."
    )


def detect_common_libs() -> str:
    """Describe what the common/ template library provides."""
    return (
        "PathLab common/ library (available via PYTHONPATH):\n"
        "  - extractors/: Pre-trained feature extractors (UNI, CONCH, Virchow, Phikon, etc.)\n"
        "  - aggregators/: MIL aggregators (ABMIL, CLAM, TransMIL, DSMIL, etc.)\n"
        "  - dataset.py, feature_dataset.py: Data loading utilities\n"
        "  - loss.py: Loss functions (CrossEntropy, focal, label smoothing)\n"
        "  - metrics.py: Evaluation metrics (AUC, accuracy, F1, etc.)\n"
        "  - utils.py: Logging, checkpointing, result saving"
    )


def build_environment_context(
    data_mounts: dict[str, str] | None = None,
    gpu_ids: list[str] | None = None,
    include_common_libs: bool = True,
) -> str:
    """Build full environment context string for system prompt injection."""
    sections = []

    # GPU
    if gpu_ids:
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(gpu_ids)
    sections.append(detect_gpu())

    # Packages
    sections.append(detect_packages())

    # Data
    sections.append(detect_data_paths(data_mounts))

    # Pre-cached HuggingFace models (pathology FMs)
    sections.append(detect_hf_model_cache())

    # Common libs
    if include_common_libs:
        sections.append(detect_common_libs())

    return "\n\n".join(sections)
