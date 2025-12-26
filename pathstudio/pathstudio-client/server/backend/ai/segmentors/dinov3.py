from typing import Any
import torch
import timm

from .base import BaseSegmentor
from ._segmentation_decoder import build_segmentation_decoder
from .checkpoint_manager import get_backbone_source, list_supported_backbones
from .tools.transforms import (
    make_segmentation_eval_transforms,
    make_segmentation_train_transforms,
)


class Dinov3Segmentor(BaseSegmentor):
    """DINOv3 ViT-L segmentation network.

    Uses a pre-trained DINOv3 ViT-L model as the backbone for segmentation tasks.
    Expected output logits shape: [B, num_classes, H, W].
    """

    def __init__(
        self,
        num_classes: int,
        backbone: str,
        backbone_out_layers="FOUR_EVEN_INTERVALS",
        hf_token: str = "",
    ):
        """
        Args:
            num_classes: number of segmentation classes
            backbone: backbone model name, supported: 'vit_large_patch16_dinov3', 'vit_huge_plus_patch16_dinov3'
            backbone_out_layers: which set of layers to take from the backbone, supported "FOUR_EVEN_INTERVALS", "FOUR_LAST", "LAST".
            hf_token: HuggingFace token for gated timm weights download
        """
        super().__init__(num_classes=num_classes)
        backbone_key = backbone.strip().lower()
        supported_backbones = list_supported_backbones()
        if backbone_key not in supported_backbones:
            raise ValueError(
                f"Unsupported backbone: {backbone}. Supported backbones are: {supported_backbones}"
            )
        if backbone_out_layers not in ["FOUR_EVEN_INTERVALS", "FOUR_LAST", "LAST"]:
            raise ValueError(
                f"Unsupported backbone_out_layers: {backbone_out_layers}. Supported options are: 'FOUR_EVEN_INTERVALS', 'FOUR_LAST', 'LAST'."
            )

        model_source = get_backbone_source(backbone_key, hf_token=hf_token)
        self.backbone = timm.create_model(
            model_source,
            pretrained=True,
        )

        self.segmentation_model = build_segmentation_decoder(
            backbone_model=self.backbone,
            backbone_out_layers=backbone_out_layers,
            decoder_type="linear",
            num_classes=num_classes,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: input images [B, 3, H, W]
        Returns:
            logits: [B, num_classes, H, W]
        """
        logits = self.segmentation_model(x)
        return logits

    def get_transforms(self, mode) -> Any:
        if mode == "train":
            return make_segmentation_train_transforms(
                img_size=512,
                random_img_size_ratio_range=[0.5, 2.0],
                crop_size=[512, 512],
                flip_prob=0.5,
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            )
        elif mode == "eval":
            return make_segmentation_eval_transforms(
                img_size=512,
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            )
        else:
            raise ValueError(f"Unsupported mode: {mode}. Supported modes are: 'train', 'eval'.")

    @classmethod
    def build(cls, num_classes: int, **kwargs: Any):
        return cls(num_classes=num_classes, **kwargs)


if __name__ == "__main__":
    # Simple test
    model = Dinov3Segmentor.build(
        num_classes=3,
        # backbone="vit_large_patch16_dinov3",
        backbone="vit_huge_plus_patch16_dinov3",
        backbone_out_layers="FOUR_EVEN_INTERVALS",
    )
    model.eval()
    with torch.no_grad():
        dummy_input = torch.randn(2, 3, 512, 512)
        output = model(dummy_input)
        print("Output shape:", output.shape)  # Expected: [2, 3, 512, 512]
