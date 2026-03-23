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
from typing import Tuple, Dict

from backend.common.config import Config


# Estimated model sizes in MB (conservative estimates including activations overhead)
# These are approximate values for FP32 weights + some buffer for activations
VRAM_WAIT_POLL_INTERVAL_SEC: int = 30


MODEL_SIZE_ESTIMATES_MB: Dict[str, int] = {
    # Small models (~100MB)
    "resnet50": 200,
    "plip": 400,
    "patho_clip": 400,
    # Medium models (~500MB-1GB)
    "conch": 600,
    "phikon": 800,
    "vit_l_16": 1200,
    # Large models (~1-2GB)
    "uni": 1500,
    "mSTAR": 1500,
    "GPFM": 1500,
    "phikon2": 1800,
    # Very large models (~2-4GB)
    "virchow": 3000,
    "virchow2": 3000,
    "conch15": 3000,
    "H-Optimus-0": 4000,
    # Giant models (~5GB+)
    "uni2": 5000,
    "openmidnight": 5500,  # DINOv2 ViT-G/14 ~1.1B params
    "H-Optimus-1": 6000,
}


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
) -> None:
    """
    Check if there's enough VRAM to load a model BEFORE actually loading it.

    Uses system-wide VRAM (pynvml) when available so that other users' GPU
    allocations on a shared server are visible.  Falls back to per-process
    PyTorch tracking when pynvml is not installed.

    Raises:
        VRAMInsufficientError: If GPU doesn't have enough VRAM for the model
    """
    if device.type != "cuda":
        return

    device_idx = device.index if device.index is not None else 0

    try:
        from backend.common.gpu_utils import get_gpu_memory_info as _get_system_vram

        _used_mb, free_mb, total_mb = _get_system_vram(device_idx)
        available_mb = free_mb
    except Exception:
        _, _, total_mb = get_vram_info(device)
        allocated_mb, _, _ = get_vram_info(device)
        available_mb = total_mb - allocated_mb

    # Get estimated model size (use default if unknown)
    model_size_mb = MODEL_SIZE_ESTIMATES_MB.get(model_name, 1000)
    min_overhead = Config.MIN_INFERENCE_OVERHEAD_MB

    # Calculate total required VRAM: model + inference overhead + batch buffer
    # Batch buffer: assume ~50MB per sample for activations (conservative)
    batch_buffer_mb = batch_size * 50
    required_mb = model_size_mb + min_overhead + batch_buffer_mb

    if required_mb > available_mb:
        # Find smaller models that might work
        suitable_models = [
            name
            for name, size in MODEL_SIZE_ESTIMATES_MB.items()
            if size + min_overhead + batch_buffer_mb <= available_mb
        ]
        suggestion = ""
        if suitable_models:
            # Sort by size descending to suggest the best one that fits
            suitable_models.sort(key=lambda x: MODEL_SIZE_ESTIMATES_MB[x], reverse=True)
            suggestion = f" Consider using: {', '.join(suitable_models[:3])}"

        raise VRAMInsufficientError(
            message=(
                f"Insufficient GPU memory for model '{model_name}'. "
                f"Required: ~{required_mb:.0f} MB, Available: {available_mb:.0f} MB "
                f"(Total GPU: {total_mb:.0f} MB).{suggestion}"
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
    mem_after = torch.cuda.memory_allocated(device_idx)

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
    allocated_mb, reserved_mb, total_mb = get_vram_info(device)

    # Calculate available VRAM (with safety threshold)
    usable_vram_mb = total_mb * safety_threshold
    available_mb = usable_vram_mb - allocated_mb

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
