from PIL import Image
import torch
from transformers import AutoImageProcessor, AutoModel
from torchvision import transforms
from PIL.Image import Resampling

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class Phikon2Extractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        self.ckpt_path = get_ckpt_path("Phikon2", hf_token)
        self.backbone = AutoModel.from_pretrained(self.ckpt_path)
        self.backbone.eval()

    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        inputs = {"pixel_values": x}
        outputs = self.backbone(**inputs)
        # concatenate CLS token and average pool of patch tokens
        cls_token = outputs.last_hidden_state[:, 0]  # size: batch x hidden
        return cls_token

    def get_transforms(self, mode="eval"):
        processor = AutoImageProcessor.from_pretrained(self.ckpt_path)
        
        transform = transforms.Compose([
            # 1. Resize最短边到224，使用BICUBIC插值（与processor一致）
            transforms.Resize(processor.size["shortest_edge"], interpolation=Resampling.BICUBIC),
            # 2. Center crop到224x224
            transforms.CenterCrop((processor.crop_size["height"], processor.crop_size["width"])),
            # 3. 转为tensor并自动除以255
            transforms.ToTensor(),
            # 4. 标准化（与processor相同参数）
            transforms.Normalize(
                mean=processor.image_mean,
                std=processor.image_std
            )
        ])
        return transform
        
    @property
    def output_dim(self) -> int:
        return 1024

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = Phikon2Extractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
    
    # comparsion with huggingface model
    hf_model = AutoModel.from_pretrained("owkin/phikon-v2")
    hf_model.eval()
    dummy_input = {'pixel_values': dummy_input}
    outpu2 = hf_model(**dummy_input).last_hidden_state[:, 0]
    error = torch.abs(output - outpu2).max()
    print("Max error compared to Huggingface model:", error)
    
