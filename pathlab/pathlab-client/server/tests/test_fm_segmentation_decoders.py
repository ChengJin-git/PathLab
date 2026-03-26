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
