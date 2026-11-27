import timm
from torchvision import transforms
import torch

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path
from .transforms import IMAGENET_MEAN, IMAGENET_STD


class mSTARExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("mSTAR", hf_token)
        # load backbone
        self.backbone = timm.create_model(
        "vit_large_patch16_224", img_size=224, patch_size=16, init_values=1e-5, num_classes=0, dynamic_img_size=True
    )
        self.backbone.load_state_dict(torch.load(ckpt_path, map_location="cpu"), strict=True)
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feats = self.backbone(x)
        return feats

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
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = mSTARExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
