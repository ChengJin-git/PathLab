"""Tests for FM segmentation decoder head types (linear / dpt / unetr / conv).

Uses a tiny fake ViT backbone (64-dim, 14x14 grid = 196 patches) running on CPU
so no GPU is required.
"""

from __future__ import annotations
import math
import pytest
import torch
import torch.nn as nn

from backend.ai.extractors.base import BaseExtractor


# ---------------------------------------------------------------------------
# Shared fake backbone + extractor
# ---------------------------------------------------------------------------


class _FakeViTBackbone(nn.Module):
    """Minimal timm-style ViT backbone with 12 identity blocks."""

    def __init__(self, embed_dim: int = 64, n_patches: int = 196):
        super().__init__()
        self.embed_dim = embed_dim
        self.n_patches = n_patches
        self.num_prefix_tokens = 1
        self.patch_size = 16
        self.blocks = nn.ModuleList([nn.Identity() for _ in range(12)])

    def forward_features(self, x: torch.Tensor) -> torch.Tensor:
        B = x.shape[0]
        return torch.zeros(B, self.n_patches + 1, self.embed_dim)

    def forward_intermediates(
        self,
        x: torch.Tensor,
        indices=None,
        output_fmt: str = "NCHW",
        intermediates_only: bool = True,
    ):
        B = x.shape[0]
        H = W = int(math.isqrt(self.n_patches))
        D = self.embed_dim
        n = len(indices) if indices is not None else 4
        if output_fmt == "NCHW":
            return [torch.zeros(B, D, H, W) for _ in range(n)]
        return [torch.zeros(B, self.n_patches, D) for _ in range(n)]


class _FakeExtractor(BaseExtractor):
    """Concrete extractor wrapping the fake ViT backbone."""

    def __init__(self, embed_dim: int = 64):
        super().__init__()
        self.backbone = _FakeViTBackbone(embed_dim=embed_dim)
        self._embed_dim = embed_dim

    @property
    def output_dim(self) -> int:
        return self._embed_dim

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.zeros(x.shape[0], self._embed_dim)

    @classmethod
    def build(cls, pretrained: bool = True, **kwargs) -> "_FakeExtractor":
        return cls()


# ---------------------------------------------------------------------------
# Task 1 — forward_multi_scale + patch_size
# ---------------------------------------------------------------------------


def test_forward_multi_scale_returns_four_maps():
    ext = _FakeExtractor(embed_dim=64)
    x = torch.zeros(2, 3, 224, 224)
    feats = ext.forward_multi_scale(x, n_levels=4)
    assert len(feats) == 4
    for f in feats:
        assert f.shape == (2, 64, 14, 14), f.shape


def test_forward_multi_scale_no_backbone_raises():
    class _NoBB(BaseExtractor):
        @property
        def output_dim(self):
            return 64

        def forward(self, x):
            return torch.zeros(x.shape[0], 64)

        @classmethod
        def build(cls, pretrained=True, **kwargs):
            return cls()

    with pytest.raises(NotImplementedError):
        _NoBB().forward_multi_scale(torch.zeros(1, 3, 224, 224))


def test_patch_size_from_backbone():
    ext = _FakeExtractor(embed_dim=64)
    assert ext.patch_size == 16


def test_patch_size_default_when_no_backbone():
    class _NoBB(BaseExtractor):
        @property
        def output_dim(self):
            return 64

        def forward(self, x):
            return torch.zeros(x.shape[0], 64)

        @classmethod
        def build(cls, pretrained=True, **kwargs):
            return cls()

    assert _NoBB().patch_size == 16


# ---------------------------------------------------------------------------
# Task 2 — UNETR Decoder
# ---------------------------------------------------------------------------

from backend.ai.segmentors.decoders.unetr import UNETRDecoder


def test_unetr_decoder_output_shape():
    B, D, H_p, W_p = 2, 64, 14, 14
    feats = [torch.zeros(B, D, H_p, W_p) for _ in range(4)]
    decoder = UNETRDecoder(embed_dim=D, base_channels=32)
    out = decoder(feats)
    assert out.shape == (B, 32, H_p * 16, W_p * 16), out.shape


def test_unetr_decoder_wrong_feature_count():
    decoder = UNETRDecoder(embed_dim=64, base_channels=32)
    with pytest.raises((AssertionError, ValueError)):
        decoder([torch.zeros(1, 64, 14, 14)] * 3)


# ---------------------------------------------------------------------------
# Task 3 — FMSegmentationModel with decoder_type
# ---------------------------------------------------------------------------

from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel


@pytest.mark.parametrize("decoder_type", ["conv", "linear", "dpt", "unetr"])
def test_fm_model_forward_shape(decoder_type):
    ext = _FakeExtractor(embed_dim=64)
    kw = {"decoder_channels": (32, 16, 8, 4)} if decoder_type == "conv" else {}
    model = FMSegmentationModel(
        extractor=ext,
        classes=2,
        input_size=224,
        decoder_type=decoder_type,
        decoder_kwargs=kw,
    )
    model.eval()
    with torch.no_grad():
        out = model(torch.zeros(2, 3, 224, 224))
    assert out.shape == (2, 2, 224, 224), f"[{decoder_type}] got {out.shape}"


def test_fm_model_decoder_state_dict_no_extractor_keys():
    ext = _FakeExtractor(embed_dim=64)
    for dt in ("conv", "linear", "dpt", "unetr"):
        m = FMSegmentationModel(
            extractor=ext, classes=1, input_size=224, decoder_type=dt
        )
        sd = m.decoder_state_dict()
        assert not any(k.startswith("extractor.") for k in sd), (
            f"[{dt}] decoder_state_dict contains extractor keys"
        )


def test_fm_model_conv_default_no_decoder_type_arg():
    ext = _FakeExtractor(embed_dim=64)
    m = FMSegmentationModel(extractor=ext, classes=1, input_size=224)
    assert m.decoder_type == "conv"
    with torch.no_grad():
        out = m(torch.zeros(1, 3, 224, 224))
    assert out.shape == (1, 1, 224, 224)


def test_fm_model_invalid_decoder_type_raises():
    ext = _FakeExtractor(embed_dim=64)
    with pytest.raises(ValueError, match="decoder_type"):
        FMSegmentationModel(
            extractor=ext, classes=1, input_size=224, decoder_type="bad"
        )
