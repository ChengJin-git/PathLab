import timm
from torchvision import transforms
import torch

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class GPFMExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("GPFM", hf_token)
        # load backbone
        self.backbone = timm.create_model(
            "vit_large_patch14_dinov2.lvd142m",
            pretrained=False,
            img_size=224,
            init_values=1.0e-05,
        )
        self.backbone.load_state_dict(
            torch.load(ckpt_path, map_location="cpu"), strict=True
        )
        self.backbone.eval()

    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feats = self.backbone(x)
        return feats

    def get_transforms(self, mode="eval"):
        return transforms.Compose(
            [
                transforms.Resize(224),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)
                ),
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
    extractor = GPFMExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
