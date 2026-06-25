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
        self.num_heads = 8
        self.attn = NystromAttention(
            dim=dim,
            dim_head=dim // 8,
            heads=self.num_heads,
            num_landmarks=dim // 2,    # number of landmarks
            pinv_iterations=6,         # number of moore-penrose iterations
            residual=True,             # residual connection
            dropout=0.1
        )
        # Store last attention for visualization
        self._last_attention: Optional[torch.Tensor] = None

    def forward(self, x: torch.Tensor, return_attention: bool = False) -> torch.Tensor:
        # x: [B, N, D]
        normed_x = self.norm(x)
        if return_attention:
            attn_out, attn = self.attn(normed_x, return_attn=True)
            self._last_attention = attn  # [B, heads, N, N]
            x = x + attn_out
        else:
            x = x + self.attn(normed_x)
        return x

    def get_last_attention(self) -> Optional[torch.Tensor]:
        """Get the last computed attention matrix. Shape: [B, heads, N, N]"""
        return self._last_attention


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
            attention: (N,) - Transformer attention weights (CLS token attending to patches)
                       Extracted from NystromAttention layer, similar to HIPT's approach.
        """
        logits, attention, _ = self._forward_internal(H, compute_attention=True)
        return logits, attention

    def _forward_internal(
        self, H: torch.Tensor, compute_attention: bool = False
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor], Optional[torch.Tensor]]:
        """
        Internal forward pass with optional attention computation.

        Uses actual transformer attention weights from the last TransLayer,
        similar to HIPT's approach: extract CLS token's attention to all patches.

        Args:
            H: Instance features of shape (N, D) or (B, N, D)
            compute_attention: Whether to extract attention from transformer layers

        Returns:
            logits: (B, C)
            attention: (N,) attention weights from CLS to patches, or None
            h_norm: (B, N+1, dim) normalized hidden states
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
        h = torch.cat((cls_tokens, h), dim=1)  # [B, 1+N_padded, dim]

        # 5. TransLayer 1
        h = self.layer1(h, return_attention=False)

        # 6. PPEG (Position Encoding)
        h = self.pos_layer(h, _H, _W)

        # 7. TransLayer 2 - extract attention if needed
        h = self.layer2(h, return_attention=compute_attention)

        # 8. Normalize
        h_norm = self.norm(h)  # [B, N_padded+1, dim]

        # 9. Classification using CLS token
        h_cls = h_norm[:, 0]  # [B, dim]
        logits = self._fc2(h_cls)  # [B, num_classes]

        # 10. Extract attention from transformer if requested
        attention = None
        if compute_attention:
            # Get attention from last TransLayer (similar to HIPT's get_last_selfattention)
            # Note: NystromAttention may add internal padding, so attention shape could be
            # [B, num_heads, seq_len_internal, seq_len_internal] where seq_len_internal >= 1+N_padded
            attn_matrix = self.layer2.get_last_attention()

            if attn_matrix is not None:
                # Our input sequence length to TransLayer2 is (1 + N_padded)
                # where 1 is CLS token and N_padded = _H * _W
                seq_len = 1 + _H * _W

                # NystromAttention pads at the BEGINNING of sequence if needed
                # So we need to take the LAST seq_len tokens
                # attn_matrix shape: [B, heads, seq_internal, seq_internal]
                attn_seq_len = attn_matrix.shape[-1]

                if attn_seq_len > seq_len:
                    # Extract only the relevant part (last seq_len tokens)
                    offset = attn_seq_len - seq_len
                    attn_matrix = attn_matrix[:, :, offset:, offset:]

                # Now attn_matrix is [B, heads, 1+N_padded, 1+N_padded]
                # Extract CLS token's attention to patch tokens
                # CLS is at index 0, patches are at indices 1:
                # Shape: [B, num_heads, N_padded]
                cls_to_patches = attn_matrix[:, :, 0, 1:]

                # Average across heads (can also use specific heads if needed)
                # Shape: [B, N_padded]
                cls_attn_avg = cls_to_patches.mean(dim=1)

                # Extract only original patches (remove PPEG padding)
                # Shape: [B, N]
                cls_attn_avg = cls_attn_avg[:, :N]

                # Squeeze batch dimension
                # Shape: [N]
                attention = cls_attn_avg.squeeze(0)

                # Renormalize after removing padding to ensure sum = 1
                attention = attention / (attention.sum() + 1e-8)

        return logits, attention, h_norm