from PIL import Image
import requests
from transformers import CLIPProcessor, CLIPModel
import torch
from torchvision import transforms
from PIL.Image import Resampling

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class PLIPExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        self.local_model_dir = get_ckpt_path("PLIP", hf_token)
        self.backbone = CLIPModel.from_pretrained(self.local_model_dir)
        self.backbone.eval()
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.

        Args:
            x: Input tensor of shape (B, 3, H, W)
        Returns:
            Feature tensor of shape (B, 512)
        """
        inputs = {"pixel_values": x}
        outputs = self.backbone.get_image_features(**inputs)
        return outputs

    def get_transforms(self, mode="eval"):
        processor = CLIPProcessor.from_pretrained(self.local_model_dir)
        img_proc = processor.image_processor
        transform = transforms.Compose([
            transforms.Resize(img_proc.size["shortest_edge"], interpolation=Resampling.BICUBIC),
            transforms.CenterCrop((img_proc.crop_size["height"], img_proc.crop_size["width"])),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=img_proc.image_mean,
                std=img_proc.image_std
            )
        ])
        return transform

    @property
    def output_dim(self) -> int:
        return 512

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = PLIPExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)

