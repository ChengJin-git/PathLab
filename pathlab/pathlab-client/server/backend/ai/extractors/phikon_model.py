from PIL import Image
import torch
from transformers import AutoImageProcessor, ViTModel
from torchvision import transforms
from PIL.Image import Resampling

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class PhikonExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        self.ckpt_path = get_ckpt_path("Phikon", hf_token)
        self.backbone = ViTModel.from_pretrained(self.ckpt_path, add_pooling_layer=False)
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        inputs = {"pixel_values": x}
        outputs = self.backbone(**inputs)
        # concatenate CLS token and average pool of patch tokens
        cls_token = outputs.last_hidden_state[:, 0]  # size: batch x hidden
        return cls_token

    def get_transforms(self, mode="eval"):
        processor = AutoImageProcessor.from_pretrained(self.ckpt_path)
        transform = transforms.Compose([
            transforms.Resize((processor.size["height"], processor.size["width"]), interpolation=Resampling.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=processor.image_mean,
                std=processor.image_std
            )
        ])
        return transform
        
    @property
    def output_dim(self) -> int:
        return 768

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = PhikonExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
    
    # comparsion with huggingface model
    hf_model = ViTModel.from_pretrained("owkin/phikon", add_pooling_layer=False)
    hf_model.eval()
    dummy_input = {'pixel_values': dummy_input}
    outpu2 = hf_model(**dummy_input).last_hidden_state[:, 0]
    error = torch.abs(output - outpu2).max()
    print("Max error compared to Huggingface model:", error)
    
