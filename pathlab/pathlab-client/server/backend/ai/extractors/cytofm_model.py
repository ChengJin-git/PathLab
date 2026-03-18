import logging
import torch
from torchvision import transforms

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path
from .transforms import IMAGENET_MEAN, IMAGENET_STD
from .dinov2.models import vision_transformer as vits

logger = logging.getLogger(__name__)


class CytoFMExtractor(BaseExtractor):
    """CytoFM feature extractor based on DINOv2 ViT-L backbone (1024-dim).

    A pure vision self-supervised foundation model for cytopathology,
    developed by HKUST Smart Lab. Uses a custom DINOv2 implementation
    with patch_size=14 and ffn_layer='mlp'.
    Uses ImageNet normalization parameters (mean/std from notes).
    """

    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("CytoFM", hf_token)

        # Build DINOv2 ViT-L model
        vit_kwargs = dict(
            img_size=224,
            patch_size=14,
            init_values=1.0e-05,
            ffn_layer="mlp",
            block_chunks=4,
            qkv_bias=True,
            proj_bias=True,
            ffn_bias=True,
        )
        self.backbone = vits.__dict__["vit_large"](**vit_kwargs)

        # Load checkpoint: format is ckpt['teacher'], keys prefixed with 'backbone.'
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        teacher_state = ckpt["teacher"]
        new_state = {}
        for k, v in teacher_state.items():
            if k.startswith("backbone."):
                new_key = k[len("backbone.") :]
                new_state[new_key] = v
        msg = self.backbone.load_state_dict(new_state, strict=True)
        logger.info(f"CytoFM checkpoint loaded: {msg}")
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)

    def get_transforms(self, mode="eval"):
        return transforms.Compose(
            [
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ]
        )

    @property
    def output_dim(self) -> int:
        return 1024

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> "CytoFMExtractor":
        """Build a CytoFMExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    extractor = CytoFMExtractor.build()
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
