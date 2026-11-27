from __future__ import annotations

from typing import Any, Dict, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.ai.extractors.base import BaseExtractor

_VALID_DECODER_TYPES = frozenset({"conv", "linear", "dpt", "unetr"})


class _DecoderBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False)
        self.bn = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.bn(self.conv(x)))
        return F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False)


class FMSegmentationModel(nn.Module):
    def __init__(
        self,
        extractor: BaseExtractor,
        classes: int = 1,
        input_size: int = 224,
        decoder_type: str = "conv",
        decoder_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__()

        if decoder_type not in _VALID_DECODER_TYPES:
            raise ValueError(
                f"Invalid decoder_type={decoder_type!r}. "
                f"Choose from {sorted(_VALID_DECODER_TYPES)}."
            )
        if not extractor.supports_spatial:
            raise ValueError(
                f"Extractor {extractor.__class__.__name__} does not support "
                "spatial feature extraction (supports_spatial=False)."
            )

        self.extractor = extractor
        for p in self.extractor.parameters():
            p.requires_grad = False
        self.extractor.eval()

        self.input_size = input_size
        self.classes = classes
        self.decoder_type = decoder_type

        embed_dim = extractor.spatial_output_dim
        kw = decoder_kwargs or {}

        if decoder_type == "conv":
            decoder_channels: Tuple[int, ...] = kw.get(
                "decoder_channels", (256, 128, 64, 32)
            )
            ch = [embed_dim] + list(decoder_channels)
            self.decoder: nn.Module = nn.Sequential(
                *[_DecoderBlock(ch[i], ch[i + 1]) for i in range(len(decoder_channels))]
            )
            self.head: nn.Module = nn.Conv2d(decoder_channels[-1], classes, 1)

        elif decoder_type == "linear":
            self.decoder = nn.Identity()
            self.head = nn.Conv2d(embed_dim, classes, 1)

        elif decoder_type == "dpt":
            from segmentation_models_pytorch.decoders.dpt.decoder import (
                DPTDecoder,
                DPTSegmentationHead,
            )

            inter_ch = kw.get("intermediate_channels", (256, 512, 1024, 1024))
            fusion_ch: int = kw.get("fusion_channels", 256)
            patch_sz = extractor.patch_size
            self.decoder = DPTDecoder(
                encoder_out_channels=(embed_dim,) * 4,
                encoder_output_strides=(patch_sz,) * 4,
                encoder_has_prefix_tokens=False,
                readout="ignore",
                intermediate_channels=inter_ch,
                fusion_channels=fusion_ch,
            )
            self.head = DPTSegmentationHead(
                in_channels=fusion_ch,
                out_channels=classes,
                kernel_size=3,
                upsampling=2,
            )

        elif decoder_type == "unetr":
            from backend.ai.segmentors.decoders.unetr import UNETRDecoder

            base_ch: int = kw.get("base_channels", 64)
            self.decoder = UNETRDecoder(embed_dim=embed_dim, base_channels=base_ch)
            self.head = nn.Conv2d(base_ch, classes, 1)

    def train(self, mode: bool = True):
        super().train(mode)
        self.extractor.eval()
        return self

    def decoder_state_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in self.state_dict().items() if not k.startswith("extractor.")
        }

    def load_decoder_state_dict(self, state_dict: dict[str, Any]) -> None:
        self.load_state_dict(state_dict, strict=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, _, H, W = x.shape

        with torch.no_grad():
            if self.decoder_type in ("dpt", "unetr"):
                feat = self.extractor.forward_multi_scale(x)
            else:
                feat = self.extractor.forward_spatial(x)

        if self.decoder_type == "dpt":
            out = self.decoder(feat, [None] * len(feat))
        else:
            out = self.decoder(feat)

        out = self.head(out)

        if out.shape[-2] != H or out.shape[-1] != W:
            out = F.interpolate(out, size=(H, W), mode="bilinear", align_corners=False)

        return out
