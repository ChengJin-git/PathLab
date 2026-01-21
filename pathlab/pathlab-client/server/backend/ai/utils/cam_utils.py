"""
CAM (Class Activation Map) utilities for patch-level heatmap visualization.

Provides two implementations:
1. ResNetCAMExtractor: For CNN backbones (ResNet50), uses Grad-CAM
2. TransformerCAMExtractor: For ViT backbones, uses CLS attention

Usage:
    from backend.ai.utils.cam_utils import get_cam_extractor

    cam_extractor = get_cam_extractor("resnet50")  # or "uni", "virchow", etc.
    cam_map = cam_extractor.extract_cam(model, input_tensor, target_class=1)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PatchCAMResult:
    """Result of CAM extraction for a single patch."""
    coord: Tuple[int, int]    # WSI level0 coordinates (x, y)
    pred: int                  # Predicted class index
    prob: float                # Prediction probability
    cam: np.ndarray           # CAM heatmap (H, W), e.g., (14, 14) or (7, 7)


# =============================================================================
# Base Class
# =============================================================================

class BaseCAMExtractor(ABC):
    """
    Abstract base class for CAM extraction.

    All CAM extractors must implement extract_cam() method.
    """

    @abstractmethod
    def extract_cam(
        self,
        model: nn.Module,
        input_tensor: torch.Tensor,
        target_class: Optional[int] = None,
    ) -> np.ndarray:
        """
        Extract CAM from model for given input.

        Args:
            model: The full model (backbone + classifier head)
            input_tensor: Input tensor of shape (B, C, H, W)
            target_class: Target class for CAM. If None, uses predicted class.

        Returns:
            CAM heatmap of shape (B, H, W) where H, W depend on the method
        """
        pass

    @abstractmethod
    def get_cam_size(self, input_size: int = 224) -> Tuple[int, int]:
        """
        Get the spatial size of CAM output.

        Args:
            input_size: Input image size

        Returns:
            (height, width) of CAM output
        """
        pass


# =============================================================================
# ResNet CAM Extractor (Grad-CAM)
# =============================================================================

class ResNetCAMExtractor(BaseCAMExtractor):
    """
    CAM extractor for ResNet-like CNN backbones using Grad-CAM.

    Uses pytorch-grad-cam library for efficient CAM computation.
    Target layer is the last convolutional block (layer4[-1]).
    """

    def __init__(self):
        super().__init__()
        self._cam = None

    def extract_cam(
        self,
        model: nn.Module,
        input_tensor: torch.Tensor,
        target_class: Optional[int] = None,
    ) -> np.ndarray:
        """
        Extract Grad-CAM from ResNet model.

        Args:
            model: nn.Sequential containing (backbone, linear_probe)
                   where backbone is ResNet50Extractor
            input_tensor: Input tensor of shape (B, 3, H, W)
            target_class: Target class index. If None, uses argmax of output.

        Returns:
            CAM of shape (B, 7, 7) for 224x224 input
        """
        try:
            from pytorch_grad_cam import GradCAM
            from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
        except ImportError:
            raise ImportError(
                "pytorch-grad-cam is required for ResNet CAM. "
                "Install with: pip install grad-cam"
            )

        # Get the backbone (first module in Sequential)
        if isinstance(model, nn.Sequential):
            backbone = model[0]
        else:
            backbone = model

        # Find target layer: layer4[-1] for ResNet
        # ResNet50Extractor stores layers in feature_extractor Sequential
        # Structure: [conv1, bn1, relu, maxpool, layer1, layer2, layer3, layer4, avgpool]
        #             [0]    [1]  [2]   [3]      [4]     [5]     [6]     [7]     [8]
        target_layers = None
        if hasattr(backbone, 'feature_extractor'):
            # ResNet50Extractor structure - layer4 is at index 7
            fe_children = list(backbone.feature_extractor.children())

            # Find layer4: it's the last Sequential block with Bottleneck children (before avgpool)
            # We iterate in reverse to find the last layer block (layer4)
            for i in range(len(fe_children) - 1, -1, -1):
                module = fe_children[i]
                if isinstance(module, nn.Sequential):
                    children = list(module.children())
                    if len(children) > 0 and hasattr(children[0], 'conv3'):
                        # Found layer4 (or the last layer block with Bottleneck)
                        # Use the last Bottleneck in this layer
                        target_layers = [children[-1]]
                        break

        if target_layers is None:
            # Fallback: try to find layer4 by name
            for name, module in backbone.named_modules():
                if 'layer4' in name and hasattr(module, 'conv3'):
                    target_layers = [module]
                    # Don't break - we want the last one (layer4.2 for ResNet50)

        if target_layers is None:
            raise ValueError("Could not find target layer for Grad-CAM in ResNet")

        # Prepare targets
        if target_class is not None:
            targets = [ClassifierOutputTarget(target_class)] * input_tensor.shape[0]
        else:
            targets = None  # Will use argmax

        # Ensure input tensor requires grad and is not in inference mode
        # Clone to avoid modifying the original tensor
        input_tensor = input_tensor.clone().detach().requires_grad_(True)

        # Create GradCAM and extract
        # Use torch.enable_grad() to ensure gradients are computed even if
        # called from within torch.inference_mode() or torch.no_grad()
        with torch.enable_grad():
            with GradCAM(model=model, target_layers=target_layers) as cam:
                grayscale_cam = cam(input_tensor=input_tensor, targets=targets)

        # Debug: check if CAM is valid
        if grayscale_cam is None:
            logger.warning("GradCAM returned None")
            raise ValueError("GradCAM returned None")
        if np.allclose(grayscale_cam, 0):
            logger.warning(
                f"GradCAM returned all zeros. "
                f"Input device: {input_tensor.device}, "
                f"Target layer: {type(target_layers[0]).__name__}, "
                f"Target class: {target_class}"
            )

        return grayscale_cam  # (B, H, W)

    def get_cam_size(self, input_size: int = 224) -> Tuple[int, int]:
        """
        Get the CAM output size.

        Note: pytorch-grad-cam by default upsamples CAM to input image size.
        The actual feature map size is 7x7 for 224 input, but the output is (224, 224).
        """
        # pytorch-grad-cam upsamples CAM to input size by default
        return (input_size, input_size)


# =============================================================================
# Transformer CAM Extractor (CLS Attention)
# =============================================================================

class TransformerCAMExtractor(BaseCAMExtractor):
    """
    CAM extractor for Vision Transformer backbones using CLS attention.

    Hooks the last transformer block's attention and extracts
    the attention from CLS token to all patch tokens.

    Supports multiple ViT implementations:
    - timm ViT (UNI, Virchow, H-Optimus, etc.)
    - HuggingFace ViT (Phikon)
    - CLIP-based (CONCH, PLIP)
    """

    def __init__(self, patch_size: int = 16, num_registers: int = 0):
        """
        Args:
            patch_size: ViT patch size (16 for most models, 14 for some)
            num_registers: Number of register tokens to skip (e.g., 4 for Virchow)
        """
        super().__init__()
        self.patch_size = patch_size
        self.num_registers = num_registers
        self._attention_maps: List[torch.Tensor] = []
        self._hooks = []

    def _get_attention_hook(self):
        """Create a hook function to capture attention weights."""
        def hook_fn(_module, _input, output):
            # output can be attention weights or (output, weights)
            if isinstance(output, tuple):
                attn = output[1] if len(output) > 1 else output[0]
            else:
                attn = output
            self._attention_maps.append(attn.detach())
        return hook_fn

    def _find_attention_module(self, backbone: nn.Module) -> Optional[nn.Module]:
        """
        Find the attention module in the last transformer block.

        Returns the module that outputs attention weights.
        """
        # Try different ViT architectures

        # 1. timm ViT structure: model.blocks[-1].attn
        if hasattr(backbone, 'blocks'):
            last_block = backbone.blocks[-1]
            if hasattr(last_block, 'attn'):
                return last_block.attn

        # 2. timm ViT with backbone attribute
        if hasattr(backbone, 'backbone'):
            inner = backbone.backbone
            if hasattr(inner, 'blocks'):
                last_block = inner.blocks[-1]
                if hasattr(last_block, 'attn'):
                    return last_block.attn

        # 3. HuggingFace ViT: model.encoder.layer[-1].attention
        if hasattr(backbone, 'encoder'):
            if hasattr(backbone.encoder, 'layer'):
                last_layer = backbone.encoder.layer[-1]
                if hasattr(last_layer, 'attention'):
                    return last_layer.attention

        # 4. CLIP-based models
        if hasattr(backbone, 'visual'):
            visual = backbone.visual
            if hasattr(visual, 'transformer'):
                transformer = visual.transformer
                if hasattr(transformer, 'resblocks'):
                    last_block = transformer.resblocks[-1]
                    if hasattr(last_block, 'attn'):
                        return last_block.attn

        # 5. Direct trunk attribute (CONCH 1.5)
        if hasattr(backbone, 'trunk'):
            trunk = backbone.trunk
            if hasattr(trunk, 'blocks'):
                last_block = trunk.blocks[-1]
                if hasattr(last_block, 'attn'):
                    return last_block.attn

        return None

    def _register_hooks(self, backbone: nn.Module) -> bool:
        """Register forward hooks to capture attention weights."""
        self._attention_maps.clear()
        self._hooks.clear()

        attn_module = self._find_attention_module(backbone)
        if attn_module is None:
            logger.warning("Could not find attention module for CAM extraction")
            return False

        # For timm models, we need to hook the attention computation
        # The attention weights are computed inside forward(), so we need
        # to modify the model to output them

        # Check if the attention module has a way to output attention weights
        if hasattr(attn_module, 'fused_attn'):
            # timm uses fused attention - need different approach
            # We'll use forward hook on the softmax output
            pass

        hook = attn_module.register_forward_hook(self._get_attention_hook())
        self._hooks.append(hook)
        return True

    def _remove_hooks(self):
        """Remove all registered hooks."""
        for hook in self._hooks:
            hook.remove()
        self._hooks.clear()
        self._attention_maps.clear()

    def extract_cam(
        self,
        model: nn.Module,
        input_tensor: torch.Tensor,
        target_class: Optional[int] = None,  # noqa: ARG002
    ) -> np.ndarray:
        """
        Extract attention-based CAM from Transformer model.

        Note: This is a basic implementation. For better results, use TimmViTCAMExtractor
        which modifies the forward pass to capture attention weights.

        Args:
            model: nn.Sequential containing (backbone, linear_probe)
                   where backbone is a ViT-based extractor
            input_tensor: Input tensor of shape (B, 3, H, W)
            target_class: Not used for attention-based CAM (kept for API consistency)

        Returns:
            CAM of shape (B, H, W) where H=W=input_size/patch_size
            e.g., (B, 14, 14) for 224x224 input with patch_size=16
        """
        # Get the backbone
        if isinstance(model, nn.Sequential):
            backbone = model[0]
        else:
            backbone = model

        # Calculate expected spatial size
        B = input_tensor.shape[0]
        H = W = input_tensor.shape[-1] // self.patch_size

        try:
            # Run forward pass to ensure model works
            with torch.no_grad():
                _ = backbone(input_tensor)

            # This basic implementation returns uniform attention
            # The TimmViTCAMExtractor provides actual attention extraction
            logger.info(
                "TransformerCAMExtractor: Using uniform attention. "
                "Consider using TimmViTCAMExtractor for actual attention maps."
            )
            attn_maps = np.ones((B, H, W), dtype=np.float32) / (H * W)

        except Exception as e:
            logger.error(f"Error in TransformerCAMExtractor: {e}")
            attn_maps = np.ones((B, H, W), dtype=np.float32) / (H * W)

        finally:
            self._remove_hooks()

        return attn_maps

    def get_cam_size(self, input_size: int = 224) -> Tuple[int, int]:
        """
        Get CAM output size.

        Note: This basic implementation returns native resolution (e.g., 14x14).
        Use TimmViTCAMExtractor for upsampled output.
        """
        size = input_size // self.patch_size
        return (size, size)


# =============================================================================
# Attention-based CAM with proper hook (Alternative Implementation)
# =============================================================================

class TimmViTCAMExtractor(BaseCAMExtractor):
    """
    CAM extractor specifically for timm ViT models.

    Uses a modified forward pass to extract attention weights.
    """

    def __init__(self, patch_size: int = 16, num_registers: int = 0):
        super().__init__()
        self.patch_size = patch_size
        self.num_registers = num_registers

    def extract_cam(
        self,
        model: nn.Module,
        input_tensor: torch.Tensor,
        target_class: Optional[int] = None,  # noqa: ARG002
    ) -> np.ndarray:
        """
        Extract attention CAM from timm ViT model.

        This modifies the attention module temporarily to output attention weights.

        Args:
            model: The model (backbone or backbone + classifier)
            input_tensor: Input tensor of shape (B, 3, H, W)
            target_class: Not used for attention-based CAM (kept for API consistency)
        """
        # Get backbone
        if isinstance(model, nn.Sequential):
            backbone = model[0]
        else:
            backbone = model

        if hasattr(backbone, 'backbone'):
            vit = backbone.backbone
        elif hasattr(backbone, 'trunk'):
            vit = backbone.trunk
        else:
            vit = backbone

        B = input_tensor.shape[0]
        H = W = input_tensor.shape[-1] // self.patch_size

        # Get the last block's attention module
        if not hasattr(vit, 'blocks'):
            logger.warning("No blocks found in ViT model")
            return np.ones((B, H, W), dtype=np.float32) / (H * W)

        last_attn = vit.blocks[-1].attn

        # Capture attention weights by modifying the forward pass
        attention_weights: List[torch.Tensor] = []

        # Store original forward
        original_forward = last_attn.forward

        def forward_with_attn(x):
            batch_size, num_tokens, _ = x.shape
            qkv = last_attn.qkv(x).reshape(
                batch_size, num_tokens, 3, last_attn.num_heads, -1
            ).permute(2, 0, 3, 1, 4)
            q, k, v = qkv.unbind(0)

            # Compute attention weights
            attn = (q @ k.transpose(-2, -1)) * last_attn.scale
            attn = attn.softmax(dim=-1)

            # Store attention
            attention_weights.append(attn.detach().cpu())

            # Continue with normal forward
            attn = last_attn.attn_drop(attn)
            x = (attn @ v).transpose(1, 2).reshape(batch_size, num_tokens, -1)
            x = last_attn.proj(x)
            x = last_attn.proj_drop(x)
            return x

        input_size = input_tensor.shape[-1]

        try:
            # Replace forward temporarily
            last_attn.forward = forward_with_attn

            with torch.no_grad():
                _ = backbone(input_tensor)

            if attention_weights:
                # Get CLS attention to patch tokens
                attn = attention_weights[-1]  # (B, heads, N, N)
                # Take CLS token (index 0) attention to other tokens
                cls_attn = attn[:, :, 0, 1:]  # (B, heads, N-1)

                # Skip register tokens if any
                if self.num_registers > 0:
                    cls_attn = cls_attn[:, :, self.num_registers:]

                # Average over heads
                cls_attn = cls_attn.mean(dim=1)  # (B, N-1)

                # Reshape to spatial
                cls_attn = cls_attn.reshape(B, H, W).numpy()

                # Normalize
                cls_attn = (cls_attn - cls_attn.min()) / (cls_attn.max() - cls_attn.min() + 1e-8)

                # Upsample to input size for consistency with ResNet CAM
                from scipy.ndimage import zoom
                scale = input_size / H
                upsampled = np.stack([
                    zoom(cls_attn[i], scale, order=1) for i in range(B)
                ])

                return upsampled
            else:
                return np.ones((B, input_size, input_size), dtype=np.float32) / (input_size * input_size)

        except Exception as e:
            logger.error(f"Error in attention extraction: {e}")
            return np.ones((B, input_size, input_size), dtype=np.float32) / (input_size * input_size)

        finally:
            # Restore original forward
            last_attn.forward = original_forward

    def get_cam_size(self, input_size: int = 224) -> Tuple[int, int]:
        """
        Get CAM output size.

        Note: CAM is upsampled to input image size for consistency with ResNet CAM.
        """
        return (input_size, input_size)



# =============================================================================
# Extractor Configuration
# =============================================================================

# Mapping of extractor names to their architecture type and parameters
_EXTRACTOR_CAM_CONFIG = {
    # CNN-based
    "resnet50": {"type": "cnn"},

    # Transformer-based (patch_size=16)
    "vit_l_16": {"type": "vit", "patch_size": 16},
    "uni": {"type": "vit", "patch_size": 16},
    "uni2": {"type": "vit", "patch_size": 16},
    "phikon": {"type": "vit", "patch_size": 16},
    "phikon2": {"type": "vit", "patch_size": 16},
    "conch": {"type": "vit", "patch_size": 16},
    "conch15": {"type": "vit", "patch_size": 16},
    "plip": {"type": "vit", "patch_size": 16},
    "patho_clip": {"type": "vit", "patch_size": 16},
    "openmidnight": {"type": "vit", "patch_size": 16},
    "mSTAR": {"type": "vit", "patch_size": 16},
    "GPFM": {"type": "vit", "patch_size": 16},

    # Transformer-based (patch_size=14)
    "virchow": {"type": "vit", "patch_size": 14, "num_registers": 4},
    "virchow2": {"type": "vit", "patch_size": 14, "num_registers": 4},
    "H-Optimus-0": {"type": "vit", "patch_size": 14},
    "H-Optimus-1": {"type": "vit", "patch_size": 14},
}


# =============================================================================
# Factory Function
# =============================================================================

def get_cam_extractor(extractor_name: str) -> BaseCAMExtractor:
    """
    Get a CAM extractor for the given feature extractor name.

    Args:
        extractor_name: Name of the feature extractor (e.g., "resnet50", "uni")

    Returns:
        Appropriate CAM extractor instance

    Raises:
        ValueError: If extractor name is not supported

    Example:
        cam_extractor = get_cam_extractor("uni")
        cam_map = cam_extractor.extract_cam(model, images, target_class=1)
    """
    if extractor_name not in _EXTRACTOR_CAM_CONFIG:
        # Default to ViT with patch_size=16 for unknown extractors
        logger.warning(
            f"Unknown extractor '{extractor_name}', assuming ViT with patch_size=16"
        )
        return TimmViTCAMExtractor(patch_size=16)

    config = _EXTRACTOR_CAM_CONFIG[extractor_name]

    if config["type"] == "cnn":
        return ResNetCAMExtractor()
    else:
        # ViT-based
        return TimmViTCAMExtractor(
            patch_size=config.get("patch_size", 16),
            num_registers=config.get("num_registers", 0)
        )


def is_cnn_extractor(extractor_name: str) -> bool:
    """Check if an extractor is CNN-based."""
    config = _EXTRACTOR_CAM_CONFIG.get(extractor_name, {})
    return config.get("type") == "cnn"


def is_vit_extractor(extractor_name: str) -> bool:
    """Check if an extractor is ViT-based."""
    config = _EXTRACTOR_CAM_CONFIG.get(extractor_name, {})
    return config.get("type") == "vit"


def get_cam_spatial_size(extractor_name: str, input_size: int = 224) -> Tuple[int, int]:  # noqa: ARG001
    """
    Get the spatial size of CAM output for a given extractor.

    Args:
        extractor_name: Name of the feature extractor (kept for API consistency)
        input_size: Input image size

    Returns:
        (height, width) of CAM output

    Note:
        CAM is upsampled to input image size for both CNN and ViT models.
        This ensures consistent overlay visualization on the input image.
    """
    # All CAM extractors now return upsampled CAM to input size
    # extractor_name is kept for API consistency but not used
    _ = extractor_name
    return (input_size, input_size)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "PatchCAMResult",
    "BaseCAMExtractor",
    "ResNetCAMExtractor",
    "TransformerCAMExtractor",
    "TimmViTCAMExtractor",
    "get_cam_extractor",
    "is_cnn_extractor",
    "is_vit_extractor",
    "get_cam_spatial_size",
]
