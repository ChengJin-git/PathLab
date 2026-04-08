from types import SimpleNamespace


def test_get_gpu_count_falls_back_to_nvml(monkeypatch):
    from backend.common import gpu_utils

    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gpu_utils, "_nvml_available", True)
    monkeypatch.setattr(
        gpu_utils,
        "_get_pynvml",
        lambda: SimpleNamespace(nvmlDeviceGetCount=lambda: 3),
    )

    assert gpu_utils.get_gpu_count() == 3


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
