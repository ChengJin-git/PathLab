"""
FM-powered Segmentation Model.

Wraps a frozen Foundation Model (FM) feature extractor as backbone and adds
a lightweight convolutional decoder for dense pixel-wise prediction.

The FM backbone produces a spatial token map via ``forward_spatial()``
(shape ``(B, D, H', W')``), and the decoder upsamples it back to the
original input resolution ``(B, classes, H, W)``.
"""

from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.ai.extractors.base import BaseExtractor


class _DecoderBlock(nn.Module):
    """Conv + BN + ReLU + 2x bilinear upsample."""

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False)
        self.bn = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        x = self.bn(x)
        x = self.relu(x)
        x = F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False)
        return x


class FMSegmentationModel(nn.Module):
    """Frozen FM backbone + lightweight upsampling decoder for segmentation.

    Parameters
    ----------
    extractor : BaseExtractor
        A feature extractor that supports ``forward_spatial()``.
        Its weights are frozen (``requires_grad=False``).
    classes : int
        Number of output segmentation classes (channels).
    input_size : int
        Expected spatial size of input images (height == width).
    decoder_channels : tuple[int, ...]
        Channel sizes for successive decoder blocks.  Each block performs 2×
        bilinear upsampling.  The default ``(256, 128, 64, 32)`` gives 16×
        total upsampling which matches ViT patch_size=16.
    """

    def __init__(
        self,
        extractor: BaseExtractor,
        classes: int = 1,
        input_size: int = 224,
        decoder_channels: Tuple[int, ...] = (256, 128, 64, 32),
    ):
        super().__init__()
        if not extractor.supports_spatial:
            raise ValueError(
                f"Extractor {extractor.__class__.__name__} does not support "
                "spatial feature extraction (supports_spatial=False)."
            )

        # Freeze the backbone
        self.extractor = extractor
        for param in self.extractor.parameters():
            param.requires_grad = False
        self.extractor.eval()

        self.input_size = input_size
        self.classes = classes

        # Build decoder from the spatial feature-map channel dimension.
        # Some extractors expose a pooled/aggregated ``output_dim`` for
        # classification that differs from the patch-token dimension returned by
        # ``forward_spatial()`` (e.g. CONCH / Virchow variants).
        embed_dim = extractor.spatial_output_dim
        channels = [embed_dim] + list(decoder_channels)
        blocks = []
        for i in range(len(decoder_channels)):
            blocks.append(_DecoderBlock(channels[i], channels[i + 1]))
        self.decoder = nn.Sequential(*blocks)

        # Final 1×1 conv to produce class logits
        self.head = nn.Conv2d(decoder_channels[-1], classes, kernel_size=1)

    # ------------------------------------------------------------------
    # Ensure backbone stays in eval mode even when model.train() is called
    # ------------------------------------------------------------------
    def train(self, mode: bool = True):
        super().train(mode)
        self.extractor.eval()
        return self

    def decoder_state_dict(self) -> dict:
        """Return only the trainable decoder + head weights (excludes frozen backbone).

        Use this when saving checkpoints to avoid storing the large FM backbone
        weights (~1-2 GB) that are already available locally.
        """
        full = self.state_dict()
        return {k: v for k, v in full.items() if not k.startswith("extractor.")}

    def load_decoder_state_dict(self, state_dict: dict) -> None:
        """Load decoder + head weights saved by :meth:`decoder_state_dict`.

        The frozen backbone weights are **not** expected in *state_dict*;
        they are already loaded from the pre-trained FM checkpoint.
        """
        self.load_state_dict(state_dict, strict=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Input images ``(B, 3, H, W)``  (H == W == input_size).

        Returns:
            Logits ``(B, classes, H, W)`` at the original input resolution.
        """
        _, _, H, W = x.shape

        # Frozen backbone → spatial feature map (B, D, H', W')
        with torch.no_grad():
            feat = self.extractor.forward_spatial(x)

        first_block = self.decoder[0] if len(self.decoder) > 0 else None
        expected_in_channels = getattr(getattr(first_block, "conv", None), "in_channels", feat.shape[1])
        if feat.shape[1] != expected_in_channels:
            raise RuntimeError(
                "FM segmentation decoder channel mismatch: "
                f"extractor={self.extractor.__class__.__name__}, "
                f"spatial_output_dim={expected_in_channels}, "
                f"forward_spatial returned {feat.shape[1]} channels. "
                "Please ensure the extractor's spatial_output_dim matches its patch-token dimension."
            )

        # Decoder upsampling
        out = self.decoder(feat)  # (B, last_ch, H'*2^n, W'*2^n)

        # Final interpolation to exact input size (handles non-power-of-2 patches)
        if out.shape[-2] != H or out.shape[-1] != W:
            out = F.interpolate(out, size=(H, W), mode="bilinear", align_corners=False)

        out = self.head(out)  # (B, classes, H, W)
        return out

