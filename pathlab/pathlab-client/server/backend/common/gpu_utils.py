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
from typing import Tuple

import torch

logger = logging.getLogger(__name__)


class NoGPUAvailableError(Exception):
    """Raised when no GPU is available but GPU is required."""
    pass


def get_gpu_memory_info(device_index: int) -> Tuple[float, float, float]:
    """
    Get memory information for a specific GPU.

    Args:
        device_index: CUDA device index

    Returns:
        Tuple of (allocated_mb, free_mb, total_mb)
    """
    props = torch.cuda.get_device_properties(device_index)
    total_mb = props.total_memory / (1024 ** 2)
    allocated_mb = torch.cuda.memory_allocated(device_index) / (1024 ** 2)
    reserved_mb = torch.cuda.memory_reserved(device_index) / (1024 ** 2)
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
        gpu_info.append({
            "index": i,
            "name": name,
            "allocated_mb": allocated_mb,
            "free_mb": free_mb,
            "total_mb": total_mb,
        })

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
        gpu_lines.append(f"  - cuda:{i}: {name} ({free_mb:.0f}/{total_mb:.0f} MB free, {utilization:.0f}% used)")
        if free_mb > best_free:
            best_free = free_mb
            best_idx = i

    return f"**GPU Status**: {num_gpus} GPUs available (auto-selecting cuda:{best_idx} with most free VRAM)\n" + "\n".join(gpu_lines)


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
            f"VRAM available: {max_free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)"
        )
    else:
        return (
            False,
            max_free_mb,
            f"VRAM insufficient: {max_free_mb:.0f}/{total_mb:.0f} MB free (required: {min_vram_mb:.0f} MB)"
        )

