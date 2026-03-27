from __future__ import annotations

import logging
import os

import torch
from torchvision import transforms

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path
from .transforms import IMAGENET_MEAN, IMAGENET_STD

logger = logging.getLogger(__name__)


class KRONOSExtractor(BaseExtractor):
    """KRONOS: Multiplex ViT-S/16, 384-dim (Mahmood Lab).

    Panel-agnostic spatial proteomics foundation model pre-trained on 47M patches
    spanning 175 protein markers.  RGB pathology patches are supported by treating
    the three channels as three independent markers with ImageNet normalization.
    Spatial output averages the per-marker token grids across the marker dimension,
    yielding a standard (B, D, H', W') feature map compatible with FM segmentation.

    Requires the 'kronos' package:
        git clone https://github.com/mahmoodlab/KRONOS.git && pip install -e ./KRONOS
    Model access (gated): https://huggingface.co/MahmoodLab/KRONOS
    """

    def __init__(self, hf_token: str = ""):
        super().__init__()
        try:
            from kronos import create_model_from_pretrained  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'kronos' package is required for KRONOSExtractor. "
                "Install: git clone https://github.com/mahmoodlab/KRONOS.git "
                "&& pip install -e ./KRONOS"
            ) from exc

        local_dir = get_ckpt_path("KRONOS", hf_token)
        ckpt_file = os.path.join(local_dir, "kronos_vits16_model.pt")
        cfg_file = os.path.join(local_dir, "config.json")
        self.model, self.precision, _embedding_dim = create_model_from_pretrained(
            checkpoint_path=ckpt_file,
            cfg_path=cfg_file,
        )
        self._output_dim: int = int(_embedding_dim)
        self.model.eval()
        logger.info(
            "KRONOSExtractor loaded — precision=%s, embedding_dim=%d",
            self.precision,
            self._output_dim,
        )

    @property
    def output_dim(self) -> int:
        return self._output_dim

    @property
    def default_image_size(self) -> int:
        return 224

    @property
    def supports_spatial(self) -> bool:
        return True

    def get_transforms(self, mode: str = "eval"):
        return transforms.Compose(
            [
                transforms.Resize(
                    224,
                    interpolation=transforms.InterpolationMode.BICUBIC,
                ),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ]
        )

    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        patch_embeddings, _marker_embeddings, _token_embeddings = self.model(x)
        return patch_embeddings

    @torch.inference_mode()
    def forward_spatial(self, x: torch.Tensor) -> torch.Tensor:
        _patch_embeddings, _marker_embeddings, patch_token_features = self.model(x)
        _B, _num_markers, _H, _W, _D = patch_token_features.shape
        return patch_token_features.mean(dim=1).permute(0, 3, 1, 2).contiguous()

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> "KRONOSExtractor":
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    extractor = KRONOSExtractor.build()
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
    spatial = extractor.forward_spatial(dummy_input)
    print(spatial.shape)
