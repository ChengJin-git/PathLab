import logging
from collections import OrderedDict

import timm
import torch
from torchvision import transforms

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path
from .transforms import OPENAI_CLIP_MEAN, OPENAI_CLIP_STD

logger = logging.getLogger(__name__)


def _load_smartcyto_weights(model, checkpoint_path, state_dict_prefix='module.visual.model.'):
    """Load SmartCyto DINOv3-based checkpoint weights.

    Handles prefix stripping, LayerScale name conversion, and RoPE periods.
    """
    logger.info(f"Loading SmartCyto checkpoint from: {checkpoint_path}")

    ckpt = torch.load(checkpoint_path, map_location='cpu', weights_only=False)

    if 'state_dict' not in ckpt:
        raise ValueError(f"Checkpoint does not contain 'state_dict' key. Found keys: {list(ckpt.keys())}")

    state_dict = ckpt['state_dict']
    logger.info(f"Checkpoint info: epoch={ckpt.get('epoch', 'N/A')}, name={ckpt.get('name', 'N/A')}")
    logger.info(f"Checkpoint contains {len(state_dict)} parameters")

    converted_state_dict = OrderedDict()
    prefix_len = len(state_dict_prefix)
    rope_periods = None

    skip_params = ['qkv.bias_mask', 'qkv.bias', 'storage_tokens', 'mask_token', 'rope_embed.periods']

    for key, value in state_dict.items():
        if not key.startswith(state_dict_prefix):
            continue

        new_key = key[prefix_len:]

        # Handle RoPE periods separately
        if new_key == 'rope_embed.periods':
            rope_periods = value
            continue

        # Skip unnecessary parameters
        if any(skip in new_key for skip in skip_params):
            continue

        # Convert LayerScale parameter names from openclip format to timm format
        if '.ls1.gamma' in new_key:
            new_key = new_key.replace('.ls1.gamma', '.gamma_1')
        elif '.ls2.gamma' in new_key:
            new_key = new_key.replace('.ls2.gamma', '.gamma_2')

        converted_state_dict[new_key] = value

    logger.info(f"Converted {len(converted_state_dict)} parameters")

    # Load RoPE periods if available
    if rope_periods is not None and hasattr(model, 'rope'):
        model.rope.periods = rope_periods
        logger.info("Loaded RoPE periods into model.rope.periods")

    # Load weights (strict=False to allow missing reg_token)
    missing_keys, unexpected_keys = model.load_state_dict(converted_state_dict, strict=False)
    if missing_keys:
        logger.info(f"Missing keys: {missing_keys}")
    if unexpected_keys:
        logger.info(f"Unexpected keys: {unexpected_keys}")

    logger.info("SmartCyto checkpoint loaded successfully")
    return model


class SmartCytoExtractor(BaseExtractor):
    """SmartCyto feature extractor based on DINOv3 ViT-B backbone (768-dim).

    Developed by HKUST Smart Lab. Uses timm's DINOv3 ViT-B/16 with custom
    weight loading (LayerScale conversion and RoPE support).
    Uses OpenCLIP normalization parameters.
    """

    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("SmartCyto", hf_token)

        # Create timm DINOv3 ViT-B model
        self.backbone = timm.create_model(
            'vit_base_patch16_dinov3',
            pretrained=False,
            img_size=224,
            num_classes=0,
        )

        # Load SmartCyto weights with custom loader
        self.backbone = _load_smartcyto_weights(
            self.backbone, ckpt_path, state_dict_prefix='module.visual.model.'
        )
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)

    def get_transforms(self, mode="eval"):
        return transforms.Compose(
            [
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=OPENAI_CLIP_MEAN, std=OPENAI_CLIP_STD),
            ]
        )

    @property
    def output_dim(self) -> int:
        return 768

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> "SmartCytoExtractor":
        """Build a SmartCytoExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    extractor = SmartCytoExtractor.build()
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)

