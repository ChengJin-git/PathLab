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

    # Common libs
    if include_common_libs:
        sections.append(detect_common_libs())

    return "\n\n".join(sections)
