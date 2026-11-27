"""CUDA / Apple Metal operations shared by built-in trainers and queue telemetry."""
from contextlib import nullcontext
from functools import lru_cache
import sys
import torch


@lru_cache(maxsize=1)
def mps_available() -> bool:
    if sys.platform != 'darwin' or not torch.backends.mps.is_available():
        return False
    try:
        return (torch.ones(2, device='mps') + 1).sum().item() == 4
    except RuntimeError:
        return False


def device_name(index: int = 0) -> str:
    return 'mps' if mps_available() and not torch.cuda.is_available() else f'cuda:{index}'


def mps_memory_info() -> tuple[float, float, float]:
    # Apple unified memory is shared with the OS. Reserve only 70% of the
    # recommended working set; driver allocations include this process's cache.
    # The scheduler additionally withholds all active cross-process leases.
    total = float(torch.mps.recommended_max_memory()) * 0.70
    used = float(torch.mps.driver_allocated_memory())
    try:
        import psutil
        free = min(max(0, total - used), psutil.virtual_memory().available * 0.70)
    except ImportError:
        free = max(0, total - used)
    return used / 1024**2, free / 1024**2, total / 1024**2


def empty_cache():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif mps_available():
        torch.mps.empty_cache()


def synchronize(device=None):
    if device is not None and torch.device(device).type == 'mps':
        torch.mps.synchronize()
    elif torch.cuda.is_available():
        torch.cuda.synchronize(device)


def training_autocast(device):
    # Use float32 on MPS until each model has verified mixed-precision kernels.
    return torch.autocast('cuda') if torch.device(device).type == 'cuda' else nullcontext()
