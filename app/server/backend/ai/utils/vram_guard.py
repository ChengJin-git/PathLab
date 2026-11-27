"""
VRAM Guard - GPU memory protection for batch processing.

This module provides runtime VRAM protection to prevent OOM (Out of Memory) errors
that could crash the system when users specify excessively large batch sizes.

The protection mechanism is based on ACTUAL MEASUREMENT, not estimation:
1. Run a single batch (batch_size=1) to measure real VRAM consumption
2. Calculate if the requested batch_size would exceed available VRAM
3. Raise an error with suggested safe batch_size if it would exceed threshold

Usage:
    from backend.ai.utils.vram_guard import check_vram_before_batch_processing

    # In your feature extraction loop:
    check_vram_before_batch_processing(
        extractor=extractor,
        sample_batch=first_batch_images,  # A tensor with batch_size=1
        requested_batch_size=user_batch_size,
        device=device,
        safety_threshold=0.85,  # Use at most 85% of available VRAM
    )
"""

from __future__ import annotations

import torch
import torch.nn as nn
from typing import Tuple

from backend.common.gpu_resources import GpuWorkload, estimate_gpu


class VRAMInsufficientError(RuntimeError):
    """Raised when GPU does not have enough VRAM to load a model."""

    def __init__(
        self,
        message: str,
        model_name: str,
        required_vram_mb: float,
        available_vram_mb: float,
        total_vram_mb: float,
    ):
        super().__init__(message)
        self.message = message
        self.model_name = model_name
        self.required_vram_mb = required_vram_mb
        self.available_vram_mb = available_vram_mb
        self.total_vram_mb = total_vram_mb


def check_vram_before_model_load(
    model_name: str,
    device: torch.device,
    batch_size: int = 1,
    operation: str = 'feature_extraction',
    trainable: bool = False,
) -> None:
    """
    Check if there's enough VRAM to load a model BEFORE actually loading it.

    Uses system-wide VRAM (pynvml) when available so that other users' GPU
    allocations on a shared server are visible. Falls back to CUDA driver free
    memory when pynvml is not installed.

    Raises:
        VRAMInsufficientError: If GPU doesn't have enough VRAM for the model
    """
    if device.type not in {"cuda", "mps"}:
        return

    device_idx = device.index if device.index is not None else 0

    try:
        from backend.common.gpu_utils import get_gpu_memory_info as _get_system_vram

        _used_mb, free_mb, total_mb = _get_system_vram(device_idx)
        available_mb = free_mb
    except Exception:
        if device.type == 'mps':
            raise RuntimeError('MPS unified-memory telemetry is unavailable; retry after freeing memory')
        free, total = torch.cuda.mem_get_info(device_idx)
        available_mb, total_mb = free / 1024**2, total / 1024**2
    reusable_mb = max(0, torch.cuda.memory_reserved(device_idx) - torch.cuda.memory_allocated(device_idx)) / 1024**2 if device.type == 'cuda' else 0
    available_mb += reusable_mb

    required_mb = estimate_gpu(GpuWorkload(operation=operation, model=model_name, batch_size=batch_size, trainable=trainable)).required_mb

    if required_mb > available_mb:
        raise VRAMInsufficientError(
            message=(
                f"Insufficient GPU memory for model '{model_name}'. "
                f"Required: ~{required_mb:.0f} MB, Available: {available_mb:.0f} MB "
                f"(Total GPU: {total_mb:.0f} MB). Requeue with a smaller batch or wait for memory."
            ),
            model_name=model_name,
            required_vram_mb=required_mb,
            available_vram_mb=available_mb,
            total_vram_mb=total_mb,
        )


class VRAMExceededError(RuntimeError):
    """Raised when requested batch_size would exceed available VRAM."""

    def __init__(
        self,
        message: str,
        requested_batch_size: int,
        suggested_batch_size: int,
        measured_per_sample_mb: float,
        available_vram_mb: float,
        total_vram_mb: float,
    ):
        super().__init__(message)
        self.requested_batch_size = requested_batch_size
        self.suggested_batch_size = suggested_batch_size
        self.measured_per_sample_mb = measured_per_sample_mb
        self.available_vram_mb = available_vram_mb
        self.total_vram_mb = total_vram_mb


def get_vram_info(device: torch.device) -> Tuple[float, float, float]:
    """
    Get current VRAM information for the specified device.

    Returns:
        Tuple of (allocated_mb, reserved_mb, total_mb)
    """
    if device.type == 'mps':
        from backend.common.accelerator import mps_memory_info
        used, _, total = mps_memory_info()
        return used, used, total
    if device.type != "cuda":
        # Non-CUDA devices don't have VRAM limits we can check
        return (0.0, 0.0, float("inf"))

    device_idx = device.index if device.index is not None else 0
    props = torch.cuda.get_device_properties(device_idx)
    total_mb = props.total_memory / (1024**2)
    allocated_mb = torch.cuda.memory_allocated(device_idx) / (1024**2)
    reserved_mb = torch.cuda.memory_reserved(device_idx) / (1024**2)

    return (allocated_mb, reserved_mb, total_mb)


def measure_single_batch_vram(
    extractor: nn.Module,
    sample_input: torch.Tensor,
    device: torch.device,
) -> float:
    """
    Measure actual VRAM consumption for a single sample.

    Args:
        extractor: The feature extraction model
        sample_input: A single sample tensor (batch_size=1)
        device: CUDA device

    Returns:
        VRAM consumption in MB for one sample

    Raises:
        RuntimeError: If even a single sample causes OOM
    """
    if device.type != "cuda":
        return 0.0

    device_idx = device.index if device.index is not None else 0

    # Ensure clean state
    torch.cuda.synchronize(device_idx)
    torch.cuda.empty_cache()

    # Record memory before
    mem_before = torch.cuda.memory_allocated(device_idx)
    torch.cuda.reset_peak_memory_stats(device_idx)

    try:
        # Run forward pass with a single sample
        with torch.inference_mode():
            sample_input = sample_input.to(device, non_blocking=True)
            _ = extractor(sample_input)
            torch.cuda.synchronize(device_idx)
    except torch.cuda.OutOfMemoryError as e:
        # Even a single sample causes OOM - model is too large for this GPU
        torch.cuda.empty_cache()
        _, _, total_mb = get_vram_info(device)
        raise RuntimeError(
            f"GPU out of memory even with batch_size=1. "
            f"The model may be too large for your GPU ({total_mb:.0f} MB total VRAM). "
            f"Try using a smaller feature extractor model."
        ) from e

    # Record memory after
    mem_after = torch.cuda.max_memory_allocated(device_idx)

    # Calculate per-sample consumption
    # Note: sample_input should have batch_size=1
    batch_size = sample_input.shape[0]
    per_sample_mb = (mem_after - mem_before) / (1024**2) / batch_size

    return per_sample_mb


def check_vram_before_batch_processing(
    extractor: nn.Module,
    sample_input: torch.Tensor,
    requested_batch_size: int,
    device: torch.device,
    safety_threshold: float = 0.85,
) -> int:
    """
    Check if the requested batch_size would exceed available VRAM.

    This function performs an ACTUAL measurement using a single sample,
    then calculates if the full batch_size would fit in available VRAM.

    Args:
        extractor: The feature extraction model
        sample_input: A sample input tensor (can be batch_size >= 1)
        requested_batch_size: The batch_size user wants to use
        device: CUDA device
        safety_threshold: Maximum fraction of VRAM to use (default 0.85 = 85%)

    Returns:
        The safe batch_size to use (may be same as requested if it fits)

    Raises:
        VRAMExceededError: If even batch_size=1 would exceed available VRAM
    """
    if device.type != "cuda":
        # No VRAM limits on CPU
        return requested_batch_size

    # Measure actual VRAM consumption per sample
    per_sample_mb = measure_single_batch_vram(extractor, sample_input[:1], device)

    # Get current VRAM state
    from backend.common.gpu_utils import get_gpu_memory_info
    _, free_mb, total_mb = get_gpu_memory_info(device.index or 0)
    # Respect other users/processes as well as this allocator's reusable cache.
    reusable = max(0, torch.cuda.memory_reserved(device) - torch.cuda.memory_allocated(device)) / 1024**2
    available_mb = max(0, (free_mb + reusable) * safety_threshold)

    # Calculate maximum safe batch_size
    if per_sample_mb <= 0:
        # Measurement failed or trivial consumption
        return requested_batch_size

    max_safe_batch_size = max(1, int(available_mb / per_sample_mb))

    if requested_batch_size <= max_safe_batch_size:
        # Requested batch_size is safe
        return requested_batch_size

    # Requested batch_size would exceed VRAM
    raise VRAMExceededError(
        message=(
            f"Requested batch_size={requested_batch_size} would exceed available VRAM. "
            f"Measured {per_sample_mb:.2f} MB per sample. "
            f"Available: {available_mb:.2f} MB (total: {total_mb:.2f} MB, threshold: {safety_threshold * 100:.0f}%). "
            f"Suggested safe batch_size: {max_safe_batch_size}"
        ),
        requested_batch_size=requested_batch_size,
        suggested_batch_size=max_safe_batch_size,
        measured_per_sample_mb=per_sample_mb,
        available_vram_mb=available_mb,
        total_vram_mb=total_mb,
    )
