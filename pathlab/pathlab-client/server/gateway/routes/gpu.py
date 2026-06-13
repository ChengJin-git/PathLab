"""
GPU Information Routes - Direct implementation in Gateway.

Provides authenticated access to GPU information for:
1. Frontend display of GPU status
2. LLM-based decision making for device selection
3. System monitoring and diagnostics
"""

from typing import List, Optional
import logging

import torch
from fastapi import APIRouter, Depends

from backend.auth import User
from backend.auth.dependencies import require_can_use_gpu
from backend.common.gpu_utils import (
    get_gpu_memory_info,
    get_optimal_device,
    NoGPUAvailableError,
)
from gateway.models import GPUInfo, GPUStatusResponse
from ..task_queue import get_task_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gpu", tags=["GPU"])


@router.get("/info", response_model=GPUStatusResponse)
async def get_gpu_info(
    user: User = Depends(require_can_use_gpu),
) -> GPUStatusResponse:
    """
    Get comprehensive GPU information.

    Requires authentication.

    Returns:
        GPUStatusResponse with:
        - available: Whether CUDA GPUs are available
        - gpu_count: Number of GPUs detected
        - gpus: List of GPU details (name, VRAM usage, etc.)
        - optimal_device: The recommended device string (e.g., "cuda:0")
        - optimal_device_index: Index of the optimal GPU
        - cuda_version: CUDA version string
    """
    if not torch.cuda.is_available():
        return GPUStatusResponse(
            available=False,
            error="No CUDA-capable GPU detected. Please ensure NVIDIA GPU and CUDA drivers are installed.",
            gpu_count=0,
            gpus=[],
            optimal_device=None,
            cuda_version=None,
        )

    num_gpus = torch.cuda.device_count()
    cuda_version = torch.version.cuda

    # Get optimal device
    try:
        optimal_device = get_optimal_device()
        optimal_device_str = str(optimal_device)
        optimal_device_idx = (
            optimal_device.index if optimal_device.index is not None else 0
        )
    except NoGPUAvailableError as e:
        return GPUStatusResponse(
            available=False,
            error=str(e),
            gpu_count=0,
            gpus=[],
            optimal_device=None,
            cuda_version=cuda_version,
        )

    bad_gpus = get_task_queue().get_bad_gpus()

    # Collect info for all GPUs
    gpus: List[GPUInfo] = []
    for i in range(num_gpus):
        name = torch.cuda.get_device_name(i)
        allocated_mb, free_mb, total_mb = get_gpu_memory_info(i)
        utilization = ((total_mb - free_mb) / total_mb * 100) if total_mb > 0 else 0

        gpus.append(
            GPUInfo(
                index=i,
                name=name,
                total_mb=round(total_mb, 2),
                allocated_mb=round(allocated_mb, 2),
                free_mb=round(free_mb, 2),
                utilization_percent=round(utilization, 2),
                is_optimal=(i == optimal_device_idx),
                is_healthy=(i not in bad_gpus),
            )
        )

    return GPUStatusResponse(
        available=True,
        gpu_count=num_gpus,
        bad_gpu_count=len(bad_gpus),
        gpus=gpus,
        optimal_device=optimal_device_str,
        optimal_device_index=optimal_device_idx,
        cuda_version=cuda_version,
    )
