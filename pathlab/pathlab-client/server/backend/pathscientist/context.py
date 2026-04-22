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

    # Curated list of (hf_repo, display_name, registry_key).
    # registry_key is the exact string to pass to
    # common.extractors.registry.get_extractor(...). Mismatches between
    # display name and registry key bit us in session_9df3fa411bbf
    # (2026-04-22), where the agent wrote
    # AutoModel.from_pretrained("MahmoodLab/UNI2-h") and got
    # "Unrecognized model in MahmoodLab/UNI2-h" from transformers because
    # UNI2's config has no standard `model_type` — it loads via timm
    # with custom kwargs + a local state_dict. Only the registry path
    # works for every entry; do NOT suggest AutoModel or bare
    # timm.create_model(..., pretrained=True) for these.
    pathology_repo_markers = [
        ("MahmoodLab/UNI2-h",     "UNI2",        "uni2"),
        ("MahmoodLab/uni",        "UNI",         "uni"),
        ("MahmoodLab/conch",      "CONCH",       "conch"),
        ("paige-ai/Virchow2",     "Virchow2",    "virchow2"),
        ("paige-ai/Virchow",      "Virchow",     "virchow"),
        ("bioptimus/H-optimus-1", "H-Optimus-1", "H-Optimus-1"),
        ("bioptimus/H-optimus-0", "H-Optimus-0", "H-Optimus-0"),
        ("owkin/phikon-v2",       "Phikon2",     "phikon2"),
        ("owkin/phikon",          "Phikon",      "phikon"),
    ]

    cached: list[tuple[str, str]] = []
    try:
        dir_names = {d.name for d in hub_dir.iterdir() if d.is_dir()}
    except PermissionError:
        dir_names = set()

    for repo, display, key in pathology_repo_markers:
        marker = "models--" + repo.replace("/", "--")
        if any(d.lower() == marker.lower() for d in dir_names):
            cached.append((display, key))

    if not cached:
        return (
            f"HuggingFace cache: {hub_dir}\n"
            "  No pathology foundation models detected in the local cache.\n"
            "  The sandbox blocks network; avoid extractors that would "
            "need a fresh download. ImageNet backbones bundled with timm "
            "(resnet50, vit_large_patch16_224, etc.) stay usable."
        )

    lines = [
        "Pre-cached pathology foundation models (loadable OFFLINE — no network needed):",
    ]
    for display, key in cached:
        lines.append(f'  - {display:<12}  get_extractor("{key}")')

    lines.append(f"  Cache: {hub_dir}  (HF_HOME={hf_home})")
    lines.append("")
    lines.append(
        "Load ONLY via common/extractors/registry.get_extractor(key). Do NOT use"
    )
    lines.append(
        "  AutoModel.from_pretrained / bare timm.create_model(..., pretrained=True)"
    )
    lines.append(
        "  for these — UNI2/CONCH/Virchow use custom configs + local state_dict"
    )
    lines.append(
        "  loads that the generic HuggingFace loaders cannot dispatch."
    )
    lines.append("")
    lines.append("Canonical usage:")
    lines.append("  import os")
    lines.append("  from common.extractors.registry import get_extractor")
    lines.append('  extractor = get_extractor("uni2", hf_token=os.getenv("HF_TOKEN", ""))')
    lines.append("  extractor.eval().cuda()")
    lines.append("  feats = extractor(patch_tensor)   # (B, D) D=extractor.output_dim")
    lines.append("  # preprocessing transforms: extractor.get_transforms()")
    lines.append("")
    lines.append(
        "HF_TOKEN: Mahmood Lab gated repos (UNI, UNI2, CONCH) require a token;"
    )
    lines.append(
        '  if not set, UNI2 init will error. If HF_TOKEN is unavailable in the'
    )
    lines.append(
        "  sandbox, prefer Virchow2 / Phikon2 / H-Optimus-1 — they do not gate."
    )
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

    # Pre-cached HuggingFace models (pathology FMs)
    sections.append(detect_hf_model_cache())

    # Common libs
    if include_common_libs:
        sections.append(detect_common_libs())

    return "\n\n".join(sections)
