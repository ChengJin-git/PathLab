"""UNETR decoder head (2-D adaptation).

Reference: Hatamizadeh et al., "UNETR: Transformers for 3D Medical Image
Segmentation", WACV 2022 — https://arxiv.org/abs/2103.10504

2-D adaptation: all 4 intermediate ViT feature maps share the same spatial
resolution (patch grid H'×W'). The decoder progressively merges them via
skip connections, doubling spatial resolution at each stage, to reach the
original input resolution H×W.

  z3, z6, z9, z12  ←  inputs (B, D, H', W') each (shallow → deep)

  bottleneck  = ConvBlock(z12) → DeconvUp → (B, ch, 2H', 2W')
  level1      = ConvBlock(concat[bottleneck, proj(z9)]) → DeconvUp → 4H'
  level2      = ConvBlock(concat[level1,     proj(z6)]) → DeconvUp → 8H'
  level3      = ConvBlock(concat[level2,     proj(z3)]) → DeconvUp → 16H' = H
  output      = ConvBlock(level3)          shape: (B, base_ch, H, W)
"""

from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F


def _conv_block(in_ch: int, out_ch: int) -> nn.Sequential:
    """Two (Conv 3×3 → BN → ReLU) layers."""
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
        nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
    )


class UNETRDecoder(nn.Module):
    """UNETR-style skip-connection decoder for frozen ViT backbones (2-D).

    Parameters
    ----------
    embed_dim : int
        Channel dimension D of each input feature map (= ViT hidden dim).
    base_channels : int
        Channel width used throughout the decoder.  Default ``64``.
    """

    def __init__(self, embed_dim: int, base_channels: int = 64) -> None:
        super().__init__()
        ch = base_channels

        # Project each skip connection: D → ch
        self.proj3 = _conv_block(embed_dim, ch)  # shallowest skip
        self.proj2 = _conv_block(embed_dim, ch)
        self.proj1 = _conv_block(embed_dim, ch)  # second-deepest skip

        # Bottleneck: deepest features → deconv up
        self.bottleneck = _conv_block(embed_dim, ch)
        self.up_bn = nn.ConvTranspose2d(ch, ch, kernel_size=2, stride=2)

        # Decoder levels: merge + conv + up
        self.dec3 = _conv_block(ch * 2, ch)  # concat(up_bn,  proj1)
        self.up3 = nn.ConvTranspose2d(ch, ch, kernel_size=2, stride=2)

        self.dec2 = _conv_block(ch * 2, ch)  # concat(up3,   proj2)
        self.up2 = nn.ConvTranspose2d(ch, ch, kernel_size=2, stride=2)

        self.dec1 = _conv_block(ch * 2, ch)  # concat(up2,   proj3)
        self.up1 = nn.ConvTranspose2d(ch, ch, kernel_size=2, stride=2)

        # Final refinement at full resolution
        self.out_conv = _conv_block(ch, ch)

    def forward(self, features: list[torch.Tensor]) -> torch.Tensor:
        """
        Args:
            features: List of 4 tensors ``(B, D, H', W')``, shallow → deep.
                      ``features[0]=z3, [1]=z6, [2]=z9, [3]=z12``

        Returns:
            ``(B, base_channels, H'×16, W'×16)``  — full input resolution.
        """
        assert len(features) == 4, (
            f"UNETRDecoder expects exactly 4 feature maps, got {len(features)}"
        )
        z3, z6, z9, z12 = features  # shallow → deep

        skip3 = self.proj3(z3)  # (B, ch, H', W')
        skip2 = self.proj2(z6)
        skip1 = self.proj1(z9)

        x = self.bottleneck(z12)  # (B, ch, H', W')
        x = self.up_bn(x)  # (B, ch, 2H', 2W')

        skip1 = F.interpolate(
            skip1, size=x.shape[-2:], mode="bilinear", align_corners=False
        )
        x = torch.cat([x, skip1], dim=1)  # (B, 2ch, 2H', 2W')
        x = self.dec3(x)  # (B, ch, 2H', 2W')
        x = self.up3(x)  # (B, ch, 4H', 4W')

        skip2 = F.interpolate(
            skip2, size=x.shape[-2:], mode="bilinear", align_corners=False
        )
        x = torch.cat([x, skip2], dim=1)
        x = self.dec2(x)
        x = self.up2(x)  # (B, ch, 8H', 8W')

        skip3 = F.interpolate(
            skip3, size=x.shape[-2:], mode="bilinear", align_corners=False
        )
        x = torch.cat([x, skip3], dim=1)
        x = self.dec1(x)
        x = self.up1(x)  # (B, ch, 16H', 16W') = full res

        return self.out_conv(x)
