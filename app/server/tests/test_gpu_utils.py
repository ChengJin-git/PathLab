from types import SimpleNamespace


def test_sandbox_assignment_maps_logical_to_visible_physical_device(monkeypatch):
    from backend.common.gpu_utils import sandbox_visible_device
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '0,3,GPU-abcd')
    assert sandbox_visible_device(1) == '3'
    assert sandbox_visible_device(2) == 'GPU-abcd'


def test_driver_memory_fallback_counts_other_processes(monkeypatch):
    from backend.common import gpu_utils
    monkeypatch.setattr(gpu_utils, '_nvml_available', False)
    monkeypatch.setattr(gpu_utils.torch.cuda, 'mem_get_info', lambda index: (2 * 1024**3, 24 * 1024**3))
    assert gpu_utils.get_gpu_memory_info(0) == (22528, 2048, 24576)


def test_get_gpu_count_falls_back_to_nvml(monkeypatch):
    from backend.common import gpu_utils

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(
        gpu_utils,
        "_get_pynvml",
        lambda: SimpleNamespace(nvmlDeviceGetCount=lambda: 3),
    )

    assert gpu_utils.get_gpu_count() == 3


def test_get_gpu_count_nvml_fallback_respects_cuda_visible_devices(monkeypatch):
    from backend.common import gpu_utils

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1,3,4,5,6,7")
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(
        gpu_utils,
        "_get_pynvml",
        lambda: SimpleNamespace(nvmlDeviceGetCount=lambda: 8),
    )

    assert gpu_utils.get_gpu_count() == 7


def test_get_all_gpu_info_uses_nvml_fallback(monkeypatch):
    from backend.common import gpu_utils

    class _Mem:
        total = 8 * 1024**3
        used = 2 * 1024**3
        free = 6 * 1024**3

    pynvml = SimpleNamespace(
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda idx: idx,
        nvmlDeviceGetName=lambda _handle: "MockGPU",
        nvmlDeviceGetMemoryInfo=lambda _handle: _Mem(),
    )

    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(gpu_utils, "_get_pynvml", lambda: pynvml)

    info = gpu_utils.get_all_gpu_info()

    assert info == [
        {
            "index": 0,
            "name": "MockGPU",
            "allocated_mb": 2048.0,
            "free_mb": 6144.0,
            "total_mb": 8192.0,
        }
    ]


def test_get_all_gpu_info_nvml_fallback_respects_cuda_visible_devices(monkeypatch):
    from backend.common import gpu_utils

    class _Mem:
        total = 8 * 1024**3
        used = 2 * 1024**3
        free = 6 * 1024**3

    pynvml = SimpleNamespace(
        nvmlDeviceGetCount=lambda: 4,
        nvmlDeviceGetHandleByIndex=lambda idx: idx,
        nvmlDeviceGetName=lambda handle: f"MockGPU-{handle}",
        nvmlDeviceGetMemoryInfo=lambda _handle: _Mem(),
    )

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,3")
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(gpu_utils, "_get_pynvml", lambda: pynvml)

    info = gpu_utils.get_all_gpu_info()

    assert info == [
        {
            "index": 0,
            "name": "MockGPU-0",
            "allocated_mb": 2048.0,
            "free_mb": 6144.0,
            "total_mb": 8192.0,
        },
        {
            "index": 1,
            "name": "MockGPU-3",
            "allocated_mb": 2048.0,
            "free_mb": 6144.0,
            "total_mb": 8192.0,
        },
    ]


def test_probe_all_gpu_health_nvml_fallback_respects_cuda_visible_devices(monkeypatch):
    from backend.common import gpu_utils

    class _Mem:
        total = 8 * 1024**3
        used = 2 * 1024**3
        free = 6 * 1024**3

    pynvml = SimpleNamespace(
        nvmlDeviceGetCount=lambda: 4,
        nvmlDeviceGetHandleByIndex=lambda idx: idx,
        nvmlDeviceGetName=lambda handle: f"MockGPU-{handle}",
        nvmlDeviceGetMemoryInfo=lambda handle: (_Mem() if handle != 3 else (_ for _ in ()).throw(RuntimeError("bad gpu"))),
    )

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,3")
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(gpu_utils, "_get_pynvml", lambda: pynvml)

    assert gpu_utils.probe_all_gpu_health() == {0: True, 1: False}


def test_check_gpu_vram_available_nvml_fallback_uses_logical_visible_index(monkeypatch):
    from backend.common import gpu_utils

    class _Mem:
        total = 8 * 1024**3
        used = 2 * 1024**3
        free = 6 * 1024**3

    pynvml = SimpleNamespace(
        nvmlDeviceGetCount=lambda: 4,
        nvmlDeviceGetHandleByIndex=lambda idx: idx,
        nvmlDeviceGetName=lambda handle: f"MockGPU-{handle}",
        nvmlDeviceGetMemoryInfo=lambda _handle: _Mem(),
    )

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,3")
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(gpu_utils, "_get_pynvml", lambda: pynvml)

    ok, free_mb, message = gpu_utils.check_gpu_vram_available(1, 1024)

    assert ok is True
    assert free_mb == 6144.0
    assert "MockGPU-3" in message
