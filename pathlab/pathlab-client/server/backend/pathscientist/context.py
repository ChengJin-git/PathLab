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


def detect_hf_model_cache(ckpts_root: "Path | None" = None) -> str:
    """List feature extractors with a usable local checkpoint.

    Truth source is the same resolver used by
    ``checkpoint_manager.get_ckpt_path``: first the PathLab checkpoint root
    (``PATHLAB_CKPT_DIR`` or bundled ``common/extractors/checkpoints``), then
    local Hugging Face snapshots under ``HF_HOME``/``HUGGINGFACE_HUB_CACHE``.

    Pass ``ckpts_root`` to point at a different checkpoints directory
    (used by tests to fake the inventory). When ``None`` (default) the
    function scans the real
    ``domain/templates/common/extractors/checkpoints/`` sibling tree.

    Motivated by session_9df3fa411bbf (2026-04-22), where the agent wrote
    ``AutoModel.from_pretrained("MahmoodLab/UNI2-h")`` and got
    ``Unrecognized model ...`` because UNI2 needs a timm+custom-kwargs
    load, not the generic HuggingFace AutoModel dispatch. The fix is to
    list each extractor with its exact ``get_extractor(key)`` call, based
    on whether a real checkpoint is actually on disk where the registry
    expects it.
    """
    extractors = [
        ("UNI2",         "UNI2",         "uni2"),
        ("UNI",          "UNI",          "uni"),
        ("CONCH",        "CONCH",        "conch"),
        ("CONCH15",      "CONCH 1.5",    "conch15"),
        ("Virchow2",     "Virchow2",     "virchow2"),
        ("Virchow",      "Virchow",      "virchow"),
        ("H-Optimus-1",  "H-Optimus-1",  "H-Optimus-1"),
        ("H-Optimus-0",  "H-Optimus-0",  "H-Optimus-0"),
        ("Phikon2",      "Phikon2",      "phikon2"),
        ("Phikon",       "Phikon",       "phikon"),
        ("mSTAR",        "mSTAR",        "mSTAR"),
        ("GPFM",         "GPFM",         "GPFM"),
        ("PathoCLIP",    "PathoCLIP",    "patho_clip"),
        ("OpenMidnight", "OpenMidnight", "openmidnight"),
        ("PLIP",         "PLIP",         "plip"),
        ("SmartCCS",     "SmartCCS",     "SmartCCS"),
        ("SmartCyto",    "SmartCyto",    "SmartCyto"),
        ("CytoFM",       "CytoFM",       "CytoFM"),
    ]

    usable: list[tuple[str, str, str]] = []     # (display, key, size)
    missing: list[tuple[str, str]] = []         # (display, key) — dir present but no ckpt

    if ckpts_root is not None and ckpts_root.is_dir():
        for dir_name, display, key in extractors:
            d = ckpts_root / dir_name
            if not d.is_dir():
                continue
            ckpt = _find_extractor_checkpoint(d)
            if ckpt is None:
                missing.append((display, key))
                continue
            try:
                size = ckpt.stat().st_size  # follows symlink by default
            except OSError:
                missing.append((display, key))
                continue
            if size < 1_000_000:     # <1MB ⇒ almost certainly a stub / LFS pointer
                missing.append((display, key))
                continue
            usable.append((display, key, _format_size(size)))
    elif ckpts_root is None:
        try:
            from .domain.templates.common.extractors.checkpoint_manager import get_ckpt_path
        except ImportError:
            from domain.templates.common.extractors.checkpoint_manager import get_ckpt_path

        manager_names = {
            "UNI2": "UNI2",
            "UNI": "UNI",
            "CONCH": "CONCH",
            "CONCH15": "CONCH15",
            "Virchow2": "Virchow2",
            "Virchow": "Virchow",
            "H-Optimus-1": "H-Optimus-1",
            "H-Optimus-0": "H-Optimus-0",
            "Phikon2": "Phikon2",
            "Phikon": "Phikon",
            "mSTAR": "mSTAR",
            "GPFM": "GPFM",
            "PathoCLIP": "PathoCLIP",
            "OpenMidnight": "OpenMidnight",
            "PLIP": "PLIP",
            "SmartCCS": "SmartCCS",
            "SmartCyto": "SmartCyto",
            "CytoFM": "CytoFM",
        }
        old_offline = os.environ.get("HF_HUB_OFFLINE")
        old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            for dir_name, display, key in extractors:
                try:
                    resolved = Path(get_ckpt_path(manager_names[dir_name], ""))
                    ckpt = _find_extractor_checkpoint(resolved) if resolved.is_dir() else resolved
                    size = ckpt.stat().st_size
                    if size < 1_000_000:
                        missing.append((display, key))
                        continue
                    usable.append((display, key, _format_size(size)))
                except Exception:
                    missing.append((display, key))
        finally:
            if old_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = old_offline
            if old_transformers_offline is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline

    if ckpts_root is None:
        ckpts_root = Path(__file__).parent / "domain" / "templates" / "common" / "extractors" / "checkpoints"

    if not usable:
        return (
            f"Extractor checkpoints: {ckpts_root} (none usable)\n"
            "  No pathology foundation model checkpoints are installed. "
            "Adding a working ckpt symlink under checkpoints/<Name>/ would "
            "unlock get_extractor(key); without one, only timm ImageNet "
            "backbones (resnet50, vit_large_patch16_224, ...) remain."
        )

    lines = [
        "Pre-installed pathology foundation models (loadable OFFLINE via registry):",
    ]
    width = max(len(d) for d, _, _ in usable)
    for display, key, size in usable:
        lines.append(f'  - {display:<{width}}  get_extractor("{key}")   [{size}]')
    lines.append(f"  Checkpoints: {ckpts_root}")
    if missing:
        lines.append(
            "  Not currently installed (calling get_extractor on these will fail): "
            + ", ".join(f'{d}/"{k}"' for d, k in missing)
        )
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
        "  loads that the generic HuggingFace loaders cannot dispatch (you will"
    )
    lines.append(
        "  get `ValueError: Unrecognized model in <repo>` and fall back to an"
    )
    lines.append(
        "  ImageNet backbone you should not have chosen)."
    )
    lines.append("")
    lines.append("Canonical usage:")
    lines.append("  from common.extractors.registry import get_extractor")
    lines.append('  extractor = get_extractor("uni2")')
    lines.append("  extractor.eval().cuda()")
    lines.append("  feats = extractor(patch_tensor)   # (B, D) D=extractor.output_dim")
    lines.append("  # preprocessing transforms: extractor.get_transforms()")
    return "\n".join(lines)


def _find_extractor_checkpoint(ckpt_dir: Path) -> Path | None:
    """Return first file/symlink in ckpt_dir that looks like a checkpoint.

    Accepts common extensions (.bin, .pth, .pt, .safetensors) and any file
    >= 1MB that resolves to an existing target. Ignores hidden dirs
    (e.g. .cache/) and the tell-tale stub sizes of Git LFS pointer files.
    """
    preferred_exts = {".bin", ".pth", ".pt", ".safetensors"}
    try:
        entries = sorted(ckpt_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return None
    candidates: list[Path] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if not entry.is_file() and not entry.is_symlink():
            continue
        if entry.suffix.lower() in preferred_exts:
            candidates.append(entry)
    # If nothing matches a known extension, fall back to any file so we at
    # least notice truly malformed installs.
    if not candidates:
        candidates = [e for e in entries if (e.is_file() or e.is_symlink()) and not e.name.startswith(".")]
    for cand in candidates:
        try:
            if cand.is_symlink() and not cand.resolve().exists():
                continue    # dangling symlink
            size = cand.stat().st_size    # follows symlink
            if size >= 1_000_000:
                return cand
        except OSError:
            continue
    return None


def _format_size(num_bytes: int) -> str:
    for unit, factor in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
        if num_bytes >= factor:
            return f"{num_bytes / factor:.1f} {unit}"
    return f"{num_bytes} B"


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

    # Pre-cached/local feature extractor weights.
    sections.append(detect_hf_model_cache())

    # Common libs
    if include_common_libs:
        sections.append(detect_common_libs())

    return "\n\n".join(sections)
