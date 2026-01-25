"""
TransMIL aggregator module.
"""

from __future__ import annotations
import torch
import torch.nn as nn
import numpy as np
from typing import Tuple, Optional
from nystrom_attention import NystromAttention

from .base import BaseAggregator 

class TransLayer(nn.Module):
    """
    TransLayer: Implementation of the Nystrom Attention layer with normalization.
    """
    def __init__(self, norm_layer=nn.LayerNorm, dim=512):
        super().__init__()
        self.norm = norm_layer(dim)
        self.attn = NystromAttention(
            dim=dim,
            dim_head=dim // 8,
            heads=8,
            num_landmarks=dim // 2,    # number of landmarks
            pinv_iterations=6,         # number of moore-penrose iterations
            residual=True,             # residual connection
            dropout=0.1
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, N, D]
        x = x + self.attn(self.norm(x))
        return x


class PPEG(nn.Module):
    """
    Pyramid Position Encoding Generator (PPEG).
    Uses conditional position encoding based on local context.
    """
    def __init__(self, dim=512):
        super(PPEG, self).__init__()
        self.proj = nn.Conv2d(dim, dim, 7, 1, 7 // 2, groups=dim)
        self.proj1 = nn.Conv2d(dim, dim, 5, 1, 5 // 2, groups=dim)
        self.proj2 = nn.Conv2d(dim, dim, 3, 1, 3 // 2, groups=dim)

    def forward(self, x: torch.Tensor, H: int, W: int) -> torch.Tensor:
        # x: [B, N, D] (Input sequence, including padding, EXCLUDING CLS token usually handling in caller)
        B, _, C = x.shape
        cls_token, feat_token = x[:, 0], x[:, 1:]
        
        # Reshape sequence to 2D grid for CNN operations
        cnn_feat = feat_token.transpose(1, 2).view(B, C, H, W)
        
        # Multi-scale convolution
        x = self.proj(cnn_feat) + cnn_feat + self.proj1(cnn_feat) + self.proj2(cnn_feat)
        
        # Flatten back to sequence
        x = x.flatten(2).transpose(1, 2)
        
        # Concatenate CLS token back
        x = torch.cat((cls_token.unsqueeze(1), x), dim=1)
        return x


class TransMILAggregator(BaseAggregator):
    """
    TransMIL: Transformer based Correlated Multiple Instance Learning for WSI Classification.
    """
    def __init__(self, in_dim: int, num_classes: int, dim: int = 512):
        super().__init__(in_dim, num_classes)
        self.dim = dim
        
        # Initial projection: in_dim -> dim
        self._fc1 = nn.Sequential(nn.Linear(in_dim, dim), nn.ReLU())
        
        # Class token
        self.cls_token = nn.Parameter(torch.randn(1, 1, dim))
        
        # Layers
        self.layer1 = TransLayer(dim=dim)
        self.pos_layer = PPEG(dim=dim)
        self.layer2 = TransLayer(dim=dim)
        
        # Final Classification
        self.norm = nn.LayerNorm(dim)
        self._fc2 = nn.Linear(dim, num_classes)

    @classmethod
    def build(cls, in_dim: int, num_classes: int, dim: int = 512) -> TransMILAggregator:
        return cls(in_dim=in_dim, num_classes=num_classes, dim=dim)

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Args:
            H: Instance features of shape (N, D)

        Returns:
            logits: (1, C)
            attention: (N,) - CLS-patch similarity based attention weights
        """
        logits, attention, _ = self._forward_internal(H, compute_attention=True)
        return logits, attention

    def _forward_internal(
        self, H: torch.Tensor, compute_attention: bool = False
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor], Optional[torch.Tensor]]:
        """
        Internal forward pass with optional attention computation.

        Args:
            H: Instance features of shape (N, D) or (B, N, D)
            compute_attention: Whether to compute CLS-patch similarity attention

        Returns:
            logits: (B, C)
            attention: (N,) CLS-patch similarity or None
            h_norm: (B, N+1, dim) normalized hidden states (for raw attention extraction)
        """
        # 1. Handle Input Shape: Ensure we have a batch dimension [B, N, D]
        if H.dim() == 2:
            H = H.unsqueeze(0)  # [1, N, D]

        # 2. Projection
        h = self._fc1(H)  # [B, N, 512]

        # 3. Squaring / Padding for PPEG
        B, N, _ = h.shape
        _H, _W = int(np.ceil(np.sqrt(N))), int(np.ceil(np.sqrt(N)))
        add_length = _H * _W - N

        # Pad by repeating the beginning of the sequence
        if add_length > 0:
            h = torch.cat([h, h[:, :add_length, :]], dim=1)  # [B, N_padded, 512]

        # 4. Append CLS Token
        cls_tokens = self.cls_token.expand(B, -1, -1).to(h.device)
        h = torch.cat((cls_tokens, h), dim=1)

        # 5. TransLayer 1
        h = self.layer1(h)

        # 6. PPEG (Position Encoding)
        h = self.pos_layer(h, _H, _W)

        # 7. TransLayer 2
        h = self.layer2(h)

        # 8. Normalize
        h_norm = self.norm(h)  # [B, N_padded+1, dim]

        # 9. Classification using CLS token
        h_cls = h_norm[:, 0]  # [B, dim]
        logits = self._fc2(h_cls)  # [B, num_classes]

        # 10. Compute attention if requested
        attention = None
        if compute_attention:
            # Extract patch tokens (excluding CLS and padding)
            patch_tokens = h_norm[:, 1:N+1, :]  # [B, N, dim] - only original patches, no padding

            # Compute CLS-patch similarity as attention weights
            # Similarity = CLS @ Patches^T -> [B, N]
            similarity = torch.bmm(h_cls.unsqueeze(1), patch_tokens.transpose(1, 2)).squeeze(1)  # [B, N]

            # Apply softmax to get attention-like weights
            attention = torch.softmax(similarity, dim=-1).squeeze(0)  # [N]

        return logits, attention, h_norm

if __name__ == "__main__":
    # Test code
    in_dim = 1024
    num_classes = 2
    model = TransMILAggregator.build(in_dim, num_classes, dim=512)

    # Simulate a bag of 6000 patches
    num_patches = 6000
    data = torch.randn((num_patches, 1024))

    print(f"Model created. Params: {sum(p.numel() for p in model.parameters())}")

    logits, attn = model(data)
    print(f"Logits shape: {logits.shape}")  # Should be (1, 2)
    print(f"Attention shape: {attn.shape if attn is not None else 'None'}")  # Should be (6000,)
    print(f"Attention sum: {attn.sum().item() if attn is not None else 'N/A'}")  # Should be ~1.0 (softmax)
    print(f"Attention min/max: {attn.min().item():.6f} / {attn.max().item():.6f}" if attn is not None else "N/A")

    # Test loss calculation
    labels = torch.tensor([1]).long()  # Batch size 1
    loss, _ = model.run_one_step(data, labels, model.default_criterion())
    print(f"Loss: {loss.item()}")