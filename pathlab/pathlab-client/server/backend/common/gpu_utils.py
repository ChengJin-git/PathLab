"""
GPU Device Selection Utilities

Provides automatic GPU selection with the following behavior:
1. If no GPU is available, raise an error (CPU mode not supported)
2. If multiple GPUs are available, select the one with the least VRAM usage

Usage:
    from backend.common.gpu_utils import get_optimal_device

    device = get_optimal_device()  # Returns torch.device("cuda:X")
"""

import logging
import os
import threading
import time
from typing import Tuple, Any, cast

import torch

logger = logging.getLogger(__name__)

# Try to import pynvml (from nvidia-ml-py package) for system-level GPU memory info
_nvml_available = False
try:
    import pynvml

    pynvml.nvmlInit()
    _nvml_available = True
    logger.info(
        "pynvml (nvidia-ml-py) initialized successfully - using system-level GPU memory detection"
    )
except Exception as e:
    logger.warning(
        f"pynvml not available ({e}), falling back to PyTorch memory detection"
    )

_cuda_to_nvml_handle: dict[int, Any] = {}

_RESERVATION_TTL_SEC: float = 600.0
_vram_reservation_lock = threading.Lock()
_vram_reservations: list[tuple[float, int, float]] = []  # (expiry, cuda_idx, mb)


def _get_pynvml() -> Any:
    return cast(Any, globals().get("pynvml"))


def _normalize_uuid(uuid_str: str) -> str:
    """Strip GPU-/MIG- prefixes so torch and pynvml UUIDs can be compared.

    torch.cuda.get_device_properties().uuid → bare UUID (no prefix)
    pynvml.nvmlDeviceGetUUID()             → "GPU-<uuid>" or "MIG-<uuid>"
    """
    s = str(uuid_str).lower()
    for prefix in ("mig-gpu-", "mig-", "gpu-"):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def _get_visible_physical_gpu_indices(nvml_count: int) -> list[int]:
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not visible_devices:
        return list(range(nvml_count))

    indices: list[int] = []
    for token in visible_devices.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            physical_idx = int(token)
        except ValueError:
            return list(range(nvml_count))
        if 0 <= physical_idx < nvml_count:
            indices.append(physical_idx)
    return indices


def _get_physical_gpu_index_for_logical_index(
    logical_index: int, nvml_count: int
) -> int | None:
    visible_indices = _get_visible_physical_gpu_indices(nvml_count)
    if logical_index < 0 or logical_index >= len(visible_indices):
        return None
    return visible_indices[logical_index]


def _add_vram_reservation(cuda_idx: int, mb: float) -> None:
    with _vram_reservation_lock:
        _vram_reservations.append(
            (time.monotonic() + _RESERVATION_TTL_SEC, cuda_idx, mb)
        )


def _get_pending_reserved_mb(cuda_idx: int) -> float:
    now = time.monotonic()
    with _vram_reservation_lock:
        active = [(exp, idx, m) for exp, idx, m in _vram_reservations if exp > now]
        _vram_reservations[:] = active
        return sum(m for exp, idx, m in active if idx == cuda_idx)


def _get_nvml_handle_for_cuda_device(cuda_index: int) -> Any:
    """
    Resolve a CUDA logical device index to its pynvml handle via UUID matching.

    nvmlDeviceGetHandleByIndex uses physical GPU indices, which diverge from CUDA
    logical indices whenever CUDA_VISIBLE_DEVICES skips a GPU (e.g. "0,1,3" makes
    CUDA:2 point to physical GPU 3, but nvml index 2 still means physical GPU 2).
    UUID matching is the only reliable cross-API bridge.
    """
    if cuda_index in _cuda_to_nvml_handle:
        return _cuda_to_nvml_handle[cuda_index]

    pynvml_mod = _get_pynvml()
    if pynvml_mod is None:
        raise RuntimeError("pynvml is not available")

    cuda_uuid = torch.cuda.get_device_properties(cuda_index).uuid
    cuda_uuid_normalized = _normalize_uuid(str(cuda_uuid))
    num_nvml = pynvml_mod.nvmlDeviceGetCount()
    for i in range(num_nvml):
        handle = pynvml_mod.nvmlDeviceGetHandleByIndex(i)
        if (
            _normalize_uuid(pynvml_mod.nvmlDeviceGetUUID(handle))
            == cuda_uuid_normalized
        ):
            _cuda_to_nvml_handle[cuda_index] = handle
            logger.debug(
                f"CUDA:{cuda_index} → physical GPU {i} (UUID {cuda_uuid_normalized[:24]}…) cached"
            )
            return handle

    raise RuntimeError(
        f"No pynvml device matched CUDA:{cuda_index} (UUID={cuda_uuid}). "
        f"Searched {num_nvml} physical GPU(s)."
    )


class NoGPUAvailableError(Exception):
    """Raised when no GPU is available but GPU is required."""

    pass


def get_gpu_memory_info(device_index: int) -> Tuple[float, float, float]:
    """
    Get memory information for a specific GPU.

    Uses pynvml (from nvidia-ml-py, NVIDIA Management Library) if available to get system-level
    memory usage (includes all processes). Falls back to PyTorch APIs which
    only track the current process.

    Args:
        device_index: CUDA device index

    Returns:
        Tuple of (used_mb, free_mb, total_mb)
        Note: First element is 'used_mb' when using pynvml, 'allocated_mb' when using PyTorch
    """
    if _nvml_available:
        try:
            handle = _get_nvml_handle_for_cuda_device(device_index)
            pynvml_mod = _get_pynvml()
            if pynvml_mod is None:
                raise RuntimeError("pynvml is not available")
            info = pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
            total_mb = float(info.total) / (1024**2)
            used_mb = float(info.used) / (1024**2)
            free_mb = float(info.free) / (1024**2)
            return (used_mb, free_mb, total_mb)
        except Exception as e:
            logger.warning(
                f"pynvml failed for GPU {device_index}: {e}, falling back to PyTorch"
            )

    # Fallback to PyTorch (only tracks current process)
    props = torch.cuda.get_device_properties(device_index)
    total_mb = props.total_memory / (1024**2)
    allocated_mb = torch.cuda.memory_allocated(device_index) / (1024**2)
    reserved_mb = torch.cuda.memory_reserved(device_index) / (1024**2)
    # Free = Total - Reserved (reserved includes allocated + cached)
    free_mb = total_mb - reserved_mb

    return (allocated_mb, free_mb, total_mb)


def get_optimal_device() -> torch.device:
    """
    Get the optimal GPU device for computation.

    Behavior:
    1. If no GPU is available, raises NoGPUAvailableError
    2. If single GPU, returns cuda:0
    3. If multiple GPUs, returns the one with the most free VRAM

    Returns:
        torch.device: The optimal CUDA device

    Raises:
        NoGPUAvailableError: If no GPU is available
    """
    if not torch.cuda.is_available():
        raise NoGPUAvailableError(
            "No GPU available. This application requires a CUDA-capable GPU. "
            "Please ensure you have a compatible NVIDIA GPU and CUDA drivers installed."
        )

    num_gpus = torch.cuda.device_count()

    if num_gpus == 1:
        device = torch.device("cuda:0")
        name = torch.cuda.get_device_name(0)
        _, free_mb, total_mb = get_gpu_memory_info(0)
        logger.info(f"Using GPU: {name} ({free_mb:.0f}/{total_mb:.0f} MB free)")
        return device

    # Multiple GPUs: find the one with most free VRAM
    best_device_idx = 0
    best_free_mb = 0

    gpu_info = []
    for i in range(num_gpus):
        name = torch.cuda.get_device_name(i)
        allocated_mb, free_mb, total_mb = get_gpu_memory_info(i)
        gpu_info.append(
            {
                "index": i,
                "name": name,
                "allocated_mb": allocated_mb,
                "free_mb": free_mb,
                "total_mb": total_mb,
            }
        )

        if free_mb > best_free_mb:
            best_free_mb = free_mb
            best_device_idx = i

    # Log all GPU info
    logger.info(f"Found {num_gpus} GPUs:")
    for info in gpu_info:
        marker = " <-- selected" if info["index"] == best_device_idx else ""
        logger.info(
            f"  cuda:{info['index']}: {info['name']} - "
            f"{info['free_mb']:.0f}/{info['total_mb']:.0f} MB free{marker}"
        )

    device = torch.device(f"cuda:{best_device_idx}")
    return device


def get_device_string() -> str:
    """
    Get the optimal device as a string (e.g., "cuda:0").

    This is a convenience function for code that expects a string device.

    Returns:
        str: Device string like "cuda:0"

    Raises:
        NoGPUAvailableError: If no GPU is available
    """
    return str(get_optimal_device())


def ensure_gpu_available() -> None:
    """
    Ensure that at least one GPU is available.

    Call this at application startup to fail fast if no GPU is present.

    Raises:
        NoGPUAvailableError: If no GPU is available
    """
    if not torch.cuda.is_available():
        raise NoGPUAvailableError(
            "No GPU available. This application requires a CUDA-capable GPU. "
            "Please ensure you have a compatible NVIDIA GPU and CUDA drivers installed."
        )

    num_gpus = torch.cuda.device_count()
    logger.info(f"GPU check passed: {num_gpus} GPU(s) available")
    for i in range(num_gpus):
        name = torch.cuda.get_device_name(i)
        _, free_mb, total_mb = get_gpu_memory_info(i)
        logger.info(f"  cuda:{i}: {name} ({free_mb:.0f}/{total_mb:.0f} MB free)")


def get_gpu_summary_for_prompt() -> str:
    """
    Get a human-readable GPU summary for inclusion in system prompts.

    Returns:
        str: A formatted string describing GPU availability and status
    """
    if not torch.cuda.is_available():
        return "**GPU Status**: No GPU available - training and inference will fail"

    num_gpus = torch.cuda.device_count()

    if num_gpus == 1:
        name = torch.cuda.get_device_name(0)
        _, free_mb, total_mb = get_gpu_memory_info(0)
        utilization = ((total_mb - free_mb) / total_mb) * 100
        return f"**GPU Status**: ✅ {name} ({free_mb:.0f}/{total_mb:.0f} MB free, {utilization:.0f}% used)"

    # Multiple GPUs
    gpu_lines = []
    best_idx = 0
    best_free = 0

    for i in range(num_gpus):
        name = torch.cuda.get_device_name(i)
        _, free_mb, total_mb = get_gpu_memory_info(i)
        utilization = ((total_mb - free_mb) / total_mb) * 100
        gpu_lines.append(
            f"  - cuda:{i}: {name} ({free_mb:.0f}/{total_mb:.0f} MB free, {utilization:.0f}% used)"
        )
        if free_mb > best_free:
            best_free = free_mb
            best_idx = i

    return (
        f"**GPU Status**: {num_gpus} GPUs available (auto-selecting cuda:{best_idx} with most free VRAM)\n"
        + "\n".join(gpu_lines)
    )


def is_gpu_healthy(gpu_index: int) -> bool:
    """
    Return True if gpu_index can execute a minimal CUDA kernel, False otherwise.

    torch.cuda.device_count() still lists a GPU even after a hardware failure;
    this function catches those failures by running a tiny tensor op and forcing
    a CPU sync (which surfaces asynchronous CUDA errors).
    """
    try:
        with torch.cuda.device(gpu_index):
            device = torch.device(f"cuda:{gpu_index}")
            t = torch.zeros(4, device=device)
            _ = (
                (t + 1.0).sum().item()
            )  # .item() forces CUDA sync — surfaces async errors
        return True
    except Exception as e:
        logger.warning(f"GPU {gpu_index} health check FAILED: {type(e).__name__}: {e}")
        return False


def probe_all_gpu_health() -> dict[int, bool]:
    """
    Return {gpu_index: is_healthy} for every GPU visible to this process.

    When CUDA is available, runs a tiny kernel on each device (the only way
    to surface hardware faults that torch.cuda.device_count() hides).
    When CUDA init itself failed (e.g. one faulty GPU poisoned cuInit), falls
    back to pynvml: a GPU is considered healthy if its memory info is readable.
    """
    if torch.cuda.is_available():
        num_gpus = torch.cuda.device_count()
        results: dict[int, bool] = {}
        logger.info(f"Running GPU health probe on {num_gpus} GPU(s)...")
        for i in range(num_gpus):
            healthy = is_gpu_healthy(i)
            results[i] = healthy
            name = torch.cuda.get_device_name(i)
            logger.info(f"  cuda:{i} ({name}): {'OK' if healthy else 'FAILED'}")
        bad = [i for i, ok in results.items() if not ok]
        if bad:
            logger.warning(
                f"Detected {len(bad)} unhealthy GPU(s): {['cuda:' + str(i) for i in bad]}. "
                f"These GPUs will be excluded from task scheduling."
            )
        else:
            logger.info("All GPUs passed health check.")
        return results

    if not _nvml_available:
        return {}

    try:
        pynvml_mod = _get_pynvml()
        if pynvml_mod is None:
            return {}
        visible_physical_indices = _get_visible_physical_gpu_indices(
            pynvml_mod.nvmlDeviceGetCount()
        )
        results: dict[int, bool] = {}
        logger.info(
            f"CUDA unavailable; running pynvml health probe on {len(visible_physical_indices)} visible GPU(s)..."
        )
        for logical_idx, physical_idx in enumerate(visible_physical_indices):
            try:
                handle = pynvml_mod.nvmlDeviceGetHandleByIndex(physical_idx)
                pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
                name = pynvml_mod.nvmlDeviceGetName(handle)
                results[logical_idx] = True
                logger.info(f"  cuda:{logical_idx} ({name}): OK")
            except Exception as e:
                results[logical_idx] = False
                logger.warning(f"  cuda:{logical_idx}: FAILED via pynvml — {e}")
        bad = [i for i, ok in results.items() if not ok]
        if bad:
            logger.warning(
                f"Detected {len(bad)} unhealthy GPU(s): {['cuda:' + str(i) for i in bad]}. "
                f"These GPUs will be excluded from task scheduling."
            )
        else:
            logger.info("All GPUs passed pynvml health check.")
        return results
    except Exception as e:
        logger.warning(f"pynvml GPU health probe failed: {e}")
        return {}


def get_max_available_vram_mb() -> float:
    """
    Get the maximum available VRAM across all GPUs.

    This is useful for queue-level VRAM checks to determine if any GPU
    has enough free memory to start a new task.

    Returns:
        float: Maximum free VRAM in MB across all GPUs.
               Returns 0.0 if no GPU is available.
    """
    if not torch.cuda.is_available():
        return 0.0

    num_gpus = torch.cuda.device_count()
    max_free_mb = 0.0

    for i in range(num_gpus):
        _, free_mb, _ = get_gpu_memory_info(i)
        if free_mb > max_free_mb:
            max_free_mb = free_mb

    return max_free_mb


def get_total_vram_mb() -> float:
    """
    Get the total VRAM of the GPU with the most memory.

    Returns:
        float: Total VRAM in MB of the largest GPU.
               Returns 0.0 if no GPU is available.
    """
    if not torch.cuda.is_available():
        return 0.0

    num_gpus = torch.cuda.device_count()
    max_total_mb = 0.0

    for i in range(num_gpus):
        _, _, total_mb = get_gpu_memory_info(i)
        if total_mb > max_total_mb:
            max_total_mb = total_mb

    return max_total_mb


def check_vram_available(min_vram_mb: float) -> Tuple[bool, float, str]:
    """
    Check if there's enough VRAM available to start a GPU task.

    Args:
        min_vram_mb: Minimum required free VRAM in MB

    Returns:
        Tuple of (is_available, current_free_mb, message)
        - is_available: True if enough VRAM is available
        - current_free_mb: Current maximum free VRAM across all GPUs
        - message: Human-readable status message
    """
    if not torch.cuda.is_available():
        return (False, 0.0, "No GPU available")

    max_free_mb = get_max_available_vram_mb()
    total_mb = get_total_vram_mb()

    if max_free_mb >= min_vram_mb:
        return (
            True,
            max_free_mb,
            f"VRAM available: {max_free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)",
        )
    else:
        return (
            False,
            max_free_mb,
            f"VRAM insufficient: {max_free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)",
        )


def get_gpu_count() -> int:
    """
    Get the number of available GPUs.

    Returns:
        int: Number of CUDA devices available. Returns 0 if no GPU.
    """
    if torch.cuda.is_available():
        return torch.cuda.device_count()
    # cuInit() can fail when a hardware-failed GPU poisons CUDA initialisation for
    # the whole process (CUDA_ERROR_UNKNOWN).  pynvml uses the driver API and is
    # unaffected, so fall back to it for headcount.
    if _nvml_available:
        try:
            pynvml_mod = _get_pynvml()
            if pynvml_mod is None:
                return 0
            return len(
                _get_visible_physical_gpu_indices(pynvml_mod.nvmlDeviceGetCount())
            )
        except Exception:
            pass
    return 0


def get_all_gpu_info() -> list[Any]:
    """
    Get information about all available GPUs.

    Returns:
        List of dicts with GPU info:
        [
            {
                "index": int,
                "name": str,
                "allocated_mb": float,
                "free_mb": float,
                "total_mb": float,
            },
            ...
        ]
        Returns empty list if no GPU available.
    """
    if torch.cuda.is_available():
        num_gpus = torch.cuda.device_count()
        gpu_info = []
        for i in range(num_gpus):
            name = torch.cuda.get_device_name(i)
            allocated_mb, free_mb, total_mb = get_gpu_memory_info(i)
            gpu_info.append(
                {
                    "index": i,
                    "name": name,
                    "allocated_mb": allocated_mb,
                    "free_mb": free_mb,
                    "total_mb": total_mb,
                }
            )
        return gpu_info

    # CUDA runtime unavailable — fall back to pynvml.
    # GPUs that fail the pynvml query (e.g. hardware-failed GPU 0) are silently
    # skipped; the caller's _bad_gpus filter handles any that were pre-marked.
    if not _nvml_available:
        return []
    try:
        pynvml_mod = _get_pynvml()
        if pynvml_mod is None:
            return []
        visible_physical_indices = _get_visible_physical_gpu_indices(
            pynvml_mod.nvmlDeviceGetCount()
        )
        gpu_info = []
        for logical_idx, physical_idx in enumerate(visible_physical_indices):
            try:
                handle = pynvml_mod.nvmlDeviceGetHandleByIndex(physical_idx)
                name = pynvml_mod.nvmlDeviceGetName(handle)
                mem = pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
                total_mb = float(mem.total) / (1024**2)
                free_mb = float(mem.free) / (1024**2)
                used_mb = float(mem.used) / (1024**2)
                gpu_info.append(
                    {
                        "index": logical_idx,
                        "name": name,
                        "allocated_mb": used_mb,
                        "free_mb": free_mb,
                        "total_mb": total_mb,
                    }
                )
            except Exception:
                pass  # hardware-failed GPU — skip, don't include in scheduling pool
        return gpu_info
    except Exception:
        return []


def check_gpu_vram_available(
    gpu_index: int, min_vram_mb: float
) -> Tuple[bool, float, str]:
    """
    Check if a specific GPU has enough VRAM available.

    Args:
        gpu_index: CUDA device index
        min_vram_mb: Minimum required free VRAM in MB

    Returns:
        Tuple of (is_available, current_free_mb, message)
        - is_available: True if enough VRAM is available on this GPU
        - current_free_mb: Current free VRAM on this GPU
        - message: Human-readable status message
    """
    if not torch.cuda.is_available():
        if not _nvml_available:
            return (False, 0.0, "No GPU available")
        try:
            pynvml_mod = _get_pynvml()
            if pynvml_mod is None:
                return (False, 0.0, "No GPU available")
            physical_idx = _get_physical_gpu_index_for_logical_index(
                gpu_index, pynvml_mod.nvmlDeviceGetCount()
            )
            if physical_idx is None:
                return (False, 0.0, f"Invalid GPU index: {gpu_index}")
            handle = pynvml_mod.nvmlDeviceGetHandleByIndex(physical_idx)
            mem = pynvml_mod.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml_mod.nvmlDeviceGetName(handle)
            free_mb = float(mem.free) / (1024**2)
            total_mb = float(mem.total) / (1024**2)
            ok = free_mb >= min_vram_mb
            msg = f"cuda:{gpu_index} ({name}): {free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)"
            return (ok, free_mb, msg)
        except Exception as e:
            return (False, 0.0, f"cuda:{gpu_index} unavailable: {e}")

    num_gpus = torch.cuda.device_count()
    if gpu_index < 0 or gpu_index >= num_gpus:
        return (False, 0.0, f"Invalid GPU index: {gpu_index}")

    _, free_mb, total_mb = get_gpu_memory_info(gpu_index)
    name = torch.cuda.get_device_name(gpu_index)
    ok = free_mb >= min_vram_mb
    msg = f"cuda:{gpu_index} ({name}): {free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)"
    return (ok, free_mb, msg)


def select_optimal_gpu_for_task(min_vram_mb: float = 0) -> Tuple[int, float]:
    """
    Select the optimal GPU for a new task based on current VRAM availability.

    Selects the GPU with the most free VRAM that meets the minimum requirement.

    Args:
        min_vram_mb: Minimum required free VRAM in MB (0 = no minimum)

    Returns:
        Tuple of (gpu_index, free_mb)
        - gpu_index: Index of the optimal GPU, or -1 if no suitable GPU found
        - free_mb: Free VRAM on the selected GPU
    """
    if not torch.cuda.is_available():
        return (-1, 0.0)

    num_gpus = torch.cuda.device_count()
    best_gpu_idx = -1
    best_free_mb = 0.0

    for i in range(num_gpus):
        _, raw_free_mb, _ = get_gpu_memory_info(i)
        pending = _get_pending_reserved_mb(i)
        effective_free = max(0.0, raw_free_mb - pending)
        if effective_free >= min_vram_mb and effective_free > best_free_mb:
            best_free_mb = effective_free
            best_gpu_idx = i

    if best_gpu_idx >= 0:
        _add_vram_reservation(best_gpu_idx, min_vram_mb)

    return (best_gpu_idx, best_free_mb)
