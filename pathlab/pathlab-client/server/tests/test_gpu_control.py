import os
import sys
import types
import pytest


class TestDetectAndExcludeBadGpus:
    def test_respects_existing_cvd_and_returns_empty(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1,3")

        fake_pynvml = types.ModuleType("pynvml")
        fake_pynvml.nvmlInit = lambda: None
        fake_pynvml.nvmlDeviceGetCount = lambda: 4
        monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

        if "main" in sys.modules:
            del sys.modules["main"]
        import main as m

        result = m._detect_and_exclude_bad_gpus()

        assert result == []
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == "0,1,3"

    def test_auto_excludes_bad_gpus_when_cvd_unset(self, monkeypatch):
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

        fake_pynvml = types.ModuleType("pynvml")
        fake_pynvml.nvmlInit = lambda: None
        fake_pynvml.nvmlDeviceGetCount = lambda: 3

        def fake_get_handle(i):
            return i

        def fake_get_memory_info(handle):
            if handle == 1:
                raise RuntimeError("GPU failure simulated")

            class _Mem:
                total = 8 * 1024**3
                used = 1 * 1024**3
                free = 7 * 1024**3

            return _Mem()

        def fake_get_name(handle):
            return f"MockGPU-{handle}"

        fake_pynvml.nvmlDeviceGetHandleByIndex = fake_get_handle
        fake_pynvml.nvmlDeviceGetMemoryInfo = fake_get_memory_info
        fake_pynvml.nvmlDeviceGetName = fake_get_name
        monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

        if "main" in sys.modules:
            del sys.modules["main"]
        import main as m

        result = m._detect_and_exclude_bad_gpus()

        assert 1 in result
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == "0,2"
