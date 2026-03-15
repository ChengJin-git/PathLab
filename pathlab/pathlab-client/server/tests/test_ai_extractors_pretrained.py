import os
from contextlib import contextmanager

import pytest
import torch

HF_TOKEN = os.getenv("HF_TOKEN", "")


def _select_device() -> torch.device:
    if not torch.cuda.is_available():
        return torch.device("cpu")
    best = max(
        range(torch.cuda.device_count()), key=lambda i: torch.cuda.mem_get_info(i)[0]
    )
    return torch.device(f"cuda:{best}")


DEVICE = _select_device()

_MODEL_CACHE: dict = {}


def _get(name: str):
    if name not in _MODEL_CACHE:
        from backend.ai.extractors.registry import get_extractor

        m = get_extractor(name, pretrained=True, hf_token=HF_TOKEN)
        m.eval()
        _MODEL_CACHE[name] = m
    return _MODEL_CACHE[name]


@contextmanager
def _on_gpu(name: str):
    m = _get(name)
    m.to(DEVICE)
    try:
        yield m
    finally:
        m.to("cpu")
        torch.cuda.empty_cache()


HF_EXTRACTOR_CONFIGS = [
    ("conch", 512, 448),
    ("uni", 1024, 224),
    ("uni2", 1536, 224),
    ("virchow", 2560, 224),
    ("virchow2", 2560, 224),
    ("plip", 512, 224),
    ("phikon", 768, 224),
    ("phikon2", 1024, 224),
    ("patho_clip", 768, 224),
    ("openmidnight", 1536, 224),
    ("conch15", 768, 448),
    ("H-Optimus-1", 1536, 224),
    ("H-Optimus-0", 1536, 224),
    ("mSTAR", 1024, 224),
    ("GPFM", 1024, 224),
    ("SmartCCS", 1024, 224),
    ("SmartCyto", 768, 224),
]

HF_SPATIAL_CONFIGS = [
    ("conch", 768, 448),
    ("uni", 1024, 224),
    ("uni2", 1536, 224),
    ("virchow", 1280, 224),
    ("virchow2", 1280, 224),
    ("plip", 768, 224),
    ("phikon", 768, 224),
    ("phikon2", 1024, 224),
    ("patho_clip", 1024, 224),
    ("openmidnight", 1536, 224),
    ("conch15", 1024, 448),
    ("H-Optimus-1", 1536, 224),
    ("H-Optimus-0", 1536, 224),
    ("mSTAR", 1024, 224),
    ("GPFM", 1024, 224),
    ("SmartCCS", 1024, 224),
    ("SmartCyto", 768, 224),
]


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_output_dim(name, expected_dim, img_size):
    m = _get(name)
    assert m.output_dim == expected_dim, f"{name}: output_dim mismatch"


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_forward_shape(name, expected_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            out = m(x)
    assert out.shape == (1, expected_dim), (
        f"{name}: expected (1, {expected_dim}), got {tuple(out.shape)}"
    )


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_output_finite(name, expected_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            out = m(x)
    assert torch.isfinite(out).all(), f"{name}: output contains NaN or Inf"


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_output_on_gpu(name, expected_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            out = m(x)
    assert out.device.type == "cuda", f"{name}: output not on CUDA"


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_batch_consistency(name, expected_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            o1 = m(x)
            o2 = m(x)
    assert torch.allclose(o1, o2, atol=1e-5), (
        f"{name}: same input gives different outputs"
    )


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_different_inputs_differ(name, expected_dim, img_size):
    with _on_gpu(name) as m:
        x1 = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        x2 = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            o1 = m(x1)
            o2 = m(x2)
    assert not torch.allclose(o1, o2), (
        f"{name}: different inputs produce identical outputs"
    )


@pytest.mark.parametrize("name,expected_dim,img_size", HF_EXTRACTOR_CONFIGS)
def test_extractor_supports_spatial_flag(name, expected_dim, img_size):
    from backend.ai.extractors.registry import extractor_supports_spatial

    m = _get(name)
    registry_flag = extractor_supports_spatial(name)
    assert registry_flag is True, f"{name}: should be spatial in registry"
    assert m.supports_spatial is True, f"{name}: model.supports_spatial should be True"


@pytest.mark.parametrize("name,spatial_dim,img_size", HF_SPATIAL_CONFIGS)
def test_extractor_forward_spatial_shape(name, spatial_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            feat_map = m.forward_spatial(x)
    assert feat_map.ndim == 4, f"{name}: forward_spatial should return 4D tensor"
    B, D, H, W = feat_map.shape
    assert B == 1, f"{name}: batch dim mismatch"
    assert D == spatial_dim, f"{name}: spatial_dim expected {spatial_dim}, got {D}"
    assert H == W, f"{name}: spatial map should be square, got {H}x{W}"
    assert H > 0, f"{name}: spatial map has zero spatial extent"


@pytest.mark.parametrize("name,spatial_dim,img_size", HF_SPATIAL_CONFIGS)
def test_extractor_forward_spatial_finite(name, spatial_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            feat_map = m.forward_spatial(x)
    assert torch.isfinite(feat_map).all(), (
        f"{name}: forward_spatial output contains NaN or Inf"
    )


@pytest.mark.parametrize("name,spatial_dim,img_size", HF_SPATIAL_CONFIGS)
def test_extractor_forward_spatial_on_gpu(name, spatial_dim, img_size):
    with _on_gpu(name) as m:
        x = torch.randn(1, 3, img_size, img_size, device=DEVICE)
        with torch.no_grad():
            feat_map = m.forward_spatial(x)
    assert feat_map.device.type == "cuda", f"{name}: forward_spatial output not on CUDA"


class TestExtractorTransformIntegration:
    @pytest.mark.parametrize("name,_dim,img_size", HF_EXTRACTOR_CONFIGS)
    def test_get_transforms_eval_returns_callable(self, name, _dim, img_size):
        m = _get(name)
        t = m.get_transforms(mode="eval")
        assert callable(t), f"{name}: get_transforms(eval) not callable"

    @pytest.mark.parametrize("name,_dim,img_size", HF_EXTRACTOR_CONFIGS)
    def test_transforms_produce_correct_tensor_from_pil(self, name, _dim, img_size):
        import numpy as np
        from PIL import Image

        m = _get(name)
        t = m.get_transforms(mode="eval")
        img = Image.fromarray(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8))
        tensor = t(img)
        assert isinstance(tensor, torch.Tensor)
        assert tensor.ndim == 3
        assert tensor.shape[0] == 3
